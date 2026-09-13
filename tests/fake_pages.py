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

from dataporter.browser import export_page

FIXTURES = Path(__file__).parent / "fixtures" / "pages"

CHAT_ID = "11111111-2222-4333-8444-555555555555"
GENERATING_CHAT_ID = "66666666-7777-4888-8999-aaaaaaaaaaaa"
RESPONDING_CHAT_ID = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"
MIGRATED_CHAT_ID = "dddddddd-eeee-4fff-8aaa-bbbbbbbbbbbb"

MIGRATED_SOURCE = "aa000001-1111-4111-8111-111111111111"
MIGRATED_PARTS = 2
MIGRATED_TITLE = "Notes on pooling"
"""What `migrated.html` is a chat of: the source conversation it was migrated
from, how many parts it became, and what the rename step called it. `17`'s
expectations are built from these rather than from the HTML, so a fixture edited
without its expectations fails rather than passes differently."""

ROUTES: dict[str, str] = {
    "/login": "login.html",
    "/login/form": "login-form.html",
    "/new": "new.html",
    f"/chat/{CHAT_ID}": "chat.html",
    f"/chat/{GENERATING_CHAT_ID}": "generating.html",
    f"/chat/{RESPONDING_CHAT_ID}": "responding.html",
    f"/chat/{MIGRATED_CHAT_ID}": "migrated.html",
    "/settings/profile": "dialog.html",
    export_page.EXPORT_PAGE_PATH: "settings-export.html",
}
"""Path to fixture. `/settings/profile` is deliberately a real page: `08` needs
somewhere outside the migration surface to point its safety gate at.

The export page is served at the path `31` names rather than at one of its own,
so that a corrected UI map moves the fixture with the code and no second
spelling of the path exists here."""


class _Handler(BaseHTTPRequestHandler):
    routes: Mapping[str, str] = ROUTES
    directory: Path = FIXTURES

    def do_GET(self) -> None:
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

    def log_message(self, fmt: str, *args: object) -> None:
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
