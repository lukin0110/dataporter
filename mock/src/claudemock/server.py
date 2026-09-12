"""The mock, as a served site.

One threaded HTTPS server, a handler that is a routing table, and nothing else:
every decision about what the site *does* is in `site.py`, and everything about
what it *looks* like is in `pages.py`. What is here is the wire — cookies,
methods, status codes, JSON in and JSON out — and the reachability block the
operator is told to paste.

Three things about it are worth knowing:

- **It is HTTPS, always.** The tool refuses every URL that is not
  `https://claude.ai/…` (§17, §22), and that refusal is what a rehearsal is
  partly there to exercise. Serving plain HTTP would make the mock reachable only
  by a tool that had been told to accept it, which is the door in the wall ADR
  0001 refuses.
- **It is stateful and it is in memory.** A rehearsal in several sessions sees
  the same chats throughout; restarting the process resets it.
- **It counts.** Every request that does something — a sign-in, a chat, a
  message, a file, a rename — goes through the ledger, which is the only witness
  a rehearsal record can reconcile against (§25).
"""

import json
import secrets
import ssl
import threading
from collections.abc import Mapping
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import BaseServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

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

MAX_UPLOAD_BYTES = 32 * 1024 * 1024
MAX_BODY_BYTES = 8 * 1024 * 1024
"""A seed is tens of kilobytes and a rehearsal attachment is smaller still.
A cap because this reads `Content-Length` off the wire."""

REFUSED = "Those details do not match an account here."

POLL_INTERVAL_S = 0.05
"""How often `serve_forever` looks for a shutdown. The default is half a second,
and `shutdown()` waits for it — which is half a second of teardown per test that
starts a mock, and the same half-second `22` took out of the tool's own slow
half. It costs twenty wake-ups a second in a process that is otherwise idle."""


class Handler(BaseHTTPRequestHandler):
    """Every route the mock answers, in one place.

    `protocol_version` is HTTP/1.1 because Chrome keeps the connection open and
    a server that answered 1.0 would make every request a new TLS handshake —
    which shows up as a rehearsal that is slower than the pacing it configured.
    """

    protocol_version = "HTTP/1.1"
    site: Site

    # -- plumbing ----------------------------------------------------------- #

    @property
    def route(self) -> str:
        return urlparse(self.path).path

    @property
    def query(self) -> Mapping[str, list[str]]:
        return parse_qs(urlparse(self.path).query)

    def cookie(self, name: str) -> str | None:
        jar = SimpleCookie(self.headers.get("Cookie", ""))
        found = jar.get(name)
        return found.value if found is not None else None

    def session(self) -> str | None:
        token = self.cookie(SESSION_COOKIE)
        return token if self.site.signed_in(token) else None

    def body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            return b""
        return self.rfile.read(length)

    def payload(self) -> dict[str, Any]:
        raw = self.body()[:MAX_BODY_BYTES]
        try:
            loaded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def form(self) -> Mapping[str, list[str]]:
        return parse_qs(self.body().decode("utf-8", "replace"))

    def reply(
        self,
        status: HTTPStatus,
        content: bytes = b"",
        *,
        content_type: str = "text/html; charset=utf-8",
        cookies: Mapping[str, str] = {},
        location: str = "",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        for name, value in cookies.items():
            lifetime = (
                f"; Max-Age={SESSION_MAX_AGE_S}" if name == SESSION_COOKIE else ""
            )
            self.send_header("Set-Cookie", f"{name}={value}; Path=/{lifetime}")
        if location:
            self.send_header("Location", location)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)

    def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.reply(
            status,
            json.dumps(payload).encode(),
            content_type="application/json",
        )

    def redirect(self, location: str, **cookies: str) -> None:
        self.reply(HTTPStatus.SEE_OTHER, location=location, cookies=cookies)

    def not_found(self) -> None:
        self.reply(HTTPStatus.NOT_FOUND, b"not found", content_type="text/plain")

    def log_message(self, format: str, *args: object) -> None:
        """Silence. A rehearsal's terminal belongs to the tool."""

    # -- GET ---------------------------------------------------------------- #

    def do_GET(self) -> None:  # noqa: N802 - the stdlib spells it this way
        route = self.route
        if route == LEDGER_PATH:
            self.reply(
                HTTPStatus.OK,
                self.site.ledger.block().encode(),
                content_type="text/plain; charset=utf-8",
            )
            return
        if route == LEDGER_JSON_PATH:
            self.send_json(self.site.counters())
            return
        if route == "/login":
            self.login_page()
            return
        if route == "/login/unsupported":
            self.reply(HTTPStatus.OK, pages.unsupported_page())
            return
        if self.session() is None:
            # `signed out`: everything but the login page redirects to it, and
            # the login page has no composer — which is how the tool's probe
            # reads a session that has expired.
            self.redirect("/login")
            return
        if route in ("/", "/new"):
            self.reply(HTTPStatus.OK, pages.chat_page(None, (), generating=False))
            return
        if route.startswith("/chat/"):
            self.chat_page(route.removeprefix("/chat/").rstrip("/"))
            return
        if route.startswith("/api/chats/"):
            self.chat_json(route.removeprefix("/api/chats/").rstrip("/"))
            return
        self.not_found()

    def login_page(self) -> None:
        if self.session() is not None:
            self.redirect("/new")
            return
        token = self.cookie(LOGIN_COOKIE)
        cookies: dict[str, str] = {}
        if not token:
            token = self.server_state().new_login_token()
            cookies[LOGIN_COOKIE] = token
        step = "password" if self.server_state().pending(token) else "email"
        self.reply(
            HTTPStatus.OK,
            pages.login_page(
                step=step,
                banner=self.cookie(BANNER_COOKIE) != "dismissed",
                error=REFUSED if self.query.get("error") else "",
            ),
            cookies=cookies,
        )

    def chat_page(self, chat_id: str) -> None:
        chat = self.site.chat(chat_id)
        if chat is None:
            self.not_found()
            return
        now = self.site.now()
        self.reply(
            HTTPStatus.OK,
            pages.chat_page(chat, chat.view(now), generating=chat.generating(now)),
        )

    def chat_json(self, chat_id: str) -> None:
        chat = self.site.chat(chat_id)
        if chat is None:
            self.not_found()
            return
        self.send_json(_chat_json(chat, self.site.now()))

    # -- POST --------------------------------------------------------------- #

    def do_POST(self) -> None:  # noqa: N802 - the stdlib spells it this way
        route = self.route
        if route == "/login/email":
            self.submit_email()
            return
        if route == "/login/password":
            self.submit_password()
            return
        session = self.session()
        if session is None:
            self.redirect("/login")
            return
        if route == "/api/chats":
            self.create_chat(session)
            return
        if route == "/api/uploads":
            self.upload(session)
            return
        if route.startswith("/api/chats/"):
            rest = route.removeprefix("/api/chats/")
            chat_id, _, action = rest.partition("/")
            chat = self.site.chat(chat_id)
            if chat is None:
                self.not_found()
                return
            if action == "messages":
                self.site.receive(chat, str(self.payload().get("text", "")))
                self.send_json(_chat_json(chat, self.site.now()))
                return
            if action == "title":
                self.site.rename(chat, str(self.payload().get("title", "")))
                self.send_json(_chat_json(chat, self.site.now()))
                return
        self.not_found()

    def submit_email(self) -> None:
        """The first step. Exactly one address gets past it (§21)."""
        token = self.cookie(LOGIN_COOKIE) or self.server_state().new_login_token()
        email = (self.form().get("email") or [""])[0]
        if email != self.site.email:
            self.server_state().forget(token)
            self.redirect("/login?error=refused", **{LOGIN_COOKIE: token})
            return
        self.server_state().remember(token, email)
        self.redirect("/login", **{LOGIN_COOKIE: token})

    def submit_password(self) -> None:
        token = self.cookie(LOGIN_COOKIE) or ""
        email = self.server_state().pending(token)
        password = (self.form().get("password") or [""])[0]
        if not email or not self.site.credentials_match(email, password):
            self.server_state().forget(token)
            self.redirect("/login?error=refused")
            return
        self.server_state().forget(token)
        self.redirect("/new", **{SESSION_COOKIE: self.site.sign_in()})

    def create_chat(self, session: str) -> None:
        text = str(self.payload().get("text", ""))
        chat = self.site.create_chat(text, session=session)
        self.send_json(_chat_json(chat, self.site.now()))

    def upload(self, session: str) -> None:
        """A file into the composer. The bytes are read and dropped: what a
        rehearsal checks is that the site took the file and showed its name."""
        name = unquote(self.headers.get("X-File-Name", "") or "")
        payload = self.body()
        if not name or not payload:
            self.send_json({"ok": False}, HTTPStatus.BAD_REQUEST)
            return
        self.site.accept_file(name, session=session)
        self.send_json({"ok": True, "file_name": name, "bytes": len(payload)})

    # -- the server this handler belongs to ---------------------------------- #

    def server_state(self) -> "MockServer":
        server: Any = self.server
        return server


def _chat_json(chat: Chat, now: float) -> dict[str, Any]:
    return {
        "id": chat.id,
        "title": chat.title,
        "generating": chat.generating(now),
        "files": list(chat.files),
        "turns": [{"role": turn.role, "text": turn.text} for turn in chat.view(now)],
    }


class MockServer(ThreadingHTTPServer):
    """The HTTPS server, plus the half-finished sign-ins it is holding.

    A sign-in is two requests, and what joins them is a cookie this server
    minted — so the pending address lives here rather than in `Site`, which is
    about chats and accounts and knows nothing about HTTP.
    """

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], site: Site) -> None:
        handler = type("BoundHandler", (Handler,), {"site": site})
        super().__init__(address, handler)
        self.site = site
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


def serve(
    site: Site,
    *,
    port: int,
    host: str = "127.0.0.1",
    material: certificate.Material,
) -> MockServer:
    """A started server, listening. The caller closes it."""
    server = MockServer((host, port), site)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(
        certfile=Path(material.cert_path), keyfile=Path(material.key_path)
    )
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(
        target=server.serve_forever, args=(POLL_INTERVAL_S,), daemon=True
    )
    thread.start()
    return server


def port_of(server: BaseServer) -> int:
    address: Any = server.server_address
    return int(address[1])
