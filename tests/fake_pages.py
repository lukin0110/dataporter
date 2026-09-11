"""A local stand-in for claude.ai.

The checked-in page fixtures, served over HTTP at the paths the real application
uses, so that `probe` can be tested against a real browser rendering real HTML
rather than against a mocked CDP reply. `kind_of` reads the path and never the
host, which is what makes `http://127.0.0.1:PORT/new` a usable `/new`.
"""

import threading
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import TracebackType
from typing import Self

FIXTURES = Path(__file__).parent / "fixtures" / "pages"

CHAT_ID = "11111111-2222-4333-8444-555555555555"
GENERATING_CHAT_ID = "66666666-7777-4888-8999-aaaaaaaaaaaa"
RESPONDING_CHAT_ID = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"

ROUTES: dict[str, str] = {
    "/login": "login.html",
    "/new": "new.html",
    f"/chat/{CHAT_ID}": "chat.html",
    f"/chat/{GENERATING_CHAT_ID}": "generating.html",
    f"/chat/{RESPONDING_CHAT_ID}": "responding.html",
    "/settings/profile": "dialog.html",
}
"""Path to fixture. `/settings/profile` is deliberately a real page: `08` needs
somewhere outside the migration surface to point its safety gate at."""


class _Handler(BaseHTTPRequestHandler):
    routes: Mapping[str, str] = ROUTES
    directory: Path = FIXTURES

    def do_GET(self) -> None:  # noqa: N802 - the stdlib spells it this way
        path = self.path.split("?", 1)[0]
        name = self.routes.get(path)
        if name is None:
            self.send_error(404)
            return
        body = (self.directory / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Silence. The default writes a line to stderr per request."""


class PageServer:
    """The fixtures on an ephemeral port. A context manager, and cheap to start."""

    def __init__(self, directory: Path = FIXTURES) -> None:
        handler = type("_BoundHandler", (_Handler,), {"directory": directory})
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def url(self, path: str = "/new") -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
