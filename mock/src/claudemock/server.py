"""The mock, as a served site.

One FastAPI application, served by uvicorn over TLS on a thread of its own, and
nothing else: every decision about what the site *does* is in `site.py`, and
everything about what it *looks* like is in `pages.py`. What is here is the
wire — cookies, methods, status codes, JSON in and JSON out — on the core's
(`mockcore.wire`: HTTPS always, a session cookie with a lifetime, the witness
routes at `/__mock/`, the server on its thread).

Two things about this site's wire are its own:

- **Signed out, everything is the login page.** The tool's probe reads a page
  with no composer as `kind: login`, and `/login` is where every other path
  sends a session that has none.
- **It hands out a link instead of an email** (`32`), and **the archive wants no
  session**: brief 03 §35 says the fetch needs none, and it is true of Claude.
  The link is on the mock's own host and port — never on `claude.ai`, because
  the tool downloads a link with Python and no resolver rule.
- **It signs people in by link** (`49`, brief 07 §79): the address step mints a
  sign-in link — on `claude.ai`, token in the fragment, as the real one is —
  and the browser that asked spends it at `/magic-link`, whose own script
  posts the token back. No password step, because claude.ai has none.

The routes are plain `def`s rather than `async def`s on purpose: `Site` is
synchronous and guards its state with a lock, so FastAPI runs each route on a
worker thread and the lock keeps doing its job. The one exception reads an
upload's body, which is the only thing in the mock worth awaiting.
"""

from collections.abc import Callable
from http import HTTPStatus
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import quote, unquote

from fastapi import Depends, FastAPI, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from mockcore import wire
from mockcore.exports import Export, Part
from mockcore.wire import (
    LOGIN_COOKIE,
    MAX_BODY_BYTES,
    SESSION_COOKIE,
    SIGN_IN_LINKS_JSON_PATH,
    SIGN_IN_LINKS_PATH,
    MockServer,
    SignedOutError,
    not_found,
    redirect,
    set_cookie,
)
from pydantic import BaseModel

from claudemock import archive, pages
from claudemock.site import SIGN_IN_LINK_PATH, Chat, SignInLink, Site

if TYPE_CHECKING:
    from mockcore.sessions import Pending

BANNER_COOKIE = "mock_banner"

LOGOUT_PATH = "/logout"
INVOLUNTARY_LOGOUT = LOGOUT_PATH + "?involuntary=1&returnTo={path}"
REAUTH_LOGIN = "/login?from=logout&reauth=1&returnTo={path}"
"""Where a request whose sign-in has lapsed is sent, and where `/logout` sends it next.

Two hops, which is what a real account does: `/new` answers with
`/logout?involuntary&returnTo=…` and `/logout` answers with
`/login?from&reauth&returnTo`. The tool sees a sign-in page either way; what the
two hops give a rehearsal is the *shape* of the journey — a URL that is on the
host and on no surface, in the middle of a run.

There is no export page path here any more. `31` guessed one, `51` found it
served nothing, and the panel is markup on `/new` behind a fragment — which no
server is ever told (`pages.SETTINGS_HASH`)."""


def attachment(filename: str) -> dict[str, str]:
    """Return the header that makes a link a download rather than a page.

    Without it the fetch fails, and the failure is the interesting part: Chrome
    *renders* `application/json`, so a manifest served plain is a document that
    loaded and went quiet — which `download.py` reads, correctly, as "the link led
    to a page, not an archive". The real manifest arrives as a download with a
    90-character filename, so the vendor sends this header too; the mock's own
    spelling of the name is shorter and is not a claim about the vendor's.
    """
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


REFUSED = "Those details do not match an account here."
NO_CODE = "That code was not accepted."
"""What the code field answers to anything typed into it: the mock mints no
code, because the code door is deferred (brief 07 §80)."""


class MessageIn(BaseModel):
    text: str = ""


class TitleIn(BaseModel):
    title: str = ""


def chat_json(chat: Chat, now: float) -> dict[str, Any]:
    return {
        "id": chat.id,
        "title": chat.title,
        "generating": chat.generating(now),
        "files": list(chat.files),
        "turns": [{"role": turn.role, "text": turn.text} for turn in chat.view(now)],
    }


# -- the application ---------------------------------------------------------- #


def create_app(  # ruff: ignore[complex-structure, too-many-statements] - one route per function
    site: Site,
    *,
    link_base: str = "",
    announce: Callable[[str], None] = wire.quiet,
    announce_sign_in: Callable[[str], None] = wire.quiet,
) -> FastAPI:
    """Return the site as an ASGI application: every route the mock answers.

    A factory rather than a module-level `app`, because the site it serves is
    constructed per process — and per test, which is what keeps the tests of
    the wire independent of one another. `link_base` is the origin an export link
    is spelled with, and `announce` is told each link as it is minted — the CLI
    prints it where the vendor would have sent an email. `announce_sign_in` is
    the same for a sign-in link (`49`).
    """
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    if link_base:
        # What the socket really bound, which only `serve` knows: every link this
        # site mints is spelled with it, the sign-in's as well as the export's.
        site.origin = link_base
    pending: Pending = site.pending_sign_ins
    account_id = archive.account_uuid(site.email)
    """The one account's id, which every export's files hang under — as a real
    manifest's do, naming the same uuid across every export it writes."""

    def link_of(export: Export) -> str:
        """Where the vendor's email would point: the index, not the archive."""
        return link_base + wire.MANIFEST_PATH.format(token=export.token)

    def part_url(part: Part) -> str:
        """Where one file of an index lives: under the account, not under the index.

        The account's own id, as the real one is — a real manifest names the same
        uuid in every export it ever writes, and a hex token per file. So nothing
        of the link an operator pasted survives into the snapshot the tool files.
        """
        return link_base + wire.PART_PATH.format(export_id=account_id, part_token=part.token)

    def sign_in_link_json(link: SignInLink) -> dict[str, Any]:
        return {"token": link.token, "link": site.link_of(link), "minted_at": link.minted_at, "spent": link.spent}

    Session = Annotated[str, Depends(wire.session_of(site.signed_in))]  # ruff: ignore[non-lowercase-variable-in-function] - it names a type

    @app.exception_handler(SignedOutError)
    def signed_out(request: Request, _failure: SignedOutError) -> Response:
        """Send a request with no live session where a real account sends one.

        Never straight to `/login`: claude.ai answers an expired session with
        `/logout?involuntary&returnTo=…` first, and `/logout` answers with the
        sign-in page. A browser that never had a session and one whose session
        lapsed take the same two hops, because the site cannot tell them apart
        either — it has a token it does not know, or no token at all.
        """
        return redirect(INVOLUNTARY_LOGOUT.format(path=quote(request.url.path)))

    @app.get(LOGOUT_PATH)
    def logout_page(return_to: Annotated[str, Query(alias="returnTo")] = "/new") -> Response:
        """Answer the second hop: the sign-in page, carrying where to come back to.

        The query is the vendor's `returnTo`, aliased rather than spelled: what is
        on the wire is claude.ai's, and what is in the code is this project's.
        """
        return redirect(REAUTH_LOGIN.format(path=quote(return_to)))

    # -- the witness ------------------------------------------------------- #

    wire.witness(app, ledger=site.ledger, exports=site._exports, link_of=link_of, expire=site.expire_sessions)  # ruff: ignore[private-member-access] - the site's, handed to the core

    @app.get(wire.MANIFEST_PATH)
    def manifest(_session: Session, token: str) -> Response:
        """Serve the index a link names: one file per category, each at its own address.

        Behind the session, because a real link is: a browserless request for one,
        minutes old and well inside its day, answered `403`.

        A token nobody minted is not found, which the tool reports as
        `link refused: HTTP 404` and leaves the ask open — a dead link (§39, 5),
        as near as a mock with no clock to expire on can come to one. The index
        itself may be read again; what it names may not.
        """
        export = site.fetch_export(token)
        if export is None:
            return not_found()
        index = archive.manifest(export, url_of=part_url)
        return JSONResponse(index, headers=attachment(archive.manifest_filename(export)))

    @app.get(wire.PART_PATH)
    def download_part(_session: Session, export_id: str, part_token: str) -> Response:
        """Serve one part of an export, once.

        "Each export URL can only be used once" is what the manifest says about
        its own files, so a second fetch is `404` — the same answer as a token
        nobody minted, because from outside they are the same thing: an address
        that is no longer good for anything.
        """
        part = site.spend_part(part_token) if export_id == account_id else None
        if part is None:
            return not_found()
        payload = archive.render(part.category, site.all_chats(), email=site.email, now=site.now())
        return Response(payload, media_type="application/zip", headers=attachment(part.filename))

    # -- sign-in by link (`49`) --------------------------------------------- #

    @app.get(SIGN_IN_LINKS_PATH)
    def sign_in_links_text() -> Response:
        """Return the sign-in links minted so far, one per line, oldest first: the inbox's stand-in."""
        return PlainTextResponse("".join(f"{site.link_of(link)}\n" for link in site.sign_in_links()))

    @app.get(SIGN_IN_LINKS_JSON_PATH)
    def sign_in_links_json() -> list[dict[str, Any]]:
        return [sign_in_link_json(link) for link in site.sign_in_links()]

    def pending_token(request: Request) -> tuple[str, dict[str, str]]:
        """Return the browser's pending-sign-in token: the cookie it carries, or a new one to set."""
        token = request.cookies.get(LOGIN_COOKIE)
        if token:
            return token, {}
        token = pending.new_token()
        return token, {LOGIN_COOKIE: token}

    @app.get("/login")
    def login_page(request: Request, error: str = "") -> Response:
        if site.signed_in(request.cookies.get(SESSION_COOKIE)):
            return redirect("/new")
        token, cookies = pending_token(request)
        response = HTMLResponse(
            pages.login_page(
                step=site.sign_in_step(token),
                banner=request.cookies.get(BANNER_COOKIE) != "dismissed",
                error={"refused": REFUSED, "code": NO_CODE}.get(error, ""),
                address=pending.pending(token) or site.email,
            )
        )
        for name, value in cookies.items():
            set_cookie(response, name, value)
        return response

    @app.get("/login/unsupported")
    def unsupported_page() -> Response:
        return HTMLResponse(pages.unsupported_page())

    @app.post("/login/email")
    def submit_email(request: Request, email: Annotated[str, Form()] = "") -> Response:
        """Take the address: exactly one gets a link (§21), minted where an email would go (`link requested`)."""
        token, _ = pending_token(request)
        link = site.request_sign_in(email, pending=token)
        if link is None:
            return redirect("/login?error=refused", **{LOGIN_COOKIE: token})
        announce_sign_in(site.link_of(link))
        return redirect("/login", **{LOGIN_COOKIE: token})

    @app.post("/login/resend")
    def resend(request: Request) -> Response:
        """Mint another link for the same sign-in: the link-sent page's *try sending it again*."""
        token, _ = pending_token(request)
        link = site.resend(token)
        if link is not None:
            announce_sign_in(site.link_of(link))
        return redirect("/login", **{LOGIN_COOKIE: token})

    @app.post("/login/change")
    def change_address(request: Request) -> Response:
        """Forget the sign-in this browser began: the link-sent page's *change email address*."""
        token, _ = pending_token(request)
        site.forget_pending(token)
        return redirect("/login", **{LOGIN_COOKIE: token})

    @app.post("/login/code")
    def submit_code(request: Request, code: Annotated[str, Form()] = "") -> Response:
        """Refuse whatever was typed into the code field: no code was ever minted (§80)."""
        token, _ = pending_token(request)
        return redirect("/login?error=code", **{LOGIN_COOKIE: token})

    @app.get(SIGN_IN_LINK_PATH)
    def magic_link_page() -> Response:
        """Where a sign-in link lands (`sign-in link`). No session: this is how one is made."""
        return HTMLResponse(pages.magic_link_page())

    @app.post("/login/redeem")
    def redeem(request: Request, token: Annotated[str, Form()] = "", email: Annotated[str, Form()] = "") -> Response:
        """Spend the link the page's script read off its fragment, in this browser.

        The pending sign-in is the browser's cookie. A link that finishes it
        signs the browser in and says where to go (`signed in by the link`);
        one that does not leaves the browser at the code page, with the cookie
        set so that `/login` shows it (`link opened elsewhere`).
        """
        browser, cookies = pending_token(request)
        session = site.redeem(token, email, pending=browser)
        if session is None:
            response = JSONResponse({"ok": False, "next": "/login"})
            for name, value in {**cookies, LOGIN_COOKIE: browser}.items():
                set_cookie(response, name, value)
            return response
        response = JSONResponse({"ok": True, "next": "/new"})
        set_cookie(response, SESSION_COOKIE, session)
        return response

    # -- the site ---------------------------------------------------------- #

    @app.get("/")
    @app.get("/new")
    def new_chat_page(_session: Session) -> Response:
        return HTMLResponse(pages.chat_page(None, (), generating=False))

    @app.get("/chat/{chat_id}")
    def chat_page(_session: Session, chat_id: str) -> Response:
        chat = site.chat(chat_id)
        if chat is None:
            return not_found()
        now = site.now()
        return HTMLResponse(pages.chat_page(chat, chat.view(now), generating=chat.generating(now)))

    @app.get("/api/chats/{chat_id}")
    def read_chat(_session: Session, chat_id: str) -> Response:
        chat = site.chat(chat_id)
        if chat is None:
            return not_found()
        return JSONResponse(chat_json(chat, site.now()))

    @app.post("/api/chats")
    def create_chat(session: Session, message: MessageIn) -> Response:
        chat = site.create_chat(message.text, session=session)
        return JSONResponse(chat_json(chat, site.now()))

    @app.post("/api/chats/{chat_id}/messages")
    def receive(_session: Session, chat_id: str, message: MessageIn) -> Response:
        chat = site.chat(chat_id)
        if chat is None:
            return not_found()
        site.receive(chat, message.text)
        return JSONResponse(chat_json(chat, site.now()))

    @app.post("/api/chats/{chat_id}/title")
    def rename(_session: Session, chat_id: str, title: TitleIn) -> Response:
        chat = site.chat(chat_id)
        if chat is None:
            return not_found()
        site.rename(chat, title.title)
        return JSONResponse(chat_json(chat, site.now()))

    # -- the settings panel (`32`, `51`) ------------------------------------ #
    #
    # No route: the panel is a fragment of `/new`, and a fragment never reaches a
    # server. `pages.settings_panel` is the markup and `pages.SETTINGS_JS` opens
    # it on the address. What is left here is the one request it makes.

    @app.post("/api/exports")
    def request_export(_session: Session) -> Response:
        """Take the ask: mint the link, count it, and say it where an email would go.

        **202, not 200.** The real ask answers *accepted* — the export is made
        later and mailed when it is ready — and answering `200` would be the mock
        saying the work was done by the time the request returned. The page reads
        `ok` from the body rather than the status, so the two agree.

        The page never shows the link — the tool reads a toast, not a sentence —
        so the response carries it for whoever is reading the wire.
        """
        export = site.request_export()
        link = link_of(export)
        announce(link)
        return JSONResponse({"ok": True, "link": link}, status_code=HTTPStatus.ACCEPTED)

    @app.post("/api/uploads")
    async def upload(session: Session, request: Request) -> Response:
        """Take a file into the composer.

        The bytes are read and dropped: what a rehearsal checks is that the site took
        the file and showed its name.

        The one `async def` here, because the body is the request's to read
        and reading it is the only thing this route awaits.
        """
        name = unquote(request.headers.get("X-File-Name", "") or "")
        length = int(request.headers.get("Content-Length") or 0)
        payload = await request.body() if 0 < length <= MAX_BODY_BYTES else b""
        if not name or not payload:
            return JSONResponse({"ok": False}, status_code=HTTPStatus.BAD_REQUEST)
        site.accept_file(name, session=session)
        return JSONResponse({"ok": True, "file_name": name, "bytes": len(payload)})

    # -- everything else --------------------------------------------------- #

    @app.get("/{_rest:path}")
    @app.post("/{_rest:path}")
    def anything_else(_session: Session, _rest: str) -> Response:
        """Last, so it catches only what no route above did.

        Signed out, it is the login page like everything else; signed in, it is not
        there.
        """
        return not_found()

    return app


def serve(
    site: Site,
    *,
    port: int,
    host: str = "127.0.0.1",
    announce: Callable[[str], None] = wire.quiet,
    announce_sign_in: Callable[[str], None] = wire.quiet,
) -> MockServer:
    """Return a started server, listening. The caller closes it.

    Both links — the sign-in's and the export's — are on the address the socket
    really bound, which is where the browser's cookie is. The fetch goes through
    the source session (`45`), so the link has to be on the origin holding it;
    `port=0` in the mock's own tests is why this is asked of the socket rather
    than assumed from `ORIGIN`.
    """
    return wire.serve(
        lambda bound_host, bound_port: create_app(
            site,
            link_base=wire.origin_of(bound_host, bound_port),
            announce=announce,
            announce_sign_in=announce_sign_in,
        ),
        port=port,
        host=host,
    )
