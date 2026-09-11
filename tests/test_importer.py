"""The import loop: one conversation end to end, and what it writes down.

Hermes and Chrome are both fakes here, and both are the fakes the slices that own
them already use: `fake_hermes` is a real process on disk that answers `-z` with
whatever a test told it to, and `fake_composer` is the modelled claude.ai page
`08` and `11` drive. Everything between them is the real thing — the real
planner, the real seed generator, the real prompt, the real runner, the real
state store.

What that is worth: it proves the *loop* — that a result becomes a state entry,
that one conversation's failure is one conversation's failure, that a run which
finds nothing to do says so, and that nothing a conversation contains reaches
stdout. It proves nothing about whether Hermes can actually drive the page; `11`
covers the procedure with a scripted agent and only `20` can measure the rest.

The world these run in is `world.py`, shared with `13`'s `test_recovery.py`;
what a failure makes the loop *do* is that module's subject, and this one keeps
to what the loop writes down.
"""

import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dataporter import cli, state
from dataporter import importer as importing
from dataporter.browser import launcher
from dataporter.browser.cdp import CdpClient
from dataporter.config import Settings
from dataporter.errors import AuthError, BrowserError, Category, HermesError
from dataporter.exit_codes import ExitCode
from dataporter.hermes import runner as hermes_running
from dataporter.state import Status
from dataporter.steps import Step
from fake_composer import Browser, FakePage
from world import (
    CHAT,
    CONTENT,
    EMPTY,
    FIRST,
    LONG,
    MODEL,
    NEW_URL,
    OTHER_CHAT,
    World,
    cli_env,
    completed,
    result,
)

# --------------------------------------------------------------------------- #
# Acceptance: one conversation, end to end
# --------------------------------------------------------------------------- #


def test_one_conversation_is_migrated_and_recorded(world: World) -> None:
    """`12`'s first acceptance criterion, with `--limit 1` on the fixture."""
    summary = world.run(limit=1)

    assert summary.exit_code is ExitCode.OK
    assert summary.selected == (FIRST,)
    entry = world.entry(FIRST)
    assert entry.status is Status.COMPLETED
    assert entry.destination.conversation_id == CHAT
    assert entry.last_step is Step.DONE
    assert entry.chunks_acked == 1
    assert entry.attempts == 1
    assert entry.error is None
    # The fixture's first conversation is two messages on the active path, and
    # both are in the one part that was acknowledged.
    assert entry.messages_represented == 2


def test_the_seed_and_the_prompt_reached_hermes(world: World) -> None:
    """The prompt names this run's seed files, and nothing else ran."""
    world.run(limit=1)

    one_shots = world.hermes.one_shots
    assert len(one_shots) == 1
    prompt = one_shots[0].prompt
    seed_part = world.settings.seeds_dir / FIRST / "part-01.txt"
    assert str(seed_part) in prompt
    assert seed_part.is_file()
    # `09`'s environment and working directory, unchanged by the loop.
    assert one_shots[0].cwd == str(world.settings.workspace)
    assert one_shots[0].env["HCM_WORKSPACE"] == str(world.settings.workspace)
    # The run's three files are named after the conversation and the attempt.
    assert (world.settings.hermes_dir / "aa000001-1.stdout.txt").is_file()


def test_the_plan_is_written_before_anything_runs(world: World) -> None:
    world.run(limit=1)

    plan = json.loads(
        (world.settings.workspace / importing.PLAN_FILENAME).read_text(encoding="utf-8")
    )
    # The whole export, not the selection: §10's "conversations found".
    assert len(plan["conversations"]) == 6
    assert plan["totals"]["migratable"] == 5


def test_every_planned_conversation_gets_an_entry(world: World) -> None:
    """Unsupported ones included, as `failed`, so `19`'s totals add up."""
    world.run(limit=1)

    migration = world.store().load()
    assert len(migration) == 6
    unsupported = migration[EMPTY]
    assert unsupported.status is Status.FAILED
    assert unsupported.error is not None
    assert unsupported.error.category is Category.UNSUPPORTED
    assert unsupported.error.retry_recommended is False
    # Never handed to Hermes: there is nothing to paste.
    assert len(world.hermes.one_shots) == 1
    assert state.status_counts(migration) == {
        "total": 6,
        "completed": 1,
        "partial": 0,
        "failed": 1,
        "pending": 4,
    }


def test_titles_are_in_state_and_nowhere_else(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """§7 puts the title in `state.json`; §10 keeps it off everything else."""
    world.run()
    captured = capsys.readouterr()

    assert world.entry(FIRST).title == "Listing files"
    for phrase in CONTENT:
        assert phrase not in captured.out
        assert phrase not in captured.err
    # Two of six are done after the first: the unsupported one was written as
    # `failed` before the loop started.
    assert captured.out.startswith("aa000001  completed  (2/6)\n")
    assert captured.out.endswith(
        "Completed:  5\nPartial:    0\nFailed:     1\nPending:    0\n"
    )


# --------------------------------------------------------------------------- #
# Acceptance: a failure is one conversation's failure
# --------------------------------------------------------------------------- #


def test_a_failing_conversation_does_not_end_the_run(world: World) -> None:
    """`12`'s second criterion: the second conversation's Hermes falls over.

    `13` gives that conversation three attempts before the loop gives up on it,
    which is why the fake answers five times for three conversations. What `12`
    asks is only the last line: giving up on one is not giving up on the run.
    """
    nonsense = "nothing that is a result"
    world.answers(completed(), nonsense, nonsense, nonsense, completed(OTHER_CHAT))
    world.exits(0, 1, 1, 1, 0)

    summary = world.run(limit=3)

    assert summary.exit_code is ExitCode.FAILED
    assert [status for status in summary.outcomes.values()] == [
        Status.COMPLETED,
        Status.FAILED,
        Status.COMPLETED,
    ]
    failed = world.entry(LONG)
    assert failed.status is Status.FAILED
    assert failed.error is not None
    assert failed.error.category is Category.HERMES
    assert failed.attempts == 3
    # The third conversation still ran, and ran after the second's last attempt.
    assert len(world.hermes.one_shots) == 5


def test_a_second_run_over_a_finished_migration_exits_4(world: World) -> None:
    """`12`'s third criterion. Nothing is pending, so there is nothing to do."""
    world.answers(completed(), completed(OTHER_CHAT))
    assert world.run().exit_code is ExitCode.OK

    again = world.run()

    assert again.exit_code is ExitCode.NOTHING_TO_DO
    assert again.selected == ()
    # Both runs are recorded, the second with its empty selection.
    runs = world.store().run().runs
    assert len(runs) == 2
    assert runs[1].selection.uuids == []
    assert runs[1].exit_code == int(ExitCode.NOTHING_TO_DO)


# --------------------------------------------------------------------------- #
# Resuming, retrying and forcing
# --------------------------------------------------------------------------- #


def test_a_partial_conversation_is_resumed_into_its_own_chat(world: World) -> None:
    """The prompt carries the chat and the count, so no second chat is opened."""
    store = world.store()
    store.ensure(
        FIRST,
        status=Status.PARTIAL,
        destination=state.Destination(conversation_id=CHAT),
        last_step=Step.ACK,
        chunks_acked=1,
        attempts=1,
    )
    world.answers(completed())

    world.run(only=[FIRST], retry_partial=True)

    prompt = world.hermes.one_shots[0].prompt
    assert f"existing conversation_id: {CHAT}" in prompt
    assert "parts already acknowledged: 1" in prompt
    assert f"resume_from: {Step.ACK}" in prompt
    entry = world.entry(FIRST)
    assert entry.attempts == 2
    assert entry.status is Status.COMPLETED
    # A second attempt is a retry, and `run.json` counts it.
    assert world.store().run().retries == 1


def test_forcing_a_completed_conversation_keeps_the_old_chat(world: World) -> None:
    """§17 deletes nothing, so the id the old chat has is remembered, not lost."""
    world.answers(completed(), completed(OTHER_CHAT))
    world.run(limit=1)

    world.run(only=[FIRST], force=True)

    assert world.entry(FIRST).destination.conversation_id == OTHER_CHAT
    assert world.store().run().previous_destinations == {FIRST: [CHAT]}
    # A forced run starts a new chat: the prompt names none.
    assert "existing conversation_id: none" in world.hermes.one_shots[1].prompt


def test_retrying_a_failed_unsupported_conversation_runs_nothing(world: World) -> None:
    """`--retry-failed` can select one, and there is still no seed to paste."""
    world.run(limit=1)

    summary = world.run(only=[EMPTY], retry_failed=True)

    assert summary.exit_code is ExitCode.FAILED
    assert summary.outcomes == {EMPTY: Status.FAILED}
    assert len(world.hermes.one_shots) == 1  # the first run's, and no more


def test_an_interrupted_entry_is_recovered_before_the_run(world: World) -> None:
    """`06`'s crash recovery, with `12` as the first thing that calls it."""
    store = world.store()
    store.ensure(
        FIRST,
        status=Status.RUNNING,
        destination=state.Destination(conversation_id=CHAT),
        attempts=1,
    )
    store.ensure(LONG, status=Status.RUNNING, attempts=1)

    world.run(limit=2, retry_partial=True)

    assert world.store().run().interrupted == 2
    # The one with a chat came back as `partial` and was resumed into it; the
    # one without came back as `pending` and started again.
    assert f"existing conversation_id: {CHAT}" in world.hermes.one_shots[0].prompt
    assert "existing conversation_id: none" in world.hermes.one_shots[1].prompt


# --------------------------------------------------------------------------- #
# What a run counts
# --------------------------------------------------------------------------- #


def test_browser_actions_come_from_our_own_log(world: World) -> None:
    """`append_probe` makes the fake write the record our helper would have."""
    world.run(limit=2)

    run = world.store().run()
    # One record per Hermes run, and the agent's own `actions: 4` is not it.
    assert run.browser_actions == 2


def test_hermes_usage_is_added_up(world: World) -> None:
    world.hermes.write(
        version="hermes 1.0.0",
        config_extra={"agent.model": MODEL},
        answers=[completed()],
        append_probe=True,
        usage={"input_tokens": 100, "output_tokens": 20, "cost_usd": 0.25},
    )

    world.run(limit=2)

    run = world.store().run()
    assert run.hermes_input_tokens == 200
    assert run.hermes_output_tokens == 40
    assert run.hermes_cost_usd == 0.5


def test_the_run_pauses_between_conversations_but_not_after_the_last(
    world: World,
) -> None:
    delay = world.settings.pacing.delay_between_conversations_s

    world.run(limit=3)

    assert world.pauses == [delay, delay]


def test_pause_sleeps_only_for_a_positive_wait() -> None:
    """The seam every wait goes through. Zero is not a sleep, and a sleep is
    short."""
    importing.pause(0)
    importing.pause(-1)
    importing.pause(0.001)


# --------------------------------------------------------------------------- #
# What ends a run rather than a conversation
# --------------------------------------------------------------------------- #


def test_a_signed_out_session_is_refused_before_anything_is_written(
    world: World,
) -> None:
    """A page with nothing to type into is what signed out looks like (`07`)."""
    world.page.composer = None

    with pytest.raises(AuthError) as raised:
        world.run(limit=1)

    assert raised.value.detail == "not logged in — run: hermes-claude-migrate login"
    assert world.hermes.one_shots == []
    assert not (world.settings.workspace / state.STATE_FILENAME).exists()


def test_an_unconfigured_hermes_is_refused_before_the_browser(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The local half of `doctor`, and no browser launched to find it out."""
    world.hermes.state_path.write_text(
        json.dumps({"profiles": [], "config": {}}), encoding="utf-8"
    )

    with pytest.raises(HermesError) as raised:
        world.run(limit=1)

    assert "hermes profile" in (raised.value.detail or "")
    assert world.launches == []


def test_a_browser_that_cannot_come_back_ends_the_run(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One conversation lands, then Chrome goes away for good: exit `6`."""

    class StopTheBrowser:
        def __init__(self) -> None:
            self.seen: list[str] = []

        def conversation(
            self, short_id: str, status: Status, counts: Mapping[str, int]
        ) -> None:
            self.seen.append(short_id)
            world.browser.chrome.stop()

        def waiting(self, seconds: float, reason: str) -> None:  # pragma: no cover
            raise AssertionError("the run should not have waited")

        def stopping(self, failures: int, category: Category) -> None:
            raise AssertionError("the run should not have tripped the breaker")

        def finish(self, counts: Mapping[str, int]) -> None:  # pragma: no cover
            raise AssertionError("the run should not have finished")

    progress = StopTheBrowser()
    launched = 0

    def refuse(settings: Settings, url: str) -> launcher.BrowserSession:
        nonlocal launched
        launched += 1
        if launched > 1:
            raise BrowserError(detail="browser exited immediately with code 1")
        return launcher.BrowserSession(
            client=CdpClient(port=world.browser.chrome.port, timeout=2.0),
            profile=settings.browser_profile_dir,
            adopted=True,
        )

    monkeypatch.setattr(launcher, "launch", refuse)

    with pytest.raises(BrowserError) as raised:
        world.importer(progress=progress).run(world.export, state.Selection(limit=2))

    assert importing.NOT_RELAUNCHABLE in (raised.value.detail or "")
    assert progress.seen == ["aa000001"]
    # The first conversation is still recorded, and the lock is not left behind.
    assert world.entry(FIRST).status is Status.COMPLETED
    assert not (world.settings.workspace / state.LOCK_FILENAME).exists()


class AfterOne:
    """A progress sink that kills the browser once, after the first conversation.

    The `_ensure_browser` path only exists for a Chrome that went away between
    conversations, and this is how a test arranges one.
    """

    def __init__(self, world: World) -> None:
        self.seen: list[str] = []
        self.world = world

    def conversation(
        self, short_id: str, status: Status, counts: Mapping[str, int]
    ) -> None:
        self.seen.append(short_id)
        if len(self.seen) == 1:
            self.world.browser.chrome.stop()

    def waiting(self, seconds: float, reason: str) -> None:
        pass

    def stopping(self, failures: int, category: Category) -> None:
        pass

    def finish(self, counts: Mapping[str, int]) -> None:
        pass


def replacement(
    monkeypatch: pytest.MonkeyPatch, world: World, browser: Browser
) -> None:
    """Launch the world's browser first, then `browser` for every relaunch."""
    launched = 0

    def launch(settings: Settings, url: str) -> launcher.BrowserSession:
        nonlocal launched
        launched += 1
        port = world.browser.chrome.port if launched == 1 else browser.chrome.port
        return launcher.BrowserSession(
            client=CdpClient(port=port, timeout=2.0),
            profile=settings.browser_profile_dir,
            adopted=True,
        )

    monkeypatch.setattr(launcher, "launch", launch)


def test_a_relaunched_browser_is_put_through_the_preflight_checks(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Chrome restarted over our profile can restore the tabs it had open, so
    the tab it leaves us with is as unproven as a freshly launched one's."""
    came_back = Browser(
        FakePage(url=NEW_URL, composer=""), FakePage(url="about:blank", composer=None)
    )
    came_back.__enter__()
    replacement(monkeypatch, world, came_back)
    progress = AfterOne(world)

    try:
        summary = world.importer(progress=progress).run(
            world.export, state.Selection(limit=2)
        )
        # The blank tab the replacement came back with is gone: `close-extra-tabs`
        # ran on it, exactly as the preflight would have.
        assert [target.url for target in came_back.chrome.targets] == [NEW_URL]
    finally:
        came_back.chrome.stop()

    assert summary.exit_code is ExitCode.OK
    assert progress.seen == ["aa000001", "bb000002"]


def test_a_relaunched_browser_that_is_signed_out_ends_the_run(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exit `3` wherever it is noticed: every conversation left would fail the
    same way, and `14` is where this becomes a pause instead."""
    came_back = Browser(FakePage(url=NEW_URL, composer=None))
    came_back.__enter__()
    replacement(monkeypatch, world, came_back)

    try:
        with pytest.raises(AuthError):
            world.importer(progress=AfterOne(world)).run(
                world.export, state.Selection(limit=2)
            )
    finally:
        came_back.chrome.stop()

    assert world.entry(FIRST).status is Status.COMPLETED
    assert world.entry(LONG).status is Status.PENDING  # never started
    assert len(world.hermes.one_shots) == 1


def test_a_browser_the_run_started_is_closed_on_the_way_out(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`07`'s rule: one this run launched is ours to close; an adopted one is
    whoever started it's, and every other test here adopts."""
    closed: list[bool] = []

    class Ours(launcher.BrowserSession):
        def close(self, *, timeout: float = launcher.CLOSE_TIMEOUT_S) -> None:
            closed.append(True)

    def launch_ours(settings: Settings, url: str) -> launcher.BrowserSession:
        return Ours(
            client=CdpClient(port=world.browser.chrome.port, timeout=2.0),
            profile=settings.browser_profile_dir,
        )

    monkeypatch.setattr(launcher, "launch", launch_ours)

    assert world.run(limit=1).exit_code is ExitCode.OK
    assert closed == [True]


def test_a_locked_workspace_is_refused_and_force_unlock_takes_it(
    world: World,
) -> None:
    world.settings.workspace.mkdir(parents=True, exist_ok=True)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (world.settings.workspace / state.LOCK_FILENAME).write_text(
        json.dumps({"pid": dead.pid, "started": "2026-09-10T14:01:07Z"}),
        encoding="utf-8",
    )

    with pytest.raises(state.WorkspaceLocked):
        world.run(limit=1)

    summary = world.importer(force_unlock=True).run(
        world.export, state.Selection(limit=1)
    )
    assert summary.exit_code is ExitCode.OK


def test_a_workspace_from_another_export_is_refused(world: World) -> None:
    world.store().bind_export("sha256:not-this-export")

    with pytest.raises(state.FingerprintMismatch):
        world.run(limit=1)

    assert world.hermes.one_shots == []


# --------------------------------------------------------------------------- #
# A conversation whose id cannot be a directory
# --------------------------------------------------------------------------- #


def test_a_conversation_id_that_is_not_a_directory_name_fails_alone(
    world: World, tmp_path: Path
) -> None:
    """`04` refuses to join it to a path; `12` records that and moves on."""
    hostile = "../escape"
    export = tmp_path / "hostile-export"
    export.mkdir()
    (export / "conversations.json").write_text(
        json.dumps(
            [
                {
                    "uuid": hostile,
                    "name": "Nowhere",
                    "created_at": "2024-05-01T09:00:00.000000Z",
                    "updated_at": "2024-05-01T09:01:00.000000Z",
                    "chat_messages": [
                        {
                            "uuid": "m1",
                            "text": "hello",
                            "sender": "human",
                            "created_at": "2024-05-01T09:00:00.000000Z",
                            "updated_at": "2024-05-01T09:00:00.000000Z",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    world.export = export

    summary = world.run(limit=1)

    assert summary.exit_code is ExitCode.FAILED
    entry = world.entry(hostile)
    assert entry.status is Status.FAILED
    assert entry.error is not None
    assert entry.error.category is Category.UNSUPPORTED
    assert world.hermes.one_shots == []
    assert not (tmp_path / "escape").exists()


# --------------------------------------------------------------------------- #
# The mapping table
# --------------------------------------------------------------------------- #


def hermes_result(**fields: Any) -> hermes_running.HermesResult:
    payload: dict[str, Any] = {"outcome": "failed", "last_step": str(Step.PASTE)}
    payload.update(fields)
    return hermes_running.HermesResult.model_validate(payload)


@pytest.mark.parametrize(
    ("result", "landed", "status", "category"),
    [
        (hermes_result(outcome="completed"), True, Status.COMPLETED, None),
        (
            hermes_result(outcome="completed"),
            False,
            Status.PARTIAL,
            Category.VERIFICATION,
        ),
        (
            hermes_result(outcome="partial", error={"category": "generation"}),
            True,
            Status.PARTIAL,
            Category.GENERATION,
        ),
        (
            hermes_result(outcome="failed", error={"category": "ui"}),
            False,
            Status.FAILED,
            Category.UI,
        ),
        (
            hermes_result(outcome="failed", error={"category": "ui"}),
            True,
            Status.PARTIAL,
            Category.UI,
        ),
        (
            hermes_result(outcome="needs_human", needs_human_reason="captcha"),
            False,
            Status.FAILED,
            Category.CAPTCHA,
        ),
        (
            hermes_result(outcome="rate_limited", retry_after_s=60),
            True,
            Status.PARTIAL,
            Category.RATE_LIMIT,
        ),
        (
            hermes_result(outcome="rate_limited", retry_after_s=60),
            False,
            Status.FAILED,
            Category.RATE_LIMIT,
        ),
    ],
)
def test_the_mapping_table(
    result: hermes_running.HermesResult,
    landed: bool,
    status: Status,
    category: Category | None,
) -> None:
    mapped = importing.interpret(result, landed=landed)
    assert mapped.status is status
    if category is None:
        assert mapped.error is None
        assert mapped.last_step is Step.DONE
        return
    assert mapped.error is not None
    assert mapped.error.category is category


def test_a_completed_result_with_no_chat_says_so() -> None:
    mapped = importing.interpret(hermes_result(outcome="completed"), landed=False)
    assert mapped.error is not None
    assert mapped.error.detail == importing.NO_CONVERSATION_ID
    assert mapped.last_step is Step.PASTE


def test_a_rate_limit_keeps_its_retry_after() -> None:
    mapped = importing.interpret(
        hermes_result(outcome="rate_limited", retry_after_s=90), landed=False
    )
    assert mapped.error is not None
    assert mapped.error.detail == "rate limited; retry after 90s"
    assert mapped.error.retry_recommended is True


def test_a_stop_with_no_error_is_recorded_as_one() -> None:
    mapped = importing.interpret(hermes_result(outcome="failed"), landed=False)
    assert mapped.error is not None
    assert mapped.error.category is Category.HERMES
    assert mapped.error.detail == importing.UNREPORTED.format(outcome="failed")


def test_a_needs_human_with_no_reason_is_still_recorded() -> None:
    mapped = importing.interpret(hermes_result(outcome="needs_human"), landed=False)
    assert mapped.error is not None
    assert mapped.error.category is Category.UI


def test_every_needs_human_reason_has_a_category() -> None:
    """`09` owns the six reasons; a seventh cannot arrive without a home."""
    assert set(importing.NEEDS_HUMAN_CATEGORIES) == set(
        hermes_running.NEEDS_HUMAN_REASONS
    )


def test_retry_recommended_is_read_off_the_error_class() -> None:
    assert importing.retry_recommended(Category.RATE_LIMIT) is True
    assert importing.retry_recommended(Category.UNSUPPORTED) is False
    # The three "per instance" rows are `19`'s `retry=unknown`.
    assert importing.retry_recommended(Category.UI) is None


@pytest.mark.parametrize(
    ("short_id", "attempt", "expected"),
    [
        ("aa000001", 1, "aa000001-1"),
        ("../evil", 2, "evil-2"),
        ("...", 3, "conversation-3"),
    ],
)
def test_run_id_for(short_id: str, attempt: int, expected: str) -> None:
    """The id becomes three filenames, so it is built rather than trusted."""
    assert importing.run_id_for(short_id, attempt) == expected


# --------------------------------------------------------------------------- #
# Through the command
# --------------------------------------------------------------------------- #


def test_import_exits_0_and_prints_the_counters(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli_env(world, monkeypatch)

    outcome = runner.invoke(
        cli.app, ["import", str(world.export), "--limit", "1"], catch_exceptions=False
    )

    assert outcome.exit_code == ExitCode.OK
    assert outcome.stdout.splitlines()[0] == "aa000001  completed  (2/6)"
    assert world.entry(FIRST).status is Status.COMPLETED


def test_import_quiet_still_prints_the_final_block(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli_env(world, monkeypatch)

    outcome = runner.invoke(
        cli.app,
        ["-q", "import", str(world.export), "--limit", "1"],
        catch_exceptions=False,
    )

    assert "aa000001" not in outcome.stdout
    assert outcome.stdout.startswith("Completed:  1\n")


def test_import_exits_1_when_a_conversation_did_not_make_it(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli_env(world, monkeypatch)
    world.answers(result(outcome="failed", error={"category": "ui", "detail": "x"}))

    outcome = runner.invoke(
        cli.app, ["import", str(world.export), "--limit", "1"], catch_exceptions=False
    )

    assert outcome.exit_code == ExitCode.FAILED


def test_import_exits_3_when_the_session_is_signed_out(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli_env(world, monkeypatch)
    world.page.composer = None

    outcome = runner.invoke(
        cli.app, ["import", str(world.export), "--limit", "1"], catch_exceptions=False
    )

    assert outcome.exit_code == ExitCode.NOT_AUTHENTICATED
    assert outcome.stderr == (
        "error: not logged in — run: hermes-claude-migrate login\n"
    )


def test_import_exits_4_when_there_is_nothing_to_do(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli_env(world, monkeypatch)
    world.run()

    outcome = runner.invoke(
        cli.app, ["import", str(world.export)], catch_exceptions=False
    )

    assert outcome.exit_code == ExitCode.NOTHING_TO_DO


def test_the_run_log_holds_no_content(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§10 again, for the file the terminal is not."""
    cli_env(world, monkeypatch)
    runner.invoke(
        cli.app, ["import", str(world.export), "--limit", "2"], catch_exceptions=False
    )

    logs = sorted((world.settings.workspace / "logs").glob("run-*.jsonl"))
    assert logs
    written = "\n".join(path.read_text(encoding="utf-8") for path in logs)
    for phrase in CONTENT:
        assert phrase not in written


def test_selection_is_recorded_in_run_json(world: World) -> None:
    """`19` says why a conversation was not touched without re-deriving it."""
    world.run(limit=2, only=[FIRST])

    selection = world.store().run().runs[0].selection
    assert selection.only == [FIRST]
    assert selection.limit == 2
    assert selection.uuids == [FIRST]


def test_an_unknown_only_is_a_selection_error(world: World) -> None:
    with pytest.raises(state.SelectionError):
        world.run(only=["nope"])


def test_line_progress_counts_done_against_the_total(
    capsys: pytest.CaptureFixture[str],
) -> None:
    counts = {"total": 127, "completed": 89, "partial": 1, "failed": 1, "pending": 36}
    importing.LineProgress().conversation("3f9c2a1e", Status.COMPLETED, counts)
    assert capsys.readouterr().out == "3f9c2a1e  completed  (91/127)\n"
