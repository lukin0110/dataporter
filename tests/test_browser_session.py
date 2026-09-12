"""Picking a tab, waiting for a login, and throwing the profile away."""

import ast
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

import dataporter
from dataporter import cli
from dataporter.browser import launcher
from dataporter.browser import session as browser_session
from dataporter.browser.cdp import CdpClient
from dataporter.browser.probe import NEW_CHAT_URL
from dataporter.config import BrowserSettings, Settings, TimeoutSettings
from dataporter.errors import BrowserError
from dataporter.exit_codes import ExitCode
from dataporter.state import StateError
from fake_chrome import Call, FakeChrome, FakeTarget, free_port, page_state

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
    """A `BrowserSession` around a fake browser, as adoption would produce."""
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
    """What a just-launched browser looks like while its first page loads. A new
    tab here would leave two windows and `08` with an `ambiguous_tab`."""
    with FakeChrome(
        targets=[FakeTarget(id="page-1", url="about:blank", evaluate=page_state())]
    ) as chrome:
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
    """`wait_for_login` retries every two seconds for ten minutes. One WebSocket
    left open per failed attempt would be three hundred of them."""

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
            FakeTarget(
                id="page-2", url="https://claude.ai/chat/x", evaluate=page_state()
            ),
        ]
    ) as chrome:
        session = session_for(chrome, tmp_path)
        assert browser_session.current_state(session).tab_count == 2


# --------------------------------------------------------------------------- #
# Waiting for the operator
# --------------------------------------------------------------------------- #


LOGGED_OUT = page_state(url="https://claude.ai/login", composer_present=False)


def test_wait_for_login_returns_once_a_composer_appears(
    chrome: FakeChrome, tmp_path: Path
) -> None:
    seen = {"probes": 0}

    def evaluate(call: Call) -> dict[str, object]:
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


class StopWaiting(Exception):
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
        raise StopWaiting

    monkeypatch.setattr(browser_session.time, "sleep", record)
    chrome.targets[0].evaluate = LOGGED_OUT
    session = session_for(chrome, tmp_path)

    with pytest.raises(StopWaiting):
        browser_session.wait_for_login(session, timeout_s=30.0, poll_s=300.0)

    assert len(slept) == 1
    assert 0 < slept[0] <= 30.0


def test_a_failed_probe_is_not_a_failed_login(
    chrome: FakeChrome, tmp_path: Path
) -> None:
    """The page is navigating, the tab is being replaced, the identity provider
    is redirecting. None of that ends the wait."""
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


def test_a_browser_that_has_gone_away_ends_the_wait(
    chrome: FakeChrome, tmp_path: Path
) -> None:
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


def test_remove_profile_deletes_the_directory(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, free_port())
    profile = launcher.ensure_profile(settings)
    (profile / "Cookies").write_text("a session", encoding="utf-8")
    assert browser_session.remove_profile(settings)
    assert not profile.exists()
    # Local only: the workspace, and the `.gitignore` beside it, stay.
    assert (settings.workspace / ".gitignore").exists()


def test_remove_profile_on_a_workspace_with_none(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, free_port())
    assert not browser_session.remove_profile(settings)


def test_a_profile_that_cannot_be_deleted_is_reported_not_crashed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read-only filesystem or a permission is fixable at the keyboard. An
    escaping `OSError` would reach the operator as `internal error` and exit
    `70`, which is where a bug in us belongs, not a locked directory."""
    settings = make_settings(tmp_path, free_port())
    profile = launcher.ensure_profile(settings)

    def refuse(path: object, *args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(browser_session.shutil, "rmtree", refuse)
    with pytest.raises(StateError, match="cannot remove .*: Permission denied"):
        browser_session.remove_profile(settings)
    assert profile.exists()


def test_session_logout_reports_a_locked_profile_as_exit_2(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(tmp_path, free_port())
    launcher.ensure_profile(settings)

    def refuse(path: object, *args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(browser_session.shutil, "rmtree", refuse)
    monkeypatch.setenv("HCM_WORKSPACE", str(settings.workspace))
    monkeypatch.setenv("HCM_BROWSER__CDP_PORT", str(settings.browser.cdp_port))
    result = runner.invoke(cli.app, ["session", "logout"], catch_exceptions=False)
    assert result.exit_code == ExitCode.USAGE
    assert result.stderr.startswith("error: cannot remove ")
    assert "Permission denied" in result.stderr
    assert "Traceback" not in result.output


def test_remove_profile_refuses_while_a_browser_is_running(tmp_path: Path) -> None:
    """Deleting the directory under a live Chrome leaves half a profile and a
    browser that still holds the session in memory."""
    with FakeChrome() as chrome:
        settings = make_settings(tmp_path, chrome.port)
        profile = launcher.ensure_profile(settings)
        with pytest.raises(launcher.PortInUse, match="still running"):
            browser_session.remove_profile(settings)
        assert profile.exists()


# --------------------------------------------------------------------------- #
# The commands themselves
# --------------------------------------------------------------------------- #


def adoptable(
    chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Settings:
    """A workspace whose profile carries a marker for this fake browser.

    `launch` then adopts rather than starting anything, which is what lets the
    command tests exercise the real path — `adopt`, `probe`, `close` — with no
    Chrome anywhere.
    """
    settings = make_settings(tmp_path, chrome.port)
    profile = launcher.ensure_profile(settings)
    launcher.write_marker(
        profile,
        launcher.ProfileMarker(
            port=chrome.port, browser_id=chrome.browser_id, pid=1, started="now"
        ),
    )
    monkeypatch.setenv("HCM_WORKSPACE", str(settings.workspace))
    monkeypatch.setenv("HCM_BROWSER__CDP_PORT", str(chrome.port))
    monkeypatch.setenv("HCM_TIMEOUTS__CDP_CALL_S", "2")
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
    assert result.stdout == (
        f"Logged in. Session stored in {settings.browser_profile_dir}/.\n"
    )
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
    monkeypatch.setenv("HCM_TIMEOUTS__LOGIN_S", "0.05")
    result = runner.invoke(cli.app, ["login"], catch_exceptions=False)
    assert result.exit_code == ExitCode.NOT_AUTHENTICATED
    assert result.stdout == f"{browser_session.LOGIN_PROMPT}\n"
    assert result.stderr == "error: timed out after 0.05s waiting for login\n"
    # No password was asked for, here or anywhere (§8).
    assert "password" not in result.output.lower()


def test_login_without_a_browser_is_exit_6(
    runner: CliRunner, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_browser(configured: Path | None = None) -> Path:
        raise BrowserError(detail="no browser found — install Google Chrome")

    monkeypatch.setattr(launcher, "find_executable", no_browser)
    monkeypatch.setenv("HCM_BROWSER__CDP_PORT", str(free_port()))
    result = runner.invoke(cli.app, ["login"], catch_exceptions=False)
    assert result.exit_code == ExitCode.ENVIRONMENT
    assert result.stderr.startswith("error: no browser found")


def test_session_status_without_a_profile_starts_nothing(
    runner: CliRunner, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(*args: object, **kwargs: object) -> None:
        raise AssertionError("no browser should be started")

    monkeypatch.setattr(launcher, "launch", never)
    monkeypatch.setenv("HCM_BROWSER__CDP_PORT", str(free_port()))
    result = runner.invoke(cli.app, ["session", "status"], catch_exceptions=False)
    assert result.exit_code == ExitCode.NOT_AUTHENTICATED
    assert result.stdout == "not logged in — run: hermes-claude-migrate login\n"


def test_session_status_reports_a_signed_in_session(
    runner: CliRunner,
    chrome: FakeChrome,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adoptable(chrome, tmp_path, monkeypatch)
    result = runner.invoke(cli.app, ["session", "status"], catch_exceptions=False)
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
    adoptable(chrome, tmp_path, monkeypatch)
    result = runner.invoke(cli.app, ["session", "status"], catch_exceptions=False)
    assert result.exit_code == ExitCode.NOT_AUTHENTICATED
    assert result.stdout == "not logged in — run: hermes-claude-migrate login\n"


def test_a_foreign_browser_on_the_port_is_exit_2(
    runner: CliRunner,
    chrome: FakeChrome,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Somebody else's Chrome. Exit `2`, not `6`: nothing is missing."""
    adoptable(chrome, tmp_path, monkeypatch)
    launcher.marker_path(
        make_settings(tmp_path, chrome.port).browser_profile_dir
    ).unlink()
    result = runner.invoke(cli.app, ["session", "status"], catch_exceptions=False)
    assert result.exit_code == ExitCode.USAGE
    assert result.stderr == (f"error: port {chrome.port} is used by another browser\n")


def test_session_logout_removes_the_profile(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(tmp_path, free_port())
    launcher.ensure_profile(settings)
    monkeypatch.setenv("HCM_WORKSPACE", str(settings.workspace))
    monkeypatch.setenv("HCM_BROWSER__CDP_PORT", str(settings.browser.cdp_port))
    result = runner.invoke(cli.app, ["session", "logout"], catch_exceptions=False)
    assert result.exit_code == ExitCode.OK
    assert result.stdout == f"Removed {settings.browser_profile_dir}/.\n"
    assert not settings.browser_profile_dir.exists()


def test_session_logout_with_nothing_to_remove(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(tmp_path, free_port())
    monkeypatch.setenv("HCM_WORKSPACE", str(settings.workspace))
    monkeypatch.setenv("HCM_BROWSER__CDP_PORT", str(settings.browser.cdp_port))
    result = runner.invoke(cli.app, ["session", "logout"], catch_exceptions=False)
    assert result.exit_code == ExitCode.OK
    assert result.stdout == (
        f"Nothing to remove: {settings.browser_profile_dir}/ does not exist.\n"
    )


def test_session_status_starts_and_stops_a_browser_of_its_own(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A profile but no running browser: `status` launches one to ask, and puts
    it away again."""
    settings = make_settings(tmp_path, free_port())
    launcher.ensure_profile(settings)
    started: list[FakeChrome] = []

    def fake_popen(command: list[str], **kwargs: object) -> object:
        started.append(
            FakeChrome(
                port=settings.browser.cdp_port,
                targets=[
                    FakeTarget(
                        id="page-1", url="https://claude.ai/new", evaluate=page_state()
                    )
                ],
            ).__enter__()
        )
        return _NeverExits()

    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)
    monkeypatch.setenv("HCM_WORKSPACE", str(settings.workspace))
    monkeypatch.setenv("HCM_BROWSER__CDP_PORT", str(settings.browser.cdp_port))
    monkeypatch.setenv("HCM_BROWSER__EXECUTABLE", sys.executable)
    monkeypatch.setenv("HCM_TIMEOUTS__CDP_CALL_S", "2")
    try:
        result = runner.invoke(cli.app, ["session", "status"], catch_exceptions=False)
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


def test_the_tool_never_asks_for_a_password() -> None:
    """§8: the tool must not request or store the operator's Claude password.

    Login happens in Chrome's own window, so no code path here has anywhere to
    put one. What is checked is the code rather than the file: the word is
    allowed in the prose that promises it will never be asked for, and nowhere
    that a program could act on — no name, no field, no prompt, no key.
    """
    package = Path(dataporter.__file__).parent
    offenders: list[str] = []
    for path in sorted(package.rglob("*.py")):
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
            spellings = [
                getattr(node, attribute, None)
                for attribute in ("id", "name", "attr", "arg", "module")
            ]
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                spellings.append(node.value)
            if any(
                isinstance(item, str) and "password" in item.lower()
                for item in spellings
            ):
                offenders.append(f"{path.relative_to(package)}:{node.lineno}")
    assert offenders == []
