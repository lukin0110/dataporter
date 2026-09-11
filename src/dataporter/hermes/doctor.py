"""`doctor`: ten checks, in dependency order, stopping at the first failure.

The order is the chain itself — Hermes, its profile, its configuration, the skill,
Chrome, the debug port, Hermes reaching that port, Hermes running one of our
helpers, and finally the session. Each check assumes everything above it passed,
which is why the run stops rather than printing nine more failures caused by the
first one.

Two of the checks run a real `hermes -z` task, because nothing short of that
answers the question `09` actually has: whether `browser.cdp_url` is honoured in
one-shot mode at all (`10`'s first open question). They are also the two that take
a minute each, and they are last for that reason.

A nonce is the weakest half of how they are judged. `hermes attaches to chrome`
also requires Hermes to report back the URL of the *other* tab in our browser,
which it can only know by listing the targets on our debug port — a Hermes that
quietly launched a Chromium of its own cannot produce it. `hermes runs helper`
requires a new record in `<workspace>/logs/actions.jsonl`, which is written by our
own helper and not by the agent; an answer with the nonce in it and no record is a
failure.

No check prints anything Hermes said. Its stdout is a workspace file that may
contain page snapshots; what reaches the terminal is a fixed phrase and a path.
"""

import json
import secrets
import time
from collections.abc import Generator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from dataporter import PROGRAM_NAME, log
from dataporter.browser import helpers as browser_helpers
from dataporter.browser import launcher
from dataporter.browser import session as browser_session
from dataporter.browser.cdp import CdpClient
from dataporter.browser.probe import NEW_CHAT_URL
from dataporter.config import Settings
from dataporter.errors import BrowserError, HermesError
from dataporter.hermes import profile as profiling
from dataporter.hermes import skill as skilling
from dataporter.hermes import version as versioning
from dataporter.hermes.client import HermesCli, home_relative, mismatches, quoted
from dataporter.hermes.runner import HermesRunner

_logger = log.get_logger(__name__)

LABEL_WIDTH = 25
"""Wide enough for the longest label, so the `ok` column lines up (`09`)."""

HERMES_ON_PATH = "hermes on PATH"
HERMES_PROFILE = "hermes profile"
HERMES_MODEL = "hermes model"
HERMES_CONFIG = "hermes config"
SKILL_INSTALLED = "skill installed"
CHROME_EXECUTABLE = "chrome executable"
CHROME_LAUNCH = "chrome launch + cdp"
HERMES_ATTACHES = "hermes attaches to chrome"
HERMES_HELPER = "hermes runs helper"
SESSION = "session"

LABELS: tuple[str, ...] = (
    HERMES_ON_PATH,
    HERMES_PROFILE,
    HERMES_MODEL,
    HERMES_CONFIG,
    SKILL_INSTALLED,
    CHROME_EXECUTABLE,
    CHROME_LAUNCH,
    HERMES_ATTACHES,
    HERMES_HELPER,
    SESSION,
)
"""In order. A test reads this rather than the ten strings, so a label that is
renamed cannot be renamed in only one of the two places."""

LOCAL_LABELS: tuple[str, ...] = LABELS[:5]
"""The checks that need neither a browser nor a Hermes task.

`12`'s preflight is exactly these five: they are local, they take milliseconds,
and between them they answer "is the chain installed and configured". The two
that run a real `hermes -z` are left to `doctor` — they cost a minute each, and a
migration is about to prove the same thing with work that counts.
"""

BLANK_URL = "about:blank"
SETUP_HINT = f"run: {PROGRAM_NAME} setup"
LOGIN_HINT = f"run: {PROGRAM_NAME} login"

ATTACH_PROMPT = """\
A Chrome is already running with remote debugging on {cdp_url}, and it has two \
tabs open. Attach to it and do exactly this, nothing else:

1. Take a browser_snapshot of the tab whose URL is {blank_url}.
2. Reply with two lines: the word {nonce}, then the full URL of the other tab.

Do not type, paste, click or upload anything. Do not open any new page.
"""
"""Read-only, and says so three times. A `doctor` that could modify the
destination account would be a `doctor` nobody runs before a migration."""

HELPER_PROMPT = """\
Use the terminal tool to run exactly this command, once:

  {command}

It prints one JSON object. Then reply with two lines: the word {nonce}, then the \
value of that object's "ok" field.

Do not run any other command. Do not type, paste, click or upload anything.
"""


@dataclass(frozen=True)
class Check:
    """One line of `doctor` output."""

    label: str
    ok: bool
    detail: str = ""

    def render(self) -> str:
        if self.ok:
            tail = f"ok  ({self.detail})" if self.detail else "ok"
        else:
            tail = f"FAIL {self.detail}" if self.detail else "FAIL"
        return f"{self.label:<{LABEL_WIDTH}} {tail}"


def nonce() -> str:
    """A token Hermes cannot have seen before and cannot guess."""
    return f"HCM-{secrets.token_hex(5).upper()}"


def checks(settings: Settings) -> Generator[Check, None, None]:
    """Yield one `Check` per check, ending after the first failure.

    A generator so that the CLI prints each line as it is produced — the two
    Hermes checks take a minute each, and ten lines arriving at once after two
    minutes of silence reads like a hang. Close it (`contextlib.closing`) to be
    sure the browser it may have launched is shut down.
    """
    cli = HermesCli(settings)

    # -- Hermes itself ------------------------------------------------------- #
    try:
        path = cli.path
        installed = cli.version()
    except HermesError as exc:
        yield Check(HERMES_ON_PATH, False, exc.detail or type(exc).__name__)
        return
    if not versioning.at_least(installed):
        yield Check(
            HERMES_ON_PATH,
            False,
            f"hermes {versioning.format_version(installed)} is older than the "
            f"minimum {versioning.format_version(versioning.MINIMUM_VERSION)}",
        )
        return
    yield Check(
        HERMES_ON_PATH,
        True,
        f"{versioning.format_version(installed)} at {home_relative(path)}",
    )

    try:
        profiles = cli.profiles()
    except HermesError as exc:
        yield Check(HERMES_PROFILE, False, exc.detail or type(exc).__name__)
        return
    if cli.profile not in profiles:
        yield Check(HERMES_PROFILE, False, f"no {cli.profile} profile — {SETUP_HINT}")
        return
    yield Check(HERMES_PROFILE, True, cli.profile)

    try:
        config = cli.config()
    except HermesError as exc:
        # Reported as the model check rather than as a check of its own: `config
        # show` is how the model is read, and a profile that cannot be read has
        # no model as far as anything downstream is concerned.
        yield Check(HERMES_MODEL, False, exc.detail or type(exc).__name__)
        return
    model = profiling.configured_model(config)
    if not model:
        yield Check(HERMES_MODEL, False, profiling.NO_MODEL.format(profile=cli.profile))
        return
    yield Check(HERMES_MODEL, True, model)

    wrong = mismatches(config, profiling.profile_config(settings))
    if wrong:
        yield Check(HERMES_CONFIG, False, f"{'; '.join(wrong)} — {SETUP_HINT}")
        return
    yield Check(
        HERMES_CONFIG,
        True,
        ", ".join(f"{key}={config[key]}" for key in profiling.CHECKED_KEYS),
    )

    meta = skilling.installed(settings)
    if meta is None:
        yield Check(
            SKILL_INSTALLED,
            False,
            f"not in {skilling.install_dir(settings)} — {SETUP_HINT}",
        )
        return
    yield Check(SKILL_INSTALLED, True, str(meta))

    # -- Chrome, and Hermes reaching it -------------------------------------- #
    try:
        executable = launcher.find_executable(settings.browser.executable)
    except BrowserError as exc:
        yield Check(CHROME_EXECUTABLE, False, exc.detail or "no browser found")
        return
    yield Check(CHROME_EXECUTABLE, True, str(executable))

    started = time.monotonic()
    try:
        browser = launcher.launch(settings, NEW_CHAT_URL)
    except BrowserError as exc:
        yield Check(CHROME_LAUNCH, False, exc.detail or type(exc).__name__)
        return
    try:
        yield Check(
            CHROME_LAUNCH,
            True,
            f"port {settings.browser.cdp_port}, {time.monotonic() - started:.1f}s",
        )
        # Written out rather than looped, because each of the three is only
        # worth running if the one before it passed — and the two Hermes tasks
        # cost a minute each, so "run it anyway and throw the line away" is not
        # a cheap simplification.
        attached = _hermes_reaches_chrome(settings, browser.client)
        yield attached
        if not attached.ok:
            return
        helper = _hermes_runs_helper(settings)
        yield helper
        if not helper.ok:
            return
        yield _session_check(browser)
    finally:
        # A browser this command started is a browser this command closes; one it
        # adopted belongs to whoever started it, as `session status` has it.
        if not browser.adopted:
            browser.close()


def local_failure(settings: Settings) -> Check | None:
    """The first of `LOCAL_LABELS` that fails, or `None` when all five pass.

    `checks` is a generator, so stopping at the fifth is what keeps this from
    launching a browser: nothing past `skill installed` is ever evaluated, and
    closing the generator runs its `finally` clauses either way.
    """
    with closing(checks(settings)) as stream:
        for check in stream:
            if not check.ok:
                return check
            if check.label == SKILL_INSTALLED:
                break
    return None


def _hermes_reaches_chrome(settings: Settings, client: CdpClient) -> Check:
    """Run one `-z` task against a throwaway `about:blank` tab."""
    token = nonce()
    try:
        target_id = _open_blank_tab(client)
    except BrowserError as exc:
        return Check(HERMES_ATTACHES, False, exc.detail or "cannot open a tab")
    try:
        prompt = ATTACH_PROMPT.format(
            cdp_url=profiling.cdp_url(settings),
            blank_url=BLANK_URL,
            nonce=token,
        )
        answered = _ask(settings, prompt, run_id="doctor-attach", label=HERMES_ATTACHES)
        if isinstance(answered, Check):
            return answered
        if token not in answered.stdout:
            return Check(
                HERMES_ATTACHES,
                False,
                f"hermes did not answer with the nonce; stdout: {answered.stdout_path}",
            )
        if NEW_CHAT_URL not in answered.stdout:
            # The nonce came back but the other tab did not: Hermes answered
            # without ever listing the targets on our debug port, which is what
            # attaching to a browser of its own looks like. `10` owns the ladder.
            return Check(
                HERMES_ATTACHES,
                False,
                f"hermes did not report our claude.ai tab, so it is not attached "
                f"to our Chrome; stdout: {answered.stdout_path}",
            )
        return Check(
            HERMES_ATTACHES,
            True,
            f"{BLANK_URL} snapshotted, our claude.ai tab listed",
        )
    finally:
        _close_quietly(client, target_id)


def _hermes_runs_helper(settings: Settings) -> Check:
    """Run one `-z` task whose only job is to invoke `browser probe`."""
    token = nonce()
    command = quoted(
        [
            PROGRAM_NAME,
            "--workspace",
            str(settings.workspace),
            "browser",
            "probe",
        ]
    )
    before = _probe_records(settings)
    answered = _ask(
        settings,
        HELPER_PROMPT.format(command=command, nonce=token),
        run_id="doctor-helper",
        label=HERMES_HELPER,
    )
    if isinstance(answered, Check):
        return answered
    if token not in answered.stdout:
        return Check(
            HERMES_HELPER,
            False,
            f"hermes did not answer with the nonce; stdout: {answered.stdout_path}",
        )
    if _probe_records(settings) <= before:
        # Our own helper appends that record, so this is evidence rather than an
        # agent's account of itself.
        return Check(
            HERMES_HELPER,
            False,
            f"no probe recorded in {browser_helpers.actions_path(settings.workspace)}",
        )
    return Check(HERMES_HELPER, True, "browser probe via terminal tool")


def _session_check(browser: launcher.BrowserSession) -> Check:
    try:
        if browser_session.signed_in(browser):
            return Check(SESSION, True, "logged in")
    except BrowserError as exc:
        return Check(SESSION, False, exc.detail or type(exc).__name__)
    return Check(SESSION, False, f"not logged in — {LOGIN_HINT}")


@dataclass(frozen=True)
class _Answer:
    """A finished `doctor` task: what it printed, and where that is."""

    stdout: str
    stdout_path: Path


def _ask(
    settings: Settings, prompt: str, *, run_id: str, label: str
) -> "_Answer | Check":
    """Run a `doctor` task, or the `Check` that says why it could not be run."""
    runner = HermesRunner(settings)
    try:
        raw = runner.run_raw(
            prompt, run_id=run_id, timeout_s=settings.timeouts.hermes_check_s
        )
    except HermesError as exc:
        return Check(label, False, exc.detail or type(exc).__name__)
    if raw.returncode != 0:
        return Check(
            label,
            False,
            f"hermes exited {raw.returncode}; stderr: {raw.stderr_path}",
        )
    return _Answer(stdout=raw.stdout, stdout_path=raw.stdout_path)


def _open_blank_tab(client: CdpClient) -> str:
    with client.browser_connection() as connection:
        created = connection.send("Target.createTarget", {"url": BLANK_URL})
    target_id = str(created.get("targetId", ""))
    if not target_id:  # pragma: no cover - defensive
        raise BrowserError(detail="browser refused to open a tab")
    return target_id


def _close_quietly(client: CdpClient, target_id: str) -> None:
    try:
        client.close_target(target_id)
    except BrowserError:
        _logger.warning("throwaway tab not closed")


def _probe_records(settings: Settings) -> int:
    """How many `probe` records `logs/actions.jsonl` holds.

    Parsed rather than grepped: the file is ours, but a count that a change to
    `record_action`'s spelling could silently zero would turn this check from
    evidence into decoration.
    """
    path = browser_helpers.actions_path(settings.workspace)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    total = 0
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:  # pragma: no cover - we wrote these lines
            continue
        if isinstance(record, dict) and record.get("helper") == "probe":
            total += 1
    return total
