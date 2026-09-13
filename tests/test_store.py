"""The store: the layout, the write order, and the listing (`30`).

What is being checked here is a set of promises about files rather than about
output — brief `03` §33 says a snapshot is created once, never renamed, and told
from an unfinished one by a marker that lands last — so most of these assert on
what is on disk and in what order it got there, and the one golden string is the
§33 block.
"""

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dataporter import cli, store
from dataporter.config import load_settings, with_store_dir
from dataporter.console import Collected
from dataporter.errors import FetchError, StoreError, UsageError
from dataporter.exit_codes import ExitCode

STAMP = "2026-09-12T20-51-07Z"
MOMENT = datetime(2026, 9, 12, 20, 51, 7, tzinfo=UTC)

BLOCK = (
    "claude/old-personal   2026-09-12T20-51-07Z   127 conversations   complete\n"
    "claude/old-personal   2026-10-01T03-00-00Z   131 conversations   complete\n"
    "chatgpt/work          2026-09-30T18-12-44Z    88 conversations   2 gaps\n"
)
"""§33's block, byte for byte. The three rows are the brief's own."""


def archive(tmp_path: Path, body: bytes = b"PK\x03\x04 pretend") -> Path:
    """A file to be filed. The store never looks inside one."""
    target = tmp_path / "export.zip"
    target.write_bytes(body)
    return target


def filing(path: Path, **overrides: Any) -> store.Filing:
    fields: dict[str, Any] = {
        "source": "claude",
        "account": "old-personal",
        "stamp": STAMP,
        "origin": "file",
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "export_fingerprint": "f" * 64,
        "counts": store.Counts(conversations=127, projects=4, memories=1),
    }
    fields.update(overrides)
    return store.Filing(**fields)


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_at(
    root: Path, source: str, account: str, stamp: str, **fields: object
) -> Path:
    """A finished snapshot written by hand, for the listing to read back."""
    directory = root / source / account / stamp
    directory.mkdir(parents=True)
    (directory / store.ARCHIVE_NAME).write_bytes(b"PK\x03\x04")
    manifest = store.Snapshot(
        source=source,
        account=account,
        stamp=stamp,
        origin="file",
        filed_at=MOMENT,
        tool_version="0.1.0",
        **fields,  # type: ignore[arg-type]
    )
    (directory / store.MANIFEST_NAME).write_text(manifest.model_dump_json(indent=2))
    (directory / store.COMPLETE_NAME).write_bytes(b"")
    return directory


@pytest.fixture
def no_renames(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`os.replace` and `os.rename` raise for the duration of a filing.

    §33 shapes the disk layout so that an object store — which has no rename —
    can be a second writer of the same files. `state.write_atomically` is the
    house style for writing a file and is exactly what this layout may not use,
    so the rule is enforced rather than remembered.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the store never renames")

    monkeypatch.setattr(os, "replace", refuse)
    monkeypatch.setattr(os, "rename", refuse)
    yield


# --------------------------------------------------------------------------- #
# Stamps
# --------------------------------------------------------------------------- #


def test_a_stamp_is_utc_to_the_second() -> None:
    assert store.stamp_of(MOMENT) == STAMP


def test_a_stamp_round_trips() -> None:
    assert store.parse_stamp(store.stamp_of(MOMENT)) == MOMENT


def test_a_local_time_is_stamped_as_the_utc_it_names() -> None:
    from datetime import timedelta, timezone

    local = MOMENT.astimezone(timezone(timedelta(hours=2)))
    assert store.stamp_of(local) == STAMP


def test_a_naive_moment_is_read_as_utc() -> None:
    assert store.stamp_of(MOMENT.replace(tzinfo=None)) == STAMP


def test_something_that_is_not_a_stamp_parses_to_nothing() -> None:
    assert store.parse_stamp("yesterday") is None


def test_every_source_has_a_name_to_print_it_with() -> None:
    assert set(store.SOURCE_NAMES) == set(store.SOURCES)


# --------------------------------------------------------------------------- #
# Filing
# --------------------------------------------------------------------------- #


def test_a_snapshot_is_three_files_in_one_directory(
    tmp_path: Path, no_renames: None
) -> None:
    source = archive(tmp_path)
    directory, snapshot = store.Store(tmp_path / "store").file_archive(
        source, filing(source)
    )

    assert directory == tmp_path / "store" / "claude" / "old-personal" / STAMP
    assert sorted(item.name for item in directory.iterdir()) == sorted(
        store.SNAPSHOT_FILES
    )
    assert (directory / store.ARCHIVE_NAME).read_bytes() == source.read_bytes()
    assert (directory / store.COMPLETE_NAME).read_bytes() == b""
    assert snapshot.archive.sha256 == _sha256(source)
    assert snapshot.archive.bytes == source.stat().st_size


def test_the_marker_is_created_last(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A marker that lands before the bytes are durable is a marker that lies."""
    created: list[str] = []
    real = os.open

    def watch(path: object, flags: int, *args: object, **kwargs: object) -> int:
        if flags & os.O_CREAT:
            created.append(Path(str(path)).name)
        return real(path, flags, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "open", watch)
    source = archive(tmp_path)
    store.Store(tmp_path / "store").file_archive(source, filing(source))

    assert created == list(store.SNAPSHOT_FILES)


def test_a_stamp_that_exists_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    root = tmp_path / "store"
    directory = root / "claude" / "old-personal" / STAMP
    directory.mkdir(parents=True)
    source = archive(tmp_path)

    with pytest.raises(StoreError) as raised:
        store.Store(root).file_archive(source, filing(source))

    assert str(raised.value) == f"snapshot already exists: {directory}"
    assert list(directory.iterdir()) == []


def test_a_copy_that_does_not_match_stops_before_the_marker(tmp_path: Path) -> None:
    """The bytes in the store are hashed as they are written, not read back."""
    source = archive(tmp_path)
    root = tmp_path / "store"

    with pytest.raises(FetchError) as raised:
        store.Store(root).file_archive(source, filing(source, sha256="0" * 64))

    directory = root / "claude" / "old-personal" / STAMP
    assert "does not match what was downloaded" in str(raised.value)
    assert not (directory / store.COMPLETE_NAME).exists()
    assert not (directory / store.MANIFEST_NAME).exists()


def test_a_store_that_cannot_be_written_to_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "mkdir", refuse)
    source = archive(tmp_path)

    with pytest.raises(StoreError) as raised:
        store.Store(tmp_path / "store").file_archive(source, filing(source))

    assert "cannot write to the store" in str(raised.value)


def test_the_manifest_carries_the_provenance(tmp_path: Path) -> None:
    source = archive(tmp_path)
    directory, _ = store.Store(tmp_path / "store").file_archive(
        source, filing(source, origin="ask", asked_at=MOMENT)
    )
    manifest = json.loads((directory / store.MANIFEST_NAME).read_text())

    assert manifest["version"] == 1
    assert manifest["origin"] == "ask"
    assert manifest["asked_at"].startswith("2026-09-12T20:51:07")
    assert manifest["tool_version"] == store.tool_version()
    assert manifest["counts"] == {"conversations": 127, "projects": 4, "memories": 1}
    # §32: the link is not kept, under any spelling.
    assert "link" not in json.dumps(manifest)


def test_a_snapshot_with_no_references_has_no_gap(tmp_path: Path) -> None:
    source = archive(tmp_path)
    _, snapshot = store.Store(tmp_path / "store").file_archive(source, filing(source))

    assert snapshot.gaps == []
    assert snapshot.gap_count == 0


# --------------------------------------------------------------------------- #
# The listing
# --------------------------------------------------------------------------- #


def test_the_listing_is_the_brief_block(tmp_path: Path) -> None:
    root = tmp_path / "store"
    snapshot_at(
        root,
        "claude",
        "old-personal",
        "2026-09-12T20-51-07Z",
        counts=store.Counts(conversations=127),
    )
    snapshot_at(
        root,
        "claude",
        "old-personal",
        "2026-10-01T03-00-00Z",
        counts=store.Counts(conversations=131),
    )
    snapshot_at(
        root,
        "chatgpt",
        "work",
        "2026-09-30T18-12-44Z",
        counts=store.Counts(conversations=88),
        gaps=[store.Gap(kind="bytes_not_in_export", count=2, reason="files")],
    )

    assert store.listing(store.Store(root).rows()) == BLOCK


def test_an_unfinished_snapshot_is_incomplete(tmp_path: Path) -> None:
    root = tmp_path / "store"
    directory = snapshot_at(
        root, "claude", "a", STAMP, counts=store.Counts(conversations=3)
    )
    (directory / store.COMPLETE_NAME).unlink()

    row = store.Store(root).rows()[0]
    assert row.state == store.INCOMPLETE
    assert row.note == "incomplete"
    assert row.conversations == 3


def test_a_manifest_that_will_not_parse_is_unreadable(tmp_path: Path) -> None:
    root = tmp_path / "store"
    directory = snapshot_at(root, "claude", "a", STAMP)
    (directory / store.MANIFEST_NAME).write_text("{not json")

    row = store.Store(root).rows()[0]
    assert row.state == store.UNREADABLE
    assert row.count == store.UNKNOWN_COUNT


def test_only_source_account_stamp_is_walked(tmp_path: Path) -> None:
    """A store is a directory somebody else may write to as well."""
    root = tmp_path / "store"
    snapshot_at(root, "claude", "a", STAMP)
    (root / "claude" / "a" / "notes").mkdir()
    (root / "claude" / "a" / STAMP / "deeper").mkdir()
    (root / "loose-file.txt").write_text("x")

    assert [row.stamp for row in store.Store(root).rows()] == [STAMP]


def test_rows_are_ordered_by_account_then_source_then_stamp(tmp_path: Path) -> None:
    root = tmp_path / "store"
    snapshot_at(root, "claude", "work", "2026-01-01T00-00-00Z")
    snapshot_at(root, "chatgpt", "work", "2026-01-01T00-00-00Z")
    snapshot_at(root, "claude", "personal", "2026-02-02T00-00-00Z")
    snapshot_at(root, "claude", "personal", "2026-01-01T00-00-00Z")

    assert [
        (row.account, row.source, row.stamp) for row in store.Store(root).rows()
    ] == [
        ("personal", "claude", "2026-01-01T00-00-00Z"),
        ("personal", "claude", "2026-02-02T00-00-00Z"),
        ("work", "chatgpt", "2026-01-01T00-00-00Z"),
        ("work", "claude", "2026-01-01T00-00-00Z"),
    ]


def test_an_empty_store_is_an_answer(tmp_path: Path, workspace: Path) -> None:
    settings = with_store_dir(load_settings(), tmp_path / "s")
    sink = Collected()
    outcome = store.list_command(settings, sink=sink)

    assert outcome.exit_code == 0
    assert outcome.rows == []
    assert sink.stdout == f"No snapshots in {tmp_path / 's'}.\n"


def test_the_json_rows_round_trip(tmp_path: Path, workspace: Path) -> None:
    root = tmp_path / "s"
    snapshot_at(root, "claude", "a", STAMP, counts=store.Counts(conversations=7))
    settings = with_store_dir(load_settings(), root)
    sink = Collected()
    store.list_command(settings, json_output=True, sink=sink)

    rows = [
        store.SnapshotRow.model_validate_json(json.dumps(item))
        for item in json.loads(sink.stdout)
    ]
    assert rows == store.Store(root).rows()


# --------------------------------------------------------------------------- #
# A snapshot is read, never written to
# --------------------------------------------------------------------------- #


def test_a_workspace_inside_a_snapshot_is_refused(tmp_path: Path) -> None:
    snapshot = snapshot_at(tmp_path / "store", "claude", "a", STAMP)

    with pytest.raises(UsageError) as raised:
        store.refuse_workspace_inside(snapshot, snapshot / "migration")

    assert str(raised.value) == (
        f"the workspace cannot be inside a snapshot: {snapshot / 'migration'}"
    )


def test_a_workspace_beside_a_snapshot_is_fine(tmp_path: Path) -> None:
    snapshot = snapshot_at(tmp_path / "store", "claude", "a", STAMP)
    store.refuse_workspace_inside(snapshot, tmp_path / "migration")


def test_an_export_is_not_guarded(tmp_path: Path, export_dir: Path) -> None:
    """`migration/` beside an export is what the first brief has always done."""
    store.refuse_workspace_inside(export_dir, export_dir / "migration")


# --------------------------------------------------------------------------- #
# A snapshot stands in for an export (§37)
# --------------------------------------------------------------------------- #


def test_inspect_reads_a_snapshot_as_it_reads_an_archive(
    runner: CliRunner, workspace: Path, snapshot_dir: Path, export_zip: Path
) -> None:
    for flags in ([], ["--json"]):
        of_snapshot = runner.invoke(
            cli.app, ["inspect", str(snapshot_dir), *flags], catch_exceptions=False
        )
        of_archive = runner.invoke(
            cli.app, ["inspect", str(export_zip), *flags], catch_exceptions=False
        )

        assert of_snapshot.exit_code == of_archive.exit_code == 0
        assert of_snapshot.stdout == of_archive.stdout


def test_a_dry_run_of_a_snapshot_matches_the_archive(
    runner: CliRunner, workspace: Path, snapshot_dir: Path, export_zip: Path
) -> None:
    """§39's question 3, at the command an operator would actually type."""
    of_snapshot = runner.invoke(
        cli.app, ["import", str(snapshot_dir), "--dry-run"], catch_exceptions=False
    )
    of_archive = runner.invoke(
        cli.app, ["import", str(export_zip), "--dry-run"], catch_exceptions=False
    )

    assert of_snapshot.stdout == of_archive.stdout


def test_an_incomplete_snapshot_is_refused_by_inspect(
    runner: CliRunner, workspace: Path, snapshot_dir: Path
) -> None:
    (snapshot_dir / store.COMPLETE_NAME).unlink()
    result = runner.invoke(
        cli.app, ["inspect", str(snapshot_dir)], catch_exceptions=False
    )

    assert result.exit_code == ExitCode.USAGE
    assert result.stderr == f"error: snapshot is incomplete: {snapshot_dir}\n"


def test_a_run_may_not_write_its_workspace_into_a_snapshot(
    runner: CliRunner, workspace: Path, snapshot_dir: Path
) -> None:
    before = sorted(item.name for item in snapshot_dir.iterdir())
    result = runner.invoke(
        cli.app,
        ["--workspace", str(snapshot_dir / "migration"), "import", str(snapshot_dir)],
        catch_exceptions=False,
    )

    assert result.exit_code == ExitCode.USAGE
    assert "the workspace cannot be inside a snapshot" in result.stderr
    assert sorted(item.name for item in snapshot_dir.iterdir()) == before


def test_seeds_may_not_write_into_a_snapshot_either(
    runner: CliRunner, workspace: Path, snapshot_dir: Path
) -> None:
    result = runner.invoke(
        cli.app,
        ["--workspace", str(snapshot_dir / "migration"), "seeds", str(snapshot_dir)],
        catch_exceptions=False,
    )

    assert result.exit_code == ExitCode.USAGE
    assert not (snapshot_dir / "migration").exists()


# --------------------------------------------------------------------------- #
# Writing files that are never rewritten
# --------------------------------------------------------------------------- #

# The three below reach for the private helpers directly. Everything above goes
# through `file_archive`, and these are the failures it cannot be made to
# produce from the outside: a disk that fills between two files, and a create
# that loses a race with another writer of the same store.


def test_a_file_that_is_already_there_is_never_truncated(tmp_path: Path) -> None:
    target = tmp_path / "once"
    store._create(target, b"first")

    with pytest.raises(StoreError, match="snapshot already exists"):
        store._create(target, b"second")

    assert target.read_bytes() == b"first"


def test_a_file_that_cannot_be_created_names_the_store(tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="cannot write to the store"):
        store._create(tmp_path / "no-such-directory" / "f", b"x")


def test_a_write_that_fails_is_a_store_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def full(handle: int) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", full)
    source = archive(tmp_path)

    with pytest.raises(StoreError, match="No space left on device"):
        store._create(tmp_path / "manifest", b"{}")
    with pytest.raises(StoreError, match="No space left on device"):
        store._copy(source, tmp_path / "copy.zip")


def test_one_gap_is_not_one_gaps(tmp_path: Path) -> None:
    """The last column is read by a person. (Raised by Copilot in review on #43.)"""
    root = tmp_path / "store"
    snapshot_at(
        root,
        "claude",
        "a",
        STAMP,
        counts=store.Counts(conversations=2),
        gaps=[store.Gap(kind="bytes_not_in_export", count=1, reason="file")],
    )

    assert store.Store(root).rows()[0].note == "1 gap"


def test_a_snapshot_is_the_owners_to_read(tmp_path: Path) -> None:
    """A snapshot holds the account's conversations, in a long-lived store shared
    between accounts. (Raised by Copilot in review on #43.)"""
    source = archive(tmp_path)
    directory, _ = store.Store(tmp_path / "store").file_archive(source, filing(source))

    for name in store.SNAPSHOT_FILES:
        mode = (directory / name).stat().st_mode & 0o777
        assert mode == store.SNAPSHOT_MODE, name
