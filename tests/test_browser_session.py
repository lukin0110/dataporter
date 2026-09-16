"""Picking a tab, waiting for a login, and throwing the profile away."""

import ast
import json
import shutil
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import dataporter
from dataporter import cli, log
from dataporter.browser import export_page, launcher, probe
from dataporter.browser import session as browser_session
from dataporter.browser.cdp import CdpClient
from dataporter.browser.probe import NEW_CHAT_URL
from dataporter.config import (
    ASK_FILENAME,
    TMP_DIRNAME,
    AccountsSettings,
    BrowserSettings,
    Settings,
    TimeoutSettings,
    with_account,
    with_session_account,
)
from dataporter.errors import BrowserError, UsageError
from dataporter.exit_codes import ExitCode
from dataporter.state import StateError
from fake_chrome import Call, FakeChrome, FakeTarget, entered, free_port, page_state

pytestmark = pytest.mark.slow
"""Slow all the way through: a fake Chrome per test, binding two ports, and three
login waits that really wait — for a twentieth of a second each, since `22`."""


def make_settings(tmp_path: Path, port: int) -> Settings:
    return Settings(
        workspace=tmp_path / "migration",
        browser=BrowserSettings(executable=Path(sys.executable), cdp_port=port),
        timeouts=TimeoutSettings(cdp_call_s=2.0),
    )


def session_for(chrome: FakeChrome, tmp_path: Path) -> launcher.BrowserSession:
    """Return a `BrowserSession` around a fake browser, as adoption would produce."""
    settings = make_settings(tmp_path, chrome.port)
    return launcher.BrowserSession(
        client=CdpClient(port=chrome.port, timeout=2.0),
        profile=settings.browser_profile_dir,
        adopted=True,
    )


@pytest.fixture
def chrome() -> Iterator[FakeChrome]:
    with FakeChrome(
        targets=[
            FakeTarget(
                id="page-1",
                url="https://claude.ai/new",
                evaluate=page_state(),
            )
        ]
    ) as fake:
        yield fake


# --------------------------------------------------------------------------- #
# Choosing the tab
# --------------------------------------------------------------------------- #


def test_an_existing_claude_tab_is_used(chrome: FakeChrome, tmp_path: Path) -> None:
    session = session_for(chrome, tmp_path)
    page = browser_session.open_claude_tab(session)
    try:
        assert page.target.id == "page-1"
    finally:
        page.close()
    assert "Page.navigate" not in chrome.methods()
    assert len(chrome.targets) == 1


def test_a_blank_tab_is_navigated_rather_than_a_second_one_opened(
    tmp_path: Path,
) -> None:
    """What a just-launched browser looks like while its first page loads.

    A new tab here would leave two windows and `08` with an `ambiguous_tab`.
    """
    with FakeChrome(targets=[FakeTarget(id="page-1", url="about:blank", evaluate=page_state())]) as chrome:
        session = session_for(chrome, tmp_path)
        page = browser_session.open_claude_tab(session, NEW_CHAT_URL)
        try:
            assert page.target.id == "page-1"
        finally:
            page.close()
        assert len(chrome.targets) == 1
        assert chrome.targets[0].url == NEW_CHAT_URL


def test_a_tab_is_created_when_there_is_none(tmp_path: Path) -> None:
    with FakeChrome(targets=[]) as chrome:
        session = session_for(chrome, tmp_path)
        page = browser_session.open_claude_tab(session, NEW_CHAT_URL)
        try:
            assert page.target.url == NEW_CHAT_URL
        finally:
            page.close()
        assert "Target.createTarget" in chrome.methods()


def test_a_failed_navigation_does_not_leak_the_connection(tmp_path: Path) -> None:
    """`wait_for_login` retries every two seconds for ten minutes.

    One WebSocket left open per failed attempt would be three hundred of them.
    """

    def responder(fake: FakeChrome, call: Call) -> dict[str, object] | None:
        if call.method != "Page.navigate":
            return None
        return {"result": {"errorText": "net::ERR_CONNECTION_REFUSED"}}

    with FakeChrome(
        targets=[FakeTarget(id="page-1", url="about:blank", evaluate=page_state())],
        responder=responder,
    ) as chrome:
        session = session_for(chrome, tmp_path)
        for _ in range(3):
            with pytest.raises(BrowserError, match="ERR_CONNECTION_REFUSED"):
                browser_session.open_claude_tab(session, NEW_CHAT_URL)
        deadline = time.monotonic() + 5.0
        while chrome.open_connections and time.monotonic() < deadline:
            time.sleep(0.05)
        assert chrome.open_connections == 0


def test_claude_tabs_ignores_other_sites_and_workers(tmp_path: Path) -> None:
    with FakeChrome(
        targets=[
            FakeTarget(id="page-1", url="https://example.com/"),
            FakeTarget(id="page-2", url="https://claude.ai/new"),
            FakeTarget(id="sw-1", url="https://claude.ai/sw.js", type="service_worker"),
        ]
    ) as chrome:
        client = CdpClient(port=chrome.port, timeout=2.0)
        assert [item.id for item in browser_session.claude_tabs(client)] == ["page-2"]


def test_current_state_counts_the_claude_tabs(tmp_path: Path) -> None:
    with FakeChrome(
        targets=[
            FakeTarget(id="page-1", url="https://claude.ai/new", evaluate=page_state()),
            FakeTarget(id="page-2", url="https://claude.ai/chat/x", evaluate=page_state()),
        ]
    ) as chrome:
        session = session_for(chrome, tmp_path)
        assert browser_session.current_state(session).tab_count == 2


# --------------------------------------------------------------------------- #
# Waiting for the operator
# --------------------------------------------------------------------------- #


LOGGED_OUT = page_state(url="https://claude.ai/login", composer_present=False)


def test_wait_for_login_returns_once_a_composer_appears(chrome: FakeChrome, tmp_path: Path) -> None:
    seen = {"probes": 0}

    def evaluate(call: Call) -> dict[str, object] | str:
        # The settle check is not a probe: it is `07` waiting for the tab to
        # hold a page at all, and this tab already does.
        if str(call.params.get("expression", "")) == browser_session.READY_JS:
            return "https://claude.ai/new"
        seen["probes"] += 1
        return LOGGED_OUT if seen["probes"] < 3 else page_state()

    chrome.targets[0].evaluate = evaluate
    session = session_for(chrome, tmp_path)
    state = browser_session.wait_for_login(session, timeout_s=5.0, poll_s=0.01)
    assert state is not None
    assert state.logged_in
    assert seen["probes"] == 3


def test_wait_for_login_gives_up(chrome: FakeChrome, tmp_path: Path) -> None:
    chrome.targets[0].evaluate = LOGGED_OUT
    session = session_for(chrome, tmp_path)
    assert browser_session.wait_for_login(session, timeout_s=0.05, poll_s=0.01) is None


class StopWaitingError(Exception):
    """Raised out of a patched `sleep`, to end a wait at its first poll."""


def test_a_wait_never_sleeps_past_its_own_deadline(
    chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A poll longer than what is left of the budget is cut to what is left.

    Sleeping a whole `poll_s` at the end overshoots the timeout by up to two
    seconds — `login` with a five-second budget giving up at seven — and the end
    of a wait is the part somebody is watching.

    Judged by what the wait asks `sleep` for, and arranged so that no real
    duration decides the outcome. A budget of `0.05` would have done neither: a
    probe is a WebSocket handshake, a busy machine can spend longer than that
    inside the first one, and the wait would then give up having slept nothing —
    a test that flaps rather than one that fails. So the budget is 30 s, which
    no probe against a fake reaches, the poll is ten times it, and `sleep` ends
    the wait the moment it is called. Nothing sleeps and nothing is timed: what
    is asserted is the *argument*, which the fix clamps to the budget and the
    bug leaves at `poll_s`.

    Faking `monotonic` too — the other way to make this deterministic — would
    reach further than the code under test: `browser_session.time` is the `time`
    module itself, and `websockets` is timing this connection by the same clock.
    """
    slept: list[float] = []

    def record(seconds: float) -> None:
        slept.append(seconds)
        raise StopWaitingError

    monkeypatch.setattr(browser_session.time, "sleep", record)
    chrome.targets[0].evaluate = LOGGED_OUT
    session = session_for(chrome, tmp_path)

    with pytest.raises(StopWaitingError):
        browser_session.wait_for_login(session, timeout_s=30.0, poll_s=300.0)

    assert len(slept) == 1
    assert 0 < slept[0] <= 30.0


def test_a_failed_probe_is_not_a_failed_login(chrome: FakeChrome, tmp_path: Path) -> None:
    """The page is navigating, the tab is being replaced, the identity provider is redirecting.

    None of that ends the wait.
    """
    seen = {"probes": 0}

    def responder(fake: FakeChrome, call: Call) -> dict[str, object] | None:
        if call.method != "Runtime.evaluate":
            return None
        seen["probes"] += 1
        if seen["probes"] == 1:
            return {"error": {"code": -32000, "message": "Target closed"}}
        return None

    chrome.responder = responder
    session = session_for(chrome, tmp_path)
    state = browser_session.wait_for_login(session, timeout_s=5.0, poll_s=0.01)
    assert state is not None
    assert seen["probes"] == 2


def test_a_browser_that_has_gone_away_ends_the_wait(chrome: FakeChrome, tmp_path: Path) -> None:
    session = session_for(chrome, tmp_path)
    chrome.stop()
    with pytest.raises(BrowserError):
        browser_session.wait_for_login(session, timeout_s=5.0, poll_s=0.01)


def test_signed_in_is_one_probe(chrome: FakeChrome, tmp_path: Path) -> None:
    session = session_for(chrome, tmp_path)
    assert browser_session.signed_in(session)
    chrome.targets[0].evaluate = LOGGED_OUT
    assert not browser_session.signed_in(session)


# --------------------------------------------------------------------------- #
# Logging out
# --------------------------------------------------------------------------- #


def furnished(settings: Settings) -> dict[str, Path]:
    """Build an account home holding all four things, as the commands that write them do."""
    home = settings.account_home
    assert home is not None
    profile = launcher.ensure_profile(settings)
    (profile / "Cookies").write_text("a session", encoding="utf-8")
    ask = home / ASK_FILENAME
    ask.write_text('{"asked_at": "2026-09-16T00:00:00+00:00"}\n', encoding="utf-8")
    staged = home / TMP_DIRNAME / "conversations.zip"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text("an export nobody filed", encoding="utf-8")
    kept = home / log.LOGS_DIRNAME / "run-earlier.jsonl"
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text('{"event": "an earlier run"}\n', encoding="utf-8")
    return {"profile": profile, "ask": ask, "staged": staged, "kept": kept}


def test_logout_removes_everything_but_the_logs(tmp_path: Path) -> None:
    """§83: the session, the open ask and what a fetch staged. Not `logs/`."""
    settings = account_settings(tmp_path, free_port())
    home = settings.account_home
    assert home is not None
    there = furnished(settings)

    assert browser_session.discard_session(settings, home)

    assert not there["profile"].exists()
    assert not there["ask"].exists()
    assert not there["staged"].parent.exists()
    assert there["kept"].read_text(encoding="utf-8") == '{"event": "an earlier run"}\n'


def test_logout_removes_what_is_there_and_not_what_is_not(tmp_path: Path) -> None:
    """Each of the three missing on its own is still a sign-out, not a refusal."""
    for leave_out in ("profile", "ask", "staged"):
        settings = account_settings(tmp_path / leave_out, free_port())
        home = settings.account_home
        assert home is not None
        there = furnished(settings)
        gone = there[leave_out]
        if gone.is_dir():
            shutil.rmtree(gone)
        elif leave_out == "staged":
            shutil.rmtree(gone.parent)
        else:
            gone.unlink()

        assert browser_session.discard_session(settings, home), leave_out
        assert not there["profile"].exists()
        assert not there["ask"].exists()
        assert there["kept"].exists()


def test_logout_with_nothing_to_remove(tmp_path: Path) -> None:
    settings = account_settings(tmp_path, free_port())
    home = settings.account_home
    assert home is not None
    assert not browser_session.discard_session(settings, home)


def test_the_library_refuses_a_logout_with_no_account(tmp_path: Path) -> None:
    """`23` makes the library a surface of its own, so it has its own door (§86)."""
    with pytest.raises(UsageError, match="logout names a source account"):
        browser_session.logout(make_settings(tmp_path, free_port()))


def test_an_account_home_holds_exactly_what_sign_out_knows_about(tmp_path: Path) -> None:
    """The claim §82's second line makes about the whole directory.

    Sign-out names the three it removes rather than sweeping (ADR 0009), so a fourth
    thing written into an account home would be left behind silently. This is what
    turns that red instead.
    """
    settings = account_settings(tmp_path, free_port())
    home = settings.account_home
    assert home is not None
    furnished(settings)

    assert {child.name for child in home.iterdir()} == {
        "browser-profile",
        ASK_FILENAME,
        TMP_DIRNAME,
        log.LOGS_DIRNAME,
    }


def test_a_profile_that_cannot_be_deleted_is_reported_not_crashed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read-only filesystem or a permission is fixable at the keyboard.

    An escaping `OSError` would reach the operator as `internal error` and exit `70`,
    which is where a bug in us belongs, not a locked directory.
    """
    settings = account_settings(tmp_path, free_port())
    home = settings.account_home
    assert home is not None
    there = furnished(settings)

    def refuse(path: object, *args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(browser_session.shutil, "rmtree", refuse)
    with pytest.raises(StateError, match=r"cannot remove .*: Permission denied"):
        browser_session.discard_session(settings, home)
    assert there["profile"].exists()


def test_logout_reports_a_locked_profile_as_exit_2(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = account_settings(tmp_path, free_port())
    furnished(settings)

    def refuse(path: object, *args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(browser_session.shutil, "rmtree", refuse)
    monkeypatch.setenv("DATAPORTER_WORKSPACE", str(settings.workspace))
    monkeypatch.setenv("DATAPORTER_ACCOUNTS__DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", str(settings.browser.cdp_port))
    result = runner.invoke(cli.app, ["logout", "--account", ACCOUNT], catch_exceptions=False)
    assert result.exit_code == ExitCode.USAGE
    assert result.stderr.startswith("error: cannot remove ")
    assert "Permission denied" in result.stderr
    assert "Traceback" not in result.output


def test_logout_closes_the_window_it_owns(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§85: the marker names the browser on the port, so it is ours to close.

    Silently: `login` and `session status` close theirs without a word, and a sign-out
    prints one block whatever it had to do first.
    """
    with FakeChrome() as chrome:
        settings = adoptable_account(chrome, tmp_path, monkeypatch)
        furnished(settings)

        result = runner.invoke(cli.app, ["logout", "--account", ACCOUNT], catch_exceptions=False)

        assert result.exit_code == ExitCode.OK
        assert chrome.closed
        assert result.stdout == (
            f"Signed out of Claude — {ACCOUNT}\nRemoved {settings.account_home}/, except its logs.\n"
        )
        assert not settings.browser_profile_dir.exists()


def test_logout_refuses_a_browser_it_cannot_claim_and_removes_nothing(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chrome does not say which profile it holds, so a guess deletes the wrong thing."""
    with FakeChrome() as chrome:
        settings = adoptable_account(chrome, tmp_path, monkeypatch)
        there = furnished(settings)
        launcher.marker_path(settings.browser_profile_dir).unlink()

        result = runner.invoke(cli.app, ["logout", "--account", ACCOUNT], catch_exceptions=False)

        assert result.exit_code == ExitCode.USAGE
        assert result.stderr == f"error: port {chrome.port} is used by another browser\n"
        assert there["profile"].exists()
        assert there["ask"].exists()
        assert there["staged"].exists()


def test_logout_refuses_a_browser_that_would_not_close(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closing is an ask, not a guarantee.

    `close` on an adopted browser waits, warns and returns rather than signalling, so a
    Chrome that ignored it would otherwise have its profile deleted underneath it.
    """
    with FakeChrome() as chrome:
        settings = adoptable_account(chrome, tmp_path, monkeypatch)
        there = furnished(settings)
        monkeypatch.setattr(launcher.BrowserSession, "close", lambda self, **kwargs: None)

        result = runner.invoke(cli.app, ["logout", "--account", ACCOUNT], catch_exceptions=False)

        assert result.exit_code == ExitCode.USAGE
        assert result.stderr == (
            f"error: a browser is still running on port {chrome.port} — "
            f"close it, then run: dataporter logout --source claude --account {ACCOUNT}\n"
        )
        assert there["profile"].exists()


# --------------------------------------------------------------------------- #
# The commands themselves
# --------------------------------------------------------------------------- #


def adoptable(chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Return a workspace whose profile carries a marker for this fake browser.

    `launch` then adopts rather than starting anything, which is what lets the
    command tests exercise the real path — `adopt`, `probe`, `close` — with no
    Chrome anywhere.
    """
    settings = make_settings(tmp_path, chrome.port)
    profile = launcher.ensure_profile(settings)
    launcher.write_marker(
        profile,
        launcher.ProfileMarker(port=chrome.port, browser_id=chrome.browser_id, pid=1, started="now"),
    )
    monkeypatch.setenv("DATAPORTER_WORKSPACE", str(settings.workspace))
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", str(chrome.port))
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__CDP_CALL_S", "2")
    return settings


ACCOUNT = "work"


def account_settings(tmp_path: Path, port: int) -> Settings:
    """Return the settings a `--account` invocation resolves to (`31`)."""
    base = make_settings(tmp_path, port).model_copy(update={"accounts": AccountsSettings(dir=tmp_path / "accounts")})
    return with_account(base, "claude", ACCOUNT)


def adoptable_account(chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """`adoptable`, one directory down: the account home's profile carries the marker.

    `session status` and `logout` both name an account since §86, so their command tests
    live here rather than on the workspace `login` still defaults to.
    """
    settings = account_settings(tmp_path, chrome.port)
    profile = launcher.ensure_profile(settings)
    launcher.write_marker(
        profile,
        launcher.ProfileMarker(port=chrome.port, browser_id=chrome.browser_id, pid=1, started="now"),
    )
    monkeypatch.setenv("DATAPORTER_WORKSPACE", str(settings.workspace))
    monkeypatch.setenv("DATAPORTER_ACCOUNTS__DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", str(chrome.port))
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__CDP_CALL_S", "2")
    return settings


def test_login_reports_a_session_that_is_already_signed_in(
    runner: CliRunner,
    chrome: FakeChrome,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = adoptable(chrome, tmp_path, monkeypatch)
    result = runner.invoke(cli.app, ["login"], catch_exceptions=False)
    assert result.exit_code == ExitCode.OK
    assert result.stdout == (f"Signed in to Claude\nSession stored in {settings.browser_profile_dir}/.\n")
    # Chrome flushes its profile on exit, so `login` always closes it.
    assert "Browser.close" in chrome.methods()


def test_login_asks_the_operator_and_gives_up(
    runner: CliRunner,
    chrome: FakeChrome,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chrome.targets[0].evaluate = LOGGED_OUT
    adoptable(chrome, tmp_path, monkeypatch)
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__LOGIN_S", "0.05")
    result = runner.invoke(cli.app, ["login"], catch_exceptions=False)
    assert result.exit_code == ExitCode.NOT_AUTHENTICATED
    # §73's first block, for the destination: no label, and its own command.
    assert result.stdout == (
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
    assert result.stderr == "error: timed out after 0.05s waiting for login\n"
    # No password was asked for, here or anywhere (§8).
    assert "password" not in result.output.lower()


def test_login_without_a_browser_is_exit_6(runner: CliRunner, workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_browser(configured: Path | None = None) -> Path:
        raise BrowserError(detail="no browser found — install Google Chrome")

    monkeypatch.setattr(launcher, "find_executable", no_browser)
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", str(free_port()))
    result = runner.invoke(cli.app, ["login"], catch_exceptions=False)
    assert result.exit_code == ExitCode.ENVIRONMENT
    assert result.stderr.startswith("error: no browser found")


def test_session_status_without_a_profile_starts_nothing(
    runner: CliRunner, workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(*args: object, **kwargs: object) -> None:
        raise AssertionError("no browser should be started")

    monkeypatch.setattr(launcher, "launch", never)
    monkeypatch.setenv("DATAPORTER_ACCOUNTS__DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", str(free_port()))
    result = runner.invoke(cli.app, ["session", "status", "--account", ACCOUNT], catch_exceptions=False)
    assert result.exit_code == ExitCode.NOT_AUTHENTICATED
    assert result.stdout == f"not logged in — run: dataporter login --source claude --account {ACCOUNT}\n"


def test_session_status_reports_a_signed_in_session(
    runner: CliRunner,
    chrome: FakeChrome,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adoptable_account(chrome, tmp_path, monkeypatch)
    result = runner.invoke(cli.app, ["session", "status", "--account", ACCOUNT], catch_exceptions=False)
    assert result.exit_code == ExitCode.OK
    assert result.stdout == "logged in\n"
    # A browser this command did not start is a browser it does not close.
    assert not chrome.closed


def test_session_status_reports_a_signed_out_session(
    runner: CliRunner,
    chrome: FakeChrome,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chrome.targets[0].evaluate = LOGGED_OUT
    adoptable_account(chrome, tmp_path, monkeypatch)
    result = runner.invoke(cli.app, ["session", "status", "--account", ACCOUNT], catch_exceptions=False)
    assert result.exit_code == ExitCode.NOT_AUTHENTICATED
    assert result.stdout == f"not logged in — run: dataporter login --source claude --account {ACCOUNT}\n"


def test_a_foreign_browser_on_the_port_is_exit_2(
    runner: CliRunner,
    chrome: FakeChrome,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Somebody else's Chrome. Exit `2`, not `6`: nothing is missing."""
    settings = adoptable_account(chrome, tmp_path, monkeypatch)
    launcher.marker_path(settings.browser_profile_dir).unlink()
    result = runner.invoke(cli.app, ["session", "status", "--account", ACCOUNT], catch_exceptions=False)
    assert result.exit_code == ExitCode.USAGE
    assert result.stderr == (f"error: port {chrome.port} is used by another browser\n")


def test_logout_prints_the_block_and_keeps_the_log_it_wrote(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§82's first block, and the one thing still in the directory it emptied."""
    settings = account_settings(tmp_path, free_port())
    furnished(settings)
    monkeypatch.setenv("DATAPORTER_WORKSPACE", str(settings.workspace))
    monkeypatch.setenv("DATAPORTER_ACCOUNTS__DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", str(settings.browser.cdp_port))

    result = runner.invoke(cli.app, ["-v", "logout", "--account", ACCOUNT], catch_exceptions=False)

    assert result.exit_code == ExitCode.OK
    assert result.stdout == (f"Signed out of Claude — {ACCOUNT}\nRemoved {settings.account_home}/, except its logs.\n")
    assert not settings.browser_profile_dir.exists()
    home = settings.account_home
    assert home is not None
    logs = home / log.LOGS_DIRNAME
    # The earlier run's log survived, and this sign-out left one of its own beside it:
    # `logs/` is what an account home keeps, including the record of it being emptied.
    assert (logs / "run-earlier.jsonl").exists()
    assert [path for path in logs.iterdir() if path.name != "run-earlier.jsonl"]


def test_logout_with_nothing_to_remove_is_not_an_error(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§82: sign-out states an end, and this one already held.

    Which is also the mistyped label: nothing registers one, so there is no such thing
    as an account that does not exist.
    """
    settings = account_settings(tmp_path, free_port())
    monkeypatch.setenv("DATAPORTER_WORKSPACE", str(settings.workspace))
    monkeypatch.setenv("DATAPORTER_ACCOUNTS__DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", str(settings.browser.cdp_port))

    result = runner.invoke(cli.app, ["logout", "--account", ACCOUNT], catch_exceptions=False)
    typo = runner.invoke(cli.app, ["logout", "--account", "wrok"], catch_exceptions=False)

    assert result.exit_code == ExitCode.OK
    assert result.stdout == f"Nothing to remove: {settings.account_home}/ has no session.\n"
    assert typo.exit_code == ExitCode.OK


def test_session_status_starts_and_stops_a_browser_of_its_own(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A profile but no running browser.

    `status` launches one to ask, and puts it away again.
    """
    settings = account_settings(tmp_path, free_port())
    launcher.ensure_profile(settings)
    started: list[FakeChrome] = []

    def fake_popen(command: list[str], **kwargs: object) -> object:
        started.append(
            entered(
                FakeChrome(
                    port=settings.browser.cdp_port,
                    targets=[FakeTarget(id="page-1", url="https://claude.ai/new", evaluate=page_state())],
                )
            )
        )
        return _NeverExits()

    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)
    monkeypatch.setenv("DATAPORTER_WORKSPACE", str(settings.workspace))
    monkeypatch.setenv("DATAPORTER_ACCOUNTS__DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", str(settings.browser.cdp_port))
    monkeypatch.setenv("DATAPORTER_BROWSER__EXECUTABLE", sys.executable)
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__CDP_CALL_S", "2")
    try:
        result = runner.invoke(cli.app, ["session", "status", "--account", ACCOUNT], catch_exceptions=False)
        assert result.exit_code == ExitCode.OK
        assert result.stdout == "logged in\n"
        assert started[0].closed
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


CREDENTIAL_SEAM = frozenset({"config.py", "cli.py", "signin.py", "browser/login_form.py"})
"""The four modules `24` lets name a credential: the setting that holds it, the
flag that reads it, the task that asks for it and the form filler that types
it. Everywhere else the word is a leak."""


def test_the_secret_stays_in_the_credentials_seam() -> None:
    """§8, as `24` amended it.

    Interactively the tool never asks for the operator's Claude password, and unattended
    it holds one in memory for one invocation and nowhere else.

    What is checked is the code rather than the file: outside the seam the word
    is allowed in the prose that promises it will never be asked for, and
    nowhere that a program could act on — no name, no field, no prompt, no key.
    Inside the seam a name may carry it, but no string constant may *be* one,
    and no log call may pass a field the content guard forbids.
    """
    package = Path(dataporter.__file__).parent
    offenders: list[str] = []
    for path in sorted(package.rglob("*.py")):
        relative = path.relative_to(package).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        prose = {
            id(node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        }
        """Every string that is a statement on its own: a docstring, module-,
        class- or attribute-level. Those are the promise, not an action."""
        for node in ast.walk(tree):
            if id(node) in prose:
                continue
            if relative in CREDENTIAL_SEAM:
                if _logs_a_forbidden_field(node):
                    offenders.append(f"{relative}:{node.lineno}")
                continue
            spellings = [getattr(node, attribute, None) for attribute in ("id", "name", "attr", "arg", "module")]
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                spellings.append(node.value)
            if any(isinstance(item, str) and "password" in item.lower() for item in spellings):
                offenders.append(f"{relative}:{node.lineno}")
    assert offenders == []


def _logs_a_forbidden_field(node: ast.AST) -> bool:
    """Return a `_logger.<level>(..., extra={<forbidden>: ...})` call."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
        return False
    if func.value.id != "_logger":
        return False
    for keyword in node.keywords:
        if keyword.arg == "extra" and isinstance(keyword.value, ast.Dict):
            for key in keyword.value.keys:
                if isinstance(key, ast.Constant) and key.value in log.FORBIDDEN_FIELDS:
                    return True
    return False


# --------------------------------------------------------------------------- #
# `33`: the trace a `login` leaves
# --------------------------------------------------------------------------- #


def _trace_lines(workspace: Path) -> list[dict[str, Any]]:
    traces = sorted((workspace / "logs").glob("trace-*.jsonl"))
    assert len(traces) == 1, traces
    run_logs = sorted((workspace / "logs").glob("run-*.jsonl"))
    # Paired with the run log by name: the same stamp, the same directory.
    assert [path.name.removeprefix("trace-") for path in traces] == [
        path.name.removeprefix("run-") for path in run_logs
    ]
    return [json.loads(line) for line in traces[0].read_text(encoding="utf-8").splitlines()]


def test_login_leaves_a_trace_beside_its_run_log(
    runner: CliRunner,
    chrome: FakeChrome,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = adoptable(chrome, tmp_path, monkeypatch)
    result = runner.invoke(cli.app, ["login"], catch_exceptions=False)
    assert result.exit_code == ExitCode.OK

    written = _trace_lines(settings.workspace)
    header, *_, end = written
    assert header["kind"] == "header"
    assert header["command"] == "login"
    assert header["flags"] == []
    assert header["source"] == "claude"
    assert header["host"] == "claude.ai"
    assert header["account"] is None
    assert header["root"] == str(settings.workspace)
    assert end["what"] == "end"
    assert end["exit"] == 0


def test_a_login_that_gave_up_ends_its_trace_with_70(
    runner: CliRunner,
    chrome: FakeChrome,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The body raised; the terminal says `3` and the trace says the body did not return."""
    chrome.targets[0].evaluate = LOGGED_OUT
    settings = adoptable(chrome, tmp_path, monkeypatch)
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__LOGIN_S", "0.05")
    result = runner.invoke(cli.app, ["login"], catch_exceptions=False)
    assert result.exit_code == ExitCode.NOT_AUTHENTICATED

    end = _trace_lines(settings.workspace)[-1]
    assert end["what"] == "end"
    assert end["exit"] == 70


def test_a_login_s_site_is_the_destination_s_or_the_source_s(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, 1)
    assert browser_session.site_of(settings) is probe.MIGRATION_SITE
    assert browser_session.site_of(with_session_account(settings, "claude", "old")) is export_page.EXTRACTION_SITE
    assert set(export_page.EXTRACTION_SITE.selectors) > set(probe.MIGRATION_SITE.selectors)
