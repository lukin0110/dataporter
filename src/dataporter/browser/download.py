"""Catching the download a browser makes (`45`, brief `06` §63).

A source whose vendor serves the archive only to the signed-in session cannot
be fetched with `urllib` (§54, §63). So the tool points the source session's
own tab at the link, lets the browser make the download, and catches the file
where it lands. The cookie never leaves the browser: nothing here reads the
profile, nothing carries a cookie into a request of its own, and the tool never
learns what it is.

The mechanics are two CDP domains on two sessions. On the browser target,
`Browser.setDownloadBehavior` names a directory and asks for events, and
`Browser.downloadWillBegin` and `Browser.downloadProgress` say what landed and
when it finished; `allowAndName` makes the file's name the download's own
guid, so nothing the vendor named is ever joined to a path. On the tab,
`Network.responseReceived` for the document says whether the link was refused
— a `403` for a session the vendor does not recognise — and `Page.loadEventFired`
with no download begun says the link led to a page, which is what a signed-out
download looks like.

What this module never does: click, type, or attach to a tab under a wall. The
fetch has a wall of its own (§65): the link the person handed over, and
wherever the vendor redirects it, every hop recorded by the watch as a host and
a marker (§66). The link is the one string this navigates to.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dataporter import log
from dataporter import trace as tracing
from dataporter.browser import helpers
from dataporter.browser import session as browser_session
from dataporter.browser.cdp import Connection, Page
from dataporter.browser.launcher import BrowserSession
from dataporter.config import Settings
from dataporter.errors import BrowserError

if TYPE_CHECKING:
    from collections.abc import Sequence

_logger = log.get_logger(__name__)

POLL_S = 0.25
"""How long one turn of the wait listens for events before checking the budget."""

DOWNLOAD_ACTION = "download"
"""What `actions.jsonl` and the trace call the navigation to the link."""

REFUSED = "refused"
PAGE = "page"
TOO_LARGE = "too_large"
STALLED = "stalled"
CANCELLED = "cancelled"
"""Why a download did not finish. `extract` turns each into the line an
operator reads; a log record carries this rather than the prose."""

NO_TAB = "no tab on {host} to download in"

BEHAVIOUR: dict[str, Any] = {"behavior": "allowAndName", "eventsEnabled": True}
"""`allowAndName`: the browser names the file by the download's guid. A name
the vendor chose — which may carry the account's address — never reaches a
path, and never reaches the trace either (§66): only its length and suffix do."""


class DownloadStopped(Exception):  # ruff: ignore[error-suffix-on-exception-name] - an outcome, not an error
    """The download did not finish, and why."""

    def __init__(self, reason: str, status: int = 0) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


@dataclass(frozen=True)
class Downloaded:
    """What landed: where, how big, and what the vendor called it — in outline."""

    path: Path
    bytes: int
    suffix: str
    """Of the name the vendor suggested, e.g. `.zip`. Never the name."""
    filename_chars: int


def fetch(
    settings: Settings,
    session: BrowserSession,
    link: str,
    *,
    into: Path,
    hosts: "Sequence[str]",
    poll_s: float = POLL_S,
) -> Downloaded:
    """Navigate the source session's tab to the link and catch what the browser downloads.

    `into` is where the file lands, named by its guid; the caller hashes,
    verifies and files it exactly as it does a `urllib` download (`30`).
    `timeouts.download_idle_s` is the idle budget, reset on every download
    event: a large archive on a slow link is not late, and a transfer that has
    stopped is. `store.max_download_bytes` is enforced on the progress events
    and the download cancelled the moment it is passed.
    """
    into.mkdir(parents=True, exist_ok=True)
    tabs = browser_session.tabs_on(session.client, hosts)
    if not tabs:
        raise BrowserError(detail=NO_TAB.format(host=hosts[0]))
    started = time.monotonic()
    ts = tracing.timestamp()
    with session.client.browser_connection() as browser:
        browser.send("Browser.setDownloadBehavior", {**BEHAVIOUR, "downloadPath": str(into)})
        page = session.client.attach(tabs[0].id)
        try:
            page.send("Network.enable")
            _navigate(page, link)
            got = _await(
                browser,
                page,
                into=into,
                idle_s=settings.timeouts.download_idle_s,
                max_bytes=settings.store.max_download_bytes,
                poll_s=poll_s,
            )
        except DownloadStopped as exc:
            _record(settings, link, ts=ts, ok=False, elapsed_ms=_elapsed(started), reason=exc.reason)
            raise
        finally:
            page.close()
    _record(
        settings,
        link,
        ts=ts,
        ok=True,
        elapsed_ms=_elapsed(started),
        bytes=got.bytes,
        suffix=got.suffix,
        filename_chars=got.filename_chars,
    )
    _logger.info("download complete", extra={"bytes": got.bytes, "suffix": log.safe_token(got.suffix)})
    return got


HTTP_ERROR = 400
"""The first status a vendor refuses a link with."""


@dataclass
class _Wait:
    """What the two sessions have said so far, and the idle deadline."""

    into: Path
    idle_s: float
    max_bytes: int
    deadline: float = 0.0
    guid: str | None = None
    suffix: str = ""
    chars: int = 0
    status: int = 0
    loaded_at: float | None = None

    def touch(self) -> None:
        """Push the idle deadline out: the download said something."""
        self.deadline = time.monotonic() + self.idle_s

    def browser_event(self, browser: Connection, event: dict[str, Any]) -> Downloaded | None:
        """One event from the browser target: the download beginning, growing, finishing."""
        method = str(event.get("method", ""))
        params = event.get("params") or {}
        if method == "Browser.downloadWillBegin":
            self.guid = str(params.get("guid", ""))
            name = str(params.get("suggestedFilename", ""))
            self.suffix, self.chars = Path(name).suffix, len(name)
            self.touch()
        elif method == "Browser.downloadProgress" and self.guid and params.get("guid") == self.guid:
            self.touch()
            received = int(params.get("receivedBytes") or 0)
            if received > self.max_bytes:
                browser.send("Browser.cancelDownload", {"guid": self.guid})
                raise DownloadStopped(TOO_LARGE)
            state = str(params.get("state", ""))
            if state == "completed":
                return Downloaded(
                    path=self.into / self.guid, bytes=received, suffix=self.suffix, filename_chars=self.chars
                )
            if state == "canceled":
                raise DownloadStopped(CANCELLED)
        return None

    def page_event(self, event: dict[str, Any]) -> None:
        """One event from the tab: the document's status, or a page that loaded."""
        method = str(event.get("method", ""))
        params = event.get("params") or {}
        if method == "Network.responseReceived" and params.get("type") == "Document":
            self.status = int((params.get("response") or {}).get("status") or 0)
            if self.status >= HTTP_ERROR:
                raise DownloadStopped(REFUSED, self.status)
        elif method == "Page.loadEventFired":
            self.loaded_at = time.monotonic()

    def settled_on_a_page(self, poll_s: float) -> bool:
        """Return whether a document loaded and no download began after it.

        A page where an archive should be is what a signed-out link looks like.
        One poll's grace, because the two events can arrive in either order.
        """
        return self.loaded_at is not None and self.guid is None and time.monotonic() - self.loaded_at >= poll_s


def _await(
    browser: Connection,
    page: Page,
    *,
    into: Path,
    idle_s: float,
    max_bytes: int,
    poll_s: float,
) -> Downloaded:
    """Listen on both sessions until the download finishes, or until it cannot."""
    wait = _Wait(into=into, idle_s=idle_s, max_bytes=max_bytes)
    wait.touch()
    while True:
        for event in browser.pull(poll_s):
            got = wait.browser_event(browser, event)
            if got is not None:
                return got
        for event in page.pull(0):
            wait.page_event(event)
        if wait.settled_on_a_page(poll_s):
            raise DownloadStopped(PAGE, wait.status or 200)
        if time.monotonic() >= wait.deadline:
            raise DownloadStopped(STALLED)


NAVIGATION_ABORTED = "net::ERR_ABORTED"
"""What `Page.navigate` answers when the navigation became a download: the
document was never committed, because the bytes went to a file instead. The
one error that is the expected answer."""


def _navigate(page: Page, link: str) -> None:
    """Point the tab at the link.

    Never through `cdp.Page.navigate`, whose refusal names the URL it failed
    on — and the link is a credential.
    """
    result = page.send("Page.navigate", {"url": link})
    error = str(result.get("errorText") or "")
    if error and error != NAVIGATION_ABORTED:
        raise BrowserError(detail=f"navigation to the link failed: {log.safe_token(error)}")


def _elapsed(started: float) -> int:
    """Return the milliseconds since `started`."""
    return round((time.monotonic() - started) * 1000)


def _record(settings: Settings, link: str, *, ts: str, ok: bool, elapsed_ms: int, **outline: Any) -> None:
    """One `actions.jsonl` line and one move — with the link's host and never its path (§66).

    Not `record_step`, which writes the URL into `actions.jsonl` as the ask's
    clicks do: the link is a credential, and the action log carries the action
    and nothing of where it went. The move carries what `url_fields` allows
    while a fetch is redacting — the host and a marker — and the download in
    outline: its size, and the length and suffix of the vendor's name.
    """
    helpers.record_action(Path(settings.logs_dir), DOWNLOAD_ACTION, ok=ok, elapsed_ms=elapsed_ms, ts=ts)
    current = tracing.current()
    if current is not None:
        result: dict[str, Any] = {**tracing.url_fields(link), **outline}
        current.move(DOWNLOAD_ACTION, ok=ok, elapsed_ms=elapsed_ms, conversation_id=None, result=result, ts=ts)
