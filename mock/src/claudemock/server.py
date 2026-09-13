"""The mock, as a served site.

One FastAPI application, served by uvicorn over TLS on a thread of its own, and
nothing else: every decision about what the site *does* is in `site.py`, and
everything about what it *looks* like is in `pages.py`. What is here is the
wire — cookies, methods, status codes, JSON in and JSON out — and the
reachability block the operator is told to paste.

Three things about it are worth knowing:

- **It is HTTPS, always.** The tool refuses every URL that is not
  `https://claude.ai/…` — `08`'s resolution of §17, kept by §22 — and that
  refusal is part of what a rehearsal exercises. Serving plain HTTP would make
  the mock reachable only by a tool that had been told to accept it, which is
  the door in the wall ADR 0001 refuses.
- **It is stateful and it is in memory.** A rehearsal in several sessions sees
  the same chats throughout; restarting the process resets it.
- **It counts.** Every request that does something — a sign-in, a chat, a
  message, a file, a rename — goes through the ledger, which is the only witness
  a rehearsal record can reconcile against (§25).

The routes are plain `def`s rather than `async def`s on purpose: `Site` is
synchronous and guards its state with a lock, so FastAPI runs each route on a
worker thread and the lock keeps doing its job. The one exception reads an
upload's body, which is the only thing in the mock worth awaiting.
"""

import secrets
import socket
import threading
import time
from http import HTTPStatus
from typing import Annotated, Any
from urllib.parse import unquote

import uvicorn
from fastapi import Depends, FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.responses import RedirectResponse as _RedirectResponse
from pydantic import BaseModel

from claudemock import certificate, pages
from claudemock.site import Chat, Site

SESSION_COOKIE = "mock_session"
LOGIN_COOKIE = "mock_login"
BANNER_COOKIE = "mock_banner"

LEDGER_PATH = "/__mock/ledger"
LEDGER_JSON_PATH = "/__mock/ledger.json"
"""Outside the surface any helper will drive, and deliberately not a claude.ai
path: nothing the tool does can reach it, which is what keeps the witness
independent of the thing it is a witness to."""

SESSION_MAX_AGE_S = 7 * 24 * 60 * 60
"""How long a signed-in session lasts. Long enough to survive the browser being
closed and started again, which is what `login` storing a session in the
workspace profile means: a cookie with no lifetime is discarded when Chrome
exits, and every later command would sign in again."""

MAX_BODY_BYTES = 32 * 1024 * 1024
"""A seed is tens of kilobytes and a rehearsal attachment is smaller still. A
cap because the mock reads whatever `Content-Length` promises into memory."""

REFUSED = "Those details do not match an account here."

STARTUP_TIMEOUT_S = 10.0
"""How long `serve` waits for uvicorn to report that it is accepting
connections before giving up. Starting takes milliseconds; the timeout exists
so a failure to start is an error rather than a hang."""


class Pending:
    """The half-finished sign-ins the site is holding.

    A sign-in is two requests, and what joins them is a cookie this server
    minted — so the pending address lives here rather than in `Site`, which is
    about chats and accounts and knows nothing about HTTP.
    """

    def __init__(self) -> None:
        self._pending: dict[str, str] = {}
        self._lock = threading.Lock()

    def new_login_token(self) -> str:
        return secrets.token_hex(8)

    def remember(self, token: str, email: str) -> None:
        with self._lock:
            self._pending[token] = email

    def pending(self, token: str | None) -> str:
        with self._lock:
            return self._pending.get(token or "", "")

    def forget(self, token: str | None) -> None:
        with self._lock:
            self._pending.pop(token or "", None)


class SignedOutError(Exception):
    """Raised by a route that needs a session and was not given one.

    The handler turns it into the redirect to `/login`, so that `signed out` —
    everything but the login page redirects to it, and the login page has no composer —
    is one line in every route that needs it.
    """


class MessageIn(BaseModel):
    text: str = ""


class TitleIn(BaseModel):
    title: str = ""


# -- responses ---------------------------------------------------------------- #


def set_cookie(response: Response, name: str, value: str) -> None:
    """Set a cookie for the whole site. Only the session has a lifetime."""
    response.set_cookie(
        name,
        value,
        path="/",
        max_age=SESSION_MAX_AGE_S if name == SESSION_COOKIE else None,
    )


def redirect(location: str, **cookies: str) -> Response:
    response = _RedirectResponse(location, status_code=HTTPStatus.SEE_OTHER)
    for name, value in cookies.items():
        set_cookie(response, name, value)
    return response


def not_found() -> Response:
    return PlainTextResponse("not found", status_code=HTTPStatus.NOT_FOUND)


def chat_json(chat: Chat, now: float) -> dict[str, Any]:
    return {
        "id": chat.id,
        "title": chat.title,
        "generating": chat.generating(now),
        "files": list(chat.files),
        "turns": [{"role": turn.role, "text": turn.text} for turn in chat.view(now)],
    }


# -- the application ---------------------------------------------------------- #


def create_app(site: Site) -> FastAPI:  # ruff: ignore[complex-structure, too-many-statements] - one route per function
    """Return the site as an ASGI application: every route the mock answers.

    A factory rather than a module-level `app`, because the site it serves is
    constructed per process — and per test, which is what keeps the tests of
    the wire independent of one another.
    """
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    pending = Pending()

    def session(request: Request) -> str:
        token = request.cookies.get(SESSION_COOKIE)
        if not site.signed_in(token):
            raise SignedOutError
        return str(token)

    Session = Annotated[str, Depends(session)]  # ruff: ignore[non-lowercase-variable-in-function] - it names a type

    @app.exception_handler(SignedOutError)
    def signed_out(_request: Request, _failure: SignedOutError) -> Response:
        return redirect("/login")

    # -- the witness ------------------------------------------------------- #

    @app.get(LEDGER_PATH)
    def ledger_block() -> Response:
        return PlainTextResponse(site.ledger.block())

    @app.get(LEDGER_JSON_PATH)
    def ledger_json() -> dict[str, int]:
        return site.counters()

    # -- sign-in ----------------------------------------------------------- #

    @app.get("/login")
    def login_page(request: Request, error: str = "") -> Response:
        if site.signed_in(request.cookies.get(SESSION_COOKIE)):
            return redirect("/new")
        token = request.cookies.get(LOGIN_COOKIE)
        cookies: dict[str, str] = {}
        if not token:
            token = pending.new_login_token()
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
        token = request.cookies.get(LOGIN_COOKIE) or pending.new_login_token()
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


# -- serving it --------------------------------------------------------------- #


class MockServer:
    """The HTTPS server, running on its own thread until it is closed."""

    def __init__(self, app: FastAPI, sock: socket.socket, material: certificate.Material) -> None:
        self.app = app
        self._socket = sock
        self._server = uvicorn.Server(
            uvicorn.Config(
                app,
                ssl_certfile=material.cert_path,
                ssl_keyfile=material.key_path,
                # Quiet: a rehearsal's terminal belongs to the tool. No access
                # log and no logging configuration of uvicorn's own, so nothing
                # below a warning is printed and a warning still is.
                log_config=None,
                log_level="warning",
                access_log=False,
                lifespan="off",
            )
        )
        self._failure: BaseException | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        """Run the thread's body.

        Uvicorn, and whatever stopped it, kept for `start` to report rather than printed
        by the thread on its way out.
        """
        try:
            self._server.run(sockets=[self._socket])
        except BaseException as failure:  # ruff: ignore[blind-except] — whatever stopped it is the report
            self._failure = failure

    @property
    def port(self) -> int:
        return int(self._socket.getsockname()[1])

    def start(self, timeout_s: float = STARTUP_TIMEOUT_S) -> None:
        """Start the thread and wait until uvicorn is accepting connections.

        A start that fails closes what it opened: the port is released rather than held
        by a thread nobody will join.
        """
        self._thread.start()
        try:
            self._await_started(time.monotonic() + timeout_s)
        except BaseException:
            self.close()
            raise

    def _await_started(self, deadline: float) -> None:
        """Block until uvicorn reports itself started, or say why it never will."""
        while not self._server.started:
            if not self._thread.is_alive():
                raise RuntimeError("the mock's server stopped before it started") from self._failure
            if time.monotonic() > deadline:
                raise RuntimeError("the mock's server did not start in time")
            time.sleep(0.005)

    def close(self) -> None:
        """Stop accepting, finish what is in flight, and release the port."""
        self._server.should_exit = True
        if self._thread.is_alive():
            self._thread.join()
        self._socket.close()


def listen(host: str, port: int) -> socket.socket:
    """Return a bound socket, before the server exists.

    Binding here rather than in uvicorn is what makes `port=0` answerable — the tests
    ask for any free port and need to know which one they got — and what makes a port
    already in use an error in the caller's thread rather than in the server's.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError:
        sock.close()
        raise
    return sock


def serve(
    site: Site,
    *,
    port: int,
    host: str = "127.0.0.1",
    material: certificate.Material,
) -> MockServer:
    """Return a started server, listening. The caller closes it."""
    sock = listen(host, port)
    try:
        server = MockServer(create_app(site), sock, material)
    except BaseException:
        sock.close()
        raise
    server.start()
    return server
