"""Human intervention: the ask, the wait, and the run that comes back.

Three layers, because §12 is three things at once and each of them can be wrong
on its own:

- the **block**, which `14` writes out in full and is therefore compared byte for
  byte;
- the **wait**, which is driven through a real pseudo-terminal — `isatty`, a
  blocking read, EOF, Ctrl-C — rather than a stub, because "not a TTY means pause
  to disk instead of blocking forever" is the whole reason the tool does not just
  call `input()`;
- the **run**, through `fake_world`, where a pause becomes a record in `run.json`,
  an Enter becomes a second attempt at the *same* conversation, and `resume`
  becomes a second process continuing the first one's selection.

Nothing here asserts on a title or a message. The ask carries a short id, a reason
phrase, a step and two counts, and §10 applies to it like everything else.
"""

import io
import json
import os
import pty
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

import pytest
from typer.testing import CliRunner

from dataporter import cli, state
from dataporter import importer as importing
from dataporter import intervention as intervening
from dataporter.exit_codes import ExitCode
from dataporter.hermes import runner as hermes_running
from dataporter.state import Status
from dataporter.steps import Step
from world import (
    CHAT,
    FIRST,
    LONG,
    World,
    cli_env,
    completed,
    needs_human,
    result,
)

FAILED_NETWORK = result(outcome="failed", error={"category": "network", "detail": "x"})
"""A transient failure, which `13` retries and `14` never asks anybody about."""

SPEC_BLOCK = """Human intervention required

Reason:       authentication required
Conversation: 3f9c2a1e (12 of 127)
Last step:    open
Browser:      the Chrome window is open — complete the step there

Press Enter to resume, or Ctrl-C to stop.
"""
"""`14`'s block, transcribed from the spec. The only copy in the suite."""

FIRST_BLOCK = SPEC_BLOCK.replace("3f9c2a1e (12 of 127)", "aa000001 (1 of 1)")
"""The same block for the fixture's first conversation, alone in a selection."""


# --------------------------------------------------------------------------- #
# The block
# --------------------------------------------------------------------------- #


def test_the_block_is_the_golden_string() -> None:
    """§12's ask, byte for byte, labels padded to 14 columns."""
    assert (
        intervening.block(
            intervening.Request(
                short_id="3f9c2a1e",
                reason="auth_required",
                detail="sign-in form shown at /login",
                last_step=Step.OPEN,
                position=12,
                total=127,
            )
        )
        == SPEC_BLOCK
    )


@pytest.mark.parametrize(
    ("reason", "phrase"),
    [
        ("auth_required", "authentication required"),
        ("captcha", "CAPTCHA"),
        ("security_challenge", "security challenge"),
        ("ambiguous_ui", "ambiguous UI state"),
        ("browser_error", "unrecoverable browser error"),
    ],
)
def test_each_reason_has_the_phrase_the_spec_prints(reason: str, phrase: str) -> None:
    assert intervening.Request(short_id="3f9c2a1e", reason=reason).phrase == phrase


def test_a_confirmation_says_what_is_being_confirmed() -> None:
    """The one phrase that continues: resuming is not permission (`11`, §17)."""
    request = intervening.Request(
        short_id="3f9c2a1e",
        reason="confirmation_required",
        detail="delete the draft in the composer",
    )
    assert request.phrase == "confirmation required: delete the draft in the composer"
    # Without a detail there is nothing to append, and no dangling colon.
    assert (
        intervening.Request(short_id="3f9c2a1e", reason="confirmation_required").phrase
        == "confirmation required"
    )


def test_a_reason_nobody_has_heard_of_reads_as_an_ambiguous_ui() -> None:
    """The same fallback `12` uses for the category, for the same reason."""
    assert (
        intervening.Request(short_id="3f9c2a1e", reason="meteor").phrase
        == "ambiguous UI state"
    )


def test_every_needs_human_reason_has_a_phrase() -> None:
    """`09` owns the six; a seventh cannot arrive without words to print."""
    assert set(intervening.REASON_PHRASES) == set(hermes_running.NEEDS_HUMAN_REASONS)


def test_the_offer_names_the_command_an_operator_types() -> None:
    assert (
        intervening.offer("aa000001") == "paused at aa000001 — run: dataporter resume"
    )


# --------------------------------------------------------------------------- #
# The wait
# --------------------------------------------------------------------------- #


@contextmanager
def terminal(keystrokes: str) -> Iterator[IO[str]]:
    """A real pseudo-terminal with `keystrokes` already typed into it.

    A real one rather than an object with `isatty` hardcoded: the difference
    between a terminal and a pipe is exactly what decides whether this tool waits
    for a person or pauses to disk, and a fake that answers the question the way
    the test wants it answered proves nothing about that decision.
    """
    main, follower = pty.openpty()
    if keystrokes:
        os.write(main, keystrokes.encode())
    stdin = os.fdopen(follower, "r")
    try:
        yield stdin
    finally:
        stdin.close()
        os.close(main)


def test_enter_on_a_terminal_resumes(capsys: pytest.CaptureFixture[str]) -> None:
    request = intervening.Request(
        short_id="3f9c2a1e", reason="auth_required", position=12, total=127
    )
    with terminal("\n") as stdin:
        assert intervening.Console(stdin=stdin).ask(request) is True
    assert capsys.readouterr().out == SPEC_BLOCK


def test_a_terminal_that_goes_away_stops_the_run() -> None:
    """The master end is closed before the read: EOF, or EIO, or a closed file.
    All three mean the same thing — there is nobody at the keyboard."""
    main, follower = pty.openpty()
    os.close(main)
    stdin = os.fdopen(follower, "r")
    try:
        assert intervening.Console(stdin=stdin).ask(
            intervening.Request("3f9c2a1e")
        ) is (False)
    finally:
        stdin.close()


def test_a_pipe_is_never_asked_anything(capsys: pytest.CaptureFixture[str]) -> None:
    """Non-TTY: the block is still printed — it is what the operator reads when
    they come back to the exit `5` — and nothing blocks on a stream nobody holds."""
    console = intervening.Console(stdin=io.StringIO("\n"))
    assert console.ask(intervening.Request("3f9c2a1e")) is False
    assert capsys.readouterr().out.startswith("Human intervention required\n")


def test_end_of_input_on_a_terminal_stops_the_run() -> None:
    stdin = io.StringIO("")
    setattr(stdin, "isatty", lambda: True)
    assert (
        intervening.Console(stdin=stdin).ask(intervening.Request("3f9c2a1e")) is False
    )


def test_ctrl_c_at_the_prompt_stops_the_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Ctrl-C reaches a blocking read as an exception, and ends the run the way a
    pipe does: the pause is already on disk, so this is "stop", not "crash"."""

    class Interrupted(io.StringIO):
        def isatty(self) -> bool:
            return True

        def readline(self, *args: Any) -> str:
            raise KeyboardInterrupt

    assert (
        intervening.Console(stdin=Interrupted()).ask(intervening.Request("3f9c2a1e"))
        is False
    )
    assert capsys.readouterr().out.endswith("Ctrl-C to stop.\n\n")


def test_a_closed_stdin_is_nobody_to_ask() -> None:
    stdin = io.StringIO("\n")
    setattr(stdin, "isatty", lambda: True)
    stdin.close()
    assert intervening.Console(stdin=stdin).retry("still not logged in") is False


def test_the_retry_line_is_printed_and_waited_on(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with terminal("\n") as stdin:
        assert intervening.Console(stdin=stdin).retry("still not logged in") is True
    assert capsys.readouterr().out == "still not logged in\n"


def test_a_note_goes_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    """Advisories are not questions: stdout is for the thing being waited on."""
    intervening.Console().note("paused at aa000001")
    captured = capsys.readouterr()
    assert captured.err == "paused at aa000001\n"
    assert captured.out == ""


# --------------------------------------------------------------------------- #
# Interventions a test can answer
# --------------------------------------------------------------------------- #


@dataclass
class Scripted:
    """An operator who always says they have acted, and remembers being asked."""

    asks: list[intervening.Request] = field(default_factory=list)
    retries: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    answer: bool = True

    def ask(self, request: intervening.Request) -> bool:
        self.asks.append(request)
        return self.answer

    def retry(self, message: str) -> bool:
        self.retries.append(message)
        return self.answer

    def note(self, message: str) -> None:
        self.notes.append(message)


@dataclass
class Distracted(Scripted):
    """An operator who presses Enter without logging in, and then logs in.

    The page is what settles an `auth_required` pause, so this is the only way to
    reach the re-probe: `ask` leaves the tab signed out, `retry` fixes it.
    """

    world: World | None = None

    def ask(self, request: intervening.Request) -> bool:
        self._page().composer = None
        return super().ask(request)

    def retry(self, message: str) -> bool:
        self._page().composer = ""
        return super().retry(message)

    def _page(self) -> Any:
        assert self.world is not None
        return self.world.page


# --------------------------------------------------------------------------- #
# Acceptance: a pause, an Enter, and the same conversation again
# --------------------------------------------------------------------------- #


def test_an_enter_resumes_the_same_conversation(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """`14`'s first acceptance criterion, on a pseudo-terminal."""
    world.answers(needs_human(), completed())

    with terminal("\n") as stdin:
        summary = world.importer(intervention=intervening.Console(stdin=stdin)).run(
            world.export, state.Selection(limit=1)
        )

    assert summary.exit_code is ExitCode.OK
    assert FIRST_BLOCK in capsys.readouterr().out
    entry = world.entry(FIRST)
    assert entry.status is Status.COMPLETED
    assert entry.attempts == 2
    run = world.store().run()
    assert run.human_interventions == 1
    # The ask is answered, so the record is gone: `resume` has nothing to do.
    assert run.paused is None
    assert len(world.hermes.one_shots) == 2
    assert f"resume_from: {Step.OPEN}" in world.hermes.one_shots[1].prompt


def test_a_pause_inside_an_existing_chat_resumes_into_it(world: World) -> None:
    """§12's "resume rather than restart": the chat is not opened twice."""
    world.answers(
        needs_human(
            reason="ambiguous_ui",
            conversation_id=CHAT,
            last_step=str(Step.ACK),
            chunks_acked=1,
            error={"category": "ui", "detail": "two dialogs open"},
        ),
        completed(),
    )
    scripted = Scripted()

    world.importer(intervention=scripted).run(world.export, state.Selection(limit=1))

    prompt = world.hermes.one_shots[1].prompt
    assert f"existing conversation_id: {CHAT}" in prompt
    assert f"resume_from: {Step.ACK}" in prompt
    assert "parts already acknowledged: 1" in prompt
    assert scripted.asks[0].phrase == "ambiguous UI state"
    assert scripted.asks[0].last_step is Step.ACK


def test_the_pause_record_says_what_is_being_waited_for(world: World) -> None:
    """The §7 file keeps its five statuses; `run.json` holds the sixth thing."""
    world.answers(needs_human())

    summary = world.importer(intervention=Scripted(answer=False)).run(
        world.export, state.Selection(limit=1)
    )

    assert summary.exit_code is ExitCode.PAUSED
    paused = world.store().run().paused
    assert paused is not None
    assert paused.conversation_uuid == FIRST
    assert paused.reason == "auth_required"
    assert paused.detail == "sign-in form shown at /login"
    assert paused.last_step is Step.OPEN
    assert paused.conversation_id is None
    # The conversation is neither finished nor failed: a human is being waited on.
    entry = world.entry(FIRST)
    assert entry.status is Status.RUNNING
    assert entry.error is not None
    assert entry.error.category.value == "auth"
    assert state.status_counts(world.store().load())["pending"] == 5


def test_an_enter_that_did_not_log_in_is_not_enough(world: World) -> None:
    """The one reason the tool can check for itself, checked."""
    world.answers(needs_human(), completed())
    operator = Distracted(world=world)

    summary = world.importer(intervention=operator).run(
        world.export, state.Selection(limit=1)
    )

    assert operator.retries == [intervening.STILL_NOT_LOGGED_IN]
    assert summary.exit_code is ExitCode.OK
    # Asked once, told once, and one intervention rather than two: the run stopped
    # to ask a single time and stayed there until the answer was true.
    assert len(operator.asks) == 1
    assert world.store().run().human_interventions == 1


def test_a_captcha_is_taken_on_the_human_s_word(world: World) -> None:
    """A solved CAPTCHA looks, from a probe, like a page that was never blocked."""
    world.answers(needs_human(reason="captcha"), completed())
    operator = Distracted(world=world)

    world.importer(intervention=operator).run(world.export, state.Selection(limit=1))

    # The page was left signed out by `ask` and never re-probed, so the run went
    # straight back to Hermes.
    assert operator.retries == []
    assert world.entry(FIRST).status is Status.COMPLETED


# --------------------------------------------------------------------------- #
# Acceptance: nobody to ask
# --------------------------------------------------------------------------- #


def test_without_a_terminal_the_run_pauses_to_disk_and_resume_finishes_it(
    world: World,
) -> None:
    """`14`'s second acceptance criterion."""
    world.answers(needs_human(), completed())

    paused_run = world.importer(
        intervention=intervening.Console(stdin=io.StringIO(""))
    ).run(world.export, state.Selection(limit=2))

    assert paused_run.exit_code is ExitCode.PAUSED
    assert world.store().run().paused is not None
    # Nothing was left holding the workspace or the debug port.
    assert not (world.settings.workspace / state.LOCK_FILENAME).exists()

    resumed = world.importer().resume()

    assert resumed.exit_code is ExitCode.OK
    assert world.entry(FIRST).status is Status.COMPLETED
    assert world.entry(FIRST).attempts == 2
    assert world.store().run().paused is None
    # The rest of the paused run's selection ran too, in one process.
    assert world.entry(LONG).status is Status.COMPLETED
    assert resumed.selected == (FIRST, LONG)


def test_a_resume_reports_where_it_is_in_the_paused_run(world: World) -> None:
    """`(2 of 3)` across a pause: the counts are the paused run's, not the tail's.

    A `resume` continues somebody else's selection from the middle, and an
    operator who is told "conversation 1 of 2" by the command that continues
    "conversation 2 of 3" has been told the wrong thing twice.
    """
    world.answers(completed(), needs_human())
    first = Scripted(answer=False)
    world.importer(intervention=first).run(world.export, state.Selection(limit=3))

    assert first.asks[0].position == 2
    assert first.asks[0].total == 3

    second = Scripted(answer=False)
    resumed = world.importer(intervention=second).resume()

    assert resumed.exit_code is ExitCode.PAUSED
    assert second.asks[0].short_id == first.asks[0].short_id
    assert second.asks[0].position == 2
    assert second.asks[0].total == 3
    assert world.store().run().human_interventions == 2


def test_a_resume_that_finds_the_page_still_blocked_stays_paused(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """ "Exactly as the TTY path does": re-probe, say so, and keep the record."""
    world.answers(needs_human())
    world.importer(intervention=Scripted(answer=False)).run(
        world.export, state.Selection(limit=1)
    )
    world.page.composer = None  # the human ran `resume` without logging in

    resumed = world.importer(
        intervention=intervening.Console(stdin=io.StringIO(""))
    ).resume()

    assert resumed.exit_code is ExitCode.PAUSED
    assert world.store().run().paused is not None
    assert intervening.STILL_NOT_LOGGED_IN in capsys.readouterr().out
    # Nothing was migrated, and Hermes was never run a second time.
    assert len(world.hermes.one_shots) == 1


def test_ctrl_c_leaves_the_pause_for_the_next_run(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """`14`'s third acceptance criterion."""

    class Interrupted(io.StringIO):
        def isatty(self) -> bool:
            return True

        def readline(self, *args: Any) -> str:
            raise KeyboardInterrupt

    world.answers(needs_human(), completed())
    stopped = world.importer(intervention=intervening.Console(stdin=Interrupted())).run(
        world.export, state.Selection(limit=1)
    )

    assert stopped.exit_code is ExitCode.PAUSED
    assert world.store().run().paused is not None
    assert world.entry(FIRST).status is Status.RUNNING

    operator = Scripted()
    again = world.importer(intervention=operator).run(
        world.export, state.Selection(only=[FIRST])
    )

    assert again.exit_code is ExitCode.OK
    # `06` converted the interrupted entry, and the run said where the pause was.
    assert world.store().run().interrupted == 1
    assert operator.notes == [intervening.offer("aa000001")]
    # Picking the conversation back up answers the question the pause asked.
    assert world.store().run().paused is None


# --------------------------------------------------------------------------- #
# Where `13` and `14` meet
# --------------------------------------------------------------------------- #


def test_a_pause_does_not_spend_the_retry_budget(world: World) -> None:
    """`13` counts attempts a failure caused; `14`'s are attempts a person did.

    One intervention and then two transient failures, against a budget of three:
    without the discount the second failure would land on `attempts == 3`, be
    called exhausted, and have its `retry_recommended` rewritten to `false` —
    a false statement about a `network` failure that nothing had retried yet.
    """
    world.retries(max_attempts=3, backoff_s=(1.0, 2.0))
    world.answers(needs_human(), FAILED_NETWORK, FAILED_NETWORK, completed())

    summary = world.importer(intervention=Scripted()).run(
        world.export, state.Selection(limit=1)
    )

    assert summary.exit_code is ExitCode.OK
    entry = world.entry(FIRST)
    assert entry.status is Status.COMPLETED
    # Asked once, retried twice, ran four times.
    assert entry.attempts == 4
    assert len(world.hermes.one_shots) == 4
    assert world.store().run().human_interventions == 1
    # Only the two failures were waited out, and on the schedule's own first two
    # steps: the ask is not a backoff and does not advance one.
    assert world.pauses == [1.0, 2.0]


def test_the_waiting_line_counts_retries_not_attempts(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """`13`'s line reads `retry n/max`, and an ask must not advance `n`.

    The visible half of the same bug: with the ask counted, a conversation helped
    once and then failing twice against a budget of three prints `retry 4/3`.
    """
    world.retries(max_attempts=3, backoff_s=(1.0, 2.0))
    world.answers(needs_human(), FAILED_NETWORK, FAILED_NETWORK, completed())

    world.importer(intervention=Scripted()).run(world.export, state.Selection(limit=1))

    waits = [
        line for line in capsys.readouterr().out.splitlines() if line.startswith("wait")
    ]
    assert waits == [
        "waiting 1s (retry 2/3, network)",
        "waiting 2s (retry 3/3, network)",
    ]


def test_a_deferred_pause_is_never_retried_as_a_failure(world: World) -> None:
    """`needs_human` is `deferred`, so `13`'s policy leaves it entirely alone."""
    world.retries(max_attempts=3, backoff_s=(30.0,))
    world.answers(needs_human(), completed())

    world.importer(intervention=Scripted()).run(world.export, state.Selection(limit=1))

    # No backoff was waited: the second attempt followed the human, immediately.
    assert world.pauses == []


def test_a_conversation_that_pauses_and_then_exhausts_its_retries(
    world: World,
) -> None:
    """The discount is a discount, not an exemption: real failures still run out."""
    world.retries(max_attempts=2, backoff_s=(1.0,))
    world.answers(needs_human(), FAILED_NETWORK)

    summary = world.importer(intervention=Scripted()).run(
        world.export, state.Selection(limit=1)
    )

    assert summary.exit_code is ExitCode.FAILED
    entry = world.entry(FIRST)
    assert entry.status is Status.FAILED
    # One ask, then two attempts that failed: the budget is spent and says so.
    assert entry.attempts == 3
    assert entry.error is not None
    assert entry.error.retry_recommended is False


# --------------------------------------------------------------------------- #
# Acceptance: the budget
# --------------------------------------------------------------------------- #


def test_a_run_that_keeps_asking_stops(world: World) -> None:
    """`14`'s fourth acceptance criterion: six asks end the run with exit `1`."""
    world.answers(needs_human())
    operator = Scripted()

    summary = world.importer(intervention=operator).run(
        world.export, state.Selection(limit=2)
    )

    assert summary.exit_code is ExitCode.FAILED
    assert operator.notes[-1] == intervening.TOO_MANY_INTERVENTIONS
    # Five asks answered, and a sixth that was recorded rather than put to anyone.
    assert len(operator.asks) == world.settings.run.max_interventions
    assert world.store().run().human_interventions == 6
    assert len(world.hermes.one_shots) == 6
    # The second conversation was never started, and the pause is there to resume.
    assert world.entry(LONG).status is Status.PENDING
    assert world.store().run().paused is not None


def test_the_budget_is_per_run_not_per_workspace(world: World) -> None:
    """`19` reports the cumulative number; the budget is about one sitting."""
    world.answers(needs_human(), completed(), needs_human(), completed())
    world.importer(intervention=Scripted()).run(world.export, state.Selection(limit=1))
    world.importer(intervention=Scripted()).run(
        world.export, state.Selection(only=[LONG])
    )

    assert world.store().run().human_interventions == 2
    assert world.entry(LONG).status is Status.COMPLETED


# --------------------------------------------------------------------------- #
# What `resume` refuses
# --------------------------------------------------------------------------- #


def test_a_workspace_with_nothing_paused_has_nothing_to_resume(world: World) -> None:
    with pytest.raises(importing.NothingToResume):
        world.importer().resume()


def test_a_conversation_that_finished_another_way_is_not_resumed(
    world: World,
) -> None:
    """Resuming would open a second chat for a conversation that has one, and
    §17 has no way to undo that."""
    world.answers(needs_human(), completed())
    world.importer(intervention=Scripted(answer=False)).run(
        world.export, state.Selection(limit=1)
    )
    world.importer(intervention=Scripted()).run(
        world.export, state.Selection(only=[FIRST])
    )
    world.store().set_paused(
        state.PauseRecord(conversation_uuid=FIRST, reason="captcha", since=state.now())
    )

    with pytest.raises(importing.NothingToResume):
        world.importer().resume()

    # And the record is gone, so the next `import` does not offer it again.
    assert world.store().run().paused is None


def test_a_pause_the_selection_never_knew_about_is_still_continued(
    world: World,
) -> None:
    """A `run.json` edited by hand, or a record that outlived its run."""
    world.answers(completed())
    world.importer().run(world.export, state.Selection(only=[FIRST]))
    world.store().set_paused(
        state.PauseRecord(conversation_uuid=LONG, reason="captcha", since=state.now())
    )

    resumed = world.importer(intervention=Scripted()).resume()

    assert resumed.selected == (LONG,)
    assert world.entry(LONG).status is Status.COMPLETED


def test_a_workspace_that_does_not_say_which_export_it_came_from(
    world: World,
) -> None:
    world.answers(needs_human())
    world.importer(intervention=Scripted(answer=False)).run(
        world.export, state.Selection(limit=1)
    )
    run_path = world.settings.workspace / state.RUN_FILENAME
    raw = json.loads(run_path.read_text(encoding="utf-8"))
    raw["export_path"] = ""
    state.write_atomically(run_path, json.dumps(raw))

    with pytest.raises(state.StateError, match="which export"):
        world.importer().resume()


def test_an_export_that_has_moved_since_the_pause(
    world: World, tmp_path: Path, export_dir: Path
) -> None:
    import shutil

    moved = tmp_path / "somewhere-else"
    shutil.copytree(export_dir, moved)
    world.export = moved
    world.answers(needs_human())
    world.importer(intervention=Scripted(answer=False)).run(
        world.export, state.Selection(limit=1)
    )
    shutil.rmtree(moved)

    with pytest.raises(state.StateError, match="export not found"):
        world.importer().resume()


# --------------------------------------------------------------------------- #
# Through the command
# --------------------------------------------------------------------------- #


def test_resume_exits_4_when_there_is_nothing_to_resume(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli_env(world, monkeypatch)

    outcome = runner.invoke(cli.app, ["resume"], catch_exceptions=False)

    assert outcome.exit_code == ExitCode.NOTHING_TO_DO
    assert outcome.stdout == f"{importing.NOTHING_TO_RESUME}\n"
    assert outcome.stderr == ""


def test_import_exits_5_and_resume_finishes_the_run(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two commands an operator actually types, in the order §12 has them."""
    cli_env(world, monkeypatch)
    world.answers(needs_human(), completed())

    paused = runner.invoke(
        cli.app, ["import", str(world.export), "--limit", "1"], catch_exceptions=False
    )

    assert paused.exit_code == ExitCode.PAUSED
    # `18`'s header, then `14`'s ask underneath it.
    assert paused.stdout.startswith("Claude migration\n")
    assert "\nHuman intervention required\n" in paused.stdout

    resumed = runner.invoke(cli.app, ["resume"], catch_exceptions=False)

    assert resumed.exit_code == ExitCode.OK
    assert world.entry(FIRST).status is Status.COMPLETED
    # `18`'s final block, and `19`'s account of the workspace under it.
    assert "\nPending:    4\n\nClaude migration complete\n" in resumed.stdout


def test_the_paused_block_carries_no_content(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§10 applies to the ask as much as to the progress line."""
    cli_env(world, monkeypatch)
    world.answers(
        needs_human(error={"category": "auth", "detail": "sign-in form shown"})
    )

    paused = runner.invoke(
        cli.app, ["import", str(world.export), "--limit", "1"], catch_exceptions=False
    )

    assert "Listing files" not in paused.output
    assert world.entry(FIRST).title == "Listing files"


def test_a_needs_human_with_no_reason_still_asks(world: World) -> None:
    """The contract allows a `needs_human` that names none; §12 still applies."""
    world.answers(result(outcome="needs_human"), completed())
    operator = Scripted()

    world.importer(intervention=operator).run(world.export, state.Selection(limit=1))

    assert operator.asks[0].reason == intervening.DEFAULT_REASON
    assert operator.asks[0].phrase == "ambiguous UI state"
    assert world.entry(FIRST).status is Status.COMPLETED
