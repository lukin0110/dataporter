"""Migration state: the §7 file, the run record beside it, and the lock over both.

Three files in the workspace, each with one job:

- `state.json` — §7's object, keyed by source conversation id. Nothing else goes in
  it, so it can be validated against the brief's shape with no exceptions and read
  by hand.
- `run.json` — everything that is about the *run* rather than about a conversation:
  schema version, which export the workspace belongs to, the runs so far, the
  counters `19` reports, `14`'s pause record, and the destination ids `--force`
  replaced.
- `.lock` — a pid and a start time, taken with `O_EXCL`. Two runs on one workspace
  would interleave whole-file writes and lose each other's entries.

Every mutation writes the whole file to `<name>.tmp` and then `os.replace`s it, so
a crash leaves either the previous file or the new one and never a half-written
one. That is also why the store keeps the state in memory: the lock makes this
process the only writer, so the copy on disk cannot drift from the copy here.

Nothing in this module may log a title, and `state.json` is the only place one is
written: §7 puts it there, §10 keeps it off stdout, and `log.FORBIDDEN_FIELDS`
keeps it out of the log.
"""

import json
import os
from collections.abc import ItemsView, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Annotated, Any, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    RootModel,
    ValidationError,
)

from dataporter import log, render
from dataporter.errors import Category

_logger = log.get_logger(__name__)

STATE_FILENAME = "state.json"
RUN_FILENAME = "run.json"
LOCK_FILENAME = ".lock"
TMP_SUFFIX = ".tmp"

SCHEMA_VERSION = 1
"""`run.json`'s version, checked at startup.

A change to `state.json`'s shape after real runs exist would strand whoever is
mid-migration, so a mismatch stops the run and says what to do rather than
guessing at the older or newer shape.
"""

COUNTERS: tuple[str, ...] = (
    "browser_actions",
    "retries",
    "human_interventions",
    "interrupted",
)
"""The names `bump_counter` accepts. A typo would otherwise count nothing,
silently, and `19` would report a zero that looks like a fact."""


# --------------------------------------------------------------------------- #
# Failures an operator can fix
# --------------------------------------------------------------------------- #


class StateError(Exception):
    """The workspace cannot be used as asked. The CLI reports this as exit `2`."""


class WorkspaceLocked(StateError):
    """Another run holds the lock."""


class FingerprintMismatch(StateError):
    """The workspace belongs to a different export."""


class SchemaMismatch(StateError):
    """`run.json` was written by a build with a different state schema."""


class SelectionError(StateError):
    """`--only` named something that is not in the export, or is ambiguous."""


class IllegalTransition(ValueError):
    """A status moved somewhere the §7 table does not allow.

    A `ValueError` rather than a `StateError`: no operator input produces one, so
    it is an internal invariant, and exit `70` is where those belong.
    """


class IllegalUpdate(ValueError):
    """An entry was updated with a field it does not have, or a value it cannot
    hold. Ours too: every caller of `StateStore.update` is our own code."""


# --------------------------------------------------------------------------- #
# Instants
# --------------------------------------------------------------------------- #


def _to_utc(value: datetime) -> datetime:
    """UTC, whole seconds. A naive value is read as UTC rather than as local time:
    every timestamp this tool writes is UTC, so that is what a naive one is."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0)


def _format_instant(value: datetime) -> str:
    """`2026-09-10T14:03:11Z`, exactly as §7's example writes it."""
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


Instant = Annotated[
    datetime,
    AfterValidator(_to_utc),
    PlainSerializer(_format_instant, return_type=str),
]
"""A UTC timestamp that round-trips through JSON as `…Z`, not `…+00:00`."""


def now() -> datetime:
    return _to_utc(datetime.now(UTC))


# --------------------------------------------------------------------------- #
# `state.json`
# --------------------------------------------------------------------------- #


class Status(StrEnum):
    """§7's five statuses, and no others."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


TRANSITIONS: dict[Status, frozenset[Status]] = {
    Status.PENDING: frozenset({Status.RUNNING}),
    # `pending` is crash recovery for an entry that never reached a chat.
    Status.RUNNING: frozenset(
        {Status.COMPLETED, Status.PARTIAL, Status.FAILED, Status.PENDING}
    ),
    # `completed` moves only under `--force`; selection is what enforces that,
    # because by the time a status changes the decision has already been made.
    Status.COMPLETED: frozenset({Status.RUNNING}),
    Status.PARTIAL: frozenset({Status.RUNNING}),
    Status.FAILED: frozenset({Status.RUNNING}),
}
"""The §7 transition table. Staying put is always allowed — most updates carry a
step or a count and no status at all."""

TERMINAL: frozenset[Status] = frozenset(
    {Status.COMPLETED, Status.PARTIAL, Status.FAILED}
)
"""The three `18` counts as done."""


def transition_allowed(old: Status, new: Status) -> bool:
    return old == new or new in TRANSITIONS[old]


class StateModel(BaseModel):
    """Base for everything written to the workspace: immutable, and closed.

    `extra="forbid"` is what makes the acceptance criterion — "a schema that
    allows only the keys listed" — a property of the code rather than of a test:
    an unexpected key in `state.json` is refused on the way in and impossible on
    the way out.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class Destination(StateModel):
    """Where the conversation landed. §7's third key."""

    conversation_id: str | None = None


class ErrorRecord(StateModel):
    """Why an entry is `failed` or `partial`. `19` prints it verbatim."""

    category: Category
    detail: str = ""
    retry_recommended: bool | None = None
    """`None` is `13`'s "unknown", which `19` renders as `retry=unknown`."""


class AttachmentCounts(StateModel):
    """What became of this conversation's files. §14's three classes."""

    uploaded: int = 0
    inline: int = 0
    unsupported: int = 0


class ConversationState(StateModel):
    """One entry of `state.json`.

    Field order is the order §7 and `06` write it, because that is the order
    `model_dump_json` emits and the file is meant to be read by a human.
    """

    title: str = ""
    status: Status = Status.PENDING
    destination: Destination = Destination()
    attempts: int = 0
    last_step: str | None = None
    chunks_acked: int = 0
    chunks_total: int = 0
    messages_represented: int = 0
    attachments: AttachmentCounts = AttachmentCounts()
    error: ErrorRecord | None = None
    limitations: list[str] = []
    updated_at: Instant = Field(default_factory=now)
    """Stamped by the store on every write; the factory is only so that a
    hand-written or test-built entry does not have to carry one."""


class MigrationState(RootModel[dict[str, ConversationState]]):
    """§7's top-level object: source conversation id → entry, in insertion order."""

    root: dict[str, ConversationState] = {}

    def __contains__(self, uuid: str) -> bool:
        return uuid in self.root

    def __getitem__(self, uuid: str) -> ConversationState:
        return self.root[uuid]

    def __len__(self) -> int:
        return len(self.root)

    def get(self, uuid: str) -> ConversationState | None:
        return self.root.get(uuid)

    def items(self) -> ItemsView[str, ConversationState]:
        return self.root.items()

    def status_of(self, uuid: str) -> Status:
        """The status of an entry, or `pending` for one that does not exist yet.

        A conversation in the export with no entry has not been attempted, which
        is what `pending` means; selection therefore needs no special case for a
        first run.
        """
        entry = self.root.get(uuid)
        return entry.status if entry is not None else Status.PENDING


# --------------------------------------------------------------------------- #
# `run.json`
# --------------------------------------------------------------------------- #


class Selection(StateModel):
    """What one run was asked to migrate, and what that resolved to.

    Recorded in `run.json` so a report can say why a conversation was not touched
    without re-deriving it from flags nobody kept.
    """

    only: list[str] = []
    limit: int | None = None
    """Effective, not as typed: an unset `--limit` is `run.max_conversations` by
    the time it gets here, and that is the number that shaped the run."""
    retry_failed: bool = False
    retry_partial: bool = False
    force: bool = False
    uuids: list[str] = []
    """What `select` returned, in export order."""


class RunRecord(StateModel):
    """One invocation. Appended when it starts, completed when it ends."""

    started: Instant
    ended: Instant | None = None
    exit_code: int | None = None
    selection: Selection = Selection()


class PauseRecord(StateModel):
    """`14`'s pause. Here rather than in `state.json` so the §7 file keeps its
    shape and the conversation's status stays one of the five."""

    conversation_uuid: str
    reason: str
    detail: str = ""
    last_step: str | None = None
    conversation_id: str | None = None
    since: Instant


class RunFile(StateModel):
    """`run.json`: the run-level record kept out of §7's file."""

    schema_version: int = SCHEMA_VERSION
    export_fingerprint: str = ""
    runs: list[RunRecord] = []
    browser_actions: int = 0
    retries: int = 0
    human_interventions: int = 0
    interrupted: int = 0
    """Entries crash recovery converted out of `running`."""
    paused: PauseRecord | None = None
    previous_destinations: dict[str, list[str]] = {}
    """uuid → the destination ids earlier runs created. `--force` never deletes
    anything at the destination (§17), so the old chat is remembered, not lost."""

    hermes_input_tokens: int = 0
    hermes_output_tokens: int = 0
    hermes_cost_usd: float = 0.0
    """What Hermes's `--usage-file` reported, summed over every run (`09`).

    Here and not in `COUNTERS` because a cost is not a count — `status --json`
    reports the counters and a float among them would not be one — and because
    these are read opportunistically: a Hermes build that writes no usage file
    leaves them at zero, which `19` reports as "not recorded" rather than as free.
    """

    def counters(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in COUNTERS}


# --------------------------------------------------------------------------- #
# Atomic whole-file writes
# --------------------------------------------------------------------------- #


def write_atomically(path: Path, text: str) -> None:
    """Write `<path>.tmp`, flush it to disk, then `os.replace` it into place.

    `os.replace` is atomic on every platform this runs on, so a process killed at
    any point leaves either the previous file or the new one. Surviving a power
    loss takes two flushes rather than one: the file's own bytes, and then the
    directory entry the replace rewrote — without the second, the new contents
    can be on disk while the name still points at the old ones.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + TMP_SUFFIX)
    # newline="": the JSON is written with `\n` line endings on every platform,
    # so a workspace stays diffable when it moves between them.
    with open(tmp, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _fsync_directory(path.parent)


def _fsync_directory(directory: Path) -> None:
    """Flush the directory entry `os.replace` has just rewritten.

    Best effort by necessity: a directory cannot be opened for reading on
    Windows, and some filesystems refuse to sync one. Neither weakens the
    guarantee this module actually promises and tests — `os.replace` is still
    atomic, so a killed process still finds one whole file or the other — it
    only means durability across a power loss is the platform's to give.
    """
    try:
        handle = os.open(directory, os.O_RDONLY)
    except OSError:  # pragma: no cover - Windows, and directories we cannot open
        return
    try:
        os.fsync(handle)
    except OSError:  # pragma: no cover - filesystems that refuse to sync a dir
        pass
    finally:
        os.close(handle)


def _dump(model: BaseModel) -> str:
    """Indented JSON, keys in field order, newline-terminated."""
    return model.model_dump_json(indent=2) + "\n"


def _read_json(path: Path) -> Any:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StateError(f"cannot read {path}: {exc.strerror or exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StateError(f"{path} is not valid JSON: {exc}") from exc


def _describe(exc: ValidationError) -> str:
    """The same one-line rendering `config` gives a validation failure."""
    parts = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"]) or "(root)"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)


# --------------------------------------------------------------------------- #
# The lock
# --------------------------------------------------------------------------- #


class LockInfo(StateModel):
    """What `.lock` holds: who took it, and when."""

    pid: int
    started: Instant


def process_alive(pid: int) -> bool:
    """Whether `pid` is *known* to be a live process.

    Only `--force-unlock` asks, and only to refuse to break a lock somebody is
    still using, so "unknown" answers False: taking the lock is guarded by
    `O_EXCL` either way, and the operator asking to break it has already said the
    process is gone.

    Not attempted off POSIX: `os.kill(pid, 0)` on Windows calls `TerminateProcess`
    rather than testing for the process, which would kill it.
    """
    if pid <= 0 or os.name != "posix":  # pragma: no cover - platform-dependent
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # alive, and owned by another user
    except OSError:  # pragma: no cover - defensive
        return False
    return True


class WorkspaceLock:
    """One run at a time per workspace.

    Whole-file writes are what makes this necessary: two runs would not corrupt
    `state.json` — `os.replace` sees to that — they would silently drop each
    other's entries, which is worse, because the file would still parse.
    """

    def __init__(self, workspace: Path) -> None:
        self.path = workspace / LOCK_FILENAME
        self._held = False

    def read(self) -> LockInfo | None:
        """Who holds the lock, or `None` if it is free or unreadable."""
        if not self.path.exists():
            return None
        try:
            return LockInfo.model_validate(_read_json(self.path))
        except (StateError, ValidationError):
            return None

    def acquire(self, *, force_unlock: bool = False) -> Self:
        if force_unlock:
            self.break_stale()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = _dump(LockInfo(pid=os.getpid(), started=now()))
        try:
            handle = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            raise WorkspaceLocked(self._busy_message()) from None
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(payload)
        self._held = True
        _logger.debug("workspace locked", extra={"pid": os.getpid()})
        return self

    def break_stale(self) -> bool:
        """Remove a lock whose holder is gone. `--force-unlock` is this.

        A lock whose pid is still alive is not stale, and removing it would let
        two runs write the same workspace — the one thing the lock exists to
        prevent — so this refuses rather than asking again.
        """
        info = self.read()
        if info is None:
            # Either free, or a `.lock` nothing can parse. Both are safe to
            # remove: nobody can be relying on a lock file they did not write.
            self.path.unlink(missing_ok=True)
            return False
        if process_alive(info.pid):
            raise WorkspaceLocked(
                f"workspace locked by pid {info.pid}, which is still running — "
                f"stop it before --force-unlock"
            )
        self.path.unlink(missing_ok=True)
        _logger.info("stale lock removed", extra={"pid": info.pid})
        return True

    def release(self) -> None:
        """Give up a lock this process took. Never removes somebody else's."""
        if not self._held:
            return
        self._held = False
        info = self.read()
        if info is not None and info.pid != os.getpid():  # pragma: no cover
            return
        self.path.unlink(missing_ok=True)

    def _busy_message(self) -> str:
        info = self.read()
        if info is None:
            return (
                f"workspace locked by an unreadable {LOCK_FILENAME} — "
                f"use --force-unlock if no run is in progress"
            )
        return (
            f"workspace locked by pid {info.pid} since "
            f"{info.started:%H:%M:%S} — use --force-unlock if that process is gone"
        )

    def __enter__(self) -> Self:
        if not self._held:
            self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #


class StateStore:
    """`state.json` and `run.json`, read once and written whole.

    Both files belong to one workspace and one run: the caller holds the lock, so
    this process is the only writer and the in-memory copy is the truth. Reading
    from disk on every access would only invite a second writer to look correct.
    """

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.state_path = workspace / STATE_FILENAME
        self.run_path = workspace / RUN_FILENAME
        self._state: MigrationState | None = None
        self._run: RunFile | None = None

    # -- state.json --------------------------------------------------------- #

    def load(self) -> MigrationState:
        """The §7 object. An absent file is an empty migration, not an error."""
        if self._state is None:
            self._state = self._read_state()
        return self._state

    def _read_state(self) -> MigrationState:
        if not self.state_path.exists():
            return MigrationState()
        try:
            return MigrationState.model_validate(_read_json(self.state_path))
        except ValidationError as exc:
            raise StateError(
                f"invalid {STATE_FILENAME}: {self.state_path}: {_describe(exc)}"
            ) from exc

    def _write_state(self) -> None:
        write_atomically(self.state_path, _dump(self.load()))

    def ensure(self, uuid: str, **fields: Any) -> ConversationState:
        """Create an entry if there is not one already, and leave it alone if
        there is.

        `12` re-creates every planned conversation as `pending` at the start of
        every run; without this that would reset a finished migration on resume.
        """
        existing = self.load().get(uuid)
        if existing is not None:
            return existing
        return self._put(uuid, ConversationState(**fields))

    def update(self, uuid: str, **fields: Any) -> ConversationState:
        """Merge `fields` into an entry, stamp it, and write the whole file.

        The merge goes through validation rather than `model_copy`, so an unknown
        field name or an impossible status is refused here instead of reaching
        `state.json`. An entry that does not exist yet is created.
        """
        previous = self.load().get(uuid)
        base = previous.model_dump() if previous is not None else {}
        try:
            entry = ConversationState.model_validate(
                {**base, **fields, "updated_at": now()}
            )
        except ValidationError as exc:
            # Ours, not the operator's: every caller is our own code.
            raise IllegalUpdate(
                f"cannot update {render.short_id(uuid)}: {_describe(exc)}"
            ) from exc
        if previous is not None and not transition_allowed(
            previous.status, entry.status
        ):
            raise IllegalTransition(
                f"{render.short_id(uuid)}: {previous.status} cannot become "
                f"{entry.status}"
            )
        return self._put(uuid, entry)

    def _put(self, uuid: str, entry: ConversationState) -> ConversationState:
        state = self.load()
        state.root[uuid] = entry
        self._write_state()
        return entry

    def recover(self) -> list[str]:
        """Convert `running` entries left by a killed run. Called at startup.

        A conversation with a destination id has a chat in the account, so the
        honest status is `partial` — something landed. One without never got that
        far, so it is `pending` again. `attempts` is kept either way: a run that
        died twice tried twice.
        """
        state = self.load()
        recovered: list[str] = []
        for uuid, entry in list(state.root.items()):
            if entry.status is not Status.RUNNING:
                continue
            landed = entry.destination.conversation_id is not None
            state.root[uuid] = ConversationState.model_validate(
                {
                    **entry.model_dump(),
                    "status": Status.PARTIAL if landed else Status.PENDING,
                    "updated_at": now(),
                }
            )
            recovered.append(uuid)
            _logger.warning(
                "interrupted run recovered",
                extra={
                    "conversation_id": render.short_id(uuid),
                    "status": str(state.root[uuid].status),
                },
            )
        if recovered:
            self._write_state()
            self.bump_counter("interrupted", len(recovered))
        return recovered

    # -- run.json ----------------------------------------------------------- #

    def run(self) -> RunFile:
        if self._run is None:
            self._run = self._read_run()
        return self._run

    def _read_run(self) -> RunFile:
        if not self.run_path.exists():
            return RunFile()
        raw = _read_json(self.run_path)
        if not isinstance(raw, Mapping):
            raise StateError(f"{self.run_path} is not a JSON object")
        # The version is read before the model is, so a file from a build that
        # changed the shape is reported as a version mismatch rather than as a
        # pile of unexpected keys.
        version = raw.get("schema_version")
        if version != SCHEMA_VERSION:
            raise SchemaMismatch(
                f"workspace was written with state schema {version!r}, this build "
                f"understands {SCHEMA_VERSION} — migrate the workspace or choose "
                f"another --workspace"
            )
        try:
            return RunFile.model_validate(raw)
        except ValidationError as exc:
            raise StateError(
                f"invalid {RUN_FILENAME}: {self.run_path}: {_describe(exc)}"
            ) from exc

    def _write_run(self, run: RunFile) -> RunFile:
        self._run = run
        write_atomically(self.run_path, _dump(run))
        return run

    def check_export(self, fingerprint: str) -> None:
        """Refuse a workspace that belongs to a different export. Writes nothing.

        The operator picks another `--workspace`; there is deliberately no
        `--new-workspace`, because a tool that invents a second workspace when the
        first one does not match is a tool that quietly migrates twice.
        """
        recorded = self.run().export_fingerprint
        if recorded and recorded != fingerprint:
            raise FingerprintMismatch("workspace belongs to a different export")

    def bind_export(self, fingerprint: str) -> None:
        """Check, then record, which export this workspace is for."""
        self.check_export(fingerprint)
        run = self.run()
        if run.export_fingerprint != fingerprint:
            self._write_run(run.model_copy(update={"export_fingerprint": fingerprint}))

    def add_usage(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> RunFile:
        """Add one Hermes run's usage to the totals in `run.json`.

        Primitives rather than `hermes.runner.HermesUsage`: `09` reads the usage
        file and this records what it found, and keeping the dependency pointing
        one way means `state` stays the module every other one can import.
        """
        run = self.run()
        return self._write_run(
            run.model_copy(
                update={
                    "hermes_input_tokens": run.hermes_input_tokens + input_tokens,
                    "hermes_output_tokens": run.hermes_output_tokens + output_tokens,
                    "hermes_cost_usd": round(run.hermes_cost_usd + cost_usd, 6),
                }
            )
        )

    def bump_counter(self, name: str, by: int = 1) -> int:
        """Add to one of `COUNTERS` and write `run.json`."""
        if name not in COUNTERS:
            raise ValueError(f"unknown counter: {name}")
        run = self.run()
        value = getattr(run, name) + by
        self._write_run(run.model_copy(update={name: value}))
        return value

    def start_run(self, selection: Selection) -> int:
        """Append a run record and return its index for `finish_run`."""
        run = self.run()
        records = [*run.runs, RunRecord(started=now(), selection=selection)]
        self._write_run(run.model_copy(update={"runs": records}))
        return len(records) - 1

    def finish_run(self, index: int, exit_code: int) -> None:
        run = self.run()
        records = list(run.runs)
        records[index] = records[index].model_copy(
            update={"ended": now(), "exit_code": exit_code}
        )
        self._write_run(run.model_copy(update={"runs": records}))

    def set_paused(self, paused: PauseRecord | None) -> None:
        """`14`'s pause record. `None` clears it."""
        self._write_run(self.run().model_copy(update={"paused": paused}))

    def remember_destination(self, uuid: str, conversation_id: str) -> None:
        """Keep a destination id a `--force` re-run is about to replace.

        `--force` creates another chat and never deletes the old one (§17), so
        the id an operator would need to find it has to survive somewhere.
        """
        run = self.run()
        previous = {
            key: list(value) for key, value in run.previous_destinations.items()
        }
        kept = previous.setdefault(uuid, [])
        if conversation_id not in kept:
            kept.append(conversation_id)
        self._write_run(run.model_copy(update={"previous_destinations": previous}))


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #


def resolve_only(order: Sequence[str], only: Sequence[str]) -> list[str]:
    """Turn `--only` values into uuids, in export order.

    A full uuid or the 8-character short id `04`'s acknowledgement lines carry —
    which is what an operator has in front of them when a run reports a failure.
    An unknown value is a mistake, not an empty selection: silently doing nothing
    is how a typo becomes "the tool skipped my conversation".
    """
    known = {uuid: index for index, uuid in enumerate(order)}
    chosen: dict[str, int] = {}
    for token in only:
        if token in known:
            chosen[token] = known[token]
            continue
        matches = [uuid for uuid in order if render.short_id(uuid) == token]
        if len(matches) > 1:
            raise SelectionError(f"ambiguous conversation id: {log.safe_token(token)}")
        if not matches:
            raise SelectionError(f"conversation not in export: {log.safe_token(token)}")
        chosen[matches[0]] = known[matches[0]]
    return [uuid for uuid, _ in sorted(chosen.items(), key=lambda item: item[1])]


def selectable_statuses(selection: Selection) -> frozenset[Status]:
    """Which statuses this run's flags widen the default `pending` to."""
    statuses = {Status.PENDING}
    if selection.retry_failed:
        statuses.add(Status.FAILED)
    if selection.retry_partial:
        statuses.add(Status.PARTIAL)
    if selection.force:
        statuses.add(Status.COMPLETED)
    return frozenset(statuses)


def select(
    order: Sequence[str], state: MigrationState, selection: Selection
) -> list[str]:
    """Which conversations this run touches, in export order.

    `--only` picks *which*, the status flags widen what counts as unfinished, and
    `--limit` picks *how many* — applied last, so a truncated run takes the first
    of the selection rather than a different selection.
    """
    if selection.limit is not None and selection.limit < 0:
        raise SelectionError("--limit must not be negative")
    if selection.only:
        chosen = resolve_only(order, selection.only)
    else:
        statuses = selectable_statuses(selection)
        chosen = [uuid for uuid in order if state.status_of(uuid) in statuses]
    if selection.limit is None:
        return chosen
    return chosen[: selection.limit]


# --------------------------------------------------------------------------- #
# Counting
# --------------------------------------------------------------------------- #


def status_counts(state: MigrationState) -> dict[str, int]:
    """`18`'s four numbers, from state alone.

    `Pending` is `total − done` rather than a tally of `pending` entries, which is
    `18`'s rule and also the only way a `running` entry — one this run has not
    finished, or one a crash left behind — is counted at all.
    """
    tally = {status: 0 for status in Status}
    for _, entry in state.items():
        tally[entry.status] += 1
    total = len(state)
    done = sum(tally[status] for status in TERMINAL)
    return {
        "total": total,
        "completed": tally[Status.COMPLETED],
        "partial": tally[Status.PARTIAL],
        "failed": tally[Status.FAILED],
        "pending": total - done,
    }
