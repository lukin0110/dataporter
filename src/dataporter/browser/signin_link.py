"""Spending a sign-in link in the account's own profile (`53`, brief 07 §73).

The second of §73's two commands. A person read an email and pasted its link;
this drives the profile's browser to it and reports whether the account came
back signed in. Nothing else is asked of the vendor, and nothing of the link
is kept (§74): it is checked to be `https`, navigated to once, redacted in
the trace as the export link is (§66), and gone when this returns.

Whose window it is decides how it ends. `login` (`50`) keeps its window open
until the link is spent, so this usually adopts that window — the same
profile, the same debug port, the marker `launcher.adopt` reads — and leaves
it to the command that opened it. With no window open it launches the
profile itself, spends the link there, and closes what it launched. That
second path works exactly when the pending sign-in survived Chrome closing,
which nobody has observed; the two refusals below say what happened either
way.

Headed, always. The vendor's bot management refuses a headless Chrome
(`docs/LIMITATIONS.md`, *observed 2026-09-15*), and `login` refuses the
unattended mode before this is reached, so the only way to a window here is
the one every `login` takes.
"""

import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from dataporter import log
from dataporter import trace as tracing
from dataporter.browser import helpers, launcher
from dataporter.browser import session as browser_session
from dataporter.browser import watch as watching
from dataporter.browser.cdp import CdpClient, Page
from dataporter.browser.launcher import BrowserSession
from dataporter.browser.probe import PageKind
from dataporter.browser.session import Arrival, LoginOutcome
from dataporter.config import Settings
from dataporter.console import DISCARD, Sink
from dataporter.errors import AuthError, BrowserError, UsageError
from dataporter.exit_codes import ExitCode
from dataporter.links import LINK_NOT_HTTPS, is_https

_logger = log.get_logger(__name__)

LINK_ACTION = "sign-in-link"
"""The move's name in `actions.jsonl` and the trace: the navigation to the
link, with its host and a marker where its path would be (§66)."""

NAVIGATION_FAILED = "navigation to the link failed: {error}"

LINK_POLL_S = 0.5
"""How often the wait after the link looks. Quicker than `login`'s two seconds:
the outcome is seconds away, and `login` closes its window
`session.SPENDER_GRACE_S` after it sees the same page — several of these polls,
so this command sees it first. Read at call time."""

WINDOW_CLOSED = (
    "the sign-in window closed before the link's outcome was seen; the session may well be signed in — "
    "check with: {command}"
)
"""Exit `6`: the browser this command adopted stopped answering after the link
was navigated to. `login` owns that window and closes it once it sees the
session signed in, `SPENDER_GRACE_S` late so that this command sees it first;
a window that still went early — a slow machine, a closed laptop — leaves the
outcome to `session status`, which is named rather than guessed at."""

CODE_PROMPT = (
    "the link led to a code prompt — the pending sign-in is not in this profile; sign in again with: {command}"
)
"""Exit `3`: the tab came back to the sign-in page still showing the code
field. The link was opened where the pending sign-in is not — a profile that
was signed out, or one whose pending sign-in did not survive the window
closing — and the vendor answered with a code for a window this tool no
longer has (`docs/claude-ui-map.md`, `link opened elsewhere`)."""

NOT_ACCEPTED = "the link was not accepted — it may have expired; sign in again with: {command}"
"""Exit `3`: the tab is neither signed in nor back at the code field inside
`timeouts.signin_s`. Expired, already spent, or a page this tool does not
recognise; the trace says which, and this line says what to do about any of
them."""


def spend(settings: Settings, link: str, *, sink: Sink = DISCARD, flags: Sequence[str] = ()) -> LoginOutcome:
    """Drive the account's profile to the link, and report the sign-in (§73).

    The scheme is checked before any browser is touched. A profile that is
    already signed in prints the block and spends nothing: the link stays
    whatever it was, and a person who ran this twice has lost nothing.
    """
    if not is_https(link):
        raise UsageError(LINK_NOT_HTTPS)
    log.enable_run_log(settings.logs_dir)
    session = browser_session.whose(settings)
    client = CdpClient(port=settings.browser.cdp_port, timeout=settings.timeouts.cdp_call_s)
    # `login`'s window, when it is open: the same profile on the same port,
    # which the marker proves. A browser that is not ours is `PortInUseError`
    # here as it is for `status`.
    running = launcher.adopt(client, settings.browser_profile_dir)
    browser = running or launcher.launch(settings, session.url)
    try:
        with watching.watched(
            settings, command="login", flags=flags, site=browser_session.site_of(settings), browser=browser
        ) as traced:
            if not browser_session.signed_in(browser, session.url, hosts=session.hosts):
                _drive(settings, browser, link, hosts=session.hosts)
                try:
                    arrival = _await(browser, hosts=session.hosts, timeout_s=settings.timeouts.signin_s)
                except BrowserError as exc:
                    if running is not None and not browser.client.responding():
                        raise BrowserError(
                            detail=WINDOW_CLOSED.format(command=browser_session.status_command(settings))
                        ) from exc
                    raise
                command = browser_session.login_command(settings)
                if arrival is Arrival.LINK_SENT:
                    raise AuthError(detail=CODE_PROMPT.format(command=command))
                if arrival is Arrival.TIMED_OUT:
                    raise AuthError(detail=NOT_ACCEPTED.format(command=command))
            sink.block(browser_session.signed_in_block(settings, session))
            traced.exit_code = ExitCode.OK
    finally:
        # A browser this command started is a browser this command cleans up;
        # one that was already running belongs to whoever started it (`status`'s
        # rule), and here that is the `login` still waiting on it.
        if running is None:
            browser.close()
    return LoginOutcome()


def _drive(settings: Settings, browser: BrowserSession, link: str, *, hosts: Sequence[str]) -> None:
    """Point the tab the person used at the link, and record the move without the link.

    The first tab on the site, as the fetch downloads in it (`45`): the one
    the person entered their address in, whose pending sign-in the link
    completes. Never a new tab, which would leave the person two windows and
    `login`'s wait a tab it did not open.
    """
    tabs = browser_session.tabs_on(browser.client, hosts)
    if not tabs:
        raise BrowserError(detail=f"no tab on {hosts[0]} to spend the link in")
    started = time.monotonic()
    ts = tracing.timestamp()
    page = browser.client.attach(tabs[0].id)
    ok = False
    try:
        with tracing.redacting():
            _navigate(page, link)
            ok = True
    finally:
        page.close()
        _record(settings, link, ts=ts, ok=ok, elapsed_ms=round((time.monotonic() - started) * 1000))


def _navigate(page: Page, link: str) -> None:
    """Point the tab at the link.

    Never through `cdp.Page.navigate`, whose refusal names the URL it failed
    on — and the link is a credential (`45`).
    """
    result = page.send("Page.navigate", {"url": link})
    error = str(result.get("errorText") or "")
    if error:
        raise BrowserError(detail=NAVIGATION_FAILED.format(error=log.safe_token(error)))


def _record(settings: Settings, link: str, *, ts: str, ok: bool, elapsed_ms: int) -> None:
    """One `actions.jsonl` line and one move — with the link's host and never its path (§66)."""
    helpers.record_action(Path(settings.logs_dir), LINK_ACTION, ok=ok, elapsed_ms=elapsed_ms, ts=ts)
    current = tracing.current()
    if current is not None:
        with tracing.redacting():
            result: dict[str, Any] = tracing.url_fields(link)
        current.move(LINK_ACTION, ok=ok, elapsed_ms=elapsed_ms, conversation_id=None, result=result, ts=ts)


def _await(browser: BrowserSession, *, hosts: Sequence[str], timeout_s: float) -> Arrival:
    """Wait for the link to sign the session in, or for the page to say it did not.

    `session.await_signin`'s loop with the code field meaning the opposite of
    what it means to `login`: there it is the link on its way, here it is the
    tab *back* at the sign-in page because the link found no pending sign-in to
    finish. Back, and not still: the tab was on that very page, code field
    showing, when the link was navigated to, and `Page.navigate` returns before
    the old document is gone — so the first looks may still be answered by it
    (raised by Copilot in review on #58). The code field is the answer only
    once the tab has been seen somewhere else first: off `/login`, off the
    site, or mid-navigation with nothing to read.
    """
    _logger.info("sign-in link spent; waiting for the session")
    deadline = time.monotonic() + timeout_s
    left = False
    while True:
        try:
            state, code = browser_session.observe(
                browser, hosts, settle_s=max(0.0, min(browser_session.SETTLE_S, deadline - time.monotonic()))
            )
        except BrowserError:
            if not browser.client.responding():
                raise
            # Mid-navigation, or on another host: the old document is going or gone.
            state, code, left = None, False, True
        if state is not None:
            if state.logged_in:
                return Arrival.SIGNED_IN
            if state.kind is not PageKind.LOGIN:
                left = True
            elif code and left:
                return Arrival.LINK_SENT
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return Arrival.TIMED_OUT
        time.sleep(min(LINK_POLL_S, remaining))
