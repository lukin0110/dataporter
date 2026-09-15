"""Brief 07's two commands (`50`, `53`): the wait that ends signed in, and the link that ends it.

`login` opens the window, prints §73's first block, sees the link sent, and keeps
the window until the link has been spent in it; `login --link` spends it, in the
window `login` is holding or in a profile launched for the purpose. Both against
`fake_chrome`, with a tab that answers the probe and `login_form`'s field reading
stage by stage, as a person moving through claude.ai's sign-in would make it.
"""

import json
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dataporter import cli
from dataporter.browser import launcher, login_form, signin_link
from dataporter.browser import session as browser_session
from dataporter.config import AccountsSettings, BrowserSettings, Settings, TimeoutSettings, with_account
from dataporter.exit_codes import ExitCode
from fake_chrome import SETTLE_EXPRESSION, Call, FakeChrome, FakeTarget, entered, free_port, page_state

pytestmark = pytest.mark.slow

LOGIN_URL = "https://claude.ai/login"
NEW_URL = "https://claude.ai/new"
MAGIC_URL = "https://claude.ai/magic-link"
LINK = "https://claude.ai/magic-link#0123456789abcdef:ZW1haWw"
TOKEN = "0123456789abcdef"
ACCOUNT = "old-personal"

DESTINATION_BLOCK = (
    "Claude sign-in\n"
    "\n"
    "A window is open at Claude's sign-in page. Enter the account's address\n"
    "there, and clear anything Claude asks of you.\n"
    "\n"
    "Claude will email a sign-in link. The link signs in once and expires, and\n"
    "it must be spent here rather than opened. When it arrives:\n"
    "\n"
    "  dataporter login --link <url>\n"
)
SOURCE_BLOCK = (
    f"Claude sign-in — {ACCOUNT}\n"
    "\n"
    "A window is open at Claude's sign-in page. Enter the account's address\n"
    "there, and clear anything Claude asks of you.\n"
    "\n"
    "Claude will email a sign-in link. The link signs in once and expires, and\n"
    "it must be spent here rather than opened. When it arrives:\n"
    "\n"
    f"  dataporter login --source claude --account {ACCOUNT} --link <url>\n"
)
"""§73's first block, golden, for the destination and for a source account."""

LINK_SENT = "The link is on its way. This window stays open for 10 minutes; spend the link before it closes.\n"


class SignInPage:
    """A claude.ai tab through the sign-in, answering what the tool asks of it.

    `stage` is `email` (the address not yet given), `link_sent` (the code field
    showing), `magic` (the link's own page, being redeemed: no fields, no
    composer), or `done` (signed in on `/new`). `after` moves the stage on after
    that many probes, which is how a test stands where a person would.
    """

    def __init__(self, stage: str = "email", *, after: dict[int, str] | None = None) -> None:
        self.stage = stage
        self.after = dict(after or {})
        self.probes = 0

    def __call__(self, call: Call) -> Any:
        expression = str(call.params.get("expression", ""))
        if expression.startswith(SETTLE_EXPRESSION):
            return self.url
        if login_form.LOGIN_FIELDS_TAG in expression:
            return {"email": self.stage == "email", "password": False, "code": self.stage == "link_sent"}
        self.probes += 1
        if self.probes in self.after:
            self.stage = self.after[self.probes]
        if self.stage == "done":
            return page_state()
        return page_state(url=self.url, composer_present=False)

    @property
    def url(self) -> str:
        return {"done": NEW_URL, "magic": MAGIC_URL}.get(self.stage, LOGIN_URL)


def make_settings(tmp_path: Path, port: int) -> Settings:
    return Settings(
        workspace=tmp_path / "migration",
        browser=BrowserSettings(executable=Path(sys.executable), cdp_port=port),
        timeouts=TimeoutSettings(cdp_call_s=2.0),
    )


def source_settings(tmp_path: Path, port: int) -> Settings:
    settings = make_settings(tmp_path, port).model_copy(
        update={"accounts": AccountsSettings(dir=tmp_path / "accounts")}
    )
    return with_account(settings, "claude", ACCOUNT)


@pytest.fixture
def chrome() -> Iterator[FakeChrome]:
    with FakeChrome(targets=[FakeTarget(id="page-1", url=LOGIN_URL, evaluate=SignInPage())]) as fake:
        yield fake


@pytest.fixture
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    """Poll every hundredth of a second rather than every two, so a wait that ends early ends at once.

    And no grace before the window closes: what the grace is for has its own test.
    """
    monkeypatch.setattr(browser_session, "LOGIN_POLL_S", 0.01)
    monkeypatch.setattr(signin_link, "LINK_POLL_S", 0.01)
    monkeypatch.setattr(browser_session, "SPENDER_GRACE_S", 0.0)


def adoptable(chrome: FakeChrome, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Return a profile whose marker names this fake browser: `launch` and `adopt` both find it."""
    profile = launcher.ensure_profile(settings)
    launcher.write_marker(
        profile, launcher.ProfileMarker(port=chrome.port, browser_id=chrome.browser_id, pid=1, started="now")
    )
    monkeypatch.setenv("DATAPORTER_WORKSPACE", str(settings.workspace))
    monkeypatch.setenv("DATAPORTER_ACCOUNTS__DIR", str(settings.accounts.dir or settings.workspace / "accounts"))
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", str(chrome.port))
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__CDP_CALL_S", "2")
    return settings


def page_of(chrome: FakeChrome) -> SignInPage:
    page = chrome.targets[0].evaluate
    assert isinstance(page, SignInPage)
    return page


def navigations(chrome: FakeChrome) -> list[str]:
    return [str(call.params.get("url")) for call in chrome.calls if call.method == "Page.navigate"]


def trace_lines(logs: Path) -> list[dict[str, Any]]:
    traces = sorted(logs.glob("trace-*.jsonl"))
    assert len(traces) == 1, traces
    return [json.loads(line) for line in traces[0].read_text(encoding="utf-8").splitlines()]


# --------------------------------------------------------------------------- #
# `50`: login waits for the link to be spent
# --------------------------------------------------------------------------- #


def test_login_prints_the_block_and_waits_until_the_link_is_spent(
    runner: CliRunner, chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quick: None
) -> None:
    """The whole of §73's first command, as a person and a second terminal would make it go."""
    settings = adoptable(chrome, make_settings(tmp_path, chrome.port), monkeypatch)
    page_of(chrome).after = {3: "link_sent", 6: "done"}

    result = runner.invoke(cli.app, ["login"], catch_exceptions=False)

    assert result.exit_code == ExitCode.OK
    assert result.stdout == (
        DESTINATION_BLOCK + LINK_SENT + f"Signed in to Claude\nSession stored in {settings.browser_profile_dir}/.\n"
    )
    assert "Browser.close" in chrome.methods()
    # No tab was opened by the wait: the browser it launched already had one.
    assert "Target.createTarget" not in chrome.methods()


def test_a_source_account_s_block_carries_its_label_and_its_own_command(
    runner: CliRunner, chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quick: None
) -> None:
    settings = adoptable(chrome, source_settings(tmp_path, chrome.port), monkeypatch)
    page_of(chrome).after = {2: "link_sent", 4: "done"}

    result = runner.invoke(cli.app, ["login", "--source", "claude", "--account", ACCOUNT], catch_exceptions=False)

    assert result.exit_code == ExitCode.OK
    assert result.stdout == (
        SOURCE_BLOCK
        + LINK_SENT
        + f"Signed in to Claude — {ACCOUNT}\nSession stored in {settings.browser_profile_dir}/.\n"
    )


def test_the_clock_restarts_when_the_link_is_sent(
    runner: CliRunner, chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quick: None
) -> None:
    """A link never spent: the second phase runs out, and says so with the remedy."""
    adoptable(chrome, make_settings(tmp_path, chrome.port), monkeypatch)
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__LOGIN_S", "0.05")
    page_of(chrome).stage = "link_sent"

    result = runner.invoke(cli.app, ["login"], catch_exceptions=False)

    assert result.exit_code == ExitCode.NOT_AUTHENTICATED
    assert result.stdout == DESTINATION_BLOCK + LINK_SENT.replace("10 minutes", "0.000833333 minutes")
    assert result.stderr == "error: timed out after 0.05s waiting for the link to be spent — run: dataporter login\n"
    assert "Browser.close" in chrome.methods()


def test_a_pending_sign_in_the_window_opens_on_gets_the_block_again(
    runner: CliRunner, chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quick: None
) -> None:
    """A link from an earlier `login` still on its way: the same block, the same wait."""
    adoptable(chrome, make_settings(tmp_path, chrome.port), monkeypatch)
    page_of(chrome).stage = "link_sent"
    page_of(chrome).after = {4: "done"}

    result = runner.invoke(cli.app, ["login"], catch_exceptions=False)

    assert result.exit_code == ExitCode.OK
    assert result.stdout.startswith(DESTINATION_BLOCK + LINK_SENT)


def test_the_wait_opens_no_tab_while_the_link_hops_through_another_host(
    chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quick: None
) -> None:
    """`53` navigates the tab; a mail host's redirect takes it off claude.ai for a moment."""
    settings = make_settings(tmp_path, chrome.port)
    session = launcher.BrowserSession(
        client=browser_session.CdpClient(port=chrome.port, timeout=2.0),
        profile=settings.browser_profile_dir,
        adopted=True,
    )
    target = chrome.targets[0]
    target.url = "https://mail.example/hop"
    page_of(chrome).stage = "done"

    def land() -> None:
        target.url = NEW_URL

    threading.Timer(0.05, land).start()
    arrival = browser_session.await_signin(session, timeout_s=5.0, hosts=("claude.ai",), poll_s=0.01)

    assert arrival is browser_session.Arrival.SIGNED_IN
    assert "Target.createTarget" not in chrome.methods()


def test_the_window_stays_a_grace_after_the_link_is_spent(
    runner: CliRunner, chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quick: None
) -> None:
    """`53`'s terminal reads the same window; it must get to see the signed-in page before the window goes.

    Found by `49`'s rehearsal, one run in three: seen and closed in the same
    instant, the other terminal died of a connection error after doing its job.
    """
    adoptable(chrome, make_settings(tmp_path, chrome.port), monkeypatch)
    monkeypatch.setattr(browser_session, "SPENDER_GRACE_S", 0.05)
    page_of(chrome).stage = "link_sent"
    page_of(chrome).after = {4: "done"}
    slept: list[float] = []
    real_sleep = browser_session.time.sleep

    def recording(seconds: float) -> None:
        slept.append(seconds)
        real_sleep(seconds)

    monkeypatch.setattr(browser_session.time, "sleep", recording)

    result = runner.invoke(cli.app, ["login"], catch_exceptions=False)

    assert result.exit_code == ExitCode.OK
    # The last sleep before the close is the grace, and it is longer than a poll.
    assert slept[-1] == 0.05
    assert all(pause <= 0.01 for pause in slept[:-1])
    assert "Browser.close" in chrome.methods()


def test_the_mode_is_refused_with_a_link_too(
    runner: CliRunner, chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adoptable(chrome, source_settings(tmp_path, chrome.port), monkeypatch)
    monkeypatch.setenv("DATAPORTER_NON_INTERACTIVE", "1")

    result = runner.invoke(
        cli.app, ["login", "--source", "claude", "--account", ACCOUNT, "--link", LINK], catch_exceptions=False
    )

    assert result.exit_code == ExitCode.USAGE
    assert result.stderr == (
        f"error: there is no unattended Claude sign-in; run: dataporter login --source claude --account {ACCOUNT}\n"
    )
    assert chrome.methods() == []


def test_a_source_that_signs_in_with_a_form_takes_no_link(
    runner: CliRunner, chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adoptable(chrome, source_settings(tmp_path, chrome.port), monkeypatch)

    result = runner.invoke(
        cli.app, ["login", "--source", "chatgpt", "--account", "work", "--link", LINK], catch_exceptions=False
    )

    assert result.exit_code == ExitCode.USAGE
    assert result.stderr == (
        "error: ChatGPT does not sign in with a link; run: dataporter login --source chatgpt --account work\n"
    )
    assert chrome.methods() == []


# --------------------------------------------------------------------------- #
# `53`: login --link spends it
# --------------------------------------------------------------------------- #


def spent_on_navigate(chrome: FakeChrome, stage: str = "done") -> None:
    """Have the tab move to `stage` the moment it is navigated: what the vendor does with a good link."""

    def responder(_chrome: FakeChrome, call: Call) -> None:
        if call.method == "Page.navigate":
            page_of(chrome).stage = stage

    chrome.responder = responder


def test_the_link_is_spent_in_the_window_login_is_holding(
    runner: CliRunner, chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quick: None
) -> None:
    settings = adoptable(chrome, make_settings(tmp_path, chrome.port), monkeypatch)
    page_of(chrome).stage = "link_sent"
    spent_on_navigate(chrome)

    result = runner.invoke(cli.app, ["login", "--link", LINK], catch_exceptions=False)

    assert result.exit_code == ExitCode.OK
    assert result.stdout == f"Signed in to Claude\nSession stored in {settings.browser_profile_dir}/.\n"
    assert navigations(chrome) == [LINK]
    # The window belongs to the `login` that opened it.
    assert "Browser.close" not in chrome.methods()
    assert "Target.createTarget" not in chrome.methods()


def test_the_trace_carries_the_link_s_host_and_never_the_link(
    runner: CliRunner, chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quick: None
) -> None:
    settings = adoptable(chrome, make_settings(tmp_path, chrome.port), monkeypatch)
    page_of(chrome).stage = "link_sent"
    spent_on_navigate(chrome)

    result = runner.invoke(cli.app, ["login", "--link", LINK], catch_exceptions=False)
    assert result.exit_code == ExitCode.OK

    written = trace_lines(settings.workspace / "logs")
    assert written[0]["command"] == "login"
    assert written[0]["flags"] == ["--link"]
    moves = [line for line in written if line.get("kind") == "move"]
    assert [move["helper"] for move in moves] == [signin_link.LINK_ACTION]
    assert moves[0]["result"] == {"host": "claude.ai", "path": "<link>", "query": []}
    everything = "".join(path.read_text(encoding="utf-8") for path in (settings.workspace / "logs").iterdir())
    assert TOKEN not in everything
    assert "magic-link" not in everything
    actions = [
        json.loads(line)
        for line in (settings.workspace / "logs" / "actions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [action["helper"] for action in actions] == [signin_link.LINK_ACTION]


def test_the_old_document_answering_after_the_navigation_is_not_a_code_prompt(
    runner: CliRunner, chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quick: None
) -> None:
    """`Page.navigate` returns before the old `/login` is gone; its code field is not the answer.

    Raised by Copilot in review on #58: the tab was on the link-sent page when
    the link was navigated to, so the first looks after it can still see that
    page — and a refusal there would refuse a link about to work.
    """
    settings = adoptable(chrome, make_settings(tmp_path, chrome.port), monkeypatch)
    page_of(chrome).stage = "link_sent"
    # Two looks answered by the old document, then the link lands and signs in.
    page_of(chrome).after = {4: "done"}

    result = runner.invoke(cli.app, ["login", "--link", LINK], catch_exceptions=False)

    assert result.exit_code == ExitCode.OK
    assert result.stdout == f"Signed in to Claude\nSession stored in {settings.browser_profile_dir}/.\n"
    assert navigations(chrome) == [LINK]


def test_a_link_that_lands_back_on_the_code_prompt_is_refused(
    runner: CliRunner, chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quick: None
) -> None:
    """The pending sign-in is not in this profile: the vendor showed a code to a window nobody has.

    Back at the sign-in page, and not still on it: the tab was seen on the
    link's own page first.
    """
    adoptable(chrome, source_settings(tmp_path, chrome.port), monkeypatch)
    page_of(chrome).stage = "link_sent"
    spent_on_navigate(chrome, stage="magic")
    page_of(chrome).after = {3: "link_sent"}

    result = runner.invoke(
        cli.app, ["login", "--source", "claude", "--account", ACCOUNT, "--link", LINK], catch_exceptions=False
    )

    assert result.exit_code == ExitCode.NOT_AUTHENTICATED
    assert result.stderr == (
        "error: the link led to a code prompt — the pending sign-in is not in this profile; "
        f"sign in again with: dataporter login --source claude --account {ACCOUNT}\n"
    )
    assert navigations(chrome) == [LINK]


def test_a_link_that_is_not_accepted_in_time_is_refused(
    runner: CliRunner, chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quick: None
) -> None:
    adoptable(chrome, make_settings(tmp_path, chrome.port), monkeypatch)
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__SIGNIN_S", "0.05")
    page_of(chrome).stage = "link_sent"
    # The link's page, and nothing after it: neither signed in nor back at the code field.
    spent_on_navigate(chrome, stage="magic")

    result = runner.invoke(cli.app, ["login", "--link", LINK], catch_exceptions=False)

    assert result.exit_code == ExitCode.NOT_AUTHENTICATED
    assert result.stderr == (
        "error: the link was not accepted — it may have expired; sign in again with: dataporter login\n"
    )


def test_a_window_that_closes_under_the_link_names_status_rather_than_guessing(
    runner: CliRunner, chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quick: None
) -> None:
    """The adopted window went away after the navigation: exit `6`, and `session status` to ask."""
    adoptable(chrome, source_settings(tmp_path, chrome.port), monkeypatch)
    page_of(chrome).stage = "link_sent"

    def responder(_chrome: FakeChrome, call: Call) -> None:
        if call.method == "Page.navigate":
            chrome.stop_http()

    chrome.responder = responder

    result = runner.invoke(
        cli.app, ["login", "--source", "claude", "--account", ACCOUNT, "--link", LINK], catch_exceptions=False
    )

    assert result.exit_code == ExitCode.ENVIRONMENT
    assert result.stderr == (
        "error: the sign-in window closed before the link's outcome was seen; the session may well be "
        f"signed in — check with: dataporter session status --source claude --account {ACCOUNT}\n"
    )
    assert navigations(chrome) == [LINK]


def test_a_link_that_is_not_https_is_refused_before_any_browser(
    runner: CliRunner, chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adoptable(chrome, make_settings(tmp_path, chrome.port), monkeypatch)

    result = runner.invoke(cli.app, ["login", "--link", "http://claude.ai/magic-link#x"], catch_exceptions=False)

    assert result.exit_code == ExitCode.USAGE
    assert result.stderr == "error: the link must be an https URL\n"
    assert chrome.methods() == []


def test_a_profile_that_is_already_signed_in_spends_no_link(
    runner: CliRunner, chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = adoptable(chrome, make_settings(tmp_path, chrome.port), monkeypatch)
    page_of(chrome).stage = "done"

    result = runner.invoke(cli.app, ["login", "--link", LINK], catch_exceptions=False)

    assert result.exit_code == ExitCode.OK
    assert result.stdout == f"Signed in to Claude\nSession stored in {settings.browser_profile_dir}/.\n"
    assert navigations(chrome) == []


def test_with_no_window_open_the_link_launches_the_profile_and_closes_it(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quick: None
) -> None:
    """`login` timed out, or the person ran this tomorrow: the profile is opened for the link."""
    settings = make_settings(tmp_path, free_port())
    launcher.ensure_profile(settings)
    started: list[FakeChrome] = []
    commands: list[list[str]] = []

    def fake_popen(command: list[str], **kwargs: object) -> object:
        commands.append(list(command))
        fake = entered(
            FakeChrome(
                port=settings.browser.cdp_port,
                targets=[FakeTarget(id="page-1", url=LOGIN_URL, evaluate=SignInPage(stage="link_sent"))],
            )
        )
        spent_on_navigate(fake)
        started.append(fake)
        return _NeverExits()

    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)
    monkeypatch.setenv("DATAPORTER_WORKSPACE", str(settings.workspace))
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", str(settings.browser.cdp_port))
    monkeypatch.setenv("DATAPORTER_BROWSER__EXECUTABLE", sys.executable)
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__CDP_CALL_S", "2")
    try:
        result = runner.invoke(cli.app, ["login", "--link", LINK], catch_exceptions=False)
        assert result.exit_code == ExitCode.OK
        assert result.stdout == f"Signed in to Claude\nSession stored in {settings.browser_profile_dir}/.\n"
        assert navigations(started[0]) == [LINK]
        assert started[0].closed
        # Headed: the mode was refused before this, and nothing here adds the flag.
        assert launcher.HEADLESS_FLAG not in commands[0]
    finally:
        for browser in started:
            browser.stop()


class _NeverExits:
    """A `Popen` whose process is always still there. `close` waits on it."""

    pid = 1234
    returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = 0
        return 0
