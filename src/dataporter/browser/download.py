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
— a `403` for a session the vendor does not recognise — and a document that
loaded and then went quiet, with no download begun, says the link led to a page,
which is what a signed-out download looks like.

Neither of those two domains is trusted to be the whole story. A good link is a
redirect chain whose middle hops render documents of their own, so quiet and not
merely loaded is what makes a page a page (`SETTLE_S`); and the completion event
is not always delivered at all, so a file that has appeared in the staging dir
and stopped growing counts as the download whether or not the browser said so
(`_Wait.landed`). The bytes are the one signal that cannot go missing.

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
            # What was in the staging dir before this navigation, so that what
            # the browser writes into it can be told apart from what is already
            # filed there — an earlier part, or the manifest beside it.
            before = frozenset(into.iterdir())
            _navigate(page, link)
            got = _await(
                browser,
                page,
                into=into,
                before=before,
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

CRDOWNLOAD = ".crdownload"
"""What Chrome names a download still being written; it renames on completion.

So `into` holding no `.crdownload` and a file that was not there before is a
download the browser has finished with — which is the one signal that never goes
missing, because `Browser.setDownloadBehavior` put those bytes there and nothing
else writes to the staging dir."""

SETTLE_S = 5.0
"""How long a loaded document must go quiet before it is a page and not a hop.

A good link is a redirect chain, not one response: the vendor's own hop renders a
document of its own — and fires `Page.loadEventFired` — before the archive's
signed URL on another host begins the download. Concluding "a page" on that first
load, which one poll's grace did, gives up on a download that has not started
yet; Chrome then finishes it regardless, which is how a file could land in the
staging dir under a run that had already failed with `the link led to a page`.

A signed-out link renders its login page and then says nothing more, so quiet —
no navigation, no response, no download event — is what tells the two apart. The
cost of the wait is paid only by a link that really has landed on a page.

Capped at half the idle budget where that is shorter (`_await`), so that the
page is always diagnosed before the stall: "sign in" is what an operator can act
on, and "the download stalled" is what is left when nothing else can be said."""


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
    last_event: float = 0.0
    before: frozenset[Path] = frozenset()
    settled_path: Path | None = None
    settled_size: int = -1

    def touch(self) -> None:
        """Push the idle deadline out: the download said something."""
        self.deadline = time.monotonic() + self.idle_s

    def saw_event(self) -> None:
        """Note that either session said something: the chain is still moving."""
        self.last_event = time.monotonic()

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

    def landed(self) -> Downloaded | None:
        """Return the file the browser finished writing, when no event said so.

        `Browser.downloadProgress` is not always delivered — observed against
        claude.ai, where a run would download every byte of a part and then wait
        out its idle budget for a completion that never arrived. The bytes are not
        in doubt, only the telling of them: the staging dir is this fetch's alone,
        so a file that is new, has no `.crdownload` in flight beside it, and has
        stopped growing is the download, whether or not the browser mentioned it.

        Two polls at the same size before it is believed, because a file is
        created before it is written; a `.crdownload` means the write is still
        going, which is progress and not silence, so the idle budget is pushed out.
        """
        try:
            items = list(self.into.iterdir())
        except OSError:  # pragma: no cover - the dir is made before the navigation
            return None
        if any(item.name.endswith(CRDOWNLOAD) for item in items):
            self.touch()
            self.settled_path = None
            return None
        fresh = [item for item in items if item not in self.before and item.is_file()]
        if not fresh:
            return None
        newest = max(fresh, key=lambda item: item.stat().st_mtime)
        size = newest.stat().st_size
        if size == 0:
            return None
        if self.settled_path == newest and self.settled_size == size:
            return Downloaded(path=newest, bytes=size, suffix=self.suffix, filename_chars=self.chars)
        self.settled_path, self.settled_size = newest, size
        self.touch()
        return None

    def settled_on_a_page(self, settle_s: float) -> bool:
        """Return whether a document loaded, went quiet, and no download began.

        A page where an archive should be is what a signed-out link looks like.
        Quiet and not merely loaded (`SETTLE_S`): a document that loaded while the
        redirect chain is still moving is a hop on the way to the archive, and the
        download it leads to has not begun yet.
        """
        if self.loaded_at is None or self.guid is not None:
            return False
        return time.monotonic() - max(self.loaded_at, self.last_event) >= settle_s


def _await(
    browser: Connection,
    page: Page,
    *,
    into: Path,
    before: frozenset[Path],
    idle_s: float,
    max_bytes: int,
    poll_s: float,
    settle_s: float = SETTLE_S,
) -> Downloaded:
    """Listen on both sessions until the download finishes, or until it cannot."""
    wait = _Wait(into=into, idle_s=idle_s, max_bytes=max_bytes, before=before)
    # Never longer than half the idle budget: a settle window that outlasts it
    # would let `STALLED` answer for a link that plainly landed on a page, and
    # the sign-in is the thing the operator can do something about.
    settle = min(settle_s, idle_s / 2)
    wait.touch()
    while True:
        from_browser = browser.pull(poll_s)
        for event in from_browser:
            got = wait.browser_event(browser, event)
            if got is not None:
                return got
        from_page = page.pull(0)
        for event in from_page:
            wait.page_event(event)
        if from_browser or from_page:
            # Either session speaking means the chain is still moving, so a
            # document that loaded a moment ago is a hop and not a destination.
            wait.saw_event()
        # Before the page check, so a download that finished without saying so
        # is never mistaken for a link that led to a page.
        landed = wait.landed()
        if landed is not None:
            return landed
        if wait.settled_on_a_page(settle):
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
