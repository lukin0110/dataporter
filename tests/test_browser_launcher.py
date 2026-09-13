"""Launching, adopting and closing the browser this tool owns."""

import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from dataporter.browser import launcher
from dataporter.config import BrowserSettings, Settings, TimeoutSettings
from dataporter.errors import BrowserError
from fake_chrome import FakeChrome, entered, free_port

pytestmark = pytest.mark.slow
"""Slow all the way through: launching is the subject, and the fake browser is a real
server.
"""


class StubProcess:
    """A `Popen` that never was. Enough of one for `BrowserSession.close`."""

    def __init__(self, *, exited: int | None = None, stubborn: bool = False) -> None:
        self.pid = 4242
        self.returncode = exited
        self.terminated = False
        self.killed = False
        self._stubborn = stubborn

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            if self._stubborn and not self.terminated:
                raise subprocess.TimeoutExpired("chrome", timeout or 0)
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:  # pragma: no cover - only a wedged browser gets here
        self.killed = True
        self.returncode = -9


@dataclass
class Rig:
    """What the stubbed launch did: the command, and the browser it "started"."""

    commands: list[list[str]] = field(default_factory=list)
    browsers: list[FakeChrome] = field(default_factory=list)
    processes: list[StubProcess] = field(default_factory=list)
    fail_to_start: bool = False
    """When true the stub browser never opens its port, as a sandbox failure."""

    exit_code: int | None = None
    """When set, the stub process is already gone by the time we look."""

    @property
    def command(self) -> list[str]:
        return self.commands[-1]


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> Iterator[Rig]:
    """`subprocess.Popen`, replaced by something that starts a `FakeChrome`."""
    rig = Rig()

    def fake_popen(command: list[str], **kwargs: object) -> StubProcess:
        rig.commands.append(command)
        process = StubProcess(exited=rig.exit_code)
        rig.processes.append(process)
        if not rig.fail_to_start:
            port = int(next(item for item in command if item.startswith("--remote-debugging-port=")).split("=")[1])
            rig.browsers.append(entered(FakeChrome(port=port)))
        return process

    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)
    yield rig
    for browser in rig.browsers:
        browser.stop()


def make_settings(tmp_path: Path, **browser: object) -> Settings:
    """Return a workspace with a browser that is really this Python interpreter.

    `find_executable` only has to find something executable; nothing in these
    tests runs it, because `Popen` is the stub above.
    """
    return Settings(
        workspace=tmp_path / "migration",
        browser=BrowserSettings(executable=Path(sys.executable), cdp_port=free_port(), **browser),
        timeouts=TimeoutSettings(browser_start_s=5.0, cdp_call_s=2.0),
    )


# --------------------------------------------------------------------------- #
# Finding a browser
# --------------------------------------------------------------------------- #


def test_configured_executable_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher.shutil, "which", lambda name: f"/resolved/{name}")
    assert launcher.find_executable(Path("brave-browser")) == Path("/resolved/brave-browser")


def test_a_configured_executable_that_is_not_there_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    with pytest.raises(BrowserError, match="configured browser executable not found"):
        launcher.find_executable(Path("/opt/not-a-browser"))


def test_candidates_are_tried_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chrome first: it is what claude.ai is tested against."""
    monkeypatch.setattr(
        launcher.shutil,
        "which",
        lambda name: "/usr/bin/chromium" if name in {"chromium", "brave-browser"} else None,
    )
    assert launcher.find_executable() == Path("/usr/bin/chromium")


def test_no_browser_at_all_is_exit_6_material(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    with pytest.raises(BrowserError, match="no browser found"):
        launcher.find_executable()


# --------------------------------------------------------------------------- #
# The workspace side
# --------------------------------------------------------------------------- #


def test_profile_is_private_and_the_workspace_is_ignored(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    profile = launcher.ensure_profile(settings)
    assert profile == settings.workspace / "browser-profile"
    # A live Claude session on a shared machine is not world-readable.
    assert profile.stat().st_mode & 0o777 == 0o700
    ignored = (settings.workspace / ".gitignore").read_text(encoding="utf-8")
    assert ignored.splitlines() == list(launcher.GITIGNORE_ENTRIES)


def test_an_existing_gitignore_is_added_to_not_replaced(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.workspace.mkdir(parents=True)
    path = settings.workspace / ".gitignore"
    path.write_text("notes.md\nlogs/\n", encoding="utf-8")
    launcher.ensure_gitignore(settings.workspace)
    assert path.read_text(encoding="utf-8").splitlines() == [
        "notes.md",
        "logs/",
        "browser-profile/",
        "hermes/",
        "seeds/",
    ]
    # Idempotent: a second run rewrites nothing.
    before = path.read_text(encoding="utf-8")
    launcher.ensure_gitignore(settings.workspace)
    assert path.read_text(encoding="utf-8") == before


def test_ensure_profile_on_a_directory_that_already_exists(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    launcher.ensure_profile(settings)
    assert launcher.ensure_profile(settings).exists()


# --------------------------------------------------------------------------- #
# Adoption
# --------------------------------------------------------------------------- #


def test_a_free_port_is_not_adopted(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    client = launcher.CdpClient(port=settings.browser.cdp_port, timeout=1.0)
    assert launcher.adopt(client, settings.browser_profile_dir) is None


def test_our_own_browser_is_adopted(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    profile = launcher.ensure_profile(settings)
    with FakeChrome(port=settings.browser.cdp_port) as chrome:
        launcher.write_marker(
            profile,
            launcher.ProfileMarker(port=chrome.port, browser_id=chrome.browser_id, pid=1, started="now"),
        )
        client = launcher.CdpClient(port=chrome.port, timeout=2.0)
        session = launcher.adopt(client, profile)
        assert session is not None
        assert session.adopted
        assert session.process is None


@pytest.mark.parametrize(
    ("marker", "why"),
    [
        (None, "no marker at all"),
        ({"port": 1, "browser_id": "fake-browser-id"}, "a different port"),
        ({"browser_id": "somebody-elses-browser"}, "a different browser"),
    ],
)
def test_a_browser_that_is_not_ours_is_never_adopted(
    tmp_path: Path, marker: dict[str, object] | None, why: str
) -> None:
    """Never the operator's everyday Chrome.

    Attaching to it would put the run inside the profile §17 exists to stay out of — and
    closing it would shut their windows.
    """
    settings = make_settings(tmp_path)
    profile = launcher.ensure_profile(settings)
    with FakeChrome(port=settings.browser.cdp_port) as chrome:
        if marker is not None:
            launcher.write_marker(
                profile,
                launcher.ProfileMarker(
                    port=int(marker.get("port", chrome.port)),  # type: ignore[arg-type]
                    browser_id=str(marker.get("browser_id", "")),
                    pid=1,
                    started="now",
                ),
            )
        client = launcher.CdpClient(port=chrome.port, timeout=2.0)
        with pytest.raises(launcher.PortInUseError, match="used by another browser"):
            launcher.adopt(client, profile)


def test_an_unreadable_marker_is_no_marker(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    profile = launcher.ensure_profile(settings)
    assert launcher.read_marker(profile) is None  # missing
    launcher.marker_path(profile).write_text("{not json", encoding="utf-8")
    assert launcher.read_marker(profile) is None


# --------------------------------------------------------------------------- #
# Launching
# --------------------------------------------------------------------------- #


def test_launch_uses_exactly_the_flags_the_spec_names(tmp_path: Path, rig: Rig) -> None:
    settings = make_settings(tmp_path)
    session = launcher.launch(settings, "https://claude.ai/new")
    try:
        assert rig.command == [
            sys.executable,
            f"--user-data-dir={settings.browser_profile_dir}",
            f"--remote-debugging-port={settings.browser.cdp_port}",
            "--remote-debugging-address=127.0.0.1",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--disable-features=TranslateUI",
            "--window-size=1280,900",
            "https://claude.ai/new",
        ]
        assert not session.adopted
    finally:
        session.close()


def test_extra_args_go_before_the_url(tmp_path: Path, rig: Rig) -> None:
    """The escape hatch for a container with no display; nothing else uses it."""
    settings = make_settings(tmp_path, extra_args=("--headless=new", "--no-sandbox"))
    session = launcher.launch(settings, "https://claude.ai/new")
    try:
        assert rig.command[-3:] == [
            "--headless=new",
            "--no-sandbox",
            "https://claude.ai/new",
        ]
    finally:
        session.close()


def test_launch_records_the_browser_it_started(tmp_path: Path, rig: Rig) -> None:
    settings = make_settings(tmp_path)
    session = launcher.launch(settings, "https://claude.ai/new")
    try:
        marker = launcher.read_marker(settings.browser_profile_dir)
        assert marker is not None
        assert marker.port == settings.browser.cdp_port
        assert marker.browser_id == rig.browsers[0].browser_id
        assert marker.pid == rig.processes[0].pid
        # And that marker is what makes the next run adopt rather than relaunch.
        again = launcher.launch(settings, "https://claude.ai/new")
        assert again.adopted
        assert len(rig.commands) == 1
    finally:
        session.close()


def test_a_browser_that_exits_at_once_says_so(tmp_path: Path, rig: Rig) -> None:
    """A `--user-data-dir` another Chrome already holds fails in milliseconds.

    Reporting it as a thirty-second timeout would waste the operator's time.
    """
    rig.fail_to_start = True
    rig.exit_code = 1
    settings = make_settings(tmp_path)
    with pytest.raises(BrowserError, match="exited immediately with code 1"):
        launcher.launch(settings, "https://claude.ai/new")


def test_a_browser_that_never_opens_the_port_times_out(tmp_path: Path, rig: Rig) -> None:
    rig.fail_to_start = True
    settings = make_settings(tmp_path).model_copy(
        update={"timeouts": TimeoutSettings(browser_start_s=0.5, cdp_call_s=0.5)}
    )
    with pytest.raises(BrowserError, match="did not open its debug port"):
        launcher.launch(settings, "https://claude.ai/new")
    # And no marker: the workspace does not claim a browser that never ran.
    assert launcher.read_marker(settings.browser_profile_dir) is None


def test_a_browser_that_cannot_be_started_at_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(command: list[str], **kwargs: object) -> StubProcess:
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(launcher.subprocess, "Popen", explode)
    with pytest.raises(BrowserError, match="cannot start"):
        launcher.launch(make_settings(tmp_path), "https://claude.ai/new")


# --------------------------------------------------------------------------- #
# Closing
# --------------------------------------------------------------------------- #


def test_close_asks_the_browser_to_exit(tmp_path: Path, rig: Rig) -> None:
    """Chrome flushes its cookie jar on exit.

    A profile that is never closed cleanly can come back signed out.
    """
    settings = make_settings(tmp_path)
    session = launcher.launch(settings, "https://claude.ai/new")
    session.close()
    assert "Browser.close" in rig.browsers[0].methods()
    assert rig.processes[0].returncode == 0
    assert not session.client.responding()


def test_a_browser_whose_port_has_gone_but_whose_process_has_not(tmp_path: Path, rig: Rig) -> None:
    """A dead debug port does not mean a dead Chrome.

    There is nothing to send `Browser.close` to, so the process is ended rather than
    left behind.
    """
    settings = make_settings(tmp_path)
    session = launcher.launch(settings, "https://claude.ai/new")
    rig.browsers[0].stop()
    session.close()
    assert rig.processes[0].terminated
    assert rig.processes[0].returncode == 0


def test_a_browser_that_never_opened_its_port_is_not_orphaned(tmp_path: Path, rig: Rig) -> None:
    """The failure `wait_for_port` reports: Chrome started, hung, and never answered.

    Leaving it there would hold our profile and the next run's port.
    """
    rig.fail_to_start = True
    settings = make_settings(tmp_path).model_copy(
        update={"timeouts": TimeoutSettings(browser_start_s=0.3, cdp_call_s=0.3)}
    )
    with pytest.raises(BrowserError, match="did not open its debug port"):
        launcher.launch(settings, "https://claude.ai/new")
    assert rig.processes[0].terminated
    assert rig.processes[0].returncode == 0


def test_a_browser_that_is_gone_entirely_is_left_alone(tmp_path: Path, rig: Rig) -> None:
    """Nothing on the port and nothing running.

    `close` has no work to do, and an adopted session has no process to sign for either.
    """
    settings = make_settings(tmp_path)
    session = launcher.launch(settings, "https://claude.ai/new")
    rig.browsers[0].stop()
    rig.processes[0].returncode = 3  # exited on its own
    session.close()
    assert not rig.processes[0].terminated
    assert rig.processes[0].returncode == 3

    adopted = launcher.BrowserSession(client=session.client, profile=session.profile)
    adopted.close(timeout=0.2)  # no process, no port: nothing to wait for


def test_a_browser_that_will_not_exit_is_terminated(tmp_path: Path, rig: Rig) -> None:
    settings = make_settings(tmp_path)
    session = launcher.launch(settings, "https://claude.ai/new")
    session.process = StubProcess(stubborn=True)  # type: ignore[assignment]
    session.close(timeout=0.2)
    assert isinstance(session.process, StubProcess)
    assert session.process.terminated


def test_an_adopted_browser_is_waited_on_never_signalled(tmp_path: Path) -> None:
    """It belongs to an earlier run and is holding the operator's session."""
    settings = make_settings(tmp_path)
    profile = launcher.ensure_profile(settings)
    with FakeChrome(port=settings.browser.cdp_port) as chrome:
        launcher.write_marker(
            profile,
            launcher.ProfileMarker(port=chrome.port, browser_id=chrome.browser_id, pid=1, started="now"),
        )
        session = launcher.launch(settings, "https://claude.ai/new")
        assert session.adopted
        session.close(timeout=2.0)
        assert chrome.closed


def test_an_adopted_browser_that_stays_up_is_reported(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    profile = launcher.ensure_profile(settings)
    with FakeChrome(port=settings.browser.cdp_port, responder=_ignore_close) as chrome:
        launcher.write_marker(
            profile,
            launcher.ProfileMarker(port=chrome.port, browser_id=chrome.browser_id, pid=1, started="now"),
        )
        session = launcher.launch(settings, "https://claude.ai/new")
        session.close(timeout=0.4)
        assert not chrome.closed


def _ignore_close(fake: FakeChrome, call: object) -> dict[str, object] | None:
    """Return a browser that acknowledges `Browser.close` and stays exactly where it is."""
    if getattr(call, "method", "") == "Browser.close":
        return {"result": {}}
    return None


def test_headless_follows_the_mode_and_the_setting(tmp_path: Path, rig: Rig) -> None:
    """`24`: no window under `--non-interactive`, unless `browser.headless` says otherwise.

    `browser.headless = true` alone is enough.
    """
    settings = make_settings(tmp_path).model_copy(update={"non_interactive": True})
    session = launcher.launch(settings, "https://claude.ai/new")
    try:
        assert rig.command[-2:] == [launcher.HEADLESS_FLAG, "https://claude.ai/new"]
    finally:
        session.close()

    settings = make_settings(tmp_path, headless=False).model_copy(update={"non_interactive": True})
    session = launcher.launch(settings, "https://claude.ai/new")
    try:
        assert launcher.HEADLESS_FLAG not in rig.command
    finally:
        session.close()

    settings = make_settings(tmp_path, headless=True, extra_args=("--no-sandbox",))
    session = launcher.launch(settings, "https://claude.ai/new")
    try:
        assert rig.command[-3:] == [
            launcher.HEADLESS_FLAG,
            "--no-sandbox",
            "https://claude.ai/new",
        ]
    finally:
        session.close()
