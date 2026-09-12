"""Migration state: the §7 file, `run.json`, the lock, and selection.

The properties worth testing here are the ones a killed run depends on: that a
write is all-or-nothing, that a `running` entry left behind by a crash becomes
something a later run can act on, that two runs cannot share a workspace, and
that `state.json` holds exactly what §7 says and nothing else.
"""

import json
import os
import signal
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dataporter import cli, state
from dataporter.errors import Category
from dataporter.exit_codes import ExitCode
from dataporter.state import (
    ConversationState,
    Destination,
    ErrorRecord,
    MigrationState,
    Selection,
    StateStore,
    Status,
    WorkspaceLock,
)
from dataporter.steps import Step

FIXTURES = Path(__file__).parent / "fixtures"

ORDER = [
    "aa000001-1111-4111-8111-111111111111",
    "bb000002-2222-4222-8222-222222222222",
    "cc000003-3333-4333-8333-333333333333",
    "dd000004-4444-4444-8444-444444444444",
]

SPEC_KEYS = [
    "title",
    "status",
    "destination",
    "attempts",
    "last_step",
    "chunks_acked",
    "chunks_total",
    "messages_represented",
    "attachments",
    "error",
    "limitations",
    "verified_at",
    "updated_at",
]
"""Every key `06` allows in an entry, in the order the spec writes them. Written
out rather than derived from the model, so a field added without a spec change
fails here."""


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def state_with(**statuses: Status) -> MigrationState:
    """A state built from `short id → status`, in the order given."""
    return MigrationState(
        root={
            uuid: ConversationState(status=status)
            for uuid, status in (
                (next(item for item in ORDER if item.startswith(short)), status)
                for short, status in statuses.items()
            )
        }
    )


def run(runner: CliRunner, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(cli.app, list(args), catch_exceptions=False)
    return result.exit_code, result.stdout, result.stderr


# --------------------------------------------------------------------------- #
# The file, and how it is written
# --------------------------------------------------------------------------- #


def test_an_entry_carries_exactly_the_keys_the_spec_lists(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.update(ORDER[0], title="Listing files", status=Status.RUNNING)
    entry = read(store.state_path)[ORDER[0]]
    assert list(entry) == SPEC_KEYS


def test_the_file_is_keyed_by_source_conversation_id_in_insertion_order(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path)
    for uuid in reversed(ORDER):
        store.update(uuid, title="")
    assert list(read(store.state_path)) == list(reversed(ORDER))


def test_it_is_indented_and_newline_terminated(tmp_path: Path) -> None:
    """`06` asks for a file that is diffable by hand."""
    store = StateStore(tmp_path)
    store.update(ORDER[0], title="")
    text = store.state_path.read_text(encoding="utf-8")
    assert text.startswith("{\n  ")
    assert text.endswith("}\n")


def test_updated_at_is_stamped_on_every_write_as_zulu_seconds(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.update(ORDER[0], title="")
    stamp = read(store.state_path)[ORDER[0]]["updated_at"]
    assert stamp.endswith("Z") and "+00:00" not in stamp
    assert len(stamp) == len("2026-09-10T14:03:11Z")


def test_destination_is_null_until_it_is_known(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.update(ORDER[0], title="")
    assert read(store.state_path)[ORDER[0]]["destination"] == {"conversation_id": None}


def test_an_unknown_key_is_refused_on_the_way_in(tmp_path: Path) -> None:
    """The §7 shape is closed: `extra="forbid"` is the schema."""
    store = StateStore(tmp_path)
    store.update(ORDER[0], title="")
    payload = read(store.state_path)
    payload[ORDER[0]]["notes"] = "hand-edited"
    store.state_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(state.StateError, match="invalid state.json"):
        StateStore(tmp_path).load()


def test_an_unknown_status_is_refused(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    with pytest.raises(state.IllegalUpdate):
        store.update(ORDER[0], status="finished")


def test_a_malformed_state_file_is_reported_not_guessed_at(tmp_path: Path) -> None:
    (tmp_path / state.STATE_FILENAME).write_text("{oh no", encoding="utf-8")
    with pytest.raises(state.StateError, match="not valid JSON"):
        StateStore(tmp_path).load()


def test_a_state_file_that_cannot_be_read_at_all_is_reported(tmp_path: Path) -> None:
    """Not every unreadable file is unparsable; the message says which it was."""
    (tmp_path / state.STATE_FILENAME).mkdir()
    with pytest.raises(state.StateError, match="cannot read"):
        StateStore(tmp_path).load()


def test_a_naive_timestamp_is_read_as_utc(tmp_path: Path) -> None:
    """Every timestamp this tool writes is UTC, so that is what a naive one is."""
    entry = ConversationState(updated_at=datetime(2026, 9, 10, 14, 3, 11))
    assert entry.updated_at.tzinfo is UTC
    assert json.loads(entry.model_dump_json())["updated_at"] == "2026-09-10T14:03:11Z"


def test_the_state_answers_the_questions_a_dict_does(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.update(ORDER[0], title="Listing files")
    migration = store.load()
    assert ORDER[0] in migration
    assert ORDER[1] not in migration
    assert migration[ORDER[0]].title == "Listing files"
    assert migration.get(ORDER[1]) is None
    assert len(migration) == 1


def test_no_message_body_reaches_the_state_file(tmp_path: Path) -> None:
    """Titles are stored because §7 shows them. Nothing else from the export is."""
    conversations = json.loads(
        (FIXTURES / "export-small" / "conversations.json").read_text(encoding="utf-8")
    )
    store = StateStore(tmp_path)
    for conversation in conversations:
        store.update(
            conversation["uuid"],
            title=conversation["name"],
            status=Status.RUNNING,
            messages_represented=len(conversation["chat_messages"]),
        )
    written = store.state_path.read_text(encoding="utf-8")
    bodies = [
        message["text"]
        for conversation in conversations
        for message in conversation["chat_messages"]
        if message.get("text")
    ]
    assert bodies
    assert [body for body in bodies if body[:40] in written] == []


def test_every_mutation_goes_through_a_tmp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replaced: list[tuple[str, str]] = []
    original = os.replace

    def record(src: Any, dst: Any) -> None:
        replaced.append((str(src), str(dst)))
        original(src, dst)

    monkeypatch.setattr(os, "replace", record)
    store = StateStore(tmp_path)
    store.update(ORDER[0], title="")
    store.bump_counter("retries")
    assert replaced == [
        (f"{store.state_path}{state.TMP_SUFFIX}", str(store.state_path)),
        (f"{store.run_path}{state.TMP_SUFFIX}", str(store.run_path)),
    ]


def test_the_directory_entry_is_flushed_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flushing the file's bytes is half of it: without the directory, a power
    loss can leave the new contents on disk under the old name."""
    synced: list[int] = []
    original = os.fsync

    def record(fd: int) -> None:
        synced.append(os.fstat(fd).st_ino)
        original(fd)

    monkeypatch.setattr(os, "fsync", record)
    store = StateStore(tmp_path)
    store.update(ORDER[0], title="")
    assert os.stat(tmp_path).st_ino in synced
    assert os.stat(store.state_path).st_ino in synced


@pytest.mark.skipif(not hasattr(os, "fork"), reason="POSIX only")
def test_a_kill_between_tmp_and_replace_leaves_the_previous_file(
    tmp_path: Path,
) -> None:
    """The acceptance criterion: SIGKILL mid-write, and the old file still parses."""
    store = StateStore(tmp_path)
    store.update(ORDER[0], title="first", chunks_total=1)
    before = store.state_path.read_bytes()

    child = os.fork()
    if child == 0:  # pragma: no cover - the child is killed, never measured
        try:
            os.replace = lambda *_: os.kill(os.getpid(), signal.SIGKILL)
            store.update(ORDER[0], chunks_total=2)
        finally:
            os._exit(1)
    _, status = os.waitpid(child, 0)

    assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
    assert store.state_path.read_bytes() == before
    assert read(store.state_path)[ORDER[0]]["chunks_total"] == 1
    # The temporary file is what the kill interrupted, so it is there and it is
    # the *new* content: proof the process died between the write and the swap.
    tmp = store.state_path.with_name(state.STATE_FILENAME + state.TMP_SUFFIX)
    assert read(tmp)[ORDER[0]]["chunks_total"] == 2


# --------------------------------------------------------------------------- #
# Updating
# --------------------------------------------------------------------------- #


def test_update_creates_an_entry_that_is_not_there_yet(tmp_path: Path) -> None:
    entry = StateStore(tmp_path).update(ORDER[0], title="Listing files")
    assert entry.status is Status.PENDING
    assert entry.attempts == 0


def test_ensure_leaves_an_existing_entry_alone(tmp_path: Path) -> None:
    """`12` re-creates every planned conversation on every run; a resume must not
    reset one that finished."""
    store = StateStore(tmp_path)
    store.update(ORDER[0], title="Listing files", status=Status.COMPLETED)
    kept = store.ensure(ORDER[0], title="Listing files")
    assert kept.status is Status.COMPLETED
    fresh = store.ensure(ORDER[1], title="Postgres questions")
    assert fresh.status is Status.PENDING


def test_an_update_merges_rather_than_replaces(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.update(ORDER[0], title="Listing files", status=Status.RUNNING, attempts=1)
    entry = store.update(ORDER[0], chunks_acked=2)
    assert (entry.title, entry.attempts, entry.chunks_acked) == ("Listing files", 1, 2)


def test_the_store_reads_back_what_it_wrote(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.update(
        ORDER[0],
        title="Listing files",
        status=Status.RUNNING,
        destination=Destination(conversation_id="9b1f"),
        error=ErrorRecord(category=Category.GENERATION, detail="no response"),
        limitations=["thinking_omitted:3"],
    )
    entry = StateStore(tmp_path).load()[ORDER[0]]
    assert entry.destination.conversation_id == "9b1f"
    assert entry.error is not None
    assert entry.error.category is Category.GENERATION
    assert entry.error.retry_recommended is None
    assert entry.limitations == ["thinking_omitted:3"]


# --------------------------------------------------------------------------- #
# Transitions and crash recovery
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "old, new",
    [
        (Status.PENDING, Status.RUNNING),
        (Status.RUNNING, Status.COMPLETED),
        (Status.RUNNING, Status.PARTIAL),
        (Status.RUNNING, Status.FAILED),
        (Status.RUNNING, Status.PENDING),
        (Status.PARTIAL, Status.RUNNING),
        (Status.FAILED, Status.RUNNING),
        (Status.COMPLETED, Status.RUNNING),
    ],
)
def test_the_spec_table_is_what_is_allowed(
    tmp_path: Path, old: Status, new: Status
) -> None:
    store = StateStore(tmp_path)
    store.update(ORDER[0], status=old)
    assert store.update(ORDER[0], status=new).status is new


def test_a_status_may_stay_where_it_is(tmp_path: Path) -> None:
    """Most updates carry a step or a count and no status at all."""
    store = StateStore(tmp_path)
    store.update(ORDER[0], status=Status.RUNNING)
    assert store.update(ORDER[0], last_step="submit").status is Status.RUNNING


def test_a_step_that_is_not_one_cannot_be_recorded(tmp_path: Path) -> None:
    """`11` fixed the vocabulary, and an agent reports its own `last_step`.

    `12` maps a result to a `Step` before it writes; a name it could not map —
    `10`'s throwaway prompt invented `await_response_part_2` — must not become
    the "last successful step" `19` prints.
    """
    store = StateStore(tmp_path)
    with pytest.raises(state.IllegalUpdate):
        store.update(ORDER[0], last_step="await_response_part_2")
    assert store.update(ORDER[0], last_step=Step.AWAIT).last_step is Step.AWAIT


@pytest.mark.parametrize(
    "old, new",
    [
        (Status.PENDING, Status.COMPLETED),
        (Status.COMPLETED, Status.FAILED),
        (Status.FAILED, Status.COMPLETED),
        (Status.PARTIAL, Status.PENDING),
    ],
)
def test_a_transition_outside_the_table_is_an_internal_error(
    tmp_path: Path, old: Status, new: Status
) -> None:
    """A `ValueError`, not a `StateError`: no operator input can cause one, so it
    is exit `70` rather than a message telling them to fix something."""
    store = StateStore(tmp_path)
    store.update(ORDER[0], status=old)
    with pytest.raises(state.IllegalTransition):
        store.update(ORDER[0], status=new)


def test_a_running_entry_with_a_destination_becomes_partial(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.update(
        ORDER[0],
        status=Status.RUNNING,
        attempts=2,
        destination=Destination(conversation_id="9b1f"),
    )
    assert StateStore(tmp_path).recover() == [ORDER[0]]
    entry = StateStore(tmp_path).load()[ORDER[0]]
    assert entry.status is Status.PARTIAL
    assert entry.attempts == 2  # kept: a run that died twice tried twice
    assert entry.destination.conversation_id == "9b1f"


def test_a_running_entry_without_a_destination_becomes_pending(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.update(ORDER[0], status=Status.RUNNING, attempts=1)
    store.recover()
    assert store.load()[ORDER[0]].status is Status.PENDING
    assert store.load()[ORDER[0]].attempts == 1


def test_recovery_counts_what_it_converted(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.update(ORDER[0], status=Status.RUNNING)
    store.update(ORDER[1], status=Status.RUNNING)
    store.update(ORDER[2], status=Status.COMPLETED)
    assert len(store.recover()) == 2
    assert store.run().interrupted == 2
    assert store.load()[ORDER[2]].status is Status.COMPLETED


def test_recovery_writes_nothing_when_there_was_no_crash(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.update(ORDER[0], status=Status.COMPLETED)
    assert store.recover() == []
    assert not store.run_path.exists()


# --------------------------------------------------------------------------- #
# run.json
# --------------------------------------------------------------------------- #


def test_counters_start_at_zero_and_bump(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    assert store.run().counters() == {name: 0 for name in state.COUNTERS}
    assert store.bump_counter("retries") == 1
    assert store.bump_counter("browser_actions", 12) == 12
    assert StateStore(tmp_path).run().retries == 1


def test_an_unknown_counter_is_refused(tmp_path: Path) -> None:
    """A typo would otherwise count nothing and `19` would report a zero."""
    with pytest.raises(ValueError, match="unknown counter"):
        StateStore(tmp_path).bump_counter("retrys")


def test_a_run_is_appended_when_it_starts_and_closed_when_it_ends(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path)
    index = store.start_run(Selection(limit=10, uuids=[ORDER[0]]))
    assert store.run().runs[index].ended is None
    store.finish_run(index, int(ExitCode.OK))
    record = StateStore(tmp_path).run().runs[index]
    assert record.ended is not None
    assert record.exit_code == 0
    assert record.selection.uuids == [ORDER[0]]


def test_the_state_file_keeps_its_shape_because_run_data_lives_next_door(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path)
    store.update(ORDER[0], title="")
    store.bump_counter("retries")
    store.start_run(Selection())
    assert list(read(store.state_path)) == [ORDER[0]]
    assert "schema_version" in read(store.run_path)


def test_a_forced_rerun_remembers_the_chat_it_leaves_behind(tmp_path: Path) -> None:
    """`--force` never deletes anything at the destination (§17)."""
    store = StateStore(tmp_path)
    store.remember_destination(ORDER[0], "9b1f")
    store.remember_destination(ORDER[0], "9b1f")
    store.remember_destination(ORDER[0], "c33e")
    assert store.run().previous_destinations == {ORDER[0]: ["9b1f", "c33e"]}


def test_a_pause_record_round_trips(tmp_path: Path) -> None:
    """`14` writes it; `06` only promises the field is there and is nullable."""
    store = StateStore(tmp_path)
    store.set_paused(
        state.PauseRecord(
            conversation_uuid=ORDER[0],
            reason="auth_required",
            detail="sign-in form shown at /login",
            last_step="open",
            since=state.now(),
        )
    )
    paused = StateStore(tmp_path).run().paused
    assert paused is not None and paused.reason == "auth_required"
    store.set_paused(None)
    assert StateStore(tmp_path).run().paused is None


def test_a_workspace_from_another_export_is_refused(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.bind_export("aaaa")
    with pytest.raises(state.FingerprintMismatch, match="different export"):
        StateStore(tmp_path).check_export("bbbb")


def test_binding_the_same_export_twice_is_fine(tmp_path: Path) -> None:
    StateStore(tmp_path).bind_export("aaaa")
    StateStore(tmp_path).bind_export("aaaa")
    assert StateStore(tmp_path).run().export_fingerprint == "aaaa"


def test_a_fresh_workspace_belongs_to_no_export_yet(tmp_path: Path) -> None:
    StateStore(tmp_path).check_export("aaaa")  # no record, nothing to contradict


def test_a_run_file_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    (tmp_path / state.RUN_FILENAME).write_text("[]", encoding="utf-8")
    with pytest.raises(state.StateError, match="not a JSON object"):
        StateStore(tmp_path).run()


def test_a_run_file_of_the_right_version_but_the_wrong_shape_is_refused(
    tmp_path: Path,
) -> None:
    (tmp_path / state.RUN_FILENAME).write_text(
        json.dumps({"schema_version": state.SCHEMA_VERSION, "retries": "many"}),
        encoding="utf-8",
    )
    with pytest.raises(state.StateError, match="invalid run.json"):
        StateStore(tmp_path).run()


def test_a_future_schema_version_stops_the_run(tmp_path: Path) -> None:
    """`06`'s risk: a schema change after real runs exist would strand operators."""
    (tmp_path / state.RUN_FILENAME).write_text(
        json.dumps({"schema_version": state.SCHEMA_VERSION + 1, "unknown": []}),
        encoding="utf-8",
    )
    with pytest.raises(state.SchemaMismatch, match="migrate the workspace"):
        StateStore(tmp_path).run()


# --------------------------------------------------------------------------- #
# The lock
# --------------------------------------------------------------------------- #

HOLD_THE_LOCK = """
import sys
from pathlib import Path
from dataporter.state import WorkspaceLock

lock = WorkspaceLock(Path(sys.argv[1])).acquire()
print("ready", flush=True)
sys.stdin.readline()
lock.release()
"""


@pytest.mark.slow
def test_a_second_run_on_one_workspace_is_refused(tmp_path: Path) -> None:
    """The acceptance criterion, with a real second process holding the lock.

    `slow` by hand: it spawns a Python interpreter, and neither the fixture rule
    nor the fake-construction guard can see that — the only two tests in the fast
    modules that reach for a subprocess are this one and the one below.
    """
    child = subprocess.Popen(
        [sys.executable, "-c", HOLD_THE_LOCK, str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None and child.stdin is not None
        assert child.stdout.readline() == "ready\n"
        with pytest.raises(state.WorkspaceLocked) as caught:
            WorkspaceLock(tmp_path).acquire()
        assert str(caught.value).startswith(f"workspace locked by pid {child.pid} ")
        assert str(caught.value).endswith(
            " — use --force-unlock if that process is gone"
        )
        child.stdin.write("\n")
        child.stdin.close()
        assert child.wait(timeout=10) == 0
    finally:
        child.kill()
    # Released on the child's way out, so the workspace is usable again.
    WorkspaceLock(tmp_path).acquire().release()


def test_the_locked_message_names_the_pid_and_the_time(tmp_path: Path) -> None:
    held = WorkspaceLock(tmp_path).acquire()
    info = held.read()
    assert info is not None
    with pytest.raises(state.WorkspaceLocked) as caught:
        WorkspaceLock(tmp_path).acquire()
    assert str(caught.value) == (
        f"workspace locked by pid {os.getpid()} since "
        f"{info.started:%H:%M:%S} — use --force-unlock if that process is gone"
    )


def test_the_lock_is_released_on_the_way_out_of_the_context(tmp_path: Path) -> None:
    with WorkspaceLock(tmp_path) as lock:
        assert lock.path.exists()
    assert not lock.path.exists()


@pytest.mark.slow
def test_force_unlock_removes_a_lock_whose_process_is_gone(tmp_path: Path) -> None:
    """`slow` by hand, for the reason the test above is."""
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (tmp_path / state.LOCK_FILENAME).write_text(
        json.dumps({"pid": dead.pid, "started": "2026-09-10T14:01:07Z"}),
        encoding="utf-8",
    )
    WorkspaceLock(tmp_path).acquire(force_unlock=True).release()


def test_force_unlock_refuses_a_lock_somebody_is_still_using(tmp_path: Path) -> None:
    """Breaking a live lock would let two runs write one workspace, which is the
    one thing the lock exists to prevent."""
    WorkspaceLock(tmp_path).acquire()
    with pytest.raises(state.WorkspaceLocked, match="still running"):
        WorkspaceLock(tmp_path).acquire(force_unlock=True)


def test_an_unreadable_lock_file_can_be_broken(tmp_path: Path) -> None:
    (tmp_path / state.LOCK_FILENAME).write_text("not json", encoding="utf-8")
    with pytest.raises(state.WorkspaceLocked, match="unreadable"):
        WorkspaceLock(tmp_path).acquire()
    WorkspaceLock(tmp_path).acquire(force_unlock=True).release()


def test_releasing_a_lock_we_do_not_hold_removes_nothing(tmp_path: Path) -> None:
    held = WorkspaceLock(tmp_path).acquire()
    WorkspaceLock(tmp_path).release()  # never acquired, so not ours to remove
    assert held.path.exists()
    held.release()


def test_a_free_workspace_has_no_lock_holder(tmp_path: Path) -> None:
    assert WorkspaceLock(tmp_path).read() is None
    WorkspaceLock(tmp_path).acquire(force_unlock=True).release()


def test_a_pid_that_is_not_a_pid_is_not_alive() -> None:
    assert not state.process_alive(0)
    assert state.process_alive(os.getpid())


def test_a_process_owned_by_another_user_is_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`os.kill(pid, 0)` says `EPERM` for a live process we may not signal.
    Reading that as "gone" would let `--force-unlock` break somebody's lock."""

    def refuse(pid: int, signal_number: int) -> None:
        raise PermissionError

    monkeypatch.setattr(os, "kill", refuse)
    assert state.process_alive(os.getpid())


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #


def test_pending_is_the_default_selection() -> None:
    chosen = state.select(ORDER, state_with(aa=Status.COMPLETED), Selection())
    assert chosen == ORDER[1:]  # entries with no record at all are pending


def test_retry_failed_selects_only_failed() -> None:
    migration = state_with(
        aa=Status.COMPLETED, bb=Status.FAILED, cc=Status.PARTIAL, dd=Status.COMPLETED
    )
    assert state.select(ORDER, migration, Selection(retry_failed=True)) == [ORDER[1]]


def test_retry_partial_adds_partial_and_force_adds_completed() -> None:
    migration = state_with(aa=Status.COMPLETED, bb=Status.FAILED, cc=Status.PARTIAL)
    assert state.select(ORDER, migration, Selection(retry_partial=True)) == [
        ORDER[2],
        ORDER[3],
    ]
    assert state.select(ORDER, migration, Selection(force=True)) == [
        ORDER[0],
        ORDER[3],
    ]


def test_a_running_entry_is_not_selected_until_recovery_converts_it() -> None:
    """Recovery runs at startup, so by selection time there are none left."""
    assert state.select(ORDER[:1], state_with(aa=Status.RUNNING), Selection()) == []


def test_only_accepts_a_short_id() -> None:
    assert state.select(ORDER, MigrationState(), Selection(only=["cc000003"])) == [
        ORDER[2]
    ]


def test_only_accepts_a_full_uuid_and_keeps_export_order() -> None:
    chosen = state.select(
        ORDER, MigrationState(), Selection(only=[ORDER[3], "aa000001"])
    )
    assert chosen == [ORDER[0], ORDER[3]]


def test_only_ignores_status_because_it_names_the_conversations() -> None:
    migration = state_with(aa=Status.COMPLETED)
    assert state.select(ORDER, migration, Selection(only=["aa000001"])) == [ORDER[0]]


def test_an_unknown_only_value_is_a_mistake_not_an_empty_selection() -> None:
    with pytest.raises(state.SelectionError, match="conversation not in export: nope"):
        state.select(ORDER, MigrationState(), Selection(only=["nope"]))


def test_an_ambiguous_short_id_is_refused() -> None:
    twins = ["aa000001-1111-4111-8111-111111111111", "aa000001-2222-4222-8222-2"]
    with pytest.raises(state.SelectionError, match="ambiguous"):
        state.select(twins, MigrationState(), Selection(only=["aa000001"]))


def test_limit_truncates_in_export_order() -> None:
    assert state.select(ORDER, MigrationState(), Selection(limit=1)) == [ORDER[0]]


def test_limit_applies_after_only() -> None:
    """`--only` picks which, `--limit` picks how many."""
    chosen = state.select(
        ORDER, MigrationState(), Selection(only=[ORDER[2], ORDER[1]], limit=1)
    )
    assert chosen == [ORDER[1]]


def test_a_negative_limit_is_refused() -> None:
    with pytest.raises(state.SelectionError, match="must not be negative"):
        state.select(ORDER, MigrationState(), Selection(limit=-1))


# --------------------------------------------------------------------------- #
# Counting
# --------------------------------------------------------------------------- #


def test_pending_is_everything_that_is_not_done() -> None:
    """`18`'s rule. A `running` entry counts as pending rather than as nothing."""
    counts = state.status_counts(
        state_with(aa=Status.COMPLETED, bb=Status.RUNNING, cc=Status.FAILED)
    )
    assert counts == {
        "total": 3,
        "completed": 1,
        "partial": 0,
        "failed": 1,
        "pending": 1,
    }


# --------------------------------------------------------------------------- #
# `status`
# --------------------------------------------------------------------------- #


def seed_state(workspace: Path, statuses: Sequence[Status]) -> None:
    """Write a whole `state.json` in one go.

    `update` per entry is what a run does; a test that only cares about the
    counters does not need 127 whole-file writes to get them.
    """
    migration = MigrationState(
        root={
            f"uuid-{index:04d}": ConversationState(status=status)
            for index, status in enumerate(statuses)
        }
    )
    state.write_atomically(
        workspace / state.STATE_FILENAME, migration.model_dump_json(indent=2) + "\n"
    )


def test_status_prints_the_counters_block(runner: CliRunner, workspace: Path) -> None:
    """The brief's own §10 numbers: 89 / 1 / 1 of 127."""
    seed_state(
        workspace / "migration",
        [Status.COMPLETED] * 89
        + [Status.PARTIAL, Status.FAILED]
        + [Status.PENDING] * 36,
    )
    code, out, _ = run(runner, "status")
    assert code == ExitCode.OK
    assert out == "Completed: 89\nPartial:    1\nFailed:     1\nPending:   36\n"


def test_status_widens_every_line_together(runner: CliRunner, workspace: Path) -> None:
    seed_state(workspace / "migration", [Status.COMPLETED] * 1234)
    _, out, _ = run(runner, "status")
    assert out.splitlines()[0] == "Completed: 1,234"
    assert {len(line) for line in out.splitlines()} == {len("Completed: 1,234")}


def test_status_on_a_workspace_nothing_has_run_in_is_zeros(
    runner: CliRunner, workspace: Path
) -> None:
    """`status` answers a question; "nothing has happened here" is an answer."""
    code, out, _ = run(runner, "status")
    assert code == ExitCode.OK
    assert out == "Completed:  0\nPartial:    0\nFailed:     0\nPending:    0\n"


def test_status_prints_no_title(runner: CliRunner, workspace: Path) -> None:
    StateStore(workspace / "migration").update(ORDER[0], title="Listing files")
    _, out, err = run(runner, "status")
    assert "Listing files" not in out + err


def test_status_json_is_the_state_file_plus_the_run_counters(
    runner: CliRunner, workspace: Path
) -> None:
    store = StateStore(workspace / "migration")
    store.update(ORDER[0], title="Listing files", status=Status.RUNNING)
    store.update(ORDER[0], status=Status.COMPLETED)
    store.bump_counter("retries", 17)
    code, out, _ = run(runner, "status", "--json")
    assert code == ExitCode.OK
    payload = json.loads(out)
    assert payload["state"] == read(store.state_path)
    assert payload["counters"] == {
        "total": 1,
        "completed": 1,
        "partial": 0,
        "failed": 0,
        "pending": 0,
        "browser_actions": 0,
        "retries": 17,
        "rate_limit_waits": 0,
        "human_interventions": 0,
        "auto_signins": 0,
        "interrupted": 0,
    }


def test_status_reports_a_schema_mismatch_as_exit_2(
    runner: CliRunner, workspace: Path
) -> None:
    target = workspace / "migration"
    target.mkdir()
    (target / state.RUN_FILENAME).write_text(
        json.dumps({"schema_version": 99}), encoding="utf-8"
    )
    code, _, err = run(runner, "status")
    assert code == ExitCode.USAGE
    assert err.startswith("error: workspace was written with state schema 99")


def test_status_writes_nothing(runner: CliRunner, workspace: Path) -> None:
    run(runner, "status")
    assert not (workspace / "migration").exists()


# --------------------------------------------------------------------------- #
# Selection, through `import --dry-run`
# --------------------------------------------------------------------------- #


def test_a_dry_run_counts_only_what_this_run_would_do(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    store = StateStore(workspace / "migration")
    for uuid in ORDER[:3]:
        store.update(uuid, status=Status.RUNNING)
        store.update(uuid, status=Status.COMPLETED)
    _, out, _ = run(runner, "import", str(export_dir), "--dry-run")
    assert out.startswith("Conversations found:      3\n")


def test_the_retry_flags_widen_a_dry_run_once_there_is_state(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    store = StateStore(workspace / "migration")
    for uuid in ORDER:
        store.update(uuid, status=Status.RUNNING)
    for uuid, status in zip(ORDER, [Status.COMPLETED] * 3 + [Status.FAILED]):
        store.update(uuid, status=status)
    # Two of the fixture's six were never attempted; the failed one joins them.
    _, plain, _ = run(runner, "import", str(export_dir), "--dry-run")
    assert plain.startswith("Conversations found:      2\n")
    _, widened, _ = run(
        runner, "import", str(export_dir), "--dry-run", "--retry-failed"
    )
    assert widened.startswith("Conversations found:      3\n")


def test_everything_completed_and_no_force_is_exit_4(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    store = StateStore(workspace / "migration")
    for conversation in json.loads(
        (export_dir / "conversations.json").read_text(encoding="utf-8")
    ):
        store.update(conversation["uuid"], status=Status.RUNNING)
        store.update(conversation["uuid"], status=Status.COMPLETED)
    code, out, _ = run(runner, "import", str(export_dir), "--dry-run")
    assert code == ExitCode.NOTHING_TO_DO
    assert out == ""


def test_the_default_limit_is_run_max_conversations(
    runner: CliRunner,
    workspace: Path,
    export_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HCM_RUN__MAX_CONVERSATIONS", "2")
    _, out, _ = run(runner, "import", str(export_dir), "--dry-run")
    assert out.startswith("Conversations found:      2\n")


def test_a_dry_run_against_another_export_is_exit_2(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    StateStore(workspace / "migration").bind_export("not-this-export")
    code, _, err = run(runner, "import", str(export_dir), "--dry-run")
    assert code == ExitCode.USAGE
    assert err == "error: workspace belongs to a different export\n"


def test_a_dry_run_still_writes_nothing(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    """§9: no account is modified, and no workspace appears next to the export."""
    code, _, _ = run(runner, "import", str(export_dir), "--dry-run")
    assert code == ExitCode.OK
    assert not (workspace / "migration").exists()


def test_seeds_accepts_a_short_id_too(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    """One resolver for every `--only`, so the two commands cannot drift."""
    code, out, _ = run(runner, "seeds", str(export_dir), "--only", "aa000001")
    assert code == ExitCode.OK
    assert out.startswith("aa000001  parts=")


# --------------------------------------------------------------------------- #
# Hermes usage (`09`)
# --------------------------------------------------------------------------- #


def test_usage_accumulates_across_runs(workspace: Path) -> None:
    store = state.StateStore(workspace)
    store.add_usage(input_tokens=1200, output_tokens=300, cost_usd=0.04)
    run = store.add_usage(input_tokens=800, output_tokens=120, cost_usd=0.015)
    assert run.hermes_input_tokens == 2000
    assert run.hermes_output_tokens == 420
    assert run.hermes_cost_usd == pytest.approx(0.055)
    # And it is on disk, not only in memory: `19` reads the file.
    assert state.StateStore(workspace).run().hermes_input_tokens == 2000


def test_usage_is_not_one_of_the_counters(workspace: Path) -> None:
    """A cost is not a count, and `status --json` reports counts."""
    assert "hermes_cost_usd" not in state.COUNTERS
    assert set(state.StateStore(workspace).run().counters()) == set(state.COUNTERS)
