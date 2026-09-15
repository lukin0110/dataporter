"""The mock claude.ai's chats as an export: the shape the tool validates, spelled here as literals.

`zipfile` and `json` and nothing else — the mock's tests import nothing from
`dataporter` either (ADR 0003). The keys asserted below are the ones the tool's
export model requires; if it grows a requirement, this file is where the mock
learns of it.
"""

import io
import json
import uuid
import zipfile

import pytest
from claudemock import archive
from claudemock.site import Site

from conftest import EMAIL, WALL

SEED = "Part 1 of 1\n\nReply with exactly one line:\nMIGRATION-ACK aa000001 1/1\n"

MESSAGE_KEYS = {
    "uuid",
    "text",
    "content",
    "sender",
    "created_at",
    "updated_at",
    "attachments",
    "files",
    "files_v2",
    "index",
    "parent_message_uuid",
}


@pytest.fixture
def clock() -> list[float]:
    return [100.0]


@pytest.fixture
def site(clock: list[float]) -> Site:
    return Site(email=EMAIL, reply_delay_s=1.0, reply_steps=2, clock=lambda: clock[0], wall=lambda: WALL)


def unpack(payload: bytes) -> dict[str, object]:
    with zipfile.ZipFile(io.BytesIO(payload)) as opened:
        return {name: json.loads(opened.read(name)) for name in opened.namelist()}


def test_the_archive_is_a_flat_zip_with_conversations_and_users(site: Site) -> None:
    payload = archive.render(site.all_chats(), email=EMAIL, now=site.now())
    assert zipfile.is_zipfile(io.BytesIO(payload))
    files = unpack(payload)
    assert sorted(files) == ["conversations.json", "users.json"]
    assert files["conversations.json"] == []
    assert files["users.json"] == [
        {"uuid": archive.account_uuid(EMAIL), "full_name": "Rehearsal Operator", "email_address": EMAIL}
    ]


def test_a_conversation_carries_the_keys_the_tool_validates(site: Site, clock: list[float]) -> None:
    chat = site.create_chat(SEED, session="s")
    clock[0] += 2
    site.rename(chat, "Notes on pooling")
    site.receive(chat, "and one more thing")
    clock[0] += 2

    (conversation,) = archive.conversations(site.all_chats(), email=EMAIL, now=site.now())
    assert conversation["uuid"] == chat.id
    assert conversation["name"] == "Notes on pooling"
    assert conversation["created_at"] == "2025-09-13T12:00:00.000000Z"
    assert conversation["updated_at"] == "2025-09-13T12:00:04.000000Z"
    assert conversation["account"] == {"uuid": archive.account_uuid(EMAIL)}
    messages = conversation["chat_messages"]
    assert isinstance(messages, list)
    assert [message["sender"] for message in messages] == ["human", "assistant", "human", "assistant"]
    assert [message["text"] for message in messages][1] == "MIGRATION-ACK aa000001 1/1"
    for index, message in enumerate(messages):
        assert set(message) == MESSAGE_KEYS
        assert message["index"] == index
        assert message["content"] == [{"type": "text", "text": message["text"]}]
        assert message["created_at"] == f"2025-09-13T12:00:0{index}.000000Z"
    assert messages[0]["parent_message_uuid"] is None
    assert [message["parent_message_uuid"] for message in messages[1:]] == [
        message["uuid"] for message in messages[:-1]
    ]
    assert conversation["current_leaf_message_uuid"] == messages[-1]["uuid"]


def test_a_chat_still_generating_contributes_only_its_finished_turns(site: Site, clock: list[float]) -> None:
    chat = site.create_chat(SEED, session="s")
    clock[0] += 1  # one step of two: the page shows a prefix, the archive does not
    (partial,) = archive.conversations(site.all_chats(), email=EMAIL, now=site.now())
    assert isinstance(partial["chat_messages"], list)
    assert [message["sender"] for message in partial["chat_messages"]] == ["human"]
    assert partial["current_leaf_message_uuid"] == archive.message_uuid(chat.id, 0)
    clock[0] += 1
    (whole,) = archive.conversations(site.all_chats(), email=EMAIL, now=site.now())
    assert isinstance(whole["chat_messages"], list)
    assert [message["sender"] for message in whole["chat_messages"]] == ["human", "assistant"]


def test_accepted_files_are_named_on_the_first_message_and_carried_as_bytes_nowhere(site: Site) -> None:
    """The one gap a Claude export has (§31): the archive names the files and does not carry them."""
    site.accept_file("q3-chart.png", session="s")
    site.accept_file("notes.txt", session="s")
    chat = site.create_chat(SEED, session="s")
    payload = archive.render(site.all_chats(), email=EMAIL, now=site.now())
    files = unpack(payload)
    assert sorted(files) == ["conversations.json", "users.json"]
    (conversation,) = files["conversations.json"]  # type: ignore[misc]
    first = conversation["chat_messages"][0]
    assert [ref["file_name"] for ref in first["files"]] == ["q3-chart.png", "notes.txt"]
    assert first["files_v2"] == first["files"]
    assert first["attachments"] == []
    assert all(ref["file_uuid"] != archive.message_uuid(chat.id, 0) for ref in first["files"])


def test_the_same_chats_render_the_same_bytes(site: Site, clock: list[float]) -> None:
    """A link fetched by the tool and by hand downloads one archive (§39, 2)."""
    site.create_chat(SEED, session="s")
    clock[0] += 2
    chats = site.all_chats()
    assert archive.render(chats, email=EMAIL, now=site.now()) == archive.render(chats, email=EMAIL, now=site.now())


def test_ids_are_real_uuids_and_stable() -> None:
    chat_id = "aa000001-0000-4000-8000-000000000000"
    assert uuid.UUID(archive.message_uuid(chat_id, 0)).version == 5
    assert archive.message_uuid(chat_id, 0) == archive.message_uuid(chat_id, 0)
    assert archive.message_uuid(chat_id, 0) != archive.message_uuid(chat_id, 1)
    assert uuid.UUID(archive.account_uuid(EMAIL)).version == 5
