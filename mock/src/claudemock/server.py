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
from urllib.parse import unquote

from fastapi import Depends, FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from mockcore import certificate, wire
from mockcore.exports import Export
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

EXPORT_PAGE_PATH = "/settings/data-privacy-controls"
"""Where the site lets a user ask for their data: the tool's own
`export_page.EXPORT_PAGE_PATH`, re-typed because the mock imports nothing from it
(ADR 0003). The row is `*unknown*` in the UI map; correcting it corrects both
spellings, one line each."""

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
    pending: Pending = site.pending_sign_ins

    def link_of(export: Export) -> str:
        return link_base + wire.ARCHIVE_PATH.format(token=export.token)

    def sign_in_link_json(link: SignInLink) -> dict[str, Any]:
        return {"token": link.token, "link": site.link_of(link), "minted_at": link.minted_at, "spent": link.spent}

    Session = Annotated[str, Depends(wire.session_of(site.signed_in))]  # ruff: ignore[non-lowercase-variable-in-function] - it names a type

    @app.exception_handler(SignedOutError)
    def signed_out(_request: Request, _failure: SignedOutError) -> Response:
        return redirect("/login")

    # -- the witness ------------------------------------------------------- #

    wire.witness(app, ledger=site.ledger, exports=site._exports, link_of=link_of)  # ruff: ignore[private-member-access] - the site's, handed to the core

    @app.get(wire.ARCHIVE_PATH)
    def download(token: str) -> Response:
        """Serve the archive a link names. No session: the fetch carries no cookies.

        A token nobody minted is not found, which the tool reports as
        `link refused: HTTP 404` and leaves the ask open — a dead link (§39, 5),
        as near as a mock with no clock to expire on can come to one.
        """
        if site.fetch_export(token) is None:
            return not_found()
        payload = archive.render(site.all_chats(), email=site.email, now=site.now())
        return Response(payload, media_type="application/zip")

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

    # -- the export page (`32`) --------------------------------------------- #

    @app.get(EXPORT_PAGE_PATH)
    def export_page(_session: Session) -> Response:
        return HTMLResponse(pages.export_page())

    @app.post("/api/exports")
    def request_export(_session: Session) -> Response:
        """Take the ask: mint the link, count it, and say it where an email would go.

        The page never shows the link — the tool reads a status region, not a
        sentence — so the response carries it for whoever is reading the wire.
        """
        export = site.request_export()
        link = link_of(export)
        announce(link)
        return JSONResponse({"ok": True, "link": link})

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
    material: certificate.Material,
    announce: Callable[[str], None] = wire.quiet,
    announce_sign_in: Callable[[str], None] = wire.quiet,
) -> MockServer:
    """Return a started server, listening. The caller closes it.

    The link base is spelled from the address and port the socket really got —
    `0` asks for any port — so an export link points at this process and no
    other. A host other than the loopback address is one the tool's fetch cannot
    trust (the certificate names `127.0.0.1` alone), and `cli.serve` says so. A
    sign-in link is on `claude.ai` itself, where Chrome's resolver rule sends it.
    """
    return wire.serve(
        lambda bound_host, bound_port: create_app(
            site,
            link_base=f"https://{bound_host}:{bound_port}",
            announce=announce,
            announce_sign_in=announce_sign_in,
        ),
        port=port,
        host=host,
        material=material,
    )
