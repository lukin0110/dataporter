"""`15`: how slowly the run goes, and what it does when told to wait.

Four subjects, and they are four because §13 asks for four different things.

**The parameters.** Every number §13 names is a `Settings` field with a
conservative default, settable from `config.toml`, from the environment and — for
the three §13 gives a flag — from the command line, in that order of increasing
precedence. The first section sets each of them three ways and reads back the one
that should have won.

**The ceiling.** `run.max_conversations` is not only a default: it is what one
invocation may do to a real account, so exceeding it takes `--all` and asking for
more without it is a usage error rather than a number quietly honoured.

**The waits.** A rate limit is waited out rather than retried, on the account's
own clock when it names one and on `13`'s backoff when it does not — and at the
two edges where waiting would stop being a considered act, it becomes `14`'s ask
instead. These tests drive the real loop through `world`'s fake Hermes, so what is
asserted is what a run does, not what a function returns.

**The gaps.** Twenty seconds between conversations, five between parts. The first
is this process's to sleep and is recorded by `world.pauses`; the second is the
agent's, so what is checkable here is that the prompt and the skill ask for it.
"""

import io
import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dataporter import cli
from dataporter import importer as importing
from dataporter import intervention as intervening
from dataporter import selection as selecting
from dataporter.browser import probe
from dataporter.browser import session as browser_session
from dataporter.config import (
    DEFAULT_WORKSPACE,
    ConfigError,
    PacingSettings,
    RetrySettings,
    RunSettings,
    Settings,
    TimeoutSettings,
    load_settings,
    with_pacing,
)
from dataporter.errors import BrowserError, UsageError
from dataporter.exit_codes import ExitCode
from dataporter.hermes import doctor as hermes_doctor
from dataporter.hermes import prompt as prompting
from dataporter.hermes import skill as skilling
from dataporter.state import Status
from dataporter.steps import Step
from test_intervention import Scripted
from world import CHAT, FIRST, World, completed, result

WAITING = re.compile(r"^waiting .*$", re.MULTILINE)

SPEC_PACING_LINE = (
    "pacing                    ok  (delay 20s, parts 5s, attempts 3, "
    "timeout 1800s, limit 10, rate-limit cap 3600s)"
)
"""`doctor`'s first line, byte for byte. §13's four parameters and the two `15`
adds, in the order an operator needs them: how long between conversations, how
long inside one, how many tries, how long one try may take, how many
conversations, and the longest wait the run will make on its own."""


def write_config(workspace: Path, text: str) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "config.toml").write_text(text, encoding="utf-8")


def waits(printed: str) -> list[str]:
    """Every `waiting …` line, in order."""
    return WAITING.findall(printed)


# --------------------------------------------------------------------------- #
# The parameters
# --------------------------------------------------------------------------- #


def test_the_defaults_are_the_ones_15_specifies(workspace: Path) -> None:
    """Conservative on purpose: a first real run is five to ten conversations."""
    settings = load_settings()

    assert settings.pacing.delay_between_conversations_s == 20.0
    assert settings.pacing.delay_between_parts_s == 5.0
    assert settings.pacing.max_rate_limit_wait_s == 3600.0
    assert settings.retries.max_attempts == 3
    assert settings.retries.backoff_s == (30.0, 120.0, 300.0)
    assert settings.timeouts.response_s == 300.0
    assert settings.timeouts.login_s == 600.0
    assert settings.timeouts.browser_start_s == 30.0
    assert settings.timeouts.cdp_call_s == 20.0
    assert settings.timeouts.attach_s == 60.0
    assert settings.run.max_conversations == 10
    assert settings.run.stop_after_consecutive_failures == 3
    assert settings.run.max_interventions == 5


@pytest.mark.parametrize(
    ("section", "key", "env", "read"),
    [
        (
            "pacing",
            "delay_between_conversations_s",
            "HCM_PACING__DELAY_BETWEEN_CONVERSATIONS_S",
            lambda s: s.pacing.delay_between_conversations_s,
        ),
        (
            "pacing",
            "delay_between_parts_s",
            "HCM_PACING__DELAY_BETWEEN_PARTS_S",
            lambda s: s.pacing.delay_between_parts_s,
        ),
        (
            "pacing",
            "max_rate_limit_wait_s",
            "HCM_PACING__MAX_RATE_LIMIT_WAIT_S",
            lambda s: s.pacing.max_rate_limit_wait_s,
        ),
        (
            "retries",
            "max_attempts",
            "HCM_RETRIES__MAX_ATTEMPTS",
            lambda s: s.retries.max_attempts,
        ),
        (
            "timeouts",
            "hermes_task_s",
            "HCM_TIMEOUTS__HERMES_TASK_S",
            lambda s: s.timeouts.hermes_task_s,
        ),
        (
            "timeouts",
            "response_s",
            "HCM_TIMEOUTS__RESPONSE_S",
            lambda s: s.timeouts.response_s,
        ),
        (
            "run",
            "max_conversations",
            "HCM_RUN__MAX_CONVERSATIONS",
            lambda s: s.run.max_conversations,
        ),
    ],
)
def test_every_parameter_is_readable_and_overridable(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    section: str,
    key: str,
    env: str,
    read: Any,
) -> None:
    """`15`'s first criterion: the file, then the environment over it."""
    write_config(workspace / DEFAULT_WORKSPACE, f"[{section}]\n{key} = 11\n")
    assert read(load_settings()) == 11

    monkeypatch.setenv(env, "12")
    assert read(load_settings()) == 12


def test_the_three_flags_outrank_the_environment(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The top of the ladder, for §13's three flag-configurable parameters.

    `--max-retries` is retries and `max_attempts` is attempts, so the flag's `4`
    has to arrive as a `5`: an operator asking for four more goes is asking for
    five in total.
    """
    monkeypatch.setenv("HCM_PACING__DELAY_BETWEEN_CONVERSATIONS_S", "12")
    monkeypatch.setenv("HCM_RETRIES__MAX_ATTEMPTS", "12")
    monkeypatch.setenv("HCM_TIMEOUTS__HERMES_TASK_S", "12")

    flagged = with_pacing(load_settings(), delay=1.0, max_retries=4, timeout=90.0)

    assert flagged.pacing.delay_between_conversations_s == 1.0
    assert flagged.retries.max_attempts == 5
    assert flagged.timeouts.hermes_task_s == 90.0


def test_an_unset_flag_changes_nothing(workspace: Path) -> None:
    """`None` is "not given", never a value: three of them is the same object."""
    settings = load_settings()
    assert with_pacing(settings) is settings


def test_a_flag_does_not_drop_the_rest_of_its_table(workspace: Path) -> None:
    """The reason this is a `model_copy` and not a re-read with an override."""
    write_config(
        workspace / DEFAULT_WORKSPACE,
        "[pacing]\ndelay_between_parts_s = 9\nmax_rate_limit_wait_s = 60\n",
    )
    flagged = with_pacing(load_settings(), delay=1.0)

    assert flagged.pacing.delay_between_conversations_s == 1.0
    assert flagged.pacing.delay_between_parts_s == 9.0
    assert flagged.pacing.max_rate_limit_wait_s == 60.0


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"delay": -5.0}, "delay_between_conversations_s"),
        ({"max_retries": -1}, "max_attempts"),
        ({"timeout": -30.0}, "hermes_task_s"),
        # Zero is in range for a flag counting seconds and not for a subprocess
        # deadline, so this one is the settings field's to refuse.
        ({"timeout": 0.0}, "hermes_task_s"),
    ],
)
def test_a_nonsensical_pacing_value_is_refused(
    workspace: Path, kwargs: dict[str, float], field: str
) -> None:
    """`model_copy(update=...)` does not validate, which is how `--max-retries -1`
    became a budget of zero attempts — and a conversation with no attempts has
    its first failure recorded `retry_recommended: false`, about a retry nothing
    made. The constraint is on the field, so the same value is refused however it
    arrives. (Raised by Copilot in review on #24.)
    """
    with pytest.raises(ConfigError) as raised:
        with_pacing(load_settings(), **kwargs)

    assert field in str(raised.value)


@pytest.mark.parametrize(
    ("section", "key", "env", "value"),
    [
        (
            "pacing",
            "delay_between_conversations_s",
            "HCM_PACING__DELAY_BETWEEN_CONVERSATIONS_S",
            "-1",
        ),
        ("retries", "max_attempts", "HCM_RETRIES__MAX_ATTEMPTS", "0"),
        ("timeouts", "hermes_task_s", "HCM_TIMEOUTS__HERMES_TASK_S", "0"),
    ],
)
def test_the_same_value_is_refused_from_the_environment(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    section: str,
    key: str,
    env: str,
    value: str,
) -> None:
    """The point of putting the rule on the field rather than only on the flag."""
    monkeypatch.setenv(env, value)

    with pytest.raises(ConfigError):
        load_settings()


@pytest.mark.parametrize(
    "kwargs",
    [{"delay": 0.0}, {"max_retries": 0}, {"timeout": 1.0}],
)
def test_the_edges_that_are_meant_to_work_still_do(
    workspace: Path, kwargs: dict[str, float]
) -> None:
    """No gap between conversations, no retries and a one-second budget are all
    things an operator may legitimately ask for."""
    assert with_pacing(load_settings(), **kwargs) is not None


def test_a_negative_flag_is_refused_by_the_command_line_itself(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    """And the message names the flag that was typed, not the field behind it:
    `--max-retries` counts retries and `retries.max_attempts` counts attempts."""
    result = runner.invoke(
        cli.app,
        ["import", str(export_dir), "--dry-run", "--max-retries", "-1"],
        catch_exceptions=False,
    )

    assert result.exit_code == ExitCode.USAGE
    assert "--max-retries" in result.output


def test_import_offers_the_three_flags_and_all(runner: CliRunner) -> None:
    result = runner.invoke(cli.app, ["import", "--help"], catch_exceptions=False)
    for flag in ("--delay", "--max-retries", "--timeout", "--all"):
        assert flag in result.stdout


def test_doctor_prints_the_numbers_in_force(workspace: Path) -> None:
    """`15`'s line, byte-exact. Not a check: there is nothing to fail."""
    assert hermes_doctor.pacing_check(load_settings()).render() == SPEC_PACING_LINE


def test_the_pacing_line_says_what_the_flags_made_it(workspace: Path) -> None:
    settings = with_pacing(load_settings(), delay=5.0, max_retries=0, timeout=120.0)
    rendered = hermes_doctor.pacing_check(settings).render()

    assert "delay 5s" in rendered
    assert "attempts 1" in rendered
    assert "timeout 120s" in rendered


# --------------------------------------------------------------------------- #
# The ceiling
# --------------------------------------------------------------------------- #


def test_an_unset_limit_is_the_configured_maximum(workspace: Path) -> None:
    chosen = selecting.selection_for(load_settings(), only=[], limit=None)
    assert chosen.limit == 10


def test_all_on_its_own_is_no_limit_at_all(workspace: Path) -> None:
    chosen = selecting.selection_for(
        load_settings(), only=[], limit=None, all_conversations=True
    )
    assert chosen.limit is None


def test_a_limit_under_the_ceiling_needs_nothing(workspace: Path) -> None:
    chosen = selecting.selection_for(load_settings(), only=[], limit=10)
    assert chosen.limit == 10


def test_a_limit_over_the_ceiling_is_a_usage_error(workspace: Path) -> None:
    """`15`'s fourth criterion, and the message names the flag that lifts it."""
    with pytest.raises(UsageError) as raised:
        selecting.selection_for(load_settings(), only=[], limit=11)

    # `error: ` is `01`'s prefix on every usage error, added by the CLI; the rest
    # is `15`'s words, and they are the exception's whole message.
    assert str(raised.value) == (
        "use --all to migrate more than 10 conversations in one run"
    )


def test_all_with_a_limit_is_that_limit(workspace: Path) -> None:
    """An operator who typed both has asked for a number, knowing the ceiling."""
    chosen = selecting.selection_for(
        load_settings(), only=[], limit=11, all_conversations=True
    )
    assert chosen.limit == 11


def test_a_raised_ceiling_raises_the_message_with_it(workspace: Path) -> None:
    write_config(workspace / DEFAULT_WORKSPACE, "[run]\nmax_conversations = 40\n")
    settings = load_settings()

    assert selecting.selection_for(settings, only=[], limit=40).limit == 40
    with pytest.raises(UsageError, match="more than 40 conversations"):
        selecting.selection_for(settings, only=[], limit=41)


def test_the_dry_run_refuses_the_same_limit(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    """The ceiling is about the command's intent, so it is read before the run."""
    result = runner.invoke(
        cli.app,
        ["import", str(export_dir), "--dry-run", "--limit", "11"],
        catch_exceptions=False,
    )
    assert result.exit_code == ExitCode.USAGE


# --------------------------------------------------------------------------- #
# Waiting out a rate limit
# --------------------------------------------------------------------------- #


def still_limited(world: World) -> None:
    """A page that never reports the limit lifting, so a wait runs its course.

    `world`'s default page has an enabled send control, which is
    `probe.rate_limited(...) is False` — the early exit. Tests about how long a
    wait *is* set it the other way; the one about the early exit does not.
    """
    world.page.send_enabled = False
    world.page.composer = ""


def rate_limited(**fields: Any) -> str:
    payload: dict[str, Any] = {
        "outcome": "rate_limited",
        "last_step": str(Step.SUBMIT),
        "error": {"category": "rate_limit", "detail": "the page reported a limit"},
    }
    payload.update(fields)
    return result(**payload)


def test_until_names_the_hour_the_wait_ends() -> None:
    """The account's clock in UTC, said so: `15:00` alone is read wrongly."""
    from datetime import UTC, datetime

    noon = datetime(2026, 9, 10, 14, 31, 0, tzinfo=UTC)
    assert importing.until(1740, now=noon) == "15:00 UTC"


def test_a_named_wait_is_waited_and_the_conversation_then_completes(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """`15`'s second criterion, end to end."""
    still_limited(world)
    world.answers(rate_limited(retry_after_s=3), completed())

    summary = world.run(limit=1)
    printed = capsys.readouterr().out

    assert summary.exit_code is ExitCode.OK
    assert world.entry(FIRST).status is Status.COMPLETED
    run = world.store().run()
    assert run.rate_limit_waits == 1
    # Neither a retry nor an intervention: nothing failed and nobody was asked.
    assert run.retries == 0
    assert run.human_interventions == 0
    assert world.pauses == [3.0]
    assert len(waits(printed)) == 1
    assert re.fullmatch(
        r"waiting 3s \(rate limit until \d\d:\d\d UTC\)", waits(printed)[0]
    )


def test_the_second_attempt_resumes_rather_than_starting_again(
    world: World,
) -> None:
    """A wait is not a restart: the chat the limit interrupted is continued.

    §17's rule, reached through `15`'s door. A rate limit that stopped a chat
    half-written leaves a `partial` entry, and the attempt after the wait
    continues that chat — a second one for the same conversation is the one
    mistake nothing downstream can undo.
    """
    still_limited(world)
    world.answers(
        rate_limited(retry_after_s=3, conversation_id=CHAT, chunks_acked=1),
        completed(CHAT, chunks_acked=2),
    )

    world.run(limit=1)

    prompts = [call.prompt for call in world.hermes.one_shots]
    assert len(prompts) == 2
    assert "existing conversation_id: none" in prompts[0]
    assert f"existing conversation_id: {CHAT}" in prompts[1]
    assert f"resume_from: {Step.SUBMIT}" in prompts[1]


def test_a_wait_longer_than_the_cap_is_an_intervention(world: World) -> None:
    """`15`'s third criterion. An hour is the operator's call, not ours."""
    world.settings.pacing = PacingSettings(max_rate_limit_wait_s=2.0)
    world.answers(rate_limited(retry_after_s=3), completed())
    asked = Scripted()

    summary = world.importer(intervention=asked).run(
        world.export, importing.state.Selection(limit=1)
    )

    assert summary.exit_code is ExitCode.OK
    assert len(asked.asks) == 1
    assert asked.asks[0].reason == intervening.CONFIRMATION_REQUIRED
    assert asked.asks[0].detail.startswith("rate limit until ")
    assert asked.asks[0].phrase.startswith("confirmation required: rate limit until ")
    run = world.store().run()
    assert run.human_interventions == 1
    # Escalated rather than waited: the counter that records waits records none.
    assert run.rate_limit_waits == 0
    assert world.pauses == []


def test_an_unnamed_wait_falls_back_to_the_backoff(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """No time on the page means a guess, and the line says whose guess it is."""
    still_limited(world)
    world.answers(rate_limited(), completed())

    world.run(limit=1)

    assert world.pauses == [30.0]
    assert waits(capsys.readouterr().out) == ["waiting 30s (rate limit, no time given)"]
    assert world.store().run().rate_limit_waits == 1


def test_three_unnamed_waits_in_a_row_become_an_ask(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two guesses are patience; a fourth would be a run spent achieving
    nothing."""
    still_limited(world)
    world.answers(rate_limited(), rate_limited(), rate_limited(), completed())
    asked = Scripted()

    summary = world.importer(intervention=asked).run(
        world.export, importing.state.Selection(limit=1)
    )

    assert summary.exit_code is ExitCode.OK
    # Two waited out on `13`'s schedule, the third handed to a person. The lines
    # announce the whole wait; `pauses` is it in sixty-second slices.
    assert waits(capsys.readouterr().out) == [
        "waiting 30s (rate limit, no time given)",
        "waiting 120s (rate limit, no time given)",
    ]
    assert sum(world.pauses) == 150.0
    assert len(asked.asks) == 1
    assert asked.asks[0].detail == "rate limited 3 times with no time given"
    run = world.store().run()
    assert run.rate_limit_waits == 2
    assert run.human_interventions == 1
    assert run.retries == 0


def test_three_named_limits_in_a_row_become_an_ask_too(world: World) -> None:
    """A short wait made three times over is still an account saying no.

    The spec's rule named the unknown case; a named one that keeps coming back
    would otherwise have no end at all, and a tool that sits still forever has
    stopped being one. The detail says both how often and when.
    """
    still_limited(world)
    world.answers(
        rate_limited(retry_after_s=1),
        rate_limited(retry_after_s=1),
        rate_limited(retry_after_s=1),
        completed(),
    )
    asked = Scripted()

    summary = world.importer(intervention=asked).run(
        world.export, importing.state.Selection(limit=1)
    )

    assert summary.exit_code is ExitCode.OK
    assert world.pauses == [1.0, 1.0]
    assert len(asked.asks) == 1
    assert re.fullmatch(
        r"rate limited 3 times, now until \d\d:\d\d UTC", asked.asks[0].detail
    )
    assert world.store().run().rate_limit_waits == 2


def test_an_ask_gives_the_conversation_its_patience_back(world: World) -> None:
    """The count is spent on the ask, so a helped conversation is not asked
    about again on its very next refusal."""
    still_limited(world)
    world.answers(*([rate_limited(retry_after_s=1)] * 6), completed())
    asked = Scripted()

    world.importer(intervention=asked).run(
        world.export, importing.state.Selection(limit=1)
    )

    # Refusals 1 and 2 waited, 3 asked; 4 and 5 waited, 6 asked.
    assert world.pauses == [1.0, 1.0, 1.0, 1.0]
    assert len(asked.asks) == 2


def test_a_long_wait_is_sliced_and_stops_when_the_page_can_send_again(
    world: World,
) -> None:
    """An hour that cannot be cut short is an hour spent on a lifted limit."""
    world.page.send_enabled = True
    world.answers(rate_limited(retry_after_s=3600), completed())

    world.run(limit=1)

    # One slice, and then the page said it would take a submit.
    assert world.pauses == [importing.RATE_LIMIT_PROBE_S]
    assert world.entry(FIRST).status is Status.COMPLETED


def test_a_page_that_cannot_say_is_waited_out_in_full(world: World) -> None:
    """`None` is not `False`: an idle empty composer ends no wait."""
    still_limited(world)
    world.answers(rate_limited(retry_after_s=120), completed())

    world.run(limit=1)

    assert world.pauses == [60.0, 60.0]


def test_an_account_that_never_lets_up_ends_the_run(world: World) -> None:
    """The loop is bounded at both ends, and a fake Hermes proves it.

    Three refusals of one conversation is an ask; `run.max_interventions` asks is
    the end of the run. Without the first bound this test would never return —
    an account that answers `rate_limited` forever would be waited on forever.
    """
    still_limited(world)
    world.settings.run = RunSettings(max_interventions=2)
    world.answers(rate_limited(retry_after_s=1))
    asked = Scripted()

    summary = world.importer(intervention=asked).run(
        world.export, importing.state.Selection(limit=1)
    )

    assert summary.exit_code is ExitCode.FAILED
    assert summary.stopped is True
    assert len(asked.asks) == 2
    assert intervening.TOO_MANY_INTERVENTIONS in asked.notes


def test_a_rate_limit_never_spends_a_retry(world: World) -> None:
    """`13`'s budget is for failures, and this is not one: a conversation that
    was waited out twice still has every one of its two attempts."""
    still_limited(world)
    world.retries(max_attempts=2, backoff_s=(7.0,))
    world.answers(
        rate_limited(retry_after_s=1),
        rate_limited(retry_after_s=1),
        completed(),
    )

    summary = world.run(limit=1)

    assert summary.exit_code is ExitCode.OK
    assert world.entry(FIRST).attempts == 3
    assert world.store().run().retries == 0
    # The waits are the account's number, never `13`'s seven-second backoff.
    assert world.pauses == [1.0, 1.0]


def test_the_page_decides_whether_a_limit_is_still_in_force() -> None:
    """`probe.rate_limited`'s three answers, which is what `15` waits on."""

    def state(**fields: Any) -> probe.PageState:
        base: dict[str, Any] = {
            "url": "https://claude.ai/new",
            "kind": probe.PageKind.NEW_CHAT,
            "logged_in": True,
            "composer_present": True,
            "composer_chars": 0,
            "generating": False,
            "send_enabled": False,
            "dialogs": (),
            "conversation_id": None,
            "tab_count": 1,
        }
        base.update(fields)
        return probe.PageState(**base)

    # The skill's own signal: a seed in the composer that will not go.
    assert probe.rate_limited(state(composer_chars=4000)) is True
    # It would take a submit, whatever it is still showing.
    assert probe.rate_limited(state(send_enabled=True)) is False
    # An idle new chat looks exactly like this, so it says nothing.
    assert probe.rate_limited(state()) is None


# --------------------------------------------------------------------------- #
# The gaps
# --------------------------------------------------------------------------- #


def test_the_gap_between_conversations_is_the_configured_delay(world: World) -> None:
    """`15`'s fifth criterion, on the fake clock `world` keeps."""
    world.settings.pacing = PacingSettings(delay_between_conversations_s=7.0)

    world.run(limit=3)

    assert world.pauses == [7.0, 7.0]


def test_the_delay_flag_is_what_the_run_sleeps(world: World) -> None:
    world.settings = with_pacing(world.settings, delay=3.0)

    world.run(limit=2)

    assert world.pauses == [3.0]


def test_the_prompt_tells_the_agent_how_long_to_wait_between_parts(
    world: World,
) -> None:
    """The one pacing value this process cannot spend: the per-part loop is
    inside the Hermes run, so it travels in the prompt."""
    world.settings.pacing = PacingSettings(delay_between_parts_s=5.0)

    world.run(limit=1)

    assert "delay between parts: 5" in world.hermes.one_shots[0].prompt


def test_the_prompt_renders_the_delay_as_a_plain_number() -> None:
    rendered = prompting.render(
        short_id="ab12cd34",
        parts=1,
        seed_files=(Path("/w/part-01.txt"),),
        acknowledgements=("MIGRATION-ACK ab12cd34 1/1",),
        workspace=Path("/w"),
        delay_between_parts_s=2.5,
    )
    assert "delay between parts: 2.5" in rendered


def test_a_negative_delay_is_a_bug_and_is_refused() -> None:
    with pytest.raises(prompting.PromptError):
        prompting.render(
            short_id="ab12cd34",
            parts=1,
            seed_files=(Path("/w/part-01.txt"),),
            acknowledgements=("MIGRATION-ACK ab12cd34 1/1",),
            workspace=Path("/w"),
            delay_between_parts_s=-1.0,
        )


def test_the_skill_asks_the_agent_to_make_that_gap() -> None:
    """A prompt field nothing reads would be a field nothing spends."""
    text = (skilling.packaged_dir() / skilling.SKILL_FILENAME).read_text(
        encoding="utf-8"
    )
    assert "| `delay between parts` |" in text
    assert "wait `delay between parts`" in text


# --------------------------------------------------------------------------- #
# The one intervention with a clock on it
# --------------------------------------------------------------------------- #


class NeverLogsIn(Scripted):
    """An operator who keeps pressing Enter at a page that is still signed out."""

    def __init__(self, world: World) -> None:
        super().__init__()
        self.world = world

    def ask(self, request: intervening.Request) -> bool:
        self.world.page.composer = None
        return super().ask(request)

    def retry(self, message: str) -> bool:
        self.world.page.composer = None
        return super().retry(message)


def test_an_auth_pause_nobody_resolves_in_time_stops_the_run(world: World) -> None:
    """`15`'s `auth` rule: exit `3`, and the pause stays for a later `resume`."""
    world.settings.timeouts = TimeoutSettings(
        cdp_call_s=2.0, hermes_cli_s=30.0, hermes_task_s=60.0, login_s=0.0
    )
    world.answers(
        result(
            outcome="needs_human",
            needs_human_reason="auth_required",
            error={"category": "auth", "detail": "sign-in form shown at /login"},
        )
    )
    asked = NeverLogsIn(world)

    summary = world.importer(intervention=asked).run(
        world.export, importing.state.Selection(limit=2)
    )

    assert summary.exit_code is ExitCode.NOT_AUTHENTICATED
    assert summary.stopped is True
    assert asked.notes[-1] == "still not logged in after 0s — stopping"
    # Still there to continue: the account is the problem, not the conversation.
    assert world.store().run().paused is not None
    # And nothing after it was started.
    assert len(world.hermes.one_shots) == 1


def test_a_resume_that_is_still_signed_out_stops_with_3_as_well(
    world: World,
) -> None:
    """The same deadline, entered through `14`'s other door.

    `resume` re-checks the ask before it runs anything, and does not re-print it:
    running the command *is* the operator saying they acted. So a second process
    that finds the account still signed out ends the way the first one did,
    without asking anything — keeping the pause, so a third can continue once
    somebody has logged in.
    """
    world.answers(
        result(
            outcome="needs_human",
            needs_human_reason="auth_required",
            error={"category": "auth", "detail": "sign-in form shown at /login"},
        )
    )
    paused = world.importer(
        intervention=intervening.Console(stdin=io.StringIO(""))
    ).run(world.export, importing.state.Selection(limit=1))
    assert paused.exit_code is ExitCode.PAUSED

    world.settings.timeouts = TimeoutSettings(
        cdp_call_s=2.0, hermes_cli_s=30.0, hermes_task_s=60.0, login_s=0.0
    )
    # The window the operator was asked to log in in, still showing no composer.
    world.page.composer = None
    asked = Scripted()

    resumed = world.importer(intervention=asked).resume()

    assert resumed.exit_code is ExitCode.NOT_AUTHENTICATED
    assert resumed.stopped is True
    assert resumed.selected == ()
    assert asked.asks == []
    assert asked.notes[-1] == "still not logged in after 0s — stopping"
    assert world.store().run().paused is not None
    # Nothing was run: the account is the problem, and it is the same account.
    assert len(world.hermes.one_shots) == 1


def test_a_browser_that_cannot_be_read_does_not_end_a_wait(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A probe that fails says nothing about the limit, so the wait stands.

    The safe direction: the account asked for the whole wait, and a page nobody
    could read is not evidence that it has changed its mind.
    """

    readable = browser_session.current_state
    reads = 0

    def sometimes(*args: Any, **kwargs: Any) -> Any:
        # The first read is the preflight proving the session; every read after
        # it belongs to the wait, which is the one this test is about.
        nonlocal reads
        reads += 1
        if reads == 1:
            return readable(*args, **kwargs)
        raise BrowserError(detail="the tab went away")

    monkeypatch.setattr(browser_session, "current_state", sometimes)
    world.answers(rate_limited(retry_after_s=120), completed())

    world.run(limit=1)

    assert world.pauses == [60.0, 60.0]
    assert world.entry(FIRST).status is Status.COMPLETED


def test_an_operator_who_does_log_in_is_not_timed_out(world: World) -> None:
    """The deadline bounds a stalemate, not a person taking a moment."""
    world.settings.timeouts = TimeoutSettings(
        cdp_call_s=2.0, hermes_cli_s=30.0, hermes_task_s=60.0, login_s=600.0
    )
    world.answers(
        result(
            outcome="needs_human",
            needs_human_reason="auth_required",
            error={"category": "auth", "detail": "sign-in form shown at /login"},
        ),
        completed(),
    )

    summary = world.importer(intervention=Scripted()).run(
        world.export, importing.state.Selection(limit=1)
    )

    assert summary.exit_code is ExitCode.OK
    assert world.entry(FIRST).status is Status.COMPLETED


def test_only_an_auth_ask_has_a_deadline(world: World) -> None:
    """The other five are cleared by a person's word, and a word has no clock."""
    world.settings.timeouts = TimeoutSettings(
        cdp_call_s=2.0, hermes_cli_s=30.0, hermes_task_s=60.0, login_s=0.0
    )
    world.answers(
        result(
            outcome="needs_human",
            needs_human_reason="captcha",
            error={"category": "captcha", "detail": "a challenge was shown"},
        ),
        completed(),
    )

    summary = world.importer(intervention=Scripted()).run(
        world.export, importing.state.Selection(limit=1)
    )

    assert summary.exit_code is ExitCode.OK


def test_the_retry_settings_are_untouched_by_a_pacing_flag(workspace: Path) -> None:
    """`--delay` is `pacing`'s and must not rewrite `13`'s schedule."""
    settings = load_settings()
    assert with_pacing(settings, delay=1.0).retries == RetrySettings()


def test_settings_still_load_with_a_full_pacing_table(workspace: Path) -> None:
    write_config(
        workspace / DEFAULT_WORKSPACE,
        "[pacing]\n"
        "delay_between_conversations_s = 1\n"
        "delay_between_parts_s = 2\n"
        "max_rate_limit_wait_s = 3\n",
    )
    settings: Settings = load_settings()
    assert settings.pacing == PacingSettings(
        delay_between_conversations_s=1.0,
        delay_between_parts_s=2.0,
        max_rate_limit_wait_s=3.0,
    )
