"""The store and the snapshot: where an account's data is kept, and how (`30`).

Brief `03` §32 and §33. A snapshot is one account's data, from one source, as it
stood at one moment, in the vendor's own shape; the store is where snapshots go,
addressed by source, account and stamp:

```text
<store>/claude/old-personal/2026-09-12T20-51-07Z/
    export.zip        the vendor's archive, byte for byte
    snapshot.json     everything of ours: provenance, counts, gaps
    COMPLETE          zero bytes, written last
```

Three properties are the whole of this module, and each one is a line of code
rather than a convention:

- **It never overwrites.** A stamp directory that exists is an error and nothing
  is written. Every file is created with `O_CREAT | O_EXCL`, so even a store
  somebody else is writing into at the same moment cannot lose a snapshot to us.
- **It is never renamed.** An object store has no rename, and §33 shapes the disk
  layout so that a bucket can be a second writer of the same files rather than a
  migration of the first. `state.write_atomically` is deliberately not reused
  here: it writes a temp file and `os.replace`s it into place, which is exactly
  the move this layout may not make.
- **A snapshot in progress looks like one.** `COMPLETE` lands last, after the
  bytes and the manifest are fsynced and after the directory entry that names
  them is. A marker that is durable before its files are is a marker that lies
  after a power loss.

What this module does *not* do is fetch anything: `extract.py` downloads, checks
that what arrived is an export of this source, and hands the verified file here
to be filed. Nothing here opens a browser, reads an export or knows what a
migration is.
"""

import hashlib
import json
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from dataporter import __version__, log
from dataporter.config import Settings
from dataporter.console import DISCARD, Sink
from dataporter.errors import FetchError, StoreError, UsageError
from dataporter.exit_codes import ExitCode

_logger = log.get_logger(__name__)

SOURCES: tuple[str, ...] = ("claude",)
"""The vendors this build can read (brief `03` §34).

Extraction from a source the tool does not have is refused, not attempted, so
this is a list and not a pattern. ChatGPT and Gemini are each a source beside
this one — a sign-in, a page where the export is asked for, and an archive shape
— and nothing in the store, the manifest or the commands changes when one lands.
"""

SOURCE_NAMES: dict[str, str] = {"claude": "Claude"}
"""How each source is spelled in a block an operator reads.

A table rather than `str.capitalize`, which renders `chatgpt` as `Chatgpt`: a
vendor's name is the vendor's to spell. `tests/test_store.py` holds the two
lists to each other.
"""

ARCHIVE_NAME = "export.zip"
MANIFEST_NAME = "snapshot.json"
COMPLETE_NAME = "COMPLETE"
SNAPSHOT_FILES = (ARCHIVE_NAME, MANIFEST_NAME, COMPLETE_NAME)
"""The three files of a snapshot, in the order they are created."""

STAMP_FORMAT = "%Y-%m-%dT%H-%M-%SZ"
"""§33's stamp: UTC, to the second, with `-` where a time has `:`.

ISO 8601 with the colons replaced, because the stamp is a directory name and a
colon is not one everywhere. It sorts lexicographically by time, which is the
only ordering §33 gives the store.
"""

COPY_CHUNK = 1 << 20
"""How much of an archive is copied and hashed at a time. A multi-gigabyte
export is not read into memory to be filed."""

SNAPSHOT_EXISTS = "snapshot already exists: {path}"
STORE_UNWRITABLE = "cannot write to the store ({reason}): {path}"
COPY_MISMATCH = "the copy in the store does not match what was downloaded; remove it and try again: {path}"
WORKSPACE_IN_SNAPSHOT = "the workspace cannot be inside a snapshot: {path}"
NO_SNAPSHOTS = "No snapshots in {store}."

COMPLETE = "complete"
INCOMPLETE = "incomplete"
UNREADABLE = "unreadable"
GAPS = "{count} gaps"
GAPS_ONE = "1 gap"
"""What the last column of a `snapshots` row says.

`1 gap` rather than `1 gaps`: the column is read by a person, and §33's own
block shows the plural because its example has two. (Raised by Copilot in review
on #43.)
"""

COLUMN_GAP = "   "
"""Three spaces between the columns of a `snapshots` row (§33's block)."""

UNKNOWN_COUNT = "?"
"""The conversation count of a snapshot whose manifest could not be read."""

Origin = Literal["ask", "link", "file"]
"""How a snapshot came to be: the tool asked for the export and fetched it, a
person handed over a link with no ask on record, or a person handed over an
archive they already had."""

State = Literal["complete", "incomplete", "unreadable"]


# --------------------------------------------------------------------------- #
# Stamps
# --------------------------------------------------------------------------- #


def stamp_of(instant: datetime) -> str:
    """§33's stamp for a moment: UTC, to the second.

    The moment the export was asked for, because that is the moment the account
    was as the archive describes it. A naive value is read as UTC rather than as
    the machine's local time, for the reason `export.model._utc` gives.
    """
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(UTC).strftime(STAMP_FORMAT)


def parse_stamp(stamp: str) -> datetime | None:
    """Read a stamp back to the moment it names, or `None` when it is not one.

    `None` rather than an exception: the caller is a listing walking directories
    somebody else may have created, and a directory that is not a stamp is a
    directory to skip.
    """
    try:
        return datetime.strptime(stamp, STAMP_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# What a snapshot says about itself
# --------------------------------------------------------------------------- #


class StoreModel(BaseModel):
    """Base for everything written into a snapshot: immutable, and closed.

    `extra="forbid"` for the reason `state.StateModel` has it: a snapshot is
    written once and read by whatever comes later, so an unexpected key in
    `snapshot.json` is refused on the way in and impossible on the way out.
    A `version` is what a shape change gets, not a spare field.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class Archive(StoreModel):
    """The vendor's file, as it was filed."""

    name: str = ARCHIVE_NAME
    bytes: int = 0
    sha256: str = ""
    """Of the copy in the store, computed as it was written. The manifest's job
    is to let a reader check the file beside it without trusting us."""


class Counts(StoreModel):
    """What the archive turned out to hold. Numbers only (§38)."""

    conversations: int = 0
    projects: int = 0
    memories: int = 0


class Gap(StoreModel):
    """Something the account holds that the snapshot does not (§31).

    A snapshot with gaps is a valid snapshot; one that is silent about what it
    lacks is not. `kind` is a slug the tool owns — `plan.BYTES_NOT_IN_EXPORT` is
    the only one today — and `reason` is the sentence an operator reads.
    """

    kind: str
    count: int = 0
    reason: str = ""


class Snapshot(StoreModel):
    """`snapshot.json`: everything of ours, beside the vendor's archive (§32).

    Never inside it. The provenance §32 asks for is here in full — the source,
    the label, the stamp, the tool that wrote it, whether an ask was behind it,
    when it was asked for and when it was filed — and the link is not, because
    the link expires and is a credential to the archive while it lasts.
    """

    version: Literal[1] = 1
    source: str
    account: str
    stamp: str
    origin: Origin
    asked_at: datetime | None = None
    filed_at: datetime
    tool_version: str
    archive: Archive = Archive()
    export_fingerprint: str = ""
    """The SHA-256 of `conversations.json` — `Export.fingerprint`, the same
    number a workspace records for the archive given directly. That identity is
    what makes a snapshot and its archive the same migration (ADR 0005)."""
    counts: Counts = Counts()
    gaps: list[Gap] = []

    @property
    def gap_count(self) -> int:
        """How many things the account holds that this snapshot does not."""
        return sum(gap.count for gap in self.gaps)


class Ask(StoreModel):
    """The open ask (§31): the tool asked this vendor for this account's export.

    Remembered so that the link that comes back is filed under the moment the
    account was as the export describes it. It lives in the account home rather
    than in the store — it is operational, abandonable state, and the store's
    contract (created once, marker last, never deleted) fits it badly.
    """

    asked_at: datetime
    source: str
    account: str
    tool_version: str


class SnapshotRow(StoreModel):
    """One line of `snapshots`, and one object of `snapshots --json`."""

    source: str
    account: str
    stamp: str
    state: State
    conversations: int | None = None
    """`None` when the manifest could not be read. A zero would be a claim."""
    gaps: int = 0

    @property
    def label(self) -> str:
        return f"{self.source}/{self.account}"

    @property
    def count(self) -> str:
        return UNKNOWN_COUNT if self.conversations is None else f"{self.conversations}"

    @property
    def note(self) -> str:
        """The last column: the state, or the gaps when there are any.

        A finished snapshot with gaps says so rather than saying `complete`,
        which is §31's "complete or it says so" in one word: the gaps are what a
        reader of the listing has to know about it.
        """
        if self.state != COMPLETE:
            return self.state
        if not self.gaps:
            return COMPLETE
        return GAPS_ONE if self.gaps == 1 else GAPS.format(count=self.gaps)


# --------------------------------------------------------------------------- #
# Filing
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Filing:
    """A verified archive, ready to be filed.

    Everything the manifest needs that only the fetch can know: where it came
    from, when, and what a parse of it found. `sha256` is of the file being
    filed as `extract` hashed it on the way in; the copy is hashed again as it
    is written and the two are compared before anything says `COMPLETE`.
    """

    source: str
    account: str
    stamp: str
    origin: Origin
    sha256: str
    bytes: int
    export_fingerprint: str
    counts: Counts
    gaps: tuple[Gap, ...] = ()
    asked_at: datetime | None = None


class Store:
    """A directory of snapshots. Never overwrites, never renames, never deletes.

    Constructed with a root rather than with `Settings` so that the second
    backend §33 anticipates — a bucket — is a second class beside this one and
    not a flag inside it.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def directory(self, source: str, account: str, stamp: str) -> Path:
        """`<store>/<source>/<account>/<stamp>/`, whether or not it exists.

        The three components are validated where they enter the tool
        (`config.with_account`, `stamp_of`), so nothing here can leave the root.
        """
        return self.root / source / account / stamp

    def file_archive(self, path: Path, filing: Filing) -> tuple[Path, Snapshot]:
        """Copy `path` into a fresh stamp directory and finish the snapshot.

        The order is the contract: the archive, then the manifest, then both
        fsynced and the directory entry with them, and only then the marker. A
        reader that finds `COMPLETE` has the bytes, whatever happened to the
        machine in between.
        """
        directory = self.directory(filing.source, filing.account, filing.stamp)
        self._make_directory(directory)
        digest, written = _copy(path, directory / ARCHIVE_NAME)
        if digest != filing.sha256:
            # The store now holds a stamp directory with no `COMPLETE` in it,
            # which is what an unfinished snapshot is meant to look like. The
            # tool never deletes from the store, so the message names it.
            raise FetchError(COPY_MISMATCH.format(path=directory))
        snapshot = Snapshot(
            source=filing.source,
            account=filing.account,
            stamp=filing.stamp,
            origin=filing.origin,
            asked_at=filing.asked_at,
            filed_at=datetime.now(UTC),
            tool_version=tool_version(),
            archive=Archive(name=ARCHIVE_NAME, bytes=written, sha256=digest),
            export_fingerprint=filing.export_fingerprint,
            counts=filing.counts,
            gaps=list(filing.gaps),
        )
        _create(
            directory / MANIFEST_NAME,
            (snapshot.model_dump_json(indent=2) + "\n").encode("utf-8"),
        )
        _fsync_directory(directory)
        _create(directory / COMPLETE_NAME, b"")
        _fsync_directory(directory)
        _logger.info(
            "snapshot filed",
            extra={
                "source": filing.source,
                "account": filing.account,
                "stamp": filing.stamp,
                "origin": filing.origin,
                "bytes": written,
                "gaps": snapshot.gap_count,
            },
        )
        return directory, snapshot

    def _make_directory(self, directory: Path) -> None:
        """Create the stamp directory, once. An existing one stops everything."""
        try:
            directory.mkdir(parents=True)
        except FileExistsError as exc:
            raise StoreError(SNAPSHOT_EXISTS.format(path=directory)) from exc
        except OSError as exc:
            raise StoreError(STORE_UNWRITABLE.format(reason=exc.strerror or exc, path=self.root)) from exc

    def rows(self) -> list[SnapshotRow]:
        """Every snapshot in the store, as `snapshots` prints it.

        Ordered by account, then source, then stamp. The account label is the
        operator's own word and the thing they scan a listing for; the stamp is
        the only ordering §33 gives *within* an account, and the source breaks a
        tie between two vendors the same person labelled the same way.
        """
        return sorted(
            (self._row(directory) for directory in self._stamp_directories()),
            key=lambda row: (row.account, row.source, row.stamp),
        )

    def _stamp_directories(self) -> Iterator[Path]:
        """`<source>/<account>/<stamp>` and nothing else.

        Exactly three levels, and every name at the third checked against the
        stamp format: a store is a directory somebody else may also write to,
        and a listing that wandered into a fourth level would be reporting on
        whatever it found there.
        """
        for source in _subdirectories(self.root):
            for account in _subdirectories(source):
                for stamp in _subdirectories(account):
                    if parse_stamp(stamp.name) is not None:
                        yield stamp

    def _row(self, directory: Path) -> SnapshotRow:
        source, account = directory.parent.parent.name, directory.parent.name
        snapshot = _read_manifest(directory / MANIFEST_NAME)
        if not (directory / COMPLETE_NAME).exists():
            # Unfinished, whatever the manifest says: the marker is the only
            # thing that makes a snapshot readable.
            return SnapshotRow(
                source=source,
                account=account,
                stamp=directory.name,
                state=INCOMPLETE,
                conversations=None if snapshot is None else snapshot.counts.conversations,
            )
        if snapshot is None:
            return SnapshotRow(source=source, account=account, stamp=directory.name, state=UNREADABLE)
        return SnapshotRow(
            source=source,
            account=account,
            stamp=directory.name,
            state=COMPLETE,
            conversations=snapshot.counts.conversations,
            gaps=snapshot.gap_count,
        )


def _read_manifest(path: Path) -> Snapshot | None:
    """`snapshot.json`, or `None` for anything that is not one."""
    try:
        return Snapshot.model_validate_json(path.read_bytes())
    except (OSError, ValidationError, ValueError):
        return None


def _subdirectories(path: Path) -> list[Path]:
    try:
        return sorted(item for item in path.iterdir() if item.is_dir())
    except OSError:
        return []


# --------------------------------------------------------------------------- #
# Writing files that are never rewritten
# --------------------------------------------------------------------------- #


def _create(path: Path, data: bytes) -> None:
    """Create `path`, write `data`, fsync it. Never truncates an existing file."""
    handle = _open_exclusive(path)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise StoreError(STORE_UNWRITABLE.format(reason=exc.strerror or exc, path=path)) from exc


def _copy(source: Path, target: Path) -> tuple[str, int]:
    """Copy `source` to a file that did not exist, hashing as it goes.

    Not `shutil.copy`, which opens the target with `O_TRUNC` and would overwrite
    a file already there, and not a hash of the source read a second time: the
    digest returned is of the bytes that landed in the store.
    """
    handle = _open_exclusive(target)
    try:
        return _drain(Path(source), handle)
    except OSError as exc:
        raise StoreError(STORE_UNWRITABLE.format(reason=exc.strerror or exc, path=target)) from exc


def _drain(source: Path, handle: int) -> tuple[str, int]:
    """Stream `source` into the open descriptor `handle`, hashing the bytes that land."""
    digest = hashlib.sha256()
    written = 0
    with source.open("rb") as reading, os.fdopen(handle, "wb") as writing:
        while chunk := reading.read(COPY_CHUNK):
            digest.update(chunk)
            written += len(chunk)
            writing.write(chunk)
        writing.flush()
        os.fsync(writing.fileno())
    return digest.hexdigest(), written


SNAPSHOT_MODE = 0o600
"""The mode every file in a snapshot is created with.

A snapshot holds the account's conversations — that is what it is for — and the
store is long-lived and shared between accounts and sources, so the bytes are
the owner's and nobody else's. The same mode the download's temp file and
`ask.json` already use, and a narrowing of the umask default rather than a
widening of it: a `0o644` snapshot is world-readable wherever the umask allows
it. (Raised by Copilot in review on #43.)
"""


def _open_exclusive(path: Path) -> int:
    """`O_CREAT | O_EXCL | O_WRONLY`: create it, or fail because it is there."""
    try:
        return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, SNAPSHOT_MODE)
    except FileExistsError as exc:
        raise StoreError(SNAPSHOT_EXISTS.format(path=path)) from exc
    except OSError as exc:
        raise StoreError(STORE_UNWRITABLE.format(reason=exc.strerror or exc, path=path)) from exc


def _fsync_directory(directory: Path) -> None:
    """Flush the directory entries naming the files just created.

    Best effort, for the reasons `state._fsync_directory` gives: a directory
    cannot be opened for reading on Windows and some filesystems refuse to sync
    one. What it buys here is the ordering `COMPLETE` depends on.
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


def tool_version() -> str:
    """Return the version that wrote a snapshot (§32's provenance).

    Read off the module rather than out of the installed distribution's
    metadata, for the reason `--version` is: `dataporter.__version__` is the one
    line the wheel's metadata is built from, so a snapshot filed from a checkout
    and one filed from an install say the same thing.
    """
    return __version__


# --------------------------------------------------------------------------- #
# A snapshot is read, never written to
# --------------------------------------------------------------------------- #


def is_snapshot(path: Path) -> bool:
    """Whether `path` is a snapshot directory rather than an export."""
    return path.is_dir() and (path / MANIFEST_NAME).is_file()


def refuse_workspace_inside(export: Path, workspace: Path) -> None:
    """Refuse a workspace inside the snapshot being read (§33).

    §33 says the store holds nothing a migration writes, and a workspace is
    everything a migration writes. `ensure_gitignore` and `state` would
    otherwise put `state.json` and a signed-in browser profile inside a snapshot
    that is finished by definition.

    Only a snapshot is guarded: an export is the operator's own file and
    `migration/` beside it is what the first brief has always done.
    """
    if not is_snapshot(export):
        return
    root = Path(os.path.abspath(export))  # ruff: ignore[os-path-abspath] - normalises `..` without chasing symlinks
    if Path(os.path.abspath(workspace)).is_relative_to(root):  # ruff: ignore[os-path-abspath] - normalises `..` without chasing symlinks
        raise UsageError(WORKSPACE_IN_SNAPSHOT.format(path=workspace))


# --------------------------------------------------------------------------- #
# `snapshots`
# --------------------------------------------------------------------------- #


def listing(rows: Sequence[SnapshotRow]) -> str:
    """§33's block: label, stamp, count and state, newline-terminated.

    The label column is padded to the longest label and the count is
    right-aligned, so the four columns line up whatever the store holds. Three
    spaces between them, which is the brief's own block.
    """
    labels = max(len(row.label) for row in rows)
    stamps = max(len(row.stamp) for row in rows)
    counts = max(len(row.count) for row in rows)
    return "".join(
        COLUMN_GAP.join((
            f"{row.label:<{labels}}",
            f"{row.stamp:<{stamps}}",
            f"{row.count:>{counts}} conversations",
            row.note,
        ))
        + "\n"
        for row in rows
    )


class SnapshotsOutcome(BaseModel):
    """What `snapshots` amounted to: the rows, and exit `0`."""

    rows: list[SnapshotRow] = []
    exit_code: ExitCode = ExitCode.OK


def list_command(settings: Settings, *, json_output: bool = False, sink: Sink = DISCARD) -> SnapshotsOutcome:
    """List what the store holds (§33).

    An empty store prints a line and exits `0`: `snapshots` answers a question
    about a directory, and "nothing is there" is the answer — as it is for
    `status` on a workspace nothing has run in.
    """
    rows = tuple(Store(settings.store_dir).rows())
    if json_output:
        # The rows and nothing else on stdout, so a `jq` never has to skip a
        # header. An empty store is `[]`, which is the same answer in JSON.
        sink.line(json.dumps([row.model_dump(mode="json") for row in rows], indent=2))
    elif rows:
        sink.block(listing(rows))
    else:
        sink.line(NO_SNAPSHOTS.format(store=settings.store_display))
    return SnapshotsOutcome(rows=rows)
