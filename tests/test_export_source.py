"""Reading an export: the read-only promise, and every way it can be malformed."""

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from dataporter import log
from dataporter.errors import Category, ExportError
from dataporter.export import ExportSource, load_export
from dataporter.export.source import CONVERSATIONS_FILE


def digests(root: Path) -> dict[str, str]:
    return {
        str(item.relative_to(root)): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(root.rglob("*"))
        if item.is_file()
    }


def write_export(root: Path, conversations: Any = None, **files: str) -> Path:
    """A minimal export on disk, for the shapes the fixture must not carry."""
    root.mkdir(parents=True, exist_ok=True)
    if conversations is not None:
        (root / CONVERSATIONS_FILE).write_text(json.dumps(conversations))
    for name, body in files.items():
        (root / name.replace("_", ".")).write_text(body)
    return root


def one_conversation(**extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "uuid": "conv-0001",
        "name": "A chat",
        "created_at": "2024-05-01T09:00:00Z",
        "updated_at": "2024-05-01T09:01:00Z",
        "chat_messages": [
            {
                "uuid": "m1",
                "text": "hello",
                "sender": "human",
                "created_at": "2024-05-01T09:00:00Z",
            }
        ],
    }
    data.update(extra)
    return data


def read_lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


# --------------------------------------------------------------------------- #
# The export is never written to
# --------------------------------------------------------------------------- #


def test_reading_a_directory_leaves_it_untouched(export_dir: Path) -> None:
    before = digests(export_dir)
    load_export(export_dir)
    assert digests(export_dir) == before


def test_reading_a_zip_extracts_nothing(export_zip: Path) -> None:
    before = hashlib.sha256(export_zip.read_bytes()).hexdigest()
    siblings = sorted(item.name for item in export_zip.parent.iterdir())
    load_export(export_zip)
    assert hashlib.sha256(export_zip.read_bytes()).hexdigest() == before
    assert sorted(item.name for item in export_zip.parent.iterdir()) == siblings


def test_a_zip_and_a_directory_parse_identically(
    export_dir: Path, export_zip: Path
) -> None:
    """The two code paths cannot drift apart without failing here."""
    assert load_export(export_zip).model_dump_json() == (
        load_export(export_dir).model_dump_json()
    )


def test_a_zip_wrapped_in_one_directory_is_accepted(
    export_dir: Path, tmp_path: Path
) -> None:
    target = tmp_path / "wrapped.zip"
    with zipfile.ZipFile(target, "w") as archive:
        for item in sorted(export_dir.iterdir()):
            archive.write(item, f"claude-export/{item.name}")
    assert len(load_export(target).conversations) == 6


# --------------------------------------------------------------------------- #
# Malformed input
# --------------------------------------------------------------------------- #


def test_a_missing_export_names_the_path_as_typed() -> None:
    with pytest.raises(ExportError) as excinfo:
        load_export("./nowhere")
    assert excinfo.value.detail == "export not found: ./nowhere"


def test_a_truncated_zip_names_the_archive(truncated_zip: Path) -> None:
    with pytest.raises(ExportError) as excinfo:
        load_export(truncated_zip)
    assert excinfo.value.detail.startswith("corrupt zip archive (")
    assert excinfo.value.detail.endswith(f": {truncated_zip}")
    assert excinfo.value.category is Category.EXPORT
    assert excinfo.value.transient is False


def test_something_that_is_neither_a_directory_nor_a_zip(tmp_path: Path) -> None:
    target = tmp_path / "export.tar.gz"
    target.write_bytes(b"not an archive")
    with pytest.raises(ExportError) as excinfo:
        load_export(target)
    assert "is not a directory or a .zip archive" in excinfo.value.detail


def test_missing_conversations_json(tmp_path: Path) -> None:
    root = write_export(tmp_path / "export", users_json="[]")
    with pytest.raises(ExportError) as excinfo:
        load_export(root)
    assert excinfo.value.detail.startswith("conversations.json missing from export:")


def test_conversations_json_must_be_a_json_array(tmp_path: Path) -> None:
    root = write_export(tmp_path / "export", conversations={"conversations": []})
    with pytest.raises(ExportError) as excinfo:
        load_export(root)
    assert "conversations.json is not a JSON array" in excinfo.value.detail


def test_an_element_that_is_not_an_object(tmp_path: Path) -> None:
    root = write_export(tmp_path / "export", conversations=[one_conversation(), 7])
    with pytest.raises(ExportError) as excinfo:
        load_export(root)
    assert "conversations.json[1] is not an object" in excinfo.value.detail


def test_invalid_json_reports_a_byte_offset(tmp_path: Path) -> None:
    """A byte offset, not a character offset: `JSONDecodeError.pos` counts
    characters, and the two diverge as soon as the file is not ASCII."""
    root = tmp_path / "export"
    root.mkdir()
    # "café" is five bytes and four characters, so a character offset would be
    # one short of the truth here.
    body = '[{"name": "café" "uuid": "x"}]'
    (root / CONVERSATIONS_FILE).write_text(body, encoding="utf-8")
    with pytest.raises(ExportError) as excinfo:
        load_export(root)
    offset = len(body[: body.index('"uuid"')].encode("utf-8"))
    assert f"is not valid JSON at byte {offset} " in excinfo.value.detail
    assert offset != body.index('"uuid"')


def test_bytes_that_are_not_utf8(tmp_path: Path) -> None:
    root = tmp_path / "export"
    root.mkdir()
    (root / CONVERSATIONS_FILE).write_bytes(b'[{"name": "\xff\xfe"}]')
    with pytest.raises(ExportError) as excinfo:
        load_export(root)
    assert "conversations.json is not valid UTF-8 at byte 11" in excinfo.value.detail


def test_a_conversation_missing_a_required_field_is_fatal(tmp_path: Path) -> None:
    """The models are already maximally tolerant, so what is left is structural."""
    broken = one_conversation()
    del broken["created_at"]
    root = write_export(tmp_path / "export", conversations=[broken])
    with pytest.raises(ExportError) as excinfo:
        load_export(root)
    assert "invalid conversation at conversations.json[0]" in excinfo.value.detail
    assert "created_at: Field required" in excinfo.value.detail


def test_a_validation_failure_does_not_echo_the_value(tmp_path: Path) -> None:
    """`str(ValidationError)` appends `input_value=…`; `19` prints `detail`
    verbatim into the report, so the value must never get in."""
    broken = one_conversation(created_at="the seventh of never")
    root = write_export(tmp_path / "export", conversations=[broken])
    with pytest.raises(ExportError) as excinfo:
        load_export(root)
    assert "the seventh of never" not in excinfo.value.detail


BROKEN = ["truncated_zip", "not_utf8", "bad_json", "bad_conversation"]


@pytest.mark.parametrize("kind", BROKEN, ids=lambda value: str(value))
def test_no_library_exception_escapes(
    kind: str, tmp_path: Path, export_zip: Path
) -> None:
    """Never a raw `BadZipFile`, `JSONDecodeError` or `ValidationError`."""
    root = tmp_path / "export"
    if kind == "truncated_zip":
        target = tmp_path / "truncated.zip"
        target.write_bytes(export_zip.read_bytes()[:200])
        subject: Path = target
    else:
        root.mkdir()
        subject = root
        if kind == "not_utf8":
            (root / CONVERSATIONS_FILE).write_bytes(b"[\xff]")
        elif kind == "bad_json":
            (root / CONVERSATIONS_FILE).write_text("[{")
        else:
            (root / CONVERSATIONS_FILE).write_text(json.dumps([{"uuid": "x"}]))
    with pytest.raises(ExportError) as excinfo:
        load_export(subject)
    cause = excinfo.value.__cause__
    assert isinstance(
        cause, zipfile.BadZipFile | json.JSONDecodeError | ValidationError | ValueError
    )


# --------------------------------------------------------------------------- #
# Unsupported items
# --------------------------------------------------------------------------- #


def test_an_unknown_top_level_file_is_recorded(export_dir: Path) -> None:
    export = load_export(export_dir)
    item = next(item for item in export.unsupported if item.path == "extra.json")
    assert item.reason == "unknown_file"
    assert item.count == 1


def test_an_unknown_block_type_is_recorded(export_dir: Path) -> None:
    export = load_export(export_dir)
    reasons = {item.reason for item in export.unsupported}
    assert "unknown_block_type:mcp_tool_use" in reasons


def test_an_unknown_sender_is_dropped_and_counted(tmp_path: Path) -> None:
    """`sender` is a Literal, so an unknown one cannot be modelled at all."""
    chat = one_conversation()
    chat["chat_messages"].append(
        {
            "uuid": "m2",
            "text": "system note",
            "sender": "system",
            "created_at": "2024-05-01T09:02:00Z",
        }
    )
    root = write_export(tmp_path / "export", conversations=[chat])
    export = load_export(root)
    assert len(export.conversations[0].chat_messages) == 1
    item = next(
        item for item in export.unsupported if item.reason.startswith("unknown_sender")
    )
    assert item.reason == "unknown_sender:system"
    assert item.path == "conversations.json:conv-0001"


def test_unsupported_items_are_aggregated_and_sorted(tmp_path: Path) -> None:
    """`count` has to mean something, and `03` requires a stable order."""
    chat = one_conversation()
    for position in range(3):
        chat["chat_messages"].append(
            {
                "uuid": f"x{position}",
                "sender": "system",
                "created_at": "2024-05-01T09:02:00Z",
            }
        )
    root = write_export(tmp_path / "export", conversations=[chat], zz_json="{}")
    export = load_export(root)
    counts = {(item.path, item.reason): item.count for item in export.unsupported}
    assert counts[("conversations.json:conv-0001", "unknown_sender:system")] == 3
    assert export.unsupported == sorted(
        export.unsupported, key=lambda item: (item.path, item.reason)
    )


def test_a_reason_token_is_sanitised(tmp_path: Path) -> None:
    """The sender comes from the export and ends up in `report.json`."""
    chat = one_conversation()
    chat["chat_messages"].append(
        {
            "uuid": "m2",
            "sender": "a sender with spaces, and punctuation!",
            "created_at": "2024-05-01T09:02:00Z",
        }
    )
    root = write_export(tmp_path / "export", conversations=[chat])
    export = load_export(root)
    item = next(
        item for item in export.unsupported if item.reason.startswith("unknown_sender")
    )
    assert item.reason == "unknown_sender:a_sender_with_spaces__and_punctuation_"


# --------------------------------------------------------------------------- #
# Optional files
# --------------------------------------------------------------------------- #


def test_optional_files_may_be_absent(tmp_path: Path) -> None:
    root = write_export(tmp_path / "export", conversations=[one_conversation()])
    export = load_export(root)
    assert export.users == []
    assert export.unsupported == []


def test_a_malformed_optional_file_is_not_fatal(tmp_path: Path) -> None:
    """Only `conversations.json` decides what gets migrated, so only it can stop
    a run."""
    root = write_export(
        tmp_path / "export", conversations=[one_conversation()], users_json="{oops"
    )
    export = load_export(root)
    assert export.users == []
    assert [(item.path, item.reason) for item in export.unsupported] == [
        ("users.json", "unparsable_file")
    ]


def test_users_are_read_for_counts(export_dir: Path) -> None:
    assert len(load_export(export_dir).users) == 1


# --------------------------------------------------------------------------- #
# Fingerprint and logging
# --------------------------------------------------------------------------- #


def test_the_fingerprint_is_the_sha256_of_conversations_json(export_dir: Path) -> None:
    """`03` puts this in `plan.json` and `06` in `run.json`."""
    expected = hashlib.sha256(
        (export_dir / CONVERSATIONS_FILE).read_bytes()
    ).hexdigest()
    assert load_export(export_dir).fingerprint == expected


def test_the_shape_is_logged(export_dir: Path, tmp_path: Path) -> None:
    """The record that makes a shape drift visible on the run that hits it."""
    log.configure_logging()  # the root callback always runs first; it sets the level
    path = log.enable_run_log(tmp_path / "workspace")
    load_export(export_dir)
    shape = next(
        record for record in read_lines(path) if record["event"] == "export shape"
    )
    assert shape["conversations"] == 6
    assert shape["messages"] == 51
    assert shape["with_index"] == 51
    assert shape["with_leaf"] == 5
    assert shape["with_files_v2"] == 1
    assert shape["block_types"] == [
        "mcp_tool_use",
        "text",
        "thinking",
        "token_budget",
        "tool_result",
        "tool_use",
    ]


def test_no_export_content_reaches_the_log(export_dir: Path, tmp_path: Path) -> None:
    """§10: no message content and no titles, at any verbosity."""
    log.configure_logging(verbose=True)
    path = log.enable_run_log(tmp_path / "workspace")
    load_export(export_dir)
    written = path.read_text()
    for needle in ("Postgres questions", "dataporter` — a porter", "q3-summary.txt"):
        assert needle not in written


def test_the_source_is_a_context_manager(export_zip: Path) -> None:
    with ExportSource.open(export_zip) as source:
        assert CONVERSATIONS_FILE in source.names()
        assert source.is_archive


# The two backends have to be interchangeable, so a member that is not part of
# the export has to fail identically in both — including a name that would
# resolve outside it, which a bare path join in the directory backend would have
# happily read.
OUTSIDE = ["../conversations.json", "/etc/hostname", "nested/conversations.json"]


@pytest.mark.parametrize("member", OUTSIDE, ids=lambda value: str(value))
def test_a_member_outside_the_export_is_refused(
    member: str, export_dir: Path, export_zip: Path
) -> None:
    for subject in (export_dir, export_zip):
        with ExportSource.open(subject) as source:
            with pytest.raises(ExportError) as excinfo:
                source.read(member)
        assert excinfo.value.detail == f"{member} missing from export: {subject}"


def test_both_backends_refuse_an_absent_member_alike(
    export_dir: Path, export_zip: Path
) -> None:
    details = []
    for subject in (export_dir, export_zip):
        with ExportSource.open(subject) as source:
            with pytest.raises(ExportError) as excinfo:
                source.read("nope.json")
        details.append(excinfo.value.detail.replace(str(subject), "<export>"))
    assert details[0] == details[1] == "nope.json missing from export: <export>"
