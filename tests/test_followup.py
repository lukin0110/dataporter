"""The semantic probe: one question, and what is written down about the answer.

§18's third question is the one nothing can count, so `20` asks every migrated
chat what it was about and has a person grade the reply. This module covers the
asking: who gets asked, what the task prompt says, what a probe run's answer
becomes, and — the part that matters most — that a reply reaches
`<workspace>/pilot/probes.json` and nothing else.

Hermes is a stub here rather than the fake process, in every test but the last:
what a probe run *is* is `09`'s subject and is covered there, and a probe is the
result contract on top of it. The last test is the whole command against the fake
Hermes and the fake page, which is where "the browser is opened, the session is
proved, and the replies land" is checked rather than assumed.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataporter import cli, state
from dataporter import followup as following
from dataporter.config import Settings
from dataporter.errors import HermesError
from dataporter.exit_codes import ExitCode
from dataporter.hermes import runner as hermes_running
from dataporter.state import (
    ConversationState,
    Destination,
    MigrationState,
    StateError,
    Status,
)
from world import CHAT, CONTENT, FIRST, OTHER_CHAT, World, cli_env

REPLY = "We talked about listing files in a directory from Python."
"""What a chat might answer. Content, and treated as such below."""


def settings_for(tmp_path: Path) -> Settings:
    return Settings(workspace=tmp_path / "migration")


def entry(status: Status = Status.COMPLETED, chat: str | None = CHAT) -> ConversationState:
    return ConversationState(
        title="never printed",
        status=status,
        destination=Destination(conversation_id=chat),
    )


def answer(**fields: object) -> str:
    """Return what a probe run prints last, inside a transcript that says other things."""
    payload: dict[str, object] = {
        "outcome": "answered",
        "conversation_id": CHAT,
        "reply": REPLY,
    }
    payload.update(fields)
    return f"asking…\n{json.dumps(payload)}\n"


class StubRunner:
    """A Hermes that prints what a test told it to, without a process.

    `09` proves the subprocess; this proves what is made of what it printed.
    """

    def __init__(self, stdout: str = "", error: Exception | None = None) -> None:
        self.stdout = stdout
        self.error = error
        self.prompts: list[str] = []
        self.run_ids: list[str] = []

    def run_raw(self, prompt: str, *, run_id: str, timeout_s: float) -> hermes_running.RawRun:
        self.prompts.append(prompt)
        self.run_ids.append(run_id)
        if self.error is not None:
            raise self.error
        return hermes_running.RawRun(
            run_id=run_id,
            returncode=0,
            stdout=self.stdout,
            stdout_path=Path("/nowhere/stdout.txt"),
            stderr_path=Path("/nowhere/stderr.txt"),
            usage_path=Path("/nowhere/usage.json"),
            elapsed_s=1.0,
        )


def prober(tmp_path: Path, stub: StubRunner) -> following.Prober:
    # The stub stands in for `HermesRunner`, which is the only thing `Prober`
    # asks of it: one method, one shape.
    return following.Prober(settings_for(tmp_path), runner=stub)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Who gets asked
# --------------------------------------------------------------------------- #


def test_only_completed_conversations_with_a_chat_are_probed() -> None:
    """`20` writes "each `completed` conversation".

    A `partial` chat is missing part of the conversation, so what Claude remembers of it
    measures nothing.
    """
    migration = MigrationState(
        root={
            "completed": entry(),
            "partial": entry(Status.PARTIAL),
            "failed": entry(Status.FAILED),
            "no-chat": entry(chat=None),
        }
    )

    assert [uuid for uuid, _ in following.probeable(migration)] == ["completed"]


def test_probeable_keeps_state_json_order() -> None:
    migration = MigrationState(root={"b": entry(), "a": entry()})

    assert [uuid for uuid, _ in following.probeable(migration)] == ["b", "a"]


# --------------------------------------------------------------------------- #
# The prompt
# --------------------------------------------------------------------------- #


def test_the_prompt_names_the_chat_the_question_file_and_the_helper(
    tmp_path: Path,
) -> None:
    text = following.prompt(
        short_id="aa000001",
        conversation_id=CHAT,
        question_file=tmp_path / "question.txt",
        workspace=tmp_path,
    )

    assert "short_id: aa000001" in text
    assert f"conversation_id: {CHAT}" in text
    # The url the agent navigates to, built by `17`'s own function so the chat
    # this asks in and the chat `verify` reads back cannot be two spellings.
    assert f"chat url: https://claude.ai/chat/{CHAT}" in text
    assert f"question file: {tmp_path / 'question.txt'}" in text
    assert "browser …" in text
    # The skill, because its rules are what bound this task — and the one
    # sentence `20` added to them is what lets it quote a reply at all.
    assert "claude-migrate" in text


def test_the_prompt_carries_neither_the_question_nor_any_content(
    tmp_path: Path,
) -> None:
    """The question reaches the composer as bytes through the helper, as a seed does.

    The prompt names the file and never its contents (`11`).
    """
    text = following.prompt(
        short_id="aa000001",
        conversation_id=CHAT,
        question_file=tmp_path / "question.txt",
        workspace=tmp_path,
    )

    assert following.QUESTION not in text


def test_the_question_is_written_byte_for_byte(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)

    path = following.write_question(settings)

    assert path == settings.pilot_dir / following.QUESTION_FILENAME
    assert path.read_bytes() == following.QUESTION.encode("utf-8")


# --------------------------------------------------------------------------- #
# One probe
# --------------------------------------------------------------------------- #


def test_a_reply_becomes_a_probe_record(tmp_path: Path) -> None:
    stub = StubRunner(answer())

    found = prober(tmp_path, stub).ask(FIRST, entry())

    assert found.outcome == "answered"
    assert found.answered
    assert found.reply == REPLY
    assert found.short_id == "aa000001"
    assert found.conversation_id == CHAT
    assert stub.run_ids == ["probe-aa000001"]


def test_an_agent_that_could_not_ask_is_recorded_and_not_raised(
    tmp_path: Path,
) -> None:
    """Nine conversations are waiting behind this one.

    A probe that failed is a row of the write-up rather than the end of the run.
    """
    stub = StubRunner(answer(outcome="needs_human", reply="", error="captcha"))

    found = prober(tmp_path, stub).ask(FIRST, entry())

    assert found.outcome == "needs_human"
    assert not found.answered
    assert found.line() == "aa000001  FAILED  captcha"


def test_hermes_failing_is_recorded_as_a_failed_probe(tmp_path: Path) -> None:
    stub = StubRunner(error=HermesError(detail="timeout after 60s"))

    found = prober(tmp_path, stub).ask(FIRST, entry())

    assert found.outcome == "failed"
    assert found.error == "timeout after 60s"


def test_a_transcript_with_no_result_object_is_a_failed_probe(
    tmp_path: Path,
) -> None:
    stub = StubRunner("I had a look around and then stopped.\n")

    found = prober(tmp_path, stub).ask(FIRST, entry())

    assert found.outcome == "failed"
    assert "no result json" in found.error


def test_a_result_object_that_is_not_one_is_a_failed_probe(tmp_path: Path) -> None:
    stub = StubRunner('{"outcome": "delighted"}\n')

    found = prober(tmp_path, stub).ask(FIRST, entry())

    assert found.outcome == "failed"
    assert found.error.startswith("invalid probe json: outcome:")


def test_the_last_result_object_wins_over_a_helpers_own(tmp_path: Path) -> None:
    """A transcript holds our own `browser probe` objects too.

    `09` already decided which one is the answer: the last one carrying `outcome`.
    """
    stub = StubRunner('{"ok": true, "outcome": "ignored"}\n' + answer())

    assert prober(tmp_path, stub).ask(FIRST, entry()).reply == REPLY


def test_a_reply_from_another_chat_is_not_recorded_as_this_ones(
    tmp_path: Path,
) -> None:
    """The agent is told which chat to ask in and reports which chat it asked in.

    Those disagreeing is the one way a probe produces evidence about the wrong
    conversation, which is worse than none because nothing downstream could tell.
    (Raised by Copilot in review on #29.)
    """
    stub = StubRunner(answer(conversation_id=OTHER_CHAT))

    found = prober(tmp_path, stub).ask(FIRST, entry())

    assert found.outcome == "failed"
    assert not found.reply
    assert found.error == following.WRONG_CHAT.format(reported=OTHER_CHAT)
    # The record still describes the chat this conversation was migrated into,
    # which is the one the row is about.
    assert found.conversation_id == CHAT


def test_a_reply_that_names_no_chat_at_all_is_still_a_reply(tmp_path: Path) -> None:
    """Not evidence of a wrong chat — only of an agent that did not say."""
    stub = StubRunner(answer(conversation_id=None))

    found = prober(tmp_path, stub).ask(FIRST, entry())

    assert found.answered
    assert found.reply == REPLY


def test_a_probe_line_is_a_count_and_never_the_reply(tmp_path: Path) -> None:
    stub = StubRunner(answer())

    found = prober(tmp_path, stub).ask(FIRST, entry())

    assert found.line() == f"aa000001  answered  chars={len(REPLY)}"
    assert REPLY not in found.line()


# --------------------------------------------------------------------------- #
# The file
# --------------------------------------------------------------------------- #


def test_probes_round_trip_through_the_file(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    stub = StubRunner(answer())
    found = prober(tmp_path, stub).ask(FIRST, entry())

    following.write(settings, following.ProbeFile().replace(found))

    read_back = following.read(settings)
    assert read_back.question == following.QUESTION
    assert read_back.probes == [found]


def test_the_file_is_newline_terminated(tmp_path: Path) -> None:
    """`state._dump` and `19`'s `report.json` end in one.

    One convention for the workspace's JSON keeps its diffs quiet. (Raised by Copilot in
    review on #29.)
    """
    settings = settings_for(tmp_path)

    path = following.write(settings, following.ProbeFile())

    assert path.read_text(encoding="utf-8").endswith("}\n")


def test_a_missing_file_reads_as_no_probes(tmp_path: Path) -> None:
    assert following.read(settings_for(tmp_path)).probes == []


def test_a_file_that_is_not_a_probe_file_is_an_operator_error(
    tmp_path: Path,
) -> None:
    settings = settings_for(tmp_path)
    settings.pilot_dir.mkdir(parents=True)
    following.probes_path(settings).write_text('{"probes": 7}', encoding="utf-8")

    with pytest.raises(StateError, match="is not a probe file"):
        following.read(settings)


def test_asking_again_replaces_the_answer_in_place(tmp_path: Path) -> None:
    """Two answers to one question would leave a write-up to choose between them.

    Re-asking one of ten must not reorder the other nine.
    """
    stub = StubRunner(answer())
    asking = prober(tmp_path, stub)
    first = asking.ask(FIRST, entry())
    other = asking.ask("bb000002-2222-4222-8222-222222222222", entry())
    file = following.ProbeFile().replace(first).replace(other)

    again = file.replace(first.model_copy(update={"reply": "again"}))

    assert [item.short_id for item in again.probes] == ["aa000001", "bb000002"]
    assert again.probes[0].reply == "again"


# --------------------------------------------------------------------------- #
# Through the command
# --------------------------------------------------------------------------- #


def test_followup_on_a_workspace_with_nothing_migrated_exits_4(runner: CliRunner, workspace: Path) -> None:
    result = runner.invoke(cli.app, ["followup"], catch_exceptions=False)

    assert result.exit_code == ExitCode.NOTHING_TO_DO
    assert not result.stdout


def test_followup_without_a_hermes_exits_6(runner: CliRunner, workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every probe is a Hermes task.

    The machine is checked once rather than ten identical failures being reported one
    conversation at a time.
    """
    settings = Settings(workspace=workspace / "migration")
    store = state.StateStore(settings.workspace)
    store.bind_export("fingerprint", workspace)
    store.ensure(FIRST, title="never printed", chunks_total=1)
    store.update(FIRST, status=Status.RUNNING)
    store.update(FIRST, status=Status.COMPLETED, destination=Destination(conversation_id=CHAT))
    monkeypatch.setenv("DATAPORTER_WORKSPACE", str(settings.workspace))
    monkeypatch.setenv("DATAPORTER_HERMES__EXECUTABLE", str(workspace / "no-hermes-here"))

    outcome = runner.invoke(cli.app, ["followup"], catch_exceptions=False)

    assert outcome.exit_code == ExitCode.ENVIRONMENT
    assert outcome.stderr.startswith("error: ")
    assert not outcome.stdout


def test_followup_asks_every_migrated_chat_and_keeps_the_replies(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The command, against the fake Hermes and the fake page.

    One migration, then one probe, then a reply on disk and a count on the terminal.
    """
    cli_env(world, monkeypatch)
    world.answers(
        json.dumps({
            "outcome": "completed",
            "conversation_id": CHAT,
            "last_step": "done",
            "chunks_acked": 1,
        }),
        answer(),
    )
    runner.invoke(cli.app, ["import", str(world.export), "--limit", "1"], catch_exceptions=False)

    outcome = runner.invoke(cli.app, ["followup"], catch_exceptions=False)

    assert outcome.exit_code == ExitCode.OK
    assert outcome.stdout == f"aa000001  answered  chars={len(REPLY)}\n"
    probes = following.read(world.settings).probes
    assert [item.reply for item in probes] == [REPLY]


MIGRATED = json.dumps({
    "outcome": "completed",
    "conversation_id": CHAT,
    "last_step": "done",
    "chunks_acked": 1,
})
"""What the fake Hermes answers for a conversation that migrated."""


def test_followup_spaces_the_probes_out_as_a_migration_spaces_conversations(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§13's gap, for §13's reason.

    Each probe is one more message into a real account, sent by the same browser.
    """
    cli_env(world, monkeypatch)
    world.answers(MIGRATED, MIGRATED, answer(), answer())
    runner.invoke(cli.app, ["import", str(world.export), "--limit", "2"], catch_exceptions=False)
    world.pauses.clear()

    outcome = runner.invoke(cli.app, ["followup"], catch_exceptions=False)

    assert outcome.stdout.count("answered") == 2
    # One gap, between the two, and none after the last: there is nothing after
    # it to space it from.
    assert world.pauses == [world.settings.pacing.delay_between_conversations_s]


def test_followup_only_asks_the_conversation_it_names(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli_env(world, monkeypatch)
    world.answers(MIGRATED, MIGRATED, answer())
    runner.invoke(cli.app, ["import", str(world.export), "--limit", "2"], catch_exceptions=False)

    outcome = runner.invoke(cli.app, ["followup", "--only", "aa000001"], catch_exceptions=False)

    assert outcome.exit_code == ExitCode.OK
    assert outcome.stdout.startswith("aa000001  answered")
    assert [item.short_id for item in following.read(world.settings).probes] == ["aa000001"]


def test_followup_on_a_signed_out_session_exits_3(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every probe would fail the same way, and `login` is the fix.

    The rule `12` and `17` both follow.
    """
    cli_env(world, monkeypatch)
    world.answers(MIGRATED, answer())
    runner.invoke(cli.app, ["import", str(world.export), "--limit", "1"], catch_exceptions=False)
    world.page.composer = None

    outcome = runner.invoke(cli.app, ["followup"], catch_exceptions=False)

    assert outcome.exit_code == ExitCode.NOT_AUTHENTICATED
    assert not outcome.stdout


def test_a_probe_that_went_nowhere_exits_1(world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    cli_env(world, monkeypatch)
    world.answers(
        json.dumps({
            "outcome": "completed",
            "conversation_id": CHAT,
            "last_step": "done",
            "chunks_acked": 1,
        }),
        answer(outcome="failed", reply="", error="response_timeout"),
    )
    runner.invoke(cli.app, ["import", str(world.export), "--limit", "1"], catch_exceptions=False)

    outcome = runner.invoke(cli.app, ["followup"], catch_exceptions=False)

    assert outcome.exit_code == ExitCode.FAILED
    assert outcome.stdout == "aa000001  FAILED  response_timeout\n"


def test_neither_the_terminal_nor_the_log_carries_a_reply(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§10 holds for the one command that handles a message on purpose."""
    cli_env(world, monkeypatch)
    world.answers(
        json.dumps({
            "outcome": "completed",
            "conversation_id": CHAT,
            "last_step": "done",
            "chunks_acked": 1,
        }),
        answer(),
    )
    runner.invoke(cli.app, ["import", str(world.export), "--limit", "1"], catch_exceptions=False)

    outcome = runner.invoke(cli.app, ["followup"], catch_exceptions=False)

    assert REPLY not in outcome.stdout
    logs = sorted((world.settings.workspace / "logs").glob("run-*.jsonl"))
    written = "\n".join(path.read_text(encoding="utf-8") for path in logs)
    assert REPLY not in written
    for phrase in CONTENT:
        assert phrase not in written
