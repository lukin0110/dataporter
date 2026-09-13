"""Launching, adopting and closing the Chrome this tool owns.

The profile is the point. Chrome runs with `--user-data-dir` inside the
workspace, so the destination account's session lives in a directory we created,
that `session logout` can delete, and that has nothing to do with the browser the
operator reads mail in. That is what makes §17's promise keepable — the source
account's cookies are never in the browser Hermes drives — and it sidesteps
Chrome 136+, which refuses to open a debug port on the default profile.

Headed by default: §12 needs a window a human can act in when a CAPTCHA or a
login appears, and reliability beats throughput (§13). Headless under
`--non-interactive` (`24`), where there is no human to hand a window to, or when
`browser.headless` says so; `Settings.headless` is the one answer, and
`HEADLESS_FLAG` the one flag it adds. `browser.extra_args` is for what an
environment needs on top — `--no-sandbox` in a container — and the test suite is
its only user.

Interactively the tool never sees a password (§8). It opens claude.ai and waits;
the operator types into Chrome, and what is stored afterwards is Chrome's own
profile. Unattended, `browser.login_form` types into the same Chrome from this
process, and what is stored is still only the profile.
"""

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from orval import utcnow
from pydantic import BaseModel, ConfigDict, ValidationError

from dataporter import log
from dataporter.browser.cdp import CdpClient
from dataporter.config import Settings
from dataporter.errors import BrowserError
from dataporter.state import write_atomically

_logger = log.get_logger(__name__)

MARKER_FILENAME = "dataporter-cdp.json"
GITIGNORE_FILENAME = ".gitignore"
GITIGNORE_ENTRIES: tuple[str, ...] = (
    "browser-profile/",
    "hermes/",
    "seeds/",
    "logs/",
)
"""What must never reach a repository: a live Claude session, Hermes's session
transcripts (which contain page snapshots, and therefore content), the seeds
(which are conversations) and the run logs."""

CANDIDATE_EXECUTABLES: tuple[str, ...] = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "chromium",
    "chromium-browser",
    "brave-browser",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "microsoft-edge",
)
"""Tried in this order. Chrome first because it is what claude.ai is tested
against; the Chromium family follows because CDP is the same protocol on all of
them."""

LAUNCH_FLAGS: tuple[str, ...] = (
    "--remote-debugging-address=127.0.0.1",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-sync",
    "--disable-features=TranslateUI",
    "--window-size=1280,900",
)
"""Fixed, so that two operators launch the same browser. `--disable-sync` because
signing a profile into a Google account would put the destination session
somewhere we cannot delete it from; the rest keep first-run interstitials out of
the way of a probe that is looking for a composer."""

HEADLESS_FLAG = "--headless=new"
"""Chrome without a window (`24`). The new headless mode and not the old one:
it is the same browser with the same profile, cookies and rendering, which is
what makes a session signed in headless usable headed afterwards."""

CLOSE_TIMEOUT_S = 10.0
"""How long a browser gets to exit after `Browser.close` before it is signalled.
`10` in the spec, and the same number for an adopted browser we cannot signal."""

POLL_INTERVAL_S = 0.2


class PortInUseError(BrowserError):
    """The debug port is occupied by a browser this tool must not touch.

    Raised when the port answers and the browser on it is not the one we
    launched, and when `session logout` finds a browser running over the profile
    it was asked to delete. Its own class because it is the one browser failure
    that is a usage error (exit `2`) rather than an environment one (exit `6`):
    nothing is missing, the operator just has something in the way.
    """


class ProfileMarker(BaseModel):
    """`dataporter-cdp.json`, written into the profile at launch.

    It answers "is the browser on this port the one we started", which
    `/json/version` cannot: Chrome does not report its `--user-data-dir` over
    CDP at all. `browser_id` is the browser target's own uuid, minted per
    process, so a match means the same instance and not merely the same port.
    """

    model_config = ConfigDict(extra="ignore")

    port: int
    browser_id: str
    pid: int
    started: str


@dataclass
class BrowserSession:
    """A browser this process can drive, whether or not it started it."""

    client: CdpClient
    profile: Path
    process: subprocess.Popen[bytes] | None = None
    adopted: bool = False
    """True when the browser was already running on the port and is ours."""

    def close(self, *, timeout: float = CLOSE_TIMEOUT_S) -> None:
        """Ask the browser to exit, and make sure it does.

        Closing matters more than it looks: Chrome flushes cookies and the
        session store on exit, so a profile that is never closed cleanly can
        come back logged out.

        A dead debug port is not the end of the job. A browser we started that
        never opened its port — a sandbox that hangs rather than exits — cannot
        be asked to close, and leaving it there would orphan a Chrome holding
        our profile and the next run's port. So the request is best effort and
        the process is dealt with either way.
        """
        asked = self._ask_to_close()
        if self.process is not None:
            self._wait_for_exit(timeout, asked=asked)
        elif asked:
            self._wait_for_port_to_go_quiet(timeout)

    def _ask_to_close(self) -> bool:
        """Send `Browser.close`. False when there was nothing to send it to."""
        if not self.client.responding():
            return False
        try:
            with self.client.browser_connection() as connection:
                connection.send("Browser.close")
        except BrowserError:
            # Chrome usually closes the socket rather than answering. That is
            # the request being honoured, not a failure.
            pass
        return True

    def _wait_for_exit(self, timeout: float, *, asked: bool) -> None:
        """See the process out. Ours to end: we started it.

        `asked` is what earns the browser its grace period. Waiting `timeout`
        for a process nobody has asked to exit is `timeout` spent watching a
        hung browser do nothing, on top of whatever the caller already waited.
        """
        process = self.process
        if process is None:  # pragma: no cover - guarded by the caller
            return
        if asked:
            try:
                process.wait(timeout=timeout)
                return
            except subprocess.TimeoutExpired:
                _logger.warning("browser did not exit; terminating", extra={"pid": process.pid})
        elif process.poll() is not None:
            return  # already gone, and reaped by `poll`
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:  # pragma: no cover - a wedged browser
            process.kill()
            process.wait(timeout=timeout)

    def _wait_for_port_to_go_quiet(self, timeout: float) -> None:
        """For an adopted browser there is no child to wait on, only the port.

        No signal is sent if it stays up: the process belongs to an earlier run,
        it is holding the operator's session, and killing it could lose the
        profile write we asked for.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.client.responding():
                return
            time.sleep(POLL_INTERVAL_S)
        _logger.warning("adopted browser is still on the port", extra={"port": self.client.port})


def find_executable(configured: Path | None = None) -> Path:
    """Return the browser binary to run.

    `shutil.which` for both the configured value and the candidates, so a bare
    name (`chromium`) and an absolute path (the macOS bundle) are looked up the
    same way and both are checked for being executable.
    """
    if configured is not None:
        found = shutil.which(str(Path(configured).expanduser()))
        if found is None:
            raise BrowserError(detail=f"configured browser executable not found: {configured}")
        return Path(found)
    for candidate in CANDIDATE_EXECUTABLES:
        found = shutil.which(candidate)
        if found is not None:
            return Path(found)
    raise BrowserError(
        detail="no browser found — install Google Chrome, or set browser.executable in the workspace config.toml"
    )


def marker_path(profile: Path) -> Path:
    return profile / MARKER_FILENAME


def read_marker(profile: Path) -> ProfileMarker | None:
    """Return the marker, or `None` if it is missing, unreadable or not ours."""
    path = marker_path(profile)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return ProfileMarker.model_validate_json(raw)
    except ValidationError:
        return None


def write_marker(profile: Path, marker: ProfileMarker) -> None:
    write_atomically(marker_path(profile), marker.model_dump_json(indent=2) + "\n")


def ensure_profile(settings: Settings) -> Path:
    """Create the browser profile at `0700`, and the workspace's `.gitignore`.

    `0700` explicitly rather than by umask: the directory holds a live session
    for a Claude account, and on a shared machine the default `0755` would make
    it world-readable.

    The `.gitignore` is written only when the profile is inside the workspace,
    which is where `07` put the destination's. `31`'s source profile is in the
    account home under `~/.dataporter/accounts/`, which is not a directory
    anybody checks in and not one a command about an account should be creating
    a `./migration` beside.
    """
    profile = settings.browser_profile_dir
    profile.mkdir(parents=True, exist_ok=True)
    Path(profile).chmod(0o700)
    if profile.is_relative_to(settings.workspace):
        ensure_gitignore(settings.workspace)
    return profile


def ensure_gitignore(workspace: Path) -> Path:
    """Add whatever of `GITIGNORE_ENTRIES` is missing from the workspace's file.

    Merged rather than overwritten: a workspace is the operator's directory and
    may already have a `.gitignore` they wrote.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / GITIGNORE_FILENAME
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    missing = [entry for entry in GITIGNORE_ENTRIES if entry not in existing]
    if not missing:
        return path
    lines = [*existing, *missing] if existing else list(GITIGNORE_ENTRIES)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def adopt(client: CdpClient, profile: Path) -> BrowserSession | None:
    """Reuse the browser already on the debug port, if it is ours.

    `None` means the port is free. A browser that is *not* ours is `PortInUseError`
    and never adopted: attaching to somebody's everyday Chrome would put a
    migration run inside the profile §17 exists to stay out of, and closing it
    afterwards would shut their windows.
    """
    if not client.responding():
        return None
    marker = read_marker(profile)
    if marker is not None and marker.port == client.port and marker.browser_id == client.browser_id():
        _logger.debug("adopted running browser", extra={"port": client.port})
        return BrowserSession(client=client, profile=profile, adopted=True)
    raise PortInUseError(detail=f"port {client.port} is used by another browser", transient=False)


def launch(settings: Settings, url: str) -> BrowserSession:
    """Return a browser at `url`, launched or adopted, with the debug port answering."""
    profile = ensure_profile(settings)
    client = CdpClient(port=settings.browser.cdp_port, timeout=settings.timeouts.cdp_call_s)
    running = adopt(client, profile)
    if running is not None:
        return running

    executable = find_executable(settings.browser.executable)
    command = [
        str(executable),
        f"--user-data-dir={profile}",
        f"--remote-debugging-port={settings.browser.cdp_port}",
        *LAUNCH_FLAGS,
        *([HEADLESS_FLAG] if settings.headless else []),
        *settings.browser.extra_args,
        url,
    ]
    _logger.info(
        "launching browser",
        extra={"port": settings.browser.cdp_port, "executable": str(executable)},
    )
    try:
        # Output is discarded rather than captured: Chrome writes a steady
        # stream of GPU and DBus noise on Linux, none of it ours, and a pipe
        # nobody reads fills up and blocks the browser.
        process = subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true] - the browser command we built
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise BrowserError(detail=f"cannot start {executable}: {exc}") from exc

    session = BrowserSession(client=client, profile=profile, process=process)
    try:
        wait_for_port(session, settings.timeouts.browser_start_s)
        write_marker(
            profile,
            ProfileMarker(
                port=client.port,
                browser_id=client.browser_id(),
                pid=process.pid,
                # `utcnow()` rather than `datetime.now(UTC)`: `docs/orval-
                # candidates.md` on main adopts it as this repo's spelling.
                # The `Z` suffix is hand-rolled because orval has no `iso_utc`
                # yet — candidate C3 in that document.
                started=utcnow().isoformat(timespec="seconds").replace("+00:00", "Z"),
            ),
        )
    except BrowserError:
        # Everything from here on is ours to undo: the process exists because
        # this call created it, and nothing else knows about it yet.
        session.close()
        raise
    return session


def wait_for_port(session: BrowserSession, timeout: float) -> None:
    """Poll `/json/version` until the browser answers, or give up.

    A browser that exits while we wait is reported as itself rather than as a
    timeout: `--user-data-dir` pointing at a profile another Chrome already has
    open, or a sandbox that will not start, both fail in under a second and
    would otherwise cost the operator thirty of them.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if session.client.responding():
            return
        process = session.process
        if process is not None and process.poll() is not None:
            raise BrowserError(detail=f"browser exited immediately with code {process.returncode}")
        time.sleep(POLL_INTERVAL_S)
    # The browser is not closed here: `launch` owns the process it started and
    # closes it on any failure, so doing it twice would only get the ordering
    # wrong in one of the two places.
    raise BrowserError(detail=f"browser did not open its debug port within {timeout:g}s")
