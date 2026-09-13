"""What `login`, `session status` and `session logout` actually do.

Everything the three commands know about tabs, waiting and profiles is here, so
that `12`'s run loop can ask the same questions ("is this session usable?")
without going through the CLI — and since `23`, so are the commands themselves:
`login`, `status` and `logout` at the bottom of this module are what `cli`
calls, and the CLI adds nothing but the flag parsing and the exit.
"""

import shutil
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dataporter import PROGRAM_NAME, log, signin
from dataporter.browser import launcher
from dataporter.browser.cdp import CdpClient, Page, Target
from dataporter.browser.launcher import BrowserSession, PortInUseError
from dataporter.browser.probe import CLAUDE_HOST, NEW_CHAT_URL, PageState, probe
from dataporter.config import Settings
from dataporter.console import DISCARD, Sink
from dataporter.errors import AuthError, BrowserError
from dataporter.exit_codes import ExitCode
from dataporter.state import StateError

if TYPE_CHECKING:
    from pathlib import Path

_logger = log.get_logger(__name__)

LOGIN_POLL_S = 2.0
"""How often `login` looks. Two seconds is invisible to a human filling in a
form and costs 300 probes across the ten-minute default.

Never waited out past the deadline: see `wait_for_login`.
"""

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
    """Return the tab to drive: an existing claude.ai tab, or one made to be it.

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


SETTLE_S = 10.0
"""How long a probe waits for a tab that is still loading.

A browser this tool has just launched has a tab that has not rendered yet, and a
page with no composer on it reads as a session that has expired — which sends an
unattended run into a sign-in it does not need and an attended one to `error: not
logged in`. So the probe waits for the document rather than describing a moment
before it existed. (Found by `29`'s first rehearsal, on the preflight of the
first `import` after a `login`.)
"""

SETTLE_POLL_S = 0.2

READY_JS = "document.readyState === 'complete' && location.href"
"""The URL once the document has finished loading, and `false` before then.

One expression rather than two, because both halves have to be true of the same
moment: `about:blank` is `complete` the instant it is asked, so a tab that is
loading its first page answers `complete` for a document that is not the one
being waited for.
"""


def settled(page: Page, *, timeout_s: float = SETTLE_S) -> bool:
    """Wait until the tab holds a page that is not blank. `False` on the deadline.

    Never raises: a tab that cannot be read is a tab the caller's own probe will
    report on, and turning that into an exception here would change what every
    caller of `current_state` has to handle.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            answer = page.evaluate(READY_JS)
        except BrowserError:
            return False
        if isinstance(answer, str) and answer not in BLANK_URLS:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(SETTLE_POLL_S)


def current_state(session: BrowserSession, url: str = NEW_CHAT_URL, *, settle_s: float = SETTLE_S) -> PageState:
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
        settled(page, timeout_s=settle_s)
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
    """Poll until the operator has signed in, or until the timeout.

    `None` on timeout.

    A failed probe is not a failed login: the page is being navigated, the tab is
    being replaced, the identity provider is redirecting. Only a browser that has
    stopped answering its debug port ends the wait early.

    The wait keeps its own budget: the last sleep is shortened to whatever is
    left, so a `timeout_s` shorter than `poll_s` is honoured to the second rather
    than rounded up to the next probe.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            # Never longer than the wait itself has left: this poll already has
            # a budget, and a tab that has not rendered is what it is waiting
            # for rather than a reason to overshoot the operator's timeout.
            state = current_state(
                session,
                url,
                settle_s=max(0.0, min(SETTLE_S, deadline - time.monotonic())),
            )
        except BrowserError:
            if not session.client.responding():
                raise
            _logger.debug("probe failed while waiting for login")
            state = None
        if state is not None and state.logged_in:
            return state
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        # Never past the deadline. Sleeping a whole `poll_s` here overshoots a
        # timeout by up to two seconds — an operator who asked to wait one minute
        # is told at sixty-two that their minute is up — and the last stretch of
        # a wait is the one somebody is watching.
        time.sleep(min(poll_s, remaining))


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
    client = CdpClient(port=settings.browser.cdp_port, timeout=settings.timeouts.cdp_call_s)
    if client.responding():
        raise PortInUseError(
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


# --------------------------------------------------------------------------- #
# The three commands (`23`)
# --------------------------------------------------------------------------- #

LOGIN_PROMPT = "Log in to Claude in the browser window that just opened."
LOGGED_IN = "Logged in. Session stored in {profile}/."
LOGIN_TIMED_OUT = "timed out after {seconds:g}s waiting for login"
REMOVED = "Removed {profile}/."
NOTHING_TO_REMOVE = "Nothing to remove: {profile}/ does not exist."


@dataclass(frozen=True)
class LoginOutcome:
    """`login` ended signed in. Any other ending raises."""

    exit_code: ExitCode = ExitCode.OK


@dataclass(frozen=True)
class StatusOutcome:
    """`session status`: the answer, and exit `3` when it is no."""

    signed_in: bool
    exit_code: ExitCode


@dataclass(frozen=True)
class LogoutOutcome:
    """`session logout`: whether there was a profile to remove."""

    removed: bool
    exit_code: ExitCode = ExitCode.OK


def login(settings: Settings, *, sink: Sink = DISCARD) -> LoginOutcome:
    """Open Claude in the dedicated browser profile and wait for sign-in (§8).

    The prompt is a line on the sink rather than a log record: it is an
    instruction to the person at the keyboard, and it is the only thing this
    command asks of them. A wait that runs out is `AuthError`, exit `3`.
    """
    if settings.non_interactive:
        signin.require_credentials(settings)
    # `settings.logs_dir`, which is the workspace for the destination and the
    # account home for `31`'s source: a command about one account writes its
    # records beside that account's other operational files.
    log.enable_run_log(settings.logs_dir)
    # Through the module, not a bound name: the test suite substitutes
    # `launcher.launch` to hand a command a fake Chrome.
    browser = launcher.launch(settings, NEW_CHAT_URL)
    try:
        if settings.non_interactive:
            # `24`: the tool signs in, or says what a person would have to do.
            # No prompt, because nobody is reading one; the same last line,
            # because a CI log is read the way a terminal is.
            signin.ensure_signed_in(settings, browser)
        elif not signed_in(browser):
            sink.line(LOGIN_PROMPT)
            arrived = wait_for_login(browser, timeout_s=settings.timeouts.login_s)
            if arrived is None:
                raise AuthError(detail=LOGIN_TIMED_OUT.format(seconds=settings.timeouts.login_s))
        sink.line(LOGGED_IN.format(profile=settings.browser_profile_dir))
    finally:
        # Always, on every path: Chrome writes its cookie jar and session store
        # out on exit, so a profile that is never closed can come back signed
        # out — and a browser left running would hold the next run's port.
        browser.close()
    return LoginOutcome()


def status(settings: Settings, *, sink: Sink = DISCARD) -> StatusOutcome:
    """Report whether the destination account is signed in.

    The answer is a line and an exit code rather than an `AuthError`: `SIGNED_OUT`
    is the command's result, not an error, and it carries no `error:` prefix.

    Whose session is `settings`': the destination's, or `31`'s source account
    when one was named. Nothing here knows the difference — the profile
    directory is the whole of it.
    """
    log.enable_run_log(settings.logs_dir)
    client = CdpClient(port=settings.browser.cdp_port, timeout=settings.timeouts.cdp_call_s)
    # Raises `PortInUseError` when the port answers and the browser on it is not
    # ours, which is the right answer to "what is my session doing" as well.
    running = launcher.adopt(client, settings.browser_profile_dir)
    if running is None and not settings.browser_profile_dir.exists():
        # No profile and no browser: there is nothing that could be signed in,
        # and starting Chrome to be told so would cost ten seconds and a window.
        sink.line(SIGNED_OUT)
        return StatusOutcome(signed_in=False, exit_code=ExitCode.NOT_AUTHENTICATED)

    browser = running or launcher.launch(settings, NEW_CHAT_URL)
    try:
        answer = signed_in(browser)
    finally:
        # A browser this command started is a browser this command cleans up;
        # one that was already running belongs to whoever started it.
        if running is None:
            browser.close()
    sink.line(SIGNED_IN if answer else SIGNED_OUT)
    return StatusOutcome(
        signed_in=answer,
        exit_code=ExitCode.OK if answer else ExitCode.NOT_AUTHENTICATED,
    )


def logout(settings: Settings, *, sink: Sink = DISCARD) -> LogoutOutcome:
    """Remove the browser profile.

    Local only, and said so: the account itself is untouched, and a session on another
    machine is not ended by this.
    """
    log.enable_run_log(settings.logs_dir)
    removed = remove_profile(settings)
    profile = settings.browser_profile_dir
    sink.line(REMOVED.format(profile=profile) if removed else NOTHING_TO_REMOVE.format(profile=profile))
    return LogoutOutcome(removed=removed)
