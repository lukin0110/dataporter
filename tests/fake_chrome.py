"""A browser that answers CDP without being a browser.

`tests/test_browser_probe.py` drives a real Chrome, because that is the only way
to know the page fixtures parse and the selectors match. Everything else — the
client's timeouts, the launcher's adoption rule, `session`'s tab picking — is
about our own code's behaviour when the browser answers in a particular way, and
saying "answer like this" is easier and faster than arranging for Chrome to.

The fake speaks the two halves of the protocol our client uses: the HTTP
endpoints (`/json/version`, `/json/list`, `/json/close/<id>`) and a WebSocket per
target. It records every command it is sent, so a test can assert what was asked
as well as what came back.
"""

import json
import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import dataclass, field
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Any, Self

from websockets.sync.server import Server, ServerConnection, serve

BROKEN_TARGET = "boom"
"""A target id the fake answers with a 500, for the failure that is not a race."""

HTTP_POLL_S = 0.01
"""How often the debug port's select loop wakes, and therefore what `stop_http`
costs.

`ThreadingHTTPServer.shutdown` sets a flag and blocks until the serving loop next
notices it, so a teardown costs one poll interval. The stdlib default is 0.5 s and
`22` measured what that came to: bringing the server up and answering a request is
2 ms, stopping it was 501 ms, and the WebSocket half — which has no such loop —
stops in about none. A full run builds 331 of these, so that was most of a
minute and a half spent in `select` timeouts — half the suite's runtime.

Ten milliseconds rather than zero: the loop still sleeps between wakeups, so an
idle fake costs a hundred syscalls a second instead of a busy spin.
"""


def free_port() -> int:
    """A port that was free a moment ago. As good as this gets without binding."""
    with closing(socket.socket()) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@dataclass
class FakeTarget:
    """One tab. `evaluate` is what `Runtime.evaluate` returns for it."""

    id: str
    url: str
    type: str = "page"
    evaluate: Any = field(default_factory=dict)


@dataclass
class Call:
    """One CDP command, as received."""

    method: str
    params: dict[str, Any]
    path: str


class FakeChrome:
    """An HTTP + WebSocket pair that answers like a browser on a debug port."""

    def __init__(
        self,
        *,
        browser_id: str = "fake-browser-id",
        targets: list[FakeTarget] | None = None,
        port: int = 0,
        responder: Callable[["FakeChrome", Call], dict[str, Any] | None] | None = None,
    ) -> None:
        self.browser_id = browser_id
        self.targets = (
            targets
            if targets is not None
            else [FakeTarget(id="page-1", url="https://claude.ai/new")]
        )
        self.calls: list[Call] = []
        self.responder = responder
        self.events: list[dict[str, Any]] = []
        """Pushed to a connection just before its next reply."""
        self._http_closed = False
        self._lock = threading.Lock()
        self._http = ThreadingHTTPServer(("127.0.0.1", port), self._handler_class())
        self._http_thread = threading.Thread(
            target=partial(self._http.serve_forever, poll_interval=HTTP_POLL_S),
            daemon=True,
        )
        self._ws: Server = serve(self._serve_websocket, "127.0.0.1", 0)
        self._ws_thread = threading.Thread(target=self._ws.serve_forever, daemon=True)

    # -- lifecycle ---------------------------------------------------------- #

    @property
    def port(self) -> int:
        return int(self._http.server_address[1])

    @property
    def ws_port(self) -> int:
        return int(self._ws.socket.getsockname()[1])

    def __enter__(self) -> Self:
        self._http_thread.start()
        self._ws_thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stop()

    @property
    def closed(self) -> bool:
        """Whether the debug port has stopped answering, as an exit looks."""
        return self._http_closed

    def stop(self) -> None:
        """Shut both halves down. From the test's thread, never a handler's."""
        self.stop_http()
        self._ws.shutdown()

    def stop_http(self) -> None:
        """Stop answering the debug port, which is what `responding()` asks.

        Separate from `stop` because `Browser.close` arrives on a WebSocket
        handler thread, and `Server.shutdown` joins those threads — including,
        deadlockingly, the one it was called from.
        """
        if self._http_closed:
            return
        self._http_closed = True
        self._http.shutdown()
        self._http.server_close()

    def push(self, event: dict[str, Any]) -> None:
        """Send an event to every open connection, unprompted, as Chrome does."""
        for connection in list(self._ws.connections):
            connection.send(json.dumps(event))

    @property
    def open_connections(self) -> int:
        """How many WebSockets are still attached. A leak shows up here."""
        return len(self._ws.connections)

    def target(self, target_id: str) -> FakeTarget | None:
        return next((item for item in self.targets if item.id == target_id), None)

    def methods(self) -> list[str]:
        return [call.method for call in self.calls]

    # -- the HTTP half ------------------------------------------------------ #

    def _version(self) -> dict[str, Any]:
        return {
            "Browser": "Chrome/141.0.0.0",
            "Protocol-Version": "1.3",
            "webSocketDebuggerUrl": (
                f"ws://127.0.0.1:{self.ws_port}/devtools/browser/{self.browser_id}"
            ),
        }

    def _list(self) -> list[dict[str, Any]]:
        return [
            {
                "id": item.id,
                "type": item.type,
                "url": item.url,
                # A real browser sends a title here. Our client drops it on the
                # floor, which is the point: see `cdp.Target`.
                "title": "a conversation title",
                "webSocketDebuggerUrl": (
                    f"ws://127.0.0.1:{self.ws_port}/devtools/page/{item.id}"
                ),
            }
            for item in self.targets
        ]

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - the stdlib spells it this way
                if self.path == "/json/version":
                    self._json(fake._version())
                elif self.path in ("/json/list", "/json"):
                    self._json(fake._list())
                elif self.path.startswith("/json/close/"):
                    target_id = self.path.rsplit("/", 1)[-1]
                    if target_id == BROKEN_TARGET:
                        self.send_error(500)
                        return
                    with fake._lock:
                        known = fake.target(target_id) is not None
                        fake.targets = [
                            item for item in fake.targets if item.id != target_id
                        ]
                    if not known:
                        # What a real Chrome does, verified against Chromium 141:
                        # `No such target id: X`, with a 404.
                        self.send_error(404, f"No such target id: {target_id}")
                        return
                    self._text("Target is closing")
                else:
                    self.send_error(404)

            def _json(self, payload: Any) -> None:
                self._body(json.dumps(payload).encode(), "application/json")

            def _text(self, payload: str) -> None:
                self._body(payload.encode(), "text/plain")

            def _body(self, body: bytes, content_type: str) -> None:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                """Silence."""

        return Handler

    # -- the WebSocket half -------------------------------------------------- #

    def _serve_websocket(self, connection: ServerConnection) -> None:
        path = connection.request.path
        for raw in connection:
            message = json.loads(raw)
            call = Call(
                method=str(message.get("method", "")),
                params=dict(message.get("params") or {}),
                path=path,
            )
            with self._lock:
                self.calls.append(call)
            for event in self._take_events():
                connection.send(json.dumps(event))
            reply = self._reply(call)
            if reply is None:
                # `Browser.close`: a real Chrome hangs up rather than answering.
                # The port goes first, so that a client which sees the socket
                # close can rely on the browser already being gone.
                self.stop_http()
                connection.close()
                return
            connection.send(json.dumps({"id": message.get("id"), **reply}))

    def _take_events(self) -> list[dict[str, Any]]:
        with self._lock:
            events, self.events = self.events, []
        return events

    def _reply(self, call: Call) -> dict[str, Any] | None:
        if self.responder is not None:
            override = self.responder(self, call)
            if override is not None:
                return override
        return self._default_reply(call)

    def _default_reply(self, call: Call) -> dict[str, Any] | None:
        target_id = call.path.rsplit("/", 1)[-1]
        target = self.target(target_id)
        if call.method == "Browser.close":
            return None
        if call.method == "Runtime.evaluate":
            value = target.evaluate if target is not None else None
            if callable(value):
                value = value(call)
            return {"result": {"result": {"value": value}}}
        if call.method == "Page.navigate":
            if target is not None:
                target.url = str(call.params.get("url", target.url))
            return {"result": {}}
        if call.method == "Target.createTarget":
            created = FakeTarget(
                id=f"page-{len(self.targets) + 1}", url=str(call.params.get("url", ""))
            )
            with self._lock:
                self.targets.append(created)
            return {"result": {"targetId": created.id}}
        if call.method == "DOM.getDocument":
            return {"result": {"root": {"nodeId": 1}}}
        if call.method == "DOM.querySelector":
            found = "missing" not in str(call.params.get("selector", ""))
            return {"result": {"nodeId": 2 if found else 0}}
        if call.method in ("Page.enable", "Input.insertText", "DOM.setFileInputFiles"):
            return {"result": {}}
        return {"error": {"code": -32601, "message": f"'{call.method}' wasn't found"}}


def dialog_event(kind: str = "alert") -> dict[str, Any]:
    """A `Page.javascriptDialogOpening` event, as Chrome sends it."""
    return {
        "method": "Page.javascriptDialogOpening",
        "params": {
            "type": kind,
            "message": "are you sure?",
            "url": "https://claude.ai/new",
        },
    }


def dialog_closed_event(result: bool = True) -> dict[str, Any]:
    return {"method": "Page.javascriptDialogClosed", "params": {"result": result}}


def page_state(**overrides: Any) -> dict[str, Any]:
    """What `probe.PAGE_STATE_JS` returns, with the fields a test cares about."""
    state: dict[str, Any] = {
        "url": "https://claude.ai/new",
        "composer_present": True,
        "composer_chars": 0,
        "generating": False,
        "send_enabled": False,
        "dom_dialogs": 0,
    }
    state.update(overrides)
    return state


def targets_for(*urls: str) -> Iterator[FakeTarget]:
    for index, url in enumerate(urls, start=1):
        yield FakeTarget(id=f"page-{index}", url=url, evaluate=page_state(url=url))
