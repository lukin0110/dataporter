"""What `login`, `session status` and `session logout` actually do.

The commands themselves are three short functions in `cli`; everything they know
about tabs, waiting and profiles is here, so that `12`'s run loop can ask the
same questions ("is this session usable?") without going through the CLI.
"""

import shutil
import time
from pathlib import Path

from dataporter import PROGRAM_NAME, log
from dataporter.browser.cdp import CdpClient, Page, Target
from dataporter.browser.launcher import BrowserSession, PortInUse
from dataporter.browser.probe import CLAUDE_HOST, NEW_CHAT_URL, PageState, probe
from dataporter.config import Settings
from dataporter.errors import BrowserError
from dataporter.state import StateError

_logger = log.get_logger(__name__)

LOGIN_POLL_S = 2.0
"""How often `login` looks. Two seconds is invisible to a human filling in a
form and costs 300 probes across the ten-minute default."""

BLANK_URLS = frozenset({"", "about:blank", "chrome://newtab/", "about:newtab"})

SIGNED_IN = "logged in"
SIGNED_OUT = f"not logged in — run: {PROGRAM_NAME} login"
"""What `session status` prints and what `12` refuses to start with.

Here rather than in `cli` because two commands and the import loop say it, and
an instruction an operator is given in two slightly different spellings is two
instructions as far as they can tell."""


def claude_tabs(client: CdpClient) -> list[Target]:
    """Every page target on claude.ai, in the browser's own order."""
    return [target for target in client.pages() if target.host == CLAUDE_HOST]


def open_claude_tab(session: BrowserSession, url: str = NEW_CHAT_URL) -> Page:
    """The tab to drive: an existing claude.ai tab, or one made to be it.

    A blank tab is reused before a new one is created, because that is what a
    just-launched browser looks like while its first page is still loading —
    creating a second tab there would leave the operator with two windows and
    `08` with an `ambiguous_tab`.
    """
    tabs = claude_tabs(session.client)
    if tabs:
        return session.client.attach(tabs[0].id)

    blank = [target for target in session.client.pages() if target.url in BLANK_URLS]
    if blank:
        page = session.client.attach(blank[0].id)
        try:
            page.navigate(url)
        except BrowserError:
            # The connection belongs to this function until it is handed back.
            # `wait_for_login` treats a failed probe as "not yet" and tries again
            # every two seconds, so a navigation that keeps failing would leave
            # one open WebSocket per attempt for the whole ten-minute wait.
            page.close()
            raise
        return page

    with session.client.browser_connection() as connection:
        created = connection.send("Target.createTarget", {"url": url})
    target_id = str(created.get("targetId", ""))
    if not target_id:  # pragma: no cover - defensive
        raise BrowserError(detail="browser refused to open a tab")
    return session.client.attach(target_id)


def current_state(session: BrowserSession, url: str = NEW_CHAT_URL) -> PageState:
    """Probe the claude.ai tab, opening one if there is not one yet.

    The connection is closed again on the way out. That costs a WebSocket
    handshake per probe and buys the thing a long-lived connection cannot give:
    the tab is resolved afresh every time, so a login flow that replaces the tab
    is followed rather than watched from a target that no longer exists.

    The cost is that a JavaScript dialog opened before this connection existed is
    invisible to it. That is not a hole in practice — a modal `alert()` blocks
    the page's JavaScript, so the probe's own `Runtime.evaluate` times out and
    the caller learns something is wrong — and `12`, which holds one connection
    open for a whole conversation, sees the events themselves.
    """
    page = open_claude_tab(session, url)
    try:
        return probe(page, tab_count=max(len(claude_tabs(session.client)), 1))
    finally:
        page.close()


def wait_for_login(
    session: BrowserSession,
    *,
    timeout_s: float,
    poll_s: float = LOGIN_POLL_S,
    url: str = NEW_CHAT_URL,
) -> PageState | None:
    """Poll until the operator has signed in, or until the timeout. `None` on
    timeout.

    A failed probe is not a failed login: the page is being navigated, the tab is
    being replaced, the identity provider is redirecting. Only a browser that has
    stopped answering its debug port ends the wait early.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            state = current_state(session, url)
        except BrowserError:
            if not session.client.responding():
                raise
            _logger.debug("probe failed while waiting for login")
            state = None
        if state is not None and state.logged_in:
            return state
        if time.monotonic() >= deadline:
            return None
        time.sleep(poll_s)


def signed_in(session: BrowserSession, url: str = NEW_CHAT_URL) -> bool:
    """One probe. `session status` is this plus a printed line."""
    return current_state(session, url).logged_in


def remove_profile(settings: Settings) -> bool:
    """Delete the browser profile. `False` if there was nothing to delete.

    Local only: nothing is sent to claude.ai, so the *account* is not signed out
    anywhere else. Refuses while a browser is on the debug port, because deleting
    the directory under a running Chrome leaves a half-written profile and a
    browser that still holds the session in memory.
    """
    client = CdpClient(
        port=settings.browser.cdp_port, timeout=settings.timeouts.cdp_call_s
    )
    if client.responding():
        raise PortInUse(
            detail=f"a browser is still running on port {settings.browser.cdp_port} — "
            f"close it, then run session logout again",
            transient=False,
        )
    profile: Path = settings.browser_profile_dir
    if not profile.exists():
        return False
    try:
        shutil.rmtree(profile)
    except OSError as exc:
        # A read-only filesystem, a permission the operator can grant, a file
        # another process is holding. All fixable at the keyboard, so this is
        # `StateError` — "the workspace cannot be used as asked", exit `2` —
        # rather than the exit `70` an escaping OSError would earn.
        raise StateError(f"cannot remove {profile}: {exc.strerror or exc}") from exc
    _logger.info("browser profile removed")
    return True
