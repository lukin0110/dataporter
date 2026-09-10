"""A minimal synchronous Chrome DevTools Protocol client.

Small on purpose. This is not a browser-automation library: it is the four or
five CDP calls `07` and `08` need, each with a timeout, each raising
`BrowserError` when the browser does something other than answer. Anything an
LLM drives goes through Hermes's own `browser_*` tools; nothing here is ever
exposed to a model.

Synchronous, because the whole tool is: one conversation at a time, one browser,
no asyncio (`specs/README.md`). `websockets.sync.client` gives a blocking
connection with per-call timeouts, which is exactly the shape wanted.

## What is deliberately missing

`Target` has no `title`. A claude.ai tab's title *is* a conversation title, and
§10 keeps titles off stdout and out of the logs; a field that does not exist
cannot be printed by `08`'s helpers or interpolated into a log message by
accident.

## Proxies

Every endpoint here is on `127.0.0.1`. The HTTP calls install an empty
`ProxyHandler` and the WebSocket calls pass `proxy=None`, so an `HTTP_PROXY` or
`HTTPS_PROXY` in the operator's environment — normal on a corporate machine, and
the default in a container — can never be consulted for the local browser.
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlparse

from websockets.exceptions import WebSocketException
from websockets.sync.client import ClientConnection, connect

from dataporter import log
from dataporter.errors import BrowserError

_logger = log.get_logger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9222
DEFAULT_TIMEOUT_S = 20.0

MAX_MESSAGE_BYTES = 64 * 1024 * 1024
"""Ceiling on one CDP frame. The default is 1 MB, and `Runtime.evaluate`
returning the composer's `innerText` after a 400 kB seed would exceed it."""

PAGE_TARGET = "page"

_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass(frozen=True)
class Target:
    """One CDP target: a tab, a worker, the browser itself."""

    id: str
    type: str
    url: str
    websocket_url: str

    @property
    def host(self) -> str:
        """The hostname of `url`, or `""` for `about:blank` and friends."""
        return urlparse(self.url).hostname or ""

    @property
    def is_page(self) -> bool:
        return self.type == PAGE_TARGET

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> Self:
        return cls(
            id=str(payload.get("id", "")),
            type=str(payload.get("type", "")),
            url=str(payload.get("url", "")),
            websocket_url=str(payload.get("webSocketDebuggerUrl", "")),
        )


class HttpStatusError(BrowserError):
    """A CDP HTTP endpoint answered with an error status.

    Carries the status because one of them is not really an error: Chrome
    answers `/json/close/<id>` with `404 No such target id` for a tab it does
    not have, which is the outcome the caller wanted. Everything else is a
    failure like any other, so this stays a `BrowserError`.
    """

    def __init__(self, *, detail: str, status: int) -> None:
        super().__init__(detail=detail)
        self.status = status


def http_get(url: str, timeout: float) -> str:
    """GET a CDP HTTP endpoint and return its body."""
    try:
        with _NO_PROXY.open(url, timeout=timeout) as response:
            return str(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Before URLError, which it subclasses. A status is a considered answer
        # from a browser that is there, not a browser that is not.
        raise HttpStatusError(
            detail=f"{url} answered {exc.code}", status=exc.code
        ) from exc
    except urllib.error.URLError as exc:
        # Includes the ordinary "nothing is listening" case, which callers turn
        # into "no browser on this port" rather than into a failure.
        raise BrowserError(detail=f"{url} did not answer: {exc.reason}") from exc
    except OSError as exc:  # pragma: no cover - defensive; URLError covers these
        raise BrowserError(detail=f"{url} did not answer: {exc}") from exc


def http_json(url: str, timeout: float) -> Any:
    """The same, parsed. Not every endpoint is JSON: `/json/close/<id>` answers
    `Target is closing` in plain text, which is why this is the narrower one."""
    raw = http_get(url, timeout)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise BrowserError(detail=f"{url} did not answer with JSON") from None


class Connection:
    """One WebSocket to a CDP endpoint.

    Commands are sequential and blocking: this process is the only thing driving
    this browser, so there is no request pipelining to get right. Events that
    arrive while waiting for a reply are kept rather than dropped — `probe` needs
    `Page.javascriptDialogOpening`, which arrives unsolicited.
    """

    def __init__(
        self, websocket_url: str, *, timeout: float = DEFAULT_TIMEOUT_S
    ) -> None:
        self.websocket_url = websocket_url
        self.timeout = timeout
        self._next_id = 0
        self._events: list[dict[str, Any]] = []
        # The connection is held open for the life of this object, so it is
        # entered here and exited in `close`. `websockets` 17 deprecates using
        # `connect()` without the context-manager protocol at all.
        self._stack = ExitStack()
        try:
            self._socket: ClientConnection = self._stack.enter_context(
                connect(
                    websocket_url,
                    open_timeout=timeout,
                    close_timeout=timeout,
                    max_size=MAX_MESSAGE_BYTES,
                    # A CDP connection is idle for as long as the operator takes
                    # to log in; keepalive pings against a browser that does not
                    # answer them would close it out from under us.
                    ping_interval=None,
                    proxy=None,
                )
            )
        except (WebSocketException, OSError, TimeoutError) as exc:
            raise BrowserError(
                detail=f"cannot connect to {websocket_url}: {exc}"
            ) from exc

    # -- the protocol ------------------------------------------------------- #

    def send(
        self, method: str, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send one command and return its `result`.

        A CDP-level error (`{"error": {...}}`) is a `BrowserError`: every call
        this tool makes is one it believes the page can answer, so a refusal is
        a failure and not a value.
        """
        self._next_id += 1
        message_id = self._next_id
        payload = {"id": message_id, "method": method, "params": dict(params or {})}
        try:
            self._socket.send(json.dumps(payload))
        except (WebSocketException, OSError) as exc:
            raise BrowserError(detail=f"{method} could not be sent: {exc}") from exc

        deadline = time.monotonic() + self.timeout
        while True:
            message = self._receive(deadline, method)
            if message.get("id") != message_id:
                # An event, or the tail of a command we gave up on. Keep events;
                # a stale reply is of no further use to anyone.
                if "id" not in message:
                    self._events.append(message)
                continue
            error = message.get("error")
            if error is not None:
                raise BrowserError(
                    detail=f"{method} failed: "
                    f"{error.get('message', 'unknown error')} "
                    f"({error.get('code', '?')})"
                )
            result = message.get("result", {})
            return result if isinstance(result, dict) else {}

    def drain(self, timeout: float = 0.0) -> list[dict[str, Any]]:
        """Collect whatever events are already queued, and return all of them.

        Returns every event seen since the connection opened, not only the new
        ones: a dialog that opened during an earlier call is still open now.
        """
        deadline = time.monotonic() + timeout
        while True:
            remaining = max(deadline - time.monotonic(), 0.0)
            try:
                raw = self._socket.recv(timeout=remaining)
            except TimeoutError:
                return list(self._events)
            except (WebSocketException, OSError) as exc:
                raise BrowserError(detail=f"browser connection lost: {exc}") from exc
            message = _decode(raw)
            if "id" not in message:
                self._events.append(message)

    def events(self, name: str) -> list[dict[str, Any]]:
        """Every event of one kind seen so far, oldest first."""
        return [item for item in self._events if item.get("method") == name]

    def _receive(self, deadline: float, method: str) -> dict[str, Any]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BrowserError(detail=f"{method} timed out after {self.timeout:g}s")
        try:
            raw = self._socket.recv(timeout=remaining)
        except TimeoutError:
            raise BrowserError(
                detail=f"{method} timed out after {self.timeout:g}s"
            ) from None
        except (WebSocketException, OSError) as exc:
            raise BrowserError(detail=f"browser connection lost: {exc}") from exc
        return _decode(raw)

    # -- lifecycle ---------------------------------------------------------- #

    def close(self) -> None:
        try:
            self._stack.close()
        except (WebSocketException, OSError):  # pragma: no cover - already gone
            pass

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def _decode(raw: str | bytes) -> dict[str, Any]:
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    try:
        message = json.loads(text)
    except json.JSONDecodeError:
        raise BrowserError(detail="browser sent a frame that is not JSON") from None
    if not isinstance(message, dict):
        raise BrowserError(detail="browser sent a frame that is not a CDP message")
    return message


class Page(Connection):
    """A connection bound to one page target, with the moves `08` needs.

    The methods are deliberately few and deliberately deterministic: insert this
    text, put these files in that input, go to this URL. Deciding *when* to make
    them is Hermes's job (`11`); making them exactly is ours.
    """

    def __init__(self, target: Target, *, timeout: float = DEFAULT_TIMEOUT_S) -> None:
        super().__init__(target.websocket_url, timeout=timeout)
        self.target = target
        # Dialogs are events, so the domain has to be enabled before one opens
        # for `probe` to ever see it.
        self.send("Page.enable")

    def evaluate(self, expression: str) -> Any:
        """Run an expression in the page and return its value.

        `returnByValue`, so what comes back is JSON and not a remote handle: the
        expressions here are our own, they return plain objects, and holding a
        handle would mean releasing it.
        """
        result = self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        details = result.get("exceptionDetails")
        if details is not None:
            # Our own JS threw. The text is ours, not the page's.
            raise BrowserError(
                detail=f"page expression failed: {details.get('text', 'exception')}"
            )
        value = result.get("result", {})
        return value.get("value")

    def navigate(self, url: str) -> None:
        result = self.send("Page.navigate", {"url": url})
        error = result.get("errorText")
        if error:
            raise BrowserError(detail=f"navigation to {url} failed: {error}")

    def insert_text(self, text: str) -> None:
        """Insert text as if it had been composed, not typed and not pasted.

        `08` explains why this and not `browser_type` or the clipboard.
        """
        self.send("Input.insertText", {"text": text})

    def set_file_input_files(self, selector: str, paths: Sequence[Path]) -> None:
        """Put files into the first `input[type=file]` matching `selector`."""
        root = self.send("DOM.getDocument", {"depth": 0})
        root_id = root.get("root", {}).get("nodeId")
        node_id = self.send(
            "DOM.querySelector", {"nodeId": root_id, "selector": selector}
        ).get("nodeId")
        if not node_id:
            raise BrowserError(detail=f"no element matches {selector}")
        self.send(
            "DOM.setFileInputFiles",
            {"nodeId": node_id, "files": [str(Path(item).resolve()) for item in paths]},
        )

    @property
    def url(self) -> str:
        """The live URL, read from the page rather than from `/json/list`.

        `Target.url` is a snapshot taken when the target list was fetched; a
        redirect to `/login` between then and now is exactly the thing `probe`
        exists to notice.
        """
        value = self.evaluate("location.href")
        return value if isinstance(value, str) else self.target.url


@dataclass
class CdpClient:
    """The HTTP half of the protocol: what is running, and how to reach it."""

    port: int = DEFAULT_PORT
    host: str = DEFAULT_HOST
    timeout: float = DEFAULT_TIMEOUT_S

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def version(self) -> dict[str, Any]:
        """`/json/version`, the cheapest "is a browser there" question there is."""
        payload = http_json(f"{self.base_url}/json/version", self.timeout)
        if not isinstance(payload, dict):
            raise BrowserError(detail=f"{self.base_url}/json/version is not a browser")
        return payload

    def responding(self) -> bool:
        """Whether anything answers the debug port. Never raises."""
        try:
            self.version()
        except BrowserError:
            return False
        return True

    def browser_id(self) -> str:
        """The browser instance's own target id, from its WebSocket URL.

        Unique per launched browser, which is what makes it usable as "is this
        the Chrome we started" — see `launcher.adopt`.
        """
        url = str(self.version().get("webSocketDebuggerUrl", ""))
        return url.rsplit("/", 1)[-1] if url else ""

    def targets(self) -> list[Target]:
        """Everything `/json/list` reports, in the order the browser gives."""
        payload = http_json(f"{self.base_url}/json/list", self.timeout)
        if not isinstance(payload, list):
            raise BrowserError(detail=f"{self.base_url}/json/list is not a target list")
        return [Target.from_json(item) for item in payload if isinstance(item, dict)]

    def pages(self) -> list[Target]:
        return [item for item in self.targets() if item.is_page]

    def attach(self, target_id: str) -> Page:
        """A `Page` for one target id, looked up in the live target list."""
        for target in self.targets():
            if target.id == target_id:
                if not target.websocket_url:
                    raise BrowserError(
                        detail=f"target {log.safe_token(target_id)} "
                        f"cannot be attached to"
                    )
                _logger.debug("cdp attach", extra={"target_id": target_id})
                return Page(target, timeout=self.timeout)
        raise BrowserError(detail=f"no such target: {log.safe_token(target_id)}")

    def close_target(self, target_id: str) -> None:
        """Close one tab. Idempotent: a target that is already gone is fine.

        Chrome answers `404 No such target id` for a tab it does not have, and
        that is this call's goal already met. `08`'s `close-extra-tabs`
        enumerates targets and then closes them one by one, so a tab that closed
        itself in between is an ordinary race and not a failure to report.
        """
        try:
            http_get(f"{self.base_url}/json/close/{target_id}", self.timeout)
        except HttpStatusError as exc:
            if exc.status != 404:
                raise

    @contextmanager
    def browser_connection(self) -> Iterator[Connection]:
        """A connection to the browser target itself, for `Browser.close`."""
        url = str(self.version().get("webSocketDebuggerUrl", ""))
        if not url:
            raise BrowserError(detail="browser has no debugger URL")
        connection = Connection(url, timeout=self.timeout)
        try:
            yield connection
        finally:
            connection.close()
