"""`doctor`: the pacing in force, then ten checks in dependency order.

The order is the chain itself — Hermes, its profile, its configuration, the skill,
Chrome, the debug port, Hermes reaching that port, Hermes running one of our
helpers, and finally the session. Each check assumes everything above it passed,
which is why the run stops rather than printing nine more failures caused by the
first one.

The `pacing` line in front of them is `15`'s, and is why `checks` is not the whole
command: it cannot fail, because there is nothing about it to be wrong — it is the
§13 numbers this invocation would run with. `pacing_check` renders it and the CLI
prints it before the generator starts, so an operator sees the numbers even when
the chain below is broken. A migration is slow on purpose, and "why has it done
nothing for a minute" should be answerable without reading a config file.

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

No check prints anything Hermes said, with one exception measured into the rule
rather than carved out of it. Its stdout is a workspace file that may contain
page snapshots, so what reaches the terminal is a fixed phrase and a path — but
a stdout that is *entirely* one HTTP status line is a run that never reached a
page, and `runner.api_error` will quote that much. Measured on 2026-09-16: a
profile naming a model its endpoint does not serve failed here as "hermes did
not answer with the nonce", which is accurate about the nonce and silent about
the 404 that caused it, and the path in the message was the only way to find out.
"""

import json
import secrets
import time
from collections.abc import Generator, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from dataporter import PROGRAM_NAME, log
from dataporter.browser import helpers as browser_helpers
from dataporter.browser import launcher
from dataporter.browser import session as browser_session
from dataporter.browser import watch as watching
from dataporter.browser.cdp import CdpClient
from dataporter.browser.probe import new_chat_url
from dataporter.config import Settings
from dataporter.console import DISCARD, Sink
from dataporter.errors import BrowserError, HermesError
from dataporter.exit_codes import ExitCode
from dataporter.hermes import profile as profiling
from dataporter.hermes import skill as skilling
from dataporter.hermes import version as versioning
from dataporter.hermes.client import HermesCli, home_relative, mismatches, quoted
from dataporter.hermes.runner import HermesRunner, api_error

_logger = log.get_logger(__name__)

LABEL_WIDTH = 25
"""Wide enough for the longest label, so the `ok` column lines up (`09`)."""

PACING = "pacing"
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
    """Return a token Hermes cannot have seen before and cannot guess."""
    return f"DATAPORTER-{secrets.token_hex(5).upper()}"


def pacing_check(settings: Settings) -> Check:
    """Return the §13 parameters this invocation would run with (`15`).

    A `Check` because it is a line of `doctor` output and that is what one is —
    but not one of `checks`, because it cannot fail and the generator's contract
    is that it stops at the first failure.

    Six numbers and not the whole of `Settings`: §13 names four configurable
    parameters — the delay between conversations, the maximum retries, the
    timeout and the maximum conversations per run — and the two `15` adds are the
    ones an operator watching a run that is doing nothing needs in order to
    explain what they are looking at.

    `attempts` rather than `retries` because that is what `retries.max_attempts`
    counts and the line reports what is in force, not what `--max-retries` was
    typed as. Everything is rendered with `:g` so that a whole number of seconds
    reads as one.
    """
    pacing, retries = settings.pacing, settings.retries
    return Check(
        PACING,
        ok=True,
        detail=", ".join((
            f"delay {pacing.delay_between_conversations_s:g}s",
            f"parts {pacing.delay_between_parts_s:g}s",
            f"attempts {retries.max_attempts}",
            f"timeout {settings.timeouts.hermes_task_s:g}s",
            f"limit {settings.run.max_conversations}",
            f"rate-limit cap {pacing.max_rate_limit_wait_s:g}s",
        )),
    )


def checks(settings: Settings, flags: Sequence[str] = ()) -> Generator[Check, None, None]:  # ruff: ignore[complex-structure, too-many-branches, too-many-return-statements, too-many-statements] - one branch per check, and it stops at the first failure
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
        yield Check(HERMES_ON_PATH, ok=False, detail=exc.detail or type(exc).__name__)
        return
    if not versioning.at_least(installed):
        yield Check(
            HERMES_ON_PATH,
            ok=False,
            detail=f"hermes {versioning.format_version(installed)} is older than the "
            f"minimum {versioning.format_version(versioning.MINIMUM_VERSION)}",
        )
        return
    yield Check(
        HERMES_ON_PATH,
        ok=True,
        detail=f"{versioning.format_version(installed)} at {home_relative(path)}",
    )

    try:
        profiles = cli.profiles()
    except HermesError as exc:
        yield Check(HERMES_PROFILE, ok=False, detail=exc.detail or type(exc).__name__)
        return
    if cli.profile not in profiles:
        yield Check(HERMES_PROFILE, ok=False, detail=f"no {cli.profile} profile — {SETUP_HINT}")
        return
    yield Check(HERMES_PROFILE, ok=True, detail=cli.profile)

    expected = profiling.profile_config(settings)
    try:
        config = cli.config((*expected, profiling.MODEL_KEY))
    except HermesError as exc:
        # Reported as the model check rather than as a check of its own: asking
        # for a key is how the model is read, and a profile that cannot be read
        # has no model as far as anything downstream is concerned.
        yield Check(HERMES_MODEL, ok=False, detail=exc.detail or type(exc).__name__)
        return
    model = profiling.configured_model(config)
    if not model:
        yield Check(HERMES_MODEL, ok=False, detail=profiling.NO_MODEL.format(profile=cli.profile))
        return
    yield Check(HERMES_MODEL, ok=True, detail=model)

    wrong = mismatches(config, expected)
    if wrong:
        yield Check(HERMES_CONFIG, ok=False, detail=f"{'; '.join(wrong)} — {SETUP_HINT}")
        return
    yield Check(
        HERMES_CONFIG,
        ok=True,
        detail=", ".join(f"{key}={config[key]}" for key in profiling.CHECKED_KEYS),
    )

    meta = skilling.installed(settings)
    if meta is None:
        yield Check(
            SKILL_INSTALLED,
            ok=False,
            detail=f"not in {skilling.install_dir(settings)} — {SETUP_HINT}",
        )
        return
    yield Check(SKILL_INSTALLED, ok=True, detail=str(meta))

    # -- Chrome, and Hermes reaching it -------------------------------------- #
    try:
        executable = launcher.find_executable(settings.browser.executable)
    except BrowserError as exc:
        yield Check(CHROME_EXECUTABLE, ok=False, detail=exc.detail or "no browser found")
        return
    yield Check(CHROME_EXECUTABLE, ok=True, detail=str(executable))

    started = time.monotonic()
    try:
        browser = launcher.launch(settings, new_chat_url(browser_session.destination_origin(settings)))
    except BrowserError as exc:
        yield Check(CHROME_LAUNCH, ok=False, detail=exc.detail or type(exc).__name__)
        return
    try:
        with watching.watched(
            settings, command="doctor", flags=flags, site=browser_session.site_of(settings), browser=browser
        ) as traced:
            yield Check(
                CHROME_LAUNCH,
                ok=True,
                detail=f"port {settings.browser.cdp_port}, {time.monotonic() - started:.1f}s"
                + (", headless" if settings.headless else ""),
            )
            # Written out rather than looped, because each of the three is only
            # worth running if the one before it passed — and the two Hermes tasks
            # cost a minute each, so "run it anyway and throw the line away" is not
            # a cheap simplification. The trace's exit code is set before each
            # yield that may be the last: `run_doctor` closes the generator on a
            # failed check, and the trace then ends with `6` rather than `70`.
            attached = _hermes_reaches_chrome(settings, browser.client)
            traced.exit_code = ExitCode.OK if attached.ok else ExitCode.ENVIRONMENT
            yield attached
            if not attached.ok:
                return
            helper = _hermes_runs_helper(settings)
            traced.exit_code = ExitCode.OK if helper.ok else ExitCode.ENVIRONMENT
            yield helper
            if not helper.ok:
                return
            session = _session_check(settings, browser)
            traced.exit_code = ExitCode.OK if session.ok else ExitCode.ENVIRONMENT
            yield session
    finally:
        # A browser this command started is a browser this command closes; one it
        # adopted belongs to whoever started it, as `session status` has it.
        if not browser.adopted:
            browser.close()


def local_failure(settings: Settings) -> Check | None:
    """Return the first of `LOCAL_LABELS` that fails, or `None` when all five pass.

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
        return Check(HERMES_ATTACHES, ok=False, detail=exc.detail or "cannot open a tab")
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
                ok=False,
                detail=f"hermes did not answer with the nonce; stdout: {answered.stdout_path}",
            )
        if new_chat_url(browser_session.destination_origin(settings)) not in answered.stdout:
            # The nonce came back but the other tab did not: Hermes answered
            # without ever listing the targets on our debug port, which is what
            # attaching to a browser of its own looks like. `10` owns the ladder.
            return Check(
                HERMES_ATTACHES,
                ok=False,
                detail=f"hermes did not report our claude.ai tab, so it is not attached "
                f"to our Chrome; stdout: {answered.stdout_path}",
            )
        return Check(
            HERMES_ATTACHES,
            ok=True,
            detail=f"{BLANK_URL} snapshotted, our claude.ai tab listed",
        )
    finally:
        _close_quietly(client, target_id)


def _hermes_runs_helper(settings: Settings) -> Check:
    """Run one `-z` task whose only job is to invoke `browser probe`."""
    token = nonce()
    command = quoted([
        PROGRAM_NAME,
        "--workspace",
        str(settings.workspace),
        "browser",
        "probe",
    ])
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
            ok=False,
            detail=f"hermes did not answer with the nonce; stdout: {answered.stdout_path}",
        )
    if _probe_records(settings) <= before:
        # Our own helper appends that record, so this is evidence rather than an
        # agent's account of itself.
        return Check(
            HERMES_HELPER,
            ok=False,
            detail=f"no probe recorded in {browser_helpers.actions_path(settings.workspace)}",
        )
    return Check(HERMES_HELPER, ok=True, detail="browser probe via terminal tool")


def _session_check(settings: Settings, browser: launcher.BrowserSession) -> Check:
    """Whether the destination's session is signed in, *where this run drives*.

    The origin is passed rather than defaulted (`65`). It used to read
    `signed_in`'s module defaults, which name the real site — so under `--mock`
    `doctor` reported "not logged in" about an account it had just signed into,
    having asked claude.ai instead of the mock.
    """
    session = browser_session.whose(settings)
    try:
        if browser_session.signed_in(browser, session.url, origins=session.origins):
            return Check(SESSION, ok=True, detail="logged in")
    except BrowserError as exc:
        return Check(SESSION, ok=False, detail=exc.detail or type(exc).__name__)
    return Check(SESSION, ok=False, detail=f"not logged in — {LOGIN_HINT}")


@dataclass(frozen=True)
class _Answer:
    """A finished `doctor` task: what it printed, and where that is."""

    stdout: str
    stdout_path: Path


def _ask(settings: Settings, prompt: str, *, run_id: str, label: str) -> "_Answer | Check":
    """Run a `doctor` task, or the `Check` that says why it could not be run.

    Three ways to not get an answer, and they are distinguished because they send
    an operator to three different places. `HermesError` is ours — a timeout, or a
    binary that would not start. A non-zero exit is Hermes saying so itself.

    The third is the one that has to be looked for: Hermes reaching the provider,
    getting an error back, and *exiting zero* with it where the answer belongs.
    Nothing above catches that, so it used to arrive at the nonce comparison and
    come out as "hermes did not answer with the nonce" — true, and a description
    of the symptom that names neither the model nor the endpoint. `failed` in the
    usage file is Hermes's own verdict on the run and is what this believes;
    `api_error` only decides how much of the reason fits on the line.

    That reason then splits, because the next step differs: a `5xx` is the
    provider being busy and wants nothing but another run, while a `4xx` is the
    profile naming something the endpoint does not serve and wants the two keys
    that say so. Sending the first operator to `config show` would be sending
    them to read a file that is already correct.
    """
    runner = HermesRunner(settings)
    try:
        raw = runner.run_raw(prompt, run_id=run_id, timeout_s=settings.timeouts.hermes_check_s)
    except HermesError as exc:
        return Check(label, ok=False, detail=exc.detail or type(exc).__name__)
    if raw.returncode != 0:
        return Check(
            label,
            ok=False,
            detail=f"hermes exited {raw.returncode}; stderr: {raw.stderr_path}",
        )
    if raw.usage.failed:
        reason = api_error(raw.stdout)
        if reason is None:
            # Hermes ran, exited zero, and its own usage file calls the run a
            # failure — so say that and nothing more. An earlier draft guessed
            # "hermes ran no task" here, which claims more than the flag knows:
            # `failed` does not say how far the run got, and it can be set after
            # a transcript has been written. Copilot's finding on #62.
            return Check(label, ok=False, detail=f"hermes reported the run failed; stdout: {raw.stdout_path}")
        if reason.upstream:
            return Check(label, ok=False, detail=f"{reason.line} — the provider, not the profile; run `doctor` again")
        return Check(
            label,
            ok=False,
            detail=(
                f"{reason.line}; check the model and provider in "
                f"{quoted([str(runner.cli.path), *runner.cli.profile_flags(), 'config', 'show'])}"
            ),
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


# --------------------------------------------------------------------------- #
# The `doctor` command (`23`)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DoctorOutcome:
    """Every check that ran, and exit `6` if the last one failed."""

    checks: tuple[Check, ...]
    exit_code: ExitCode


def run_doctor(settings: Settings, *, sink: Sink = DISCARD, flags: Sequence[str] = ()) -> DoctorOutcome:
    """Check that Hermes and Chrome are present and configured, stopping at the first failure (`09`).

    The pacing line comes first and unconditionally: §13's numbers are what this
    invocation would run with, and an operator whose chain is broken still wants
    to see them. The rest are printed one at a time as they are produced — the
    two Hermes checks take a minute each, and ten lines at the end reads like a
    hang. `closing` rather than a plain `for`: the generator launches a browser
    and closes it in a `finally`, and leaving that to garbage collection would
    leave a Chrome holding the debug port for as long as the interpreter felt
    like it.
    """
    log.enable_run_log(settings.workspace)
    sink.line(pacing_check(settings).render())
    ran: list[Check] = []
    failed = False
    with closing(checks(settings, flags=flags)) as stream:
        for check in stream:
            ran.append(check)
            sink.line(check.render())
            if not check.ok:
                failed = True
                break
    return DoctorOutcome(
        checks=tuple(ran),
        exit_code=ExitCode.ENVIRONMENT if failed else ExitCode.OK,
    )
