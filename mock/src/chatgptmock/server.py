"""The mock chatgpt.com, as a served site.

One FastAPI application answering as two hosts, served by uvicorn over TLS on a
thread of its own: every decision about what the site *does* is in `site.py`,
and everything about what it *looks* like is in `pages.py`. What is here is the
wire — cookies, methods, status codes, JSON in and JSON out — on the core's
(`mockcore.wire`).

Three things about this site's wire are its own (§54):

- **Two hosts, one application.** The operator's resolver rule sends
  `chatgpt.com` and `auth.openai.com` both to this process, and the routes are
  the paths alone: the sign-in steps live under paths the site host never
  serves, and the pages spell the crossing between hosts as absolute addresses.
  A right pair on the auth host comes back to the site host with a one-time
  code, which is what becomes the session cookie — a cookie set on one host is
  not sent to the other, and this is the simplest chain, since none was observed.
- **Signed out, everything is the landing page.** The site root is the landing
  page with its **Log in** control; every other path redirects there.
- **The download wants a session.** The archive is served to the signed-in
  session and refused to anyone else, while the listing of links stays open: it
  stands in for the inbox, and the inbox is not the account. The link is on the
  site's own host, because that is where the browser's session cookie is.

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
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from mockcore import wire
from mockcore.exports import Export
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

from chatgptmock import AUTH_ORIGIN, SITE_ORIGIN, archive, pages
from chatgptmock.pages import EXPORT_PAGE_PATH, LOG_IN_PATH, SETTINGS_PATH, UNSUPPORTED_PATH
from chatgptmock.site import Chat, Site

LOGIN_REDIRECT_PATH = "/auth/login"
"""A live page on the site host, the sources report; the mock sends it on to the
auth host, since the chain between the two was not observed."""

CALLBACK_PATH = "/auth/callback"
"""Where the auth host sends a signed-in browser back to, with a one-time code."""

REFUSED = "That email address or password is not right."
"""The words are the mock's own: the auth host's screens are *unknown*."""

NEEDS_SESSION = "This export is served to the account that requested it. Sign in first."


class MessageIn(BaseModel):
    text: str = ""
    pasted: list[str] = []


class TitleIn(BaseModel):
    title: str = ""


def chat_json(chat: Chat, now: float) -> dict[str, Any]:
    return {
        "id": chat.id,
        "title": chat.title,
        "generating": chat.generating(now),
        "turns": [
            {
                "role": message.role,
                "text": message.text,
                "pasted": list(message.pasted),
                "files": [upload.name for upload in message.files],
            }
            for message in chat.view(now)
        ],
    }


def link_of(export: Export) -> str:
    """Return the link an ask gets: on the site's host, where the session cookie is (§54)."""
    return SITE_ORIGIN + wire.ARCHIVE_PATH.format(token=export.token)


# -- the application ---------------------------------------------------------- #


def create_app(  # ruff: ignore[complex-structure, too-many-statements] - one route per function
    site: Site,
    *,
    announce: Callable[[str], None] = wire.quiet,
) -> FastAPI:
    """Return the site as an ASGI application: every route the mock answers, on either host.

    A factory rather than a module-level `app`, because the site it serves is
    constructed per process — and per test. `announce` is told each link as it
    is minted; the CLI prints it where the vendor would have sent an email.
    """
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    logins = site.pending_logins
    codes = site.pending_codes

    Session = Annotated[str, Depends(wire.session_of(site.signed_in))]  # ruff: ignore[non-lowercase-variable-in-function] - it names a type

    @app.exception_handler(SignedOutError)
    def signed_out(_request: Request, _failure: SignedOutError) -> Response:
        return redirect("/")

    # -- the witness ------------------------------------------------------- #

    wire.witness(app, ledger=site.ledger, exports=site._exports, link_of=link_of)  # ruff: ignore[private-member-access] - the site's, handed to the core

    @app.get(wire.ARCHIVE_PATH)
    def download(request: Request, token: str) -> Response:
        """Serve the archive a link names — to the signed-in session, and to nobody else.

        Refused before the token is looked up, so a refused fetch is not a fetch
        the record counts. A token nobody minted is not found.
        """
        if not site.signed_in(request.cookies.get(SESSION_COOKIE)):
            return PlainTextResponse(NEEDS_SESSION, status_code=HTTPStatus.FORBIDDEN)
        if site.fetch_export(token) is None:
            return not_found()
        payload = archive.render(site.all_chats(), email=site.email, now=site.now())
        return Response(payload, media_type="application/zip")

    # -- the site host, signed out ------------------------------------------ #

    @app.get("/")
    def root(request: Request) -> Response:
        """Return the landing page signed out, and a new chat signed in."""
        if site.signed_in(request.cookies.get(SESSION_COOKIE)):
            return HTMLResponse(pages.chat_page(None, (), generating=False, sidebar=site.sidebar()))
        return HTMLResponse(pages.landing_page())

    @app.get(LOGIN_REDIRECT_PATH)
    def login_redirect() -> Response:
        return redirect(AUTH_ORIGIN + LOG_IN_PATH)

    @app.get(CALLBACK_PATH)
    def callback(code: str = "") -> Response:
        """Turn the auth host's one-time code into this host's session, and count the sign-in."""
        email = codes.pending(code)
        if not email:
            return redirect(AUTH_ORIGIN + LOG_IN_PATH + "?error=refused")
        codes.forget(code)
        return redirect("/", **{SESSION_COOKIE: site.sign_in()})

    # -- the auth host ------------------------------------------------------ #

    @app.get(LOG_IN_PATH)
    def login_page(request: Request, error: str = "") -> Response:
        token = request.cookies.get(LOGIN_COOKIE)
        cookies: dict[str, str] = {}
        if not token:
            token = logins.new_token()
            cookies[LOGIN_COOKIE] = token
        step = "password" if logins.pending(token) else "email"
        response = HTMLResponse(pages.login_page(step=step, error=REFUSED if error else ""))
        for name, value in cookies.items():
            set_cookie(response, name, value)
        return response

    @app.get(UNSUPPORTED_PATH)
    def unsupported_page() -> Response:
        return HTMLResponse(pages.unsupported_page())

    @app.post(LOG_IN_PATH + "/email")
    def submit_email(request: Request, email: Annotated[str, Form()] = "") -> Response:
        """Return the first step. Exactly one address gets past it (§54)."""
        token = request.cookies.get(LOGIN_COOKIE) or logins.new_token()
        if email != site.email:
            logins.forget(token)
            return redirect(LOG_IN_PATH + "?error=refused", **{LOGIN_COOKIE: token})
        logins.remember(token, email)
        return redirect(LOG_IN_PATH, **{LOGIN_COOKIE: token})

    @app.post(LOG_IN_PATH + "/password")
    def submit_password(request: Request, password: Annotated[str, Form()] = "") -> Response:
        """Return the second step: a wrong pair goes back to the email step, a right one to the site host."""
        token = request.cookies.get(LOGIN_COOKIE) or ""
        email = logins.pending(token)
        logins.forget(token)
        if not email or not site.credentials_match(email, password):
            return redirect(LOG_IN_PATH + "?error=refused")
        code = codes.new_token()
        codes.remember(code, email)
        return redirect(f"{SITE_ORIGIN}{CALLBACK_PATH}?code={code}")

    # -- the chats ---------------------------------------------------------- #

    @app.get("/c/{chat_id}")
    def chat_page(_session: Session, chat_id: str) -> Response:
        chat = site.chat(chat_id)
        if chat is None:
            return not_found()
        now = site.now()
        return HTMLResponse(
            pages.chat_page(chat, chat.view(now), generating=chat.generating(now), sidebar=site.sidebar())
        )

    @app.get("/api/chats/{chat_id}")
    def read_chat(_session: Session, chat_id: str) -> Response:
        chat = site.chat(chat_id)
        if chat is None:
            return not_found()
        return JSONResponse(chat_json(chat, site.now()))

    @app.post("/api/chats")
    def create_chat(session: Session, message: MessageIn) -> Response:
        chat = site.create_chat(message.text, pasted=message.pasted, session=session)
        return JSONResponse(chat_json(chat, site.now()))

    @app.post("/api/chats/{chat_id}/messages")
    def receive(session: Session, chat_id: str, message: MessageIn) -> Response:
        chat = site.chat(chat_id)
        if chat is None:
            return not_found()
        site.receive(chat, message.text, pasted=message.pasted, session=session)
        return JSONResponse(chat_json(chat, site.now()))

    @app.post("/api/chats/{chat_id}/stop")
    def stop(_session: Session, chat_id: str) -> Response:
        chat = site.chat(chat_id)
        if chat is None:
            return not_found()
        site.stop(chat)
        return JSONResponse(chat_json(chat, site.now()))

    @app.post("/api/chats/{chat_id}/title")
    def rename(_session: Session, chat_id: str, title: TitleIn) -> Response:
        chat = site.chat(chat_id)
        if chat is None:
            return not_found()
        site.rename(chat, title.title)
        return JSONResponse(chat_json(chat, site.now()))

    @app.post("/api/uploads")
    async def upload(session: Session, request: Request) -> Response:
        """Take a file into the composer.

        The bytes are read and dropped: what a walk checks is that the site took
        the file and showed its name, and what the archive names is the file and
        how large it was.
        """
        name = unquote(request.headers.get("X-File-Name", "") or "")
        length = int(request.headers.get("Content-Length") or 0)
        payload = await request.body() if 0 < length <= MAX_BODY_BYTES else b""
        if not name or not payload:
            return JSONResponse({"ok": False}, status_code=HTTPStatus.BAD_REQUEST)
        site.accept_file(name, len(payload), session=session)
        return JSONResponse({"ok": True, "file_name": name, "bytes": len(payload)})

    # -- settings and the export page -------------------------------------- #

    @app.get(SETTINGS_PATH)
    def settings_page(_session: Session) -> Response:
        return HTMLResponse(pages.settings_page())

    @app.get(EXPORT_PAGE_PATH)
    def export_page(_session: Session) -> Response:
        return HTMLResponse(pages.export_page())

    @app.post("/api/exports")
    def request_export(_session: Session) -> Response:
        """Take the ask: mint the link, count it, and say it where an email would go."""
        export = site.request_export()
        link = link_of(export)
        announce(link)
        return JSONResponse({"ok": True, "link": link})

    # -- everything else --------------------------------------------------- #

    @app.get("/{_rest:path}")
    @app.post("/{_rest:path}")
    def anything_else(_session: Session, _rest: str) -> Response:
        """Last, so it catches only what no route above did.

        Signed out, it is the landing page like everything else; signed in, it
        is not there.
        """
        return not_found()

    return app


def serve(
    site: Site,
    *,
    port: int,
    host: str = "127.0.0.1",
    announce: Callable[[str], None] = wire.quiet,
) -> MockServer:
    """Return a started server, listening on the site's own port. The caller closes it.

    The links are spelled with `SITE_ORIGIN` rather than with the socket: the
    browser reaches them carrying its session cookie, and nothing without one can
    fetch them from anywhere.
    """
    return wire.serve(
        lambda _host, _port: create_app(site, announce=announce),
        port=port,
        host=host,
    )


def serve_auth(site: Site, *, port: int, host: str = "127.0.0.1") -> MockServer:
    """Return a second started server, standing in for the auth host (`65`).

    The same app on a second socket, because the two hosts used to be told apart
    by the `Host` header the operator's resolver rule supplied and there is no
    rule any more. The app serves every path on both, which is what it did
    before: `/log-in` was only ever reached on the auth host and `/` only on the
    site's, so which socket asked has never been the question — the *redirects*
    between them are, and those are absolute (`SITE_ORIGIN`, `AUTH_ORIGIN`).
    """
    return wire.serve(lambda _host, _port: create_app(site), port=port, host=host)
