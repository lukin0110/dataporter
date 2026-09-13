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

The routes are plain `def`s rather than `async def`s on purpose: `Site` is
synchronous and guards its state with a lock, so FastAPI runs each route on a
worker thread and the lock keeps doing its job. The one exception reads an
upload's body, which is the only thing in the mock worth awaiting.
"""

from collections.abc import Callable
from http import HTTPStatus
from typing import Annotated, Any
from urllib.parse import unquote

from fastapi import Depends, FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from mockcore import certificate, wire
from mockcore.exports import Export
from mockcore.sessions import Pending
from mockcore.wire import (
    LOGIN_COOKIE,
    MAX_BODY_BYTES,
    SESSION_COOKIE,
    MockServer,
    SignedOutError,
    not_found,
    redirect,
    set_cookie,
)
from pydantic import BaseModel

from claudemock import archive, pages
from claudemock.site import Chat, Site

BANNER_COOKIE = "mock_banner"

EXPORT_PAGE_PATH = "/settings/data-privacy-controls"
"""Where the site lets a user ask for their data: the tool's own
`export_page.EXPORT_PAGE_PATH`, re-typed because the mock imports nothing from it
(ADR 0003). The row is `*unknown*` in the UI map; correcting it corrects both
spellings, one line each."""

REFUSED = "Those details do not match an account here."


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
) -> FastAPI:
    """Return the site as an ASGI application: every route the mock answers.

    A factory rather than a module-level `app`, because the site it serves is
    constructed per process — and per test, which is what keeps the tests of
    the wire independent of one another. `link_base` is the origin an export link
    is spelled with, and `announce` is told each link as it is minted — the CLI
    prints it where the vendor would have sent an email.
    """
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    pending = Pending()

    def link_of(export: Export) -> str:
        return link_base + wire.ARCHIVE_PATH.format(token=export.token)

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

    # -- sign-in ----------------------------------------------------------- #

    @app.get("/login")
    def login_page(request: Request, error: str = "") -> Response:
        if site.signed_in(request.cookies.get(SESSION_COOKIE)):
            return redirect("/new")
        token = request.cookies.get(LOGIN_COOKIE)
        cookies: dict[str, str] = {}
        if not token:
            token = pending.new_token()
            cookies[LOGIN_COOKIE] = token
        step = "password" if pending.pending(token) else "email"
        response = HTMLResponse(
            pages.login_page(
                step=step,
                banner=request.cookies.get(BANNER_COOKIE) != "dismissed",
                error=REFUSED if error else "",
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
        """Return the first step. Exactly one address gets past it (§21)."""
        token = request.cookies.get(LOGIN_COOKIE) or pending.new_token()
        if email != site.email:
            pending.forget(token)
            return redirect("/login?error=refused", **{LOGIN_COOKIE: token})
        pending.remember(token, email)
        return redirect("/login", **{LOGIN_COOKIE: token})

    @app.post("/login/password")
    def submit_password(request: Request, password: Annotated[str, Form()] = "") -> Response:
        token = request.cookies.get(LOGIN_COOKIE) or ""
        email = pending.pending(token)
        if not email or not site.credentials_match(email, password):
            pending.forget(token)
            return redirect("/login?error=refused")
        pending.forget(token)
        return redirect("/new", **{SESSION_COOKIE: site.sign_in()})

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
) -> MockServer:
    """Return a started server, listening. The caller closes it.

    The link base is spelled from the address and port the socket really got —
    `0` asks for any port — so an export link points at this process and no
    other. A host other than the loopback address is one the tool's fetch cannot
    trust (the certificate names `127.0.0.1` alone), and `cli.serve` says so.
    """
    return wire.serve(
        lambda bound_host, bound_port: create_app(
            site, link_base=f"https://{bound_host}:{bound_port}", announce=announce
        ),
        port=port,
        host=host,
        material=material,
    )
