"""What `login`, `session status` and `logout` actually do.

Everything the three commands know about tabs, waiting and profiles is here, so
that `12`'s run loop can ask the same questions ("is this session usable?")
without going through the CLI — and since `23`, so are the commands themselves:
`login`, `status` and `logout` at the bottom of this module are what `cli`
calls, and the CLI adds nothing but the flag parsing and the exit.
"""

import shutil
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from dataporter import PROGRAM_NAME, log, sources
from dataporter.browser import launcher
from dataporter.browser import watch as watching
from dataporter.browser.cdp import CdpClient, Page, Target
from dataporter.browser.launcher import BrowserSession, PortInUseError
from dataporter.browser.probe import CLAUDE_HOST, MIGRATION_SITE, NEW_CHAT_URL, PageKind, PageState, probe
from dataporter.config import ASK_FILENAME, TMP_DIRNAME, Settings
from dataporter.console import DISCARD, Sink
from dataporter.errors import AuthError, BrowserError, UsageError
from dataporter.exit_codes import ExitCode
from dataporter.sources.claude import CLAUDE
from dataporter.state import StateError

if TYPE_CHECKING:
    from pathlib import Path

    from dataporter.browser.site import Site

_logger = log.get_logger(__name__)

LOGIN_POLL_S = 2.0
"""How often `login` looks. Two seconds is invisible to a human filling in a
form and costs 300 probes across the ten-minute default.

Never waited out past the deadline: see `wait_for_login`.
"""

BLANK_URLS = frozenset({"", "about:blank", "chrome://newtab/", "about:newtab"})

SIGNED_IN = "logged in"
SIGNED_OUT_LINE = "not logged in — run: {command}"
"""The words, once. `signed_out_line` fills in whichever `login` this
invocation means, and `SIGNED_OUT` is that for the destination."""

SIGNED_OUT = SIGNED_OUT_LINE.format(command=f"{PROGRAM_NAME} login")
"""What `session status` prints and what `12` refuses to start with.

Here rather than in `cli` because two commands and the import loop say it, and
an instruction an operator is given in two slightly different spellings is two
instructions as far as they can tell. For a source account the remedy carries
the account's flags (`52`): `signed_out_line` is what every caller prints, and
this constant is its destination form."""


CLAUDE_HOSTS: tuple[str, ...] = (CLAUDE_HOST,)
"""The destination's one host. A source's are its own (`42`), and every
function below that looks for a tab takes them."""


def tabs_on(client: CdpClient, hosts: Sequence[str]) -> list[Target]:
    """Every page target on one of `hosts`, in the browser's own order."""
    return [target for target in client.pages() if target.host in hosts]


def claude_tabs(client: CdpClient) -> list[Target]:
    """Every page target on claude.ai, in the browser's own order."""
    return tabs_on(client, CLAUDE_HOSTS)


def open_claude_tab(session: BrowserSession, url: str = NEW_CHAT_URL, *, hosts: Sequence[str] = CLAUDE_HOSTS) -> Page:
    """Return the tab to drive: an existing tab on the site, or one made to be it.

    A blank tab is reused before a new one is created, because that is what a
    just-launched browser looks like while its first page is still loading —
    creating a second tab there would leave the operator with two windows and
    `08` with an `ambiguous_tab`.
    """
    tabs = tabs_on(session.client, hosts)
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


def current_state(
    session: BrowserSession,
    url: str = NEW_CHAT_URL,
    *,
    settle_s: float = SETTLE_S,
    hosts: Sequence[str] = CLAUDE_HOSTS,
) -> PageState:
    """Probe the site's tab, opening one if there is not one yet.

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
    page = open_claude_tab(session, url, hosts=hosts)
    try:
        settled(page, timeout_s=settle_s)
        return probe(page, tab_count=max(len(tabs_on(session.client, hosts)), 1))
    finally:
        page.close()


def wait_for_login(
    session: BrowserSession,
    *,
    timeout_s: float,
    poll_s: float = LOGIN_POLL_S,
    url: str = NEW_CHAT_URL,
    hosts: Sequence[str] = CLAUDE_HOSTS,
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
                hosts=hosts,
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


def signed_in(session: BrowserSession, url: str = NEW_CHAT_URL, *, hosts: Sequence[str] = CLAUDE_HOSTS) -> bool:
    """One probe. `session status` is this plus a printed line."""
    return current_state(session, url, hosts=hosts).logged_in


def account_home_of(settings: Settings) -> "Path":
    """Return the account home a sign-out acts on. `UsageError` when no account was named.

    The CLI never reaches this: `--account` is required there and click refuses first
    (§82). The library is a surface of its own (`23`), so it has its own door.
    """
    home = settings.account_home
    if home is None:
        raise UsageError(NO_ACCOUNT)
    return home


def discard_session(settings: Settings, home: "Path") -> bool:
    """Delete the session, the open ask and what a fetch staged. `False` if there was none.

    `logs/` is not touched: they are the record of what was done rather than the means of
    doing it again, and §10 keeps a name, a title and a message out of them (§83). The
    three that go are named rather than swept for, so that the day an account home grows
    a fourth, §83 is what decides its fate and not an accident of what is on disk
    ([ADR 0009](../../../docs/adr/0009-sign-out-keeps-only-the-logs.md)).

    Local only: nothing is sent to the vendor, so the *account* is not signed out
    anywhere else (§84).
    """
    _close_our_window(settings)
    removed = False
    for path in (settings.browser_profile_dir, home / ASK_FILENAME, home / TMP_DIRNAME):
        removed = _remove(path) or removed
    if removed:
        _logger.info("session discarded")
    return removed


def _close_our_window(settings: Settings) -> None:
    """Close the window we opened on this profile; refuse the port to anybody else.

    Deleting a profile under a running Chrome leaves a half-written directory and a
    browser still holding the session in memory, so this runs before anything is removed
    (§85) — a refusal that arrived after the ask was gone would be a sign-out that half
    happened and reported failure.

    `adopt` answers the one question that can be answered: the marker names the browser
    on the port, so that browser is the window *we* opened on *this* profile, and closing
    it is what a person signing out meant. Anything else is `PortInUseError` from `adopt`
    itself, because Chrome does not say which profile it holds and a guess deletes the
    wrong thing.

    Closing is an ask, not a guarantee. `BrowserSession.close` deliberately sends no
    signal to an adopted browser — the process belongs to an earlier run and is holding
    the operator's session — so it waits, warns and returns. Taking that warning for a
    closed browser would put this command straight back to deleting under a running
    Chrome, which is the one thing the old blanket refusal got right.
    """
    client = CdpClient(port=settings.browser.cdp_port, timeout=settings.timeouts.cdp_call_s)
    running = launcher.adopt(client, settings.browser_profile_dir)
    if running is None:
        return
    running.close()
    if client.responding():
        raise PortInUseError(
            detail=STILL_RUNNING.format(port=client.port, command=logout_command(settings)),
            transient=False,
        )


def _remove(path: "Path") -> bool:
    """Delete one file or directory. `False` when it was not there.

    The first `OSError` stops the whole sign-out: a read-only filesystem, a permission
    the operator can grant, a file another process is holding. All fixable at the
    keyboard, so this is `StateError` — "the workspace cannot be used as asked", exit
    `2` — rather than the exit `70` an escaping OSError would earn. What was already
    removed stays removed, and the command is the same command run twice.
    """
    if not path.exists():
        return False
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError as exc:
        raise StateError(f"cannot remove {path}: {exc.strerror or exc}") from exc
    return True


# --------------------------------------------------------------------------- #
# The three commands (`23`)
# --------------------------------------------------------------------------- #

LOGIN_PROMPT = "Log in to Claude in the browser window that just opened."
LOGGED_IN = "Logged in. Session stored in {profile}/."
LOGIN_TIMED_OUT = "timed out after {seconds:g}s waiting for login"
SIGNED_OUT_BLOCK = """\
{heading}
Removed {home}/, except its logs.
"""
"""§82's first block, golden: the sign-in's mirror, and the directory it emptied."""

NOTHING_TO_REMOVE = "Nothing to remove: {home}/ has no session."
"""§82's second ending, exit `0`. Sign-out states an end, and this one already held —
which is also why a mistyped label lands here rather than on an error nobody can register
an account against."""

NO_ACCOUNT = "logout names a source account; give --account LABEL"
"""Exit `2` from the library alone (§86, `23`)."""

STILL_RUNNING = "a browser is still running on port {port} — close it, then run: {command}"
"""Exit `2`: our own window was asked to close and did not. Nothing is removed."""


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
    """`logout`: whether there was anything to remove."""

    removed: bool
    exit_code: ExitCode = ExitCode.OK


def site_of(settings: Settings) -> "Site":
    """Which site a `login` is to: the destination's, or a source's (`31`, `42`)."""
    if settings.account is None:
        return MIGRATION_SITE
    # Local: `sites` imports `helpers`, which imports this module.
    from dataporter import sources  # ruff: ignore[import-outside-top-level] - see above
    from dataporter.browser import sites  # ruff: ignore[import-outside-top-level] - see above

    return sites.extraction_site(sources.of(settings))


@dataclass(frozen=True)
class Whose:
    """Whose session a command means: where to open, what to say, which hosts.

    `vendor` and `by_link` are the source's (`50`): what the sign-in blocks
    call the site, and whether its sign-in is a link a person hands over
    rather than a form a person fills in.
    """

    url: str
    prompt: str
    hosts: tuple[str, ...]
    vendor: str = CLAUDE.display_name
    by_link: bool = CLAUDE.sign_in_by_link


def whose(settings: Settings) -> Whose:
    """Return whose session a command means: the destination's, or a source account's (`42`).

    Without an account every value is what `07` wrote — `/new`, the prompt and
    claude.ai — so a destination command's every byte is what it was; with one,
    the source says where its sign-in is and what it is called. The destination
    is a Claude account (§75), so it signs in the way Claude does.
    """
    if settings.account is None:
        return Whose(url=NEW_CHAT_URL, prompt=LOGIN_PROMPT, hosts=CLAUDE_HOSTS)
    source = sources.of(settings)
    return Whose(
        url=source.login_url,
        prompt=source.login_prompt,
        hosts=source.hosts,
        vendor=source.display_name,
        by_link=source.sign_in_by_link,
    )


def login(
    settings: Settings, *, link: str | None = None, sink: Sink = DISCARD, flags: Sequence[str] = ()
) -> LoginOutcome:
    """Sign the session in: `07`'s window, or brief 07's two commands (§73).

    A source that signs in with a form gets what `07` wrote: a window, the
    prompt, and a wait for the signed-in probe. A source that signs in by link
    — Claude, and the destination is a Claude account — gets `50`'s wait, which
    ends when the link has been spent in the window, and `53`'s `--link`, which
    spends it. Neither has an unattended half: the vendor put an attestation in
    front of the sign-in (§78), so the mode is refused before any browser
    starts, with the command a person would run instead.

    The prompt is a line on the sink rather than a log record: it is an
    instruction to the person at the keyboard, and it is the only thing this
    command asks of them. A wait that runs out is `AuthError`, exit `3`.

    `flags` are the invocation's own, for the trace's header (`33`).
    """
    from dataporter import signin  # ruff: ignore[import-outside-top-level] - signin imports login_form, which imports helpers, which imports this module

    session = whose(settings)
    if session.by_link:
        if settings.non_interactive:
            raise UsageError(UNATTENDED_REFUSED.format(vendor=session.vendor, command=login_command(settings)))
        if link is not None:
            from dataporter.browser import signin_link  # ruff: ignore[import-outside-top-level] - it imports this module

            return signin_link.spend(settings, link, sink=sink, flags=flags)
        return _login_by_link(settings, session, sink=sink, flags=flags)
    if link is not None:
        raise UsageError(NO_LINK_SIGN_IN.format(vendor=session.vendor, command=login_command(settings)))
    if settings.non_interactive:
        signin.require_credentials(settings)
    # `settings.logs_dir`, which is the workspace for the destination and the
    # account home for `31`'s source: a command about one account writes its
    # records beside that account's other operational files.
    log.enable_run_log(settings.logs_dir)
    # Through the module, not a bound name: the test suite substitutes
    # `launcher.launch` to hand a command a fake Chrome.
    browser = launcher.launch(settings, session.url)
    try:
        with watching.watched(
            settings, command="login", flags=flags, site=site_of(settings), browser=browser
        ) as traced:
            if settings.non_interactive:
                # `24`: the tool signs in, or says what a person would have to do.
                # No prompt, because nobody is reading one; the same last line,
                # because a CI log is read the way a terminal is.
                signin.ensure_signed_in(settings, browser)
            elif not signed_in(browser, session.url, hosts=session.hosts):
                sink.line(session.prompt)
                arrived = wait_for_login(
                    browser, timeout_s=settings.timeouts.login_s, url=session.url, hosts=session.hosts
                )
                if arrived is None:
                    raise AuthError(detail=LOGIN_TIMED_OUT.format(seconds=settings.timeouts.login_s))
            sink.line(LOGGED_IN.format(profile=settings.browser_profile_dir))
            traced.exit_code = ExitCode.OK
    finally:
        # Always, on every path: Chrome writes its cookie jar and session store
        # out on exit, so a profile that is never closed can come back signed
        # out — and a browser left running would hold the next run's port.
        browser.close()
    return LoginOutcome()


# --------------------------------------------------------------------------- #
# The sign-in by link (`50`, brief 07 §73)
# --------------------------------------------------------------------------- #

SIGN_IN_BLOCK = """\
{heading}

A window is open at {vendor}'s sign-in page. Enter the account's address
there, and clear anything {vendor} asks of you.

{vendor} will email a sign-in link. The link signs in once and expires, and
it must be spent here rather than opened. When it arrives:

  {command} --link <url>
"""
"""§73's first block, golden. The heading is `{vendor} sign-in`, with
` — <label>` when the session is a source account's; the command is this
invocation's own, so a person copies rather than reconstructs it."""

SIGNED_IN_BLOCK = """\
{heading}
Session stored in {profile}/.
"""
"""§73's second block, golden: `Signed in to {vendor}`, the label as above, and
where the profile is — the one thing the tool holds afterwards (§74)."""

LINK_SENT_LINE = (
    "The link is on its way. This window stays open for {minutes:g} minutes; spend the link before it closes."
)
"""Printed once the page shows the link has been sent (`link sent` in the UI
map), and the clock restarts: the mailbox's delay begins here, not when the
window opened, so a person who spent nine minutes on a challenge is not left
sixty seconds for their email."""

LINK_TIMED_OUT = "timed out after {seconds:g}s waiting for the link to be spent — run: {command}"
"""Exit `3` when the second phase runs out. The first keeps `LOGIN_TIMED_OUT`."""

SPENDER_GRACE_S = 3.0
"""How long `login` keeps its window after the session comes back signed in, before closing it.

The link is spent by `login --link` in another terminal (`53`), which reads the
same window to say so. Seen and closed in the same instant, the window is gone
before the other terminal's next look, and a command that did its job dies with
a connection error (found by `49`'s rehearsal, one run in three). One grace of
several of the other terminal's polls — it polls every `signin_link.LINK_POLL_S`
— closes that window. Read at call time, so a test can shorten it.

Both ways in, not only the link-sent one: a link spent between two of this
command's own polls takes the page from the email step to signed in without
the code field ever being seen here, and the terminal that spent it is owed
the same grace (raised by the spec review of #58)."""

UNATTENDED_REFUSED = "there is no unattended {vendor} sign-in; run: {command}"
"""Exit `2`, before any browser starts, with or without `--link` (§76): the
mode means "no person", and a sign-in behind an attestation is a person's step
whichever half of it is being asked for."""

NO_LINK_SIGN_IN = "{vendor} does not sign in with a link; run: {command}"
"""Exit `2`: `--link` on a source whose sign-in is a form. A flag that was
silently dropped would leave a person believing the link was spent."""


class Arrival(Enum):
    """How a wait for the sign-in ended."""

    SIGNED_IN = "signed_in"
    LINK_SENT = "link_sent"
    TIMED_OUT = "timed_out"


def login_command(settings: Settings) -> str:
    """Return this invocation's `login`, as a person would type it.

    With the account's flags when there is an account: a remedy that omits
    `--source` and `--account` is a command that signs in the wrong profile.
    """
    return _command(settings, "login")


def check_command(settings: Settings) -> str:
    """Return what to run to see whether a sign-in landed, as a person would type it.

    `session status` with the account's flags — or `login`, where there is no account:
    §86 left the destination without a `session status` to be sent to, and a remedy that
    cannot be typed is worse than a blunter one that can.
    """
    if settings.account is None:
        return login_command(settings)
    return _command(settings, "session status")


def logout_command(settings: Settings) -> str:
    """Return this invocation's `logout`, with the account's flags as above."""
    return _command(settings, "logout")


def _command(settings: Settings, command: str) -> str:
    if settings.account is None:
        return f"{PROGRAM_NAME} {command}"
    return f"{PROGRAM_NAME} {command} --source {settings.source} --account {settings.account}"


def _heading(prefix: str, settings: Settings) -> str:
    return prefix if settings.account is None else f"{prefix} — {settings.account}"


def sign_in_block(settings: Settings, session: "Whose | None" = None) -> str:
    """Return §73's first block for this invocation."""
    session = whose(settings) if session is None else session
    return SIGN_IN_BLOCK.format(
        heading=_heading(f"{session.vendor} sign-in", settings),
        vendor=session.vendor,
        command=login_command(settings),
    )


def signed_in_block(settings: Settings, session: "Whose | None" = None) -> str:
    """Return §73's second block for this invocation."""
    session = whose(settings) if session is None else session
    return SIGNED_IN_BLOCK.format(
        heading=_heading(f"Signed in to {session.vendor}", settings), profile=settings.browser_profile_dir
    )


def signed_out_block(settings: Settings, session: "Whose | None" = None) -> str:
    """Return §82's block for this invocation."""
    session = whose(settings) if session is None else session
    return SIGNED_OUT_BLOCK.format(
        heading=_heading(f"Signed out of {session.vendor}", settings), home=account_home_of(settings)
    )


def signed_out_line(settings: Settings) -> str:
    """Return `SIGNED_OUT` with this invocation's own remedy."""
    return SIGNED_OUT_LINE.format(command=login_command(settings))


def observe(session: BrowserSession, hosts: Sequence[str], *, settle_s: float = SETTLE_S) -> tuple[PageState, bool]:
    """Probe the site's tab without opening one: the state, and whether the code field is showing.

    `current_state` opens a tab when there is none, which is right for a
    command that has just launched a browser and wrong for a wait during which
    another command may be navigating the same tab (`53`): a link that hops
    through another host takes the tab off the site for a moment, and a wait
    that opened a second tab there would leave the person two windows. A
    browser with no tab on the site is `BrowserError`, which every wait treats
    as "not yet".

    The code field is read only on a sign-in page: a match anywhere else would
    not be `link sent`, whatever it was.
    """
    from dataporter.browser import login_form  # ruff: ignore[import-outside-top-level] - it imports helpers, which imports this module

    tabs = tabs_on(session.client, hosts)
    if not tabs:
        raise BrowserError(detail="no tab on the site yet")
    page = session.client.attach(tabs[0].id)
    try:
        settled(page, timeout_s=settle_s)
        state = probe(page, tab_count=len(tabs))
        code = state.kind is PageKind.LOGIN and login_form.fields_of(page).code
    finally:
        page.close()
    return state, code


def polling(
    session: BrowserSession, hosts: Sequence[str], *, timeout_s: float, poll_s: float
) -> Iterator[tuple[PageState | None, bool]]:
    """Yield what the site's tab shows, every `poll_s`, until `timeout_s` runs out.

    `observe`'s pair, or `(None, False)` for a look the browser could not
    answer — mid-navigation, or no tab on the site yet, both of which are "not
    yet" to everybody waiting. The one thing nobody can wait out is a browser
    that has stopped answering at all, and that still raises.

    The loop, once: two commands wait on this tab for opposite reasons (`50`
    for the link to be sent, `53` for it to have been spent), and what they
    share is the budget, the poll and the patience, not the decision. Each
    reads the pair and says when it has seen enough; running out is falling off
    the end.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            seen = observe(session, hosts, settle_s=max(0.0, min(SETTLE_S, deadline - time.monotonic())))
        except BrowserError:
            if not session.client.responding():
                raise
            seen = (None, False)
        yield seen
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(poll_s, remaining))


def await_signin(
    session: BrowserSession,
    *,
    timeout_s: float,
    hosts: Sequence[str],
    poll_s: float = LOGIN_POLL_S,
    link_sent_ends: bool = True,
) -> Arrival:
    """Poll until the session is signed in, the link has been sent, or the time is up.

    `wait_for_login`'s wait with `observe` in place of `current_state`, and one
    more way out: with `link_sent_ends`, the first sight of the code field is
    `LINK_SENT`, which is where `login` prints its line and restarts the clock.
    Without it — the second phase — the code field is what the page keeps
    showing until the link is spent, and only signed in ends the wait early.
    """
    for state, code in polling(session, hosts, timeout_s=timeout_s, poll_s=poll_s):
        if state is not None and state.logged_in:
            return Arrival.SIGNED_IN
        if code and link_sent_ends:
            return Arrival.LINK_SENT
    return Arrival.TIMED_OUT


def _login_by_link(settings: Settings, session: Whose, *, sink: Sink, flags: Sequence[str]) -> LoginOutcome:
    """§73's first command: the window, the block, the wait that ends signed in.

    Two phases on the same number, `timeouts.login_s`: one for the address and
    whatever the vendor asks of the person, restarted when the page says the
    link is on its way, and one for the link to arrive and be spent — by
    `login --link` in another terminal, adopting this window (`53`). The window
    is this command's to close, and it closes it on every path.
    """
    log.enable_run_log(settings.logs_dir)
    browser = launcher.launch(settings, session.url)
    try:
        with watching.watched(
            settings, command="login", flags=flags, site=site_of(settings), browser=browser
        ) as traced:
            timeout_s = settings.timeouts.login_s
            if not signed_in(browser, session.url, hosts=session.hosts):
                sink.block(sign_in_block(settings, session))
                # `poll_s` read at call time, so a test can shorten the module's cadence.
                arrival = await_signin(browser, timeout_s=timeout_s, hosts=session.hosts, poll_s=LOGIN_POLL_S)
                if arrival is Arrival.TIMED_OUT:
                    raise AuthError(detail=LOGIN_TIMED_OUT.format(seconds=timeout_s))
                if arrival is Arrival.LINK_SENT:
                    _logger.info("sign-in link sent")
                    sink.line(LINK_SENT_LINE.format(minutes=timeout_s / 60))
                    arrival = await_signin(
                        browser, timeout_s=timeout_s, hosts=session.hosts, poll_s=LOGIN_POLL_S, link_sent_ends=False
                    )
                    if arrival is Arrival.TIMED_OUT:
                        raise AuthError(
                            detail=LINK_TIMED_OUT.format(seconds=timeout_s, command=login_command(settings))
                        )
                # Whichever way the session came back signed in — through the
                # link-sent page, or straight from the email step because the
                # link was spent between two polls — the other terminal is
                # reading this window too, and is owed the sight of it.
                time.sleep(SPENDER_GRACE_S)
            sink.block(signed_in_block(settings, session))
            traced.exit_code = ExitCode.OK
    finally:
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
        sink.line(signed_out_line(settings))
        return StatusOutcome(signed_in=False, exit_code=ExitCode.NOT_AUTHENTICATED)

    session = whose(settings)
    browser = running or launcher.launch(settings, session.url)
    try:
        answer = signed_in(browser, session.url, hosts=session.hosts)
    finally:
        # A browser this command started is a browser this command cleans up;
        # one that was already running belongs to whoever started it.
        if running is None:
            browser.close()
    sink.line(SIGNED_IN if answer else signed_out_line(settings))
    return StatusOutcome(
        signed_in=answer,
        exit_code=ExitCode.OK if answer else ExitCode.NOT_AUTHENTICATED,
    )


def logout(settings: Settings, *, sink: Sink = DISCARD) -> LogoutOutcome:
    """Sign out: discard the session, the open ask and what a fetch staged (§83).

    Local only, and said so (§84): the account itself is untouched, and a session on
    another machine is not ended by this. The account home is resolved before the run log
    is enabled, so a refusal never leaves a log behind in a workspace it was not about.
    """
    home = account_home_of(settings)
    log.enable_run_log(settings.logs_dir)
    removed = discard_session(settings, home)
    if removed:
        sink.block(signed_out_block(settings))
    else:
        sink.line(NOTHING_TO_REMOVE.format(home=home))
    return LogoutOutcome(removed=removed)
