"""The ChatGPT archive (`43`): recognised, counted, its gaps, filed, and refused by `import`.

Every claim about the shape is *assumed* (`docs/chatgpt-export-format.md`); what these
tests pin is the tool's reading of that document, so that the day a real export
contradicts it the failure names the line.
"""

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dataporter import cli, extract, store
from dataporter.config import Settings, load_settings, with_account, with_store_dir
from dataporter.console import Collected
from dataporter.errors import ExportError, FetchError
from dataporter.exit_codes import ExitCode
from dataporter.export import ExportView, chatgpt, load_export
from dataporter.sources.chatgpt import CHATGPT
from dataporter.sources.claude import CLAUDE


@pytest.fixture
def settings(tmp_path: Path, workspace: Path) -> Settings:
    """One invocation about a ChatGPT account, its store and accounts tree under `tmp_path`."""
    loaded = with_store_dir(load_settings(), tmp_path / "store")
    return with_account(
        loaded.model_copy(update={"accounts": loaded.accounts.model_copy(update={"dir": tmp_path / "accounts"})}),
        "chatgpt",
        "work",
    )


def reading(path: Path) -> chatgpt.Reading:
    with ExportView.open(path) as view:
        return chatgpt.read(view)


def zipped(target: Path, members: dict[str, Any]) -> Path:
    with zipfile.ZipFile(target, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload if isinstance(payload, bytes) else json.dumps(payload))
    return target


def conversation(**extra: Any) -> dict[str, Any]:
    return {"title": "x", "mapping": {"r": {"id": "r", "message": None, "parent": None, "children": []}}, **extra}


# --------------------------------------------------------------------------- #
# Recognised
# --------------------------------------------------------------------------- #


def test_a_chatgpt_archive_is_recognised_by_user_json_or_a_split_member() -> None:
    assert chatgpt.looks_like(["conversations.json", "user.json"])
    assert chatgpt.looks_like(["conversations-001.json"])
    assert not chatgpt.looks_like(["conversations.json", "users.json"])
    assert not chatgpt.looks_like(["conversations.json"])


# --------------------------------------------------------------------------- #
# Counted
# --------------------------------------------------------------------------- #


def test_the_fixture_counts_three_conversations_two_files_and_two_gaps(chatgpt_zip: Path, chatgpt_dir: Path) -> None:
    found = reading(chatgpt_zip)

    assert found.conversations == 3
    assert found.files == 2
    assert found.missing_files == 2
    assert found.projects == 0
    assert found.memories == 0
    assert found.fingerprint == hashlib.sha256((chatgpt_dir / "conversations.json").read_bytes()).hexdigest()


def test_files_are_the_members_that_are_not_documents_and_not_the_rendering() -> None:
    assert chatgpt.is_file("file-aaaa1111.dat")
    assert chatgpt.is_file("dalle-generations/a.png")
    assert chatgpt.is_file("user-abc/photo.jpg")
    assert not chatgpt.is_file("conversations.json")
    assert not chatgpt.is_file("chat.html")
    assert not chatgpt.is_file("conversation_asset_file_names.json")


def test_a_split_export_is_counted_across_its_members_in_name_order(chatgpt_split_zip: Path, tmp_path: Path) -> None:
    found = reading(chatgpt_split_zip)
    with zipfile.ZipFile(chatgpt_split_zip) as archive:
        expected = hashlib.sha256(
            archive.read("conversations-001.json") + archive.read("conversations-002.json")
        ).hexdigest()

    assert found.conversations == 3
    assert found.fingerprint == expected
    assert found.files == 0
    assert found.missing_files == 0


def test_the_split_members_hash_in_name_order_however_the_zip_lists_them(tmp_path: Path) -> None:
    """One identity for a split export, whatever order the vendor wrote its members in."""
    first = json.dumps([conversation(title="1")]).encode()
    second = json.dumps([conversation(title="2"), conversation(title="3")]).encode()
    reversed_listing = tmp_path / "reversed.zip"
    with zipfile.ZipFile(reversed_listing, "w") as archive:
        archive.writestr("conversations-002.json", second)
        archive.writestr("user.json", "{}")
        archive.writestr("conversations-001.json", first)

    found = reading(reversed_listing)

    assert found.conversations == 3
    assert found.fingerprint == hashlib.sha256(first + second).hexdigest()


def test_the_object_with_a_conversations_key_shape_is_accepted(tmp_path: Path) -> None:
    wrapped = zipped(
        tmp_path / "wrapped.zip",
        {"conversations.json": {"conversations": [conversation(), conversation()]}, "user.json": {"id": "user-1"}},
    )
    assert reading(wrapped).conversations == 2


def test_a_referenced_attachment_with_no_member_is_a_gap_and_a_carried_one_is_not(tmp_path: Path) -> None:
    node = {
        "id": "n1",
        "parent": None,
        "children": [],
        "message": {
            "metadata": {
                "attachments": [
                    {"id": "file-carried1"},
                    {"id": "file_carried2"},
                    {"id": "file-missing3"},
                    {"id": "file-carried1"},
                ]
            }
        },
    }
    archive = zipped(
        tmp_path / "gaps.zip",
        {
            "conversations.json": [conversation(mapping={"n1": node})],
            "user.json": {},
            "file-carried1.dat": b"1",
            "user-x/file_carried2-photo.png": b"2",
        },
    )
    found = reading(archive)

    assert found.files == 2
    assert found.missing_files == 1


def test_an_attachment_without_a_file_id_is_not_counted(tmp_path: Path) -> None:
    node = {"id": "n", "message": {"metadata": {"attachments": [{"id": "sediment"}, {"name": "x"}, "junk"]}}}
    archive = zipped(tmp_path / "odd.zip", {"conversations.json": [conversation(mapping={"n": node})], "user.json": {}})

    assert reading(archive).missing_files == 0


def test_user_json_is_read_only_far_enough_to_be_an_object(tmp_path: Path) -> None:
    fine = zipped(tmp_path / "fine.zip", {"conversations.json": [conversation()], "user.json": {"anything": 1}})
    assert reading(fine).conversations == 1

    bad = zipped(tmp_path / "bad.zip", {"conversations.json": [conversation()], "user.json": ["not", "an", "object"]})
    with pytest.raises(ExportError) as raised:
        reading(bad)
    assert raised.value.detail == f"user.json is not an object: {bad}"


# --------------------------------------------------------------------------- #
# Refused
# --------------------------------------------------------------------------- #


def test_a_claude_archive_is_refused_by_the_name_of_what_it_looks_like(export_zip: Path) -> None:
    with pytest.raises(ExportError) as raised:
        reading(export_zip)

    assert raised.value.detail == f"the archive looks like a Claude export, not a ChatGPT one: {export_zip}"


def test_a_claude_shaped_conversation_is_refused_even_without_users_json(tmp_path: Path) -> None:
    archive = zipped(
        tmp_path / "shape.zip", {"conversations.json": [{"uuid": "c", "chat_messages": []}], "user.json": {}}
    )

    with pytest.raises(ExportError) as raised:
        reading(archive)

    assert raised.value.detail == f"the archive looks like a Claude export, not a ChatGPT one: {archive}"


def test_no_conversations_member_is_refused_naming_both_spellings(tmp_path: Path) -> None:
    archive = zipped(tmp_path / "none.zip", {"user.json": {}})

    with pytest.raises(ExportError) as raised:
        reading(archive)

    assert raised.value.detail == (
        f"no conversations member in the archive (conversations.json or conversations-NNN.json): {archive}"
    )


def test_a_conversation_without_a_mapping_is_invalid(tmp_path: Path) -> None:
    archive = zipped(tmp_path / "flat.zip", {"conversations.json": [{"title": "x"}], "user.json": {}})

    with pytest.raises(ExportError) as raised:
        reading(archive)

    assert raised.value.detail == f"invalid conversation at conversations.json[0] (mapping: Field required): {archive}"


def test_a_member_that_is_not_an_array_is_refused(tmp_path: Path) -> None:
    archive = zipped(tmp_path / "obj.zip", {"conversations.json": {"title": "x"}, "user.json": {}})

    with pytest.raises(ExportError) as raised:
        reading(archive)

    assert raised.value.detail == f"conversations.json is not a JSON array of conversations: {archive}"


def test_a_conversation_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    archive = zipped(tmp_path / "str.zip", {"conversations.json": ["x"], "user.json": {}})

    with pytest.raises(ExportError) as raised:
        reading(archive)

    assert raised.value.detail == f"conversations.json[0] is not an object: {archive}"


# --------------------------------------------------------------------------- #
# Filed
# --------------------------------------------------------------------------- #


def test_from_files_a_chatgpt_archive_with_the_chatgpt_block(settings: Settings, chatgpt_zip: Path) -> None:
    sink = Collected()
    outcome = extract.file(settings, chatgpt_zip, sink=sink)

    assert outcome.exit_code == ExitCode.OK
    assert outcome.snapshot is not None
    assert outcome.path is not None
    stamp = outcome.snapshot.stamp
    assert sink.stdout == (
        "ChatGPT extraction — work\n"
        "\n"
        "Filed chatgpt-small.zip.\n"
        "Conversations: 3     Files: 2\n"
        "Gaps: 2 files the export does not carry\n"
        "\n"
        f"Snapshot: {settings.store_display}/chatgpt/work/{stamp}\n"
    )
    assert (outcome.path / store.ARCHIVE_NAME).read_bytes() == chatgpt_zip.read_bytes()
    assert (outcome.path / store.COMPLETE_NAME).exists()


def test_the_manifest_of_a_chatgpt_snapshot_counts_files(settings: Settings, chatgpt_zip: Path) -> None:
    outcome = extract.file(settings, chatgpt_zip, sink=Collected())
    assert outcome.path is not None
    manifest = json.loads((outcome.path / store.MANIFEST_NAME).read_text(encoding="utf-8"))

    assert manifest["counts"] == {"conversations": 3, "projects": 0, "memories": 0, "files": 2}
    assert manifest["gaps"] == [
        {"kind": "bytes_not_in_export", "count": 2, "reason": "files the export does not carry"}
    ]
    assert manifest["source"] == "chatgpt"


def test_a_claude_manifest_still_carries_no_files_key(tmp_path: Path) -> None:
    """`Counts.files` is absent, not `null`, for a source that does not count them."""
    claude = store.Counts(conversations=1, projects=0, memories=0)
    assert json.loads(claude.model_dump_json()) == {"conversations": 1, "projects": 0, "memories": 0}
    assert store.Counts.model_validate({"conversations": 1, "projects": 0, "memories": 0}).files is None
    assert store.Counts.model_validate({"conversations": 1, "files": 4}).files == 4


def test_the_wrong_source_is_refused_before_anything_is_filed(
    settings: Settings, export_zip: Path, chatgpt_zip: Path, tmp_path: Path
) -> None:
    with pytest.raises(FetchError) as raised:
        extract.file(settings, export_zip, sink=Collected())
    assert str(raised.value) == f"the archive looks like a Claude export, not a ChatGPT one: {export_zip}"
    assert not (settings.store_dir / "chatgpt").exists()

    claude_settings = with_account(settings, "claude", "old")
    with pytest.raises(FetchError) as raised:
        extract.file(claude_settings, chatgpt_zip, sink=Collected())
    assert str(raised.value) == f"the archive looks like a ChatGPT export, not a Claude one: {chatgpt_zip}"
    assert not (settings.store_dir / "claude").exists()


def test_a_chatgpt_row_lists_like_any_other(settings: Settings, chatgpt_zip: Path) -> None:
    outcome = extract.file(settings, chatgpt_zip, sink=Collected())
    assert outcome.snapshot is not None
    sink = Collected()
    store.list_command(settings, sink=sink)

    assert sink.stdout == f"chatgpt/work   {outcome.snapshot.stamp}   3 conversations   2 gaps\n"


def test_the_source_s_hooks_are_the_reader_s() -> None:
    assert CHATGPT.recognise(["user.json"]) is True
    assert CLAUDE.recognise(["user.json"]) is False
    assert CHATGPT.fetch_needs_session is True
    assert CHATGPT.hosts == ("chatgpt.com", "auth.openai.com")


# --------------------------------------------------------------------------- #
# Not yet: the ask and the fetch through the session
# --------------------------------------------------------------------------- #


def test_the_chatgpt_ask_and_fetch_say_they_are_not_built_yet(settings: Settings) -> None:
    """Until `44` and `45`: exit `69`, `30`'s answer for a mode a later slice builds."""
    sink = Collected()
    outcome = extract.ask(settings, sink=sink)
    assert outcome.exit_code == ExitCode.NOT_IMPLEMENTED
    assert sink.stderr == "not implemented in this build: the ChatGPT ask\n"

    sink = Collected()
    outcome = extract.fetch(settings, "https://chatgpt.com/__mock/exports/t.zip", sink=sink)
    assert outcome.exit_code == ExitCode.NOT_IMPLEMENTED
    assert sink.stderr == "not implemented in this build: a fetch through the ChatGPT session\n"


# --------------------------------------------------------------------------- #
# Refused by `import`
# --------------------------------------------------------------------------- #


def test_a_chatgpt_zip_cannot_be_imported_and_says_why(chatgpt_zip: Path) -> None:
    with pytest.raises(ExportError) as raised:
        load_export(chatgpt_zip)

    assert raised.value.detail == (
        f"a ChatGPT export cannot be imported by this build ({chatgpt_zip}); "
        "a snapshot of a source the tool cannot import is still a backup (ADR 0005)"
    )


def test_a_chatgpt_snapshot_cannot_be_imported_and_says_why(settings: Settings, chatgpt_zip: Path) -> None:
    outcome = extract.file(settings, chatgpt_zip, sink=Collected())
    assert outcome.path is not None

    with pytest.raises(ExportError) as raised:
        load_export(outcome.path)

    assert raised.value.detail == (
        f"a ChatGPT snapshot cannot be imported by this build ({outcome.path}); "
        "a snapshot of a source the tool cannot import is still a backup (ADR 0005)"
    )


def test_inspect_and_a_dry_run_exit_2_on_a_chatgpt_snapshot(
    runner: CliRunner, settings: Settings, chatgpt_zip: Path, workspace: Path
) -> None:
    outcome = extract.file(settings, chatgpt_zip, sink=Collected())
    assert outcome.path is not None

    for argv in (
        ["inspect", str(outcome.path)],
        ["import", "--dry-run", str(outcome.path)],
        ["inspect", str(chatgpt_zip)],
    ):
        result = runner.invoke(cli.app, argv, catch_exceptions=False)
        assert result.exit_code == ExitCode.USAGE, argv
        assert "cannot be imported by this build" in result.stderr
        assert "ADR 0005" in result.stderr
    assert not (workspace / "plan.json").exists()
