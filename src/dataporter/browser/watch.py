"""The tool's own eyes on the tab (brief `04` §44, `35`).

Hermes drives the browser directly for the adaptive moves (`11`): it navigates,
it presses send, it finds the chat's menu. The tool sees none of that through
its helpers, and a trace that held only moves would have a hole where every
adaptive action was. So the run opens a second session on the same tab, beside
the agent's, and records what the page does, whoever caused it: navigations,
URL changes within a document, dialogs by type, the page's own traffic in
outline, the certificate the browser was shown, tabs appearing and closing.

## A witness, not a hand

The watch sends no input and drives nothing. It enables what it must to hear
the page — `Page`, `Network`, `Target` discovery, `Accessibility` for the
sketches it takes where the page moved — and the one expression it ever
evaluates is the sketch's selector count. A run watched and a run unwatched
are the same run.

## It never stops a run

The trace is evidence and the migration is the product. A watch that cannot
start, or whose session drops, writes `watch_lost`, warns in the run log, and
is done; the run goes on. A relaunched browser gets a new watch, and the new
certificate and navigation lines are the record of the restart.
"""

import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from dataporter import log
from dataporter import trace as tracing
from dataporter.browser import sketch as sketching
from dataporter.browser.cdp import CdpClient, Page
from dataporter.browser.site import Site
from dataporter.errors import BrowserError

if TYPE_CHECKING:
    from dataporter.browser.launcher import BrowserSession
    from dataporter.config import Settings

_logger = log.get_logger(__name__)

POLL_S = 0.25
"""How long one turn of the loop waits for an event before checking whether it
has been asked to stop."""

STOP_S = 5.0
"""How long `stop` waits for the thread after closing its connection."""

WATCHED_TYPES: tuple[str, ...] = ("Document", "XHR", "Fetch", "EventSource", "WebSocket")
"""The resource types a `request` line is written for. Static assets are noise:
the mock is a page, not a content delivery network (§44)."""

NAVIGATION = "navigation"
URL_CHANGED = "url_changed"
DIALOG_OPENED = "dialog_opened"
DIALOG_CLOSED = "dialog_closed"
REQUEST = "request"
RESPONSE = "response"
CERTIFICATE = "certificate"
TARGET_CREATED = "target_created"
TARGET_CLOSED = "target_closed"
WATCH_LOST = "watch_lost"
"""The observations, by `what` (§44)."""

ENABLES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("Network.enable", {}),
    ("Target.setDiscoverTargets", {"discover": True}),
    ("Accessibility.enable", {}),
)
"""What the watch asks for after `Page.enable`, which `Page` itself sends."""


@dataclass
class _Request:
    """One watched request between its first event and its last."""

    id: str
    started: float
    status: int = 0
    content_type: str = ""


@dataclass
class Watch:
    """One watch on one tab, for the length of a run."""

    trace: tracing.Trace | None
    site: Site
    _page: Page | None = field(default=None, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)
    _stopping: threading.Event = field(default_factory=threading.Event, repr=False)
    _known: set[str] = field(default_factory=set, repr=False)
    """Page targets that existed when the watch started, plus every one it saw
    created: `Target.setDiscoverTargets` announces the existing ones as
    created, and a tab that was already open is not one the run opened."""
    _own: str = ""
    _requests: dict[str, _Request] = field(default_factory=dict, repr=False)
    _numbered: int = 0
    _certified: set[str] = field(default_factory=set, repr=False)
    """The hosts whose certificate has been recorded: once per host, and a
    source that signs in on two hosts (`42`) shows two."""
    _await_load: str | None = None
    """The URL of a navigation whose sketch waits on `Page.loadEventFired`."""
    _dialogs: list[str] = field(default_factory=list, repr=False)

    # -- lifecycle ---------------------------------------------------------- #

    @classmethod
    def start(cls, trace: tracing.Trace | None, client: CdpClient, site: Site) -> "Watch":
        """Attach to the tab on the site's host and start listening.

        No trace, no watch. A tab that cannot be found or attached to is
        `watch_lost` on the trace, a warning, and a watch that is already
        stopped — never a raised error.
        """
        watch = cls(trace=trace, site=site)
        if trace is None:
            return watch
        try:
            page, known, own = _attach(client, site)
        except BrowserError as exc:
            watch._lost(exc)
            return watch
        watch._page = page
        watch._known = known
        watch._own = own
        watch._thread = threading.Thread(target=watch._loop, name="dataporter-watch", daemon=True)
        watch._thread.start()
        return watch

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        """Close the session and wait for the thread. Safe to call twice.

        A thread still alive after the wait keeps its reference and is warned
        about, so a stuck loop can be seen — `running` stays true — and stopped
        again later, rather than lost. (Raised by Copilot in review on #48.)
        """
        self._stopping.set()
        page, self._page = self._page, None
        if page is not None:
            page.close()
        thread = self._thread
        if thread is None:
            return
        thread.join(timeout=STOP_S)
        if thread.is_alive():
            _logger.warning("watch did not stop", extra={"waited_s": STOP_S})
            return
        self._thread = None

    # -- the loop ----------------------------------------------------------- #

    def _loop(self) -> None:
        page = self._page
        if page is None:  # pragma: no cover - `start` sets it before the thread exists
            return
        try:
            while not self._stopping.is_set():
                for event in page.pull(POLL_S):
                    self._handle(page, event)
        except BrowserError as exc:
            if not self._stopping.is_set():
                self._lost(exc)
        except tracing.TraceEndedError:
            # The run ended under the watch: its last line is written, and
            # nothing after it may be.
            return

    def _lost(self, exc: BrowserError) -> None:
        reason = exc.detail or type(exc).__name__
        _logger.warning("watch lost", extra={"reason": reason})
        self._write(WATCH_LOST, reason=log.safe_token(reason))

    def _write(self, what: str, **fields: Any) -> None:
        if self.trace is None or self.trace.ended:
            return
        self.trace.observation(what, **fields)

    def _sketch(self, page: Page, url: str) -> None:
        if self.trace is None:  # pragma: no cover - the loop exists only with a trace
            return
        try:
            self.trace.sketch(sketching.take(page, self.site, url=url, dialogs=self._dialogs))
        except BrowserError as exc:
            _logger.warning("sketch not taken", extra={"reason": exc.detail or type(exc).__name__})

    # -- the events --------------------------------------------------------- #

    def _handle(self, page: Page, event: dict[str, Any]) -> None:  # ruff: ignore[complex-structure, too-many-branches] - one branch per event the brief names
        method = str(event.get("method", ""))
        params = event.get("params") or {}
        if method == "Page.frameNavigated":
            frame = params.get("frame") or {}
            if not frame.get("parentId"):
                url = str(frame.get("url", ""))
                self._write(NAVIGATION, **self._elsewhere(url), **tracing.url_fields(url))
                self._await_load = url
        elif method == "Page.loadEventFired":
            if self._await_load is not None:
                url, self._await_load = self._await_load, None
                self._sketch(page, url)
        elif method == "Page.navigatedWithinDocument":
            url = str(params.get("url", ""))
            self._write(URL_CHANGED, **self._elsewhere(url), **tracing.url_fields(url))
            self._sketch(page, url)
        elif method == "Page.javascriptDialogOpening":
            kind = log.safe_token(str(params.get("type", "dialog")))
            self._dialogs.append(f"javascript:{kind}")
            self._write(DIALOG_OPENED, type=kind)
        elif method == "Page.javascriptDialogClosed":
            if self._dialogs:
                self._dialogs.pop(0)
            self._write(DIALOG_CLOSED, accepted=bool(params.get("result")))
        elif method == "Network.requestWillBeSent":
            self._request(params)
        elif method == "Network.responseReceived":
            self._response(params)
        elif method == "Network.loadingFinished":
            self._finished(params, int(params.get("encodedDataLength") or 0))
        elif method == "Network.loadingFailed":
            self._finished(params, 0)
        elif method == "Target.targetCreated":
            info = params.get("targetInfo") or {}
            identifier = str(info.get("targetId", ""))
            if info.get("type") == "page" and identifier and identifier not in self._known:
                self._known.add(identifier)
                self._write(TARGET_CREATED, **tracing.url_fields(str(info.get("url", ""))))
        elif method == "Target.targetDestroyed":
            identifier = str(params.get("targetId", ""))
            if identifier in self._known and identifier != self._own:
                self._known.discard(identifier)
                self._write(TARGET_CLOSED)

    def _elsewhere(self, url: str) -> dict[str, str]:
        """`host`, when a line is about a host other than the site's own.

        A one-host site never writes it, so every line `35` wrote is what it
        was; a sign-in that passes through a second host (`42`, §61) says which
        host its `/log-in` was on, since a path alone cannot.
        """
        host = urlsplit(url).hostname or ""
        return {"host": host} if host and host != self.site.host else {}

    def _request(self, params: dict[str, Any]) -> None:
        request = params.get("request") or {}
        url = str(request.get("url", ""))
        kind = str(params.get("type", ""))
        if kind not in WATCHED_TYPES:
            return
        if urlsplit(url).hostname not in self.site.hosts and not (kind == "Document" and tracing.is_redacting()):
            # Every hop of a fetch is recorded, whatever host the vendor sends
            # the link through (§65, §66); otherwise the site's own hosts only.
            return
        self._numbered += 1
        identifier = f"r{self._numbered}"
        self._requests[str(params.get("requestId", ""))] = _Request(
            id=identifier, started=float(params.get("timestamp") or 0.0)
        )
        self._write(
            REQUEST,
            id=identifier,
            method=log.safe_token(str(request.get("method", ""))),
            **self._elsewhere(url),
            **tracing.url_fields(url),
            type=kind.lower(),
        )

    def _response(self, params: dict[str, Any]) -> None:
        known = self._requests.get(str(params.get("requestId", "")))
        response = params.get("response") or {}
        if known is not None:
            known.status = int(response.get("status") or 0)
            known.content_type = log.safe_token(str(response.get("mimeType", "")))
        details = response.get("securityDetails")
        host = urlsplit(str(response.get("url", ""))).hostname or ""
        if details and host in self.site.hosts and host not in self._certified:
            self._certified.add(host)
            self._write(
                CERTIFICATE,
                host=host,
                issuer=log.safe_token(str(details.get("issuer", ""))),
                subject=log.safe_token(str(details.get("subjectName", ""))),
            )

    def _finished(self, params: dict[str, Any], size: int) -> None:
        known = self._requests.pop(str(params.get("requestId", "")), None)
        if known is None:
            return
        elapsed_ms = max(round((float(params.get("timestamp") or known.started) - known.started) * 1000), 0)
        self._write(
            RESPONSE,
            id=known.id,
            status=known.status,
            content_type=known.content_type,
            bytes=size,
            elapsed_ms=elapsed_ms,
        )


def _attach(client: CdpClient, site: Site) -> tuple[Page, set[str], str]:
    """Attach to the tab on the site's host with the domains enabled.

    Returns the page, the targets that already existed, and the tab's own id.
    Raises `BrowserError` for no tab, a failed attach or a refused enable — the
    page closed again on the last.
    """
    pages = client.pages()
    tabs = [item for item in pages if item.host in site.hosts]
    if not tabs:
        raise BrowserError(detail=f"no tab on {site.host} to watch")
    page = client.attach(tabs[0].id)
    try:
        for method, params in ENABLES:
            page.send(method, params)
    except BrowserError:
        page.close()
        raise
    return page, {item.id for item in pages}, tabs[0].id


# --------------------------------------------------------------------------- #
# A run under a watch
# --------------------------------------------------------------------------- #


@contextmanager
def watched(
    settings: "Settings",
    *,
    command: str,
    flags: Sequence[str],
    site: Site,
    browser: "BrowserSession",
    export_fingerprint: str | None = None,
) -> Iterator[tracing.Opened]:
    """`trace.opened`, with the watch started after the header and stopped before the end."""
    with tracing.opened(
        settings,
        command=command,
        flags=flags,
        site=site,
        client=browser.client,
        export_fingerprint=export_fingerprint,
    ) as traced:
        watch = Watch.start(traced.trace, browser.client, site)
        try:
            yield traced
        finally:
            watch.stop()
