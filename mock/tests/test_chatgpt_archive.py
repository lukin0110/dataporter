"""The mock chatgpt.com's chats as an export: the shape `docs/chatgpt-export-format.md` says.

`zipfile` and `json` and nothing else. Every key asserted below is a claim of that
document — *assumed* until a real export has been read — or a decision it marks as
brief `05`'s; if the document changes, this file is where the mock learns of it.
"""

import io
import json
import uuid
import zipfile

import pytest
from chatgptmock import archive
from chatgptmock.site import Site

from conftest import EMAIL, WALL

SEED = "Part 1 of 1\n\nReply with exactly one line:\nMIGRATION-ACK aa000001 1/1\n"

CONVERSATION_KEYS = {
    "title",
    "create_time",
    "update_time",
    "mapping",
    "current_node",
    "conversation_id",
    "id",
    "is_archived",
    "default_model_slug",
    "gizmo_id",
    "gizmo_type",
    "conversation_template_id",
    "moderation_results",
    "plugin_ids",
    "safe_urls",
    "blocked_urls",
    "disabled_tool_ids",
    "conversation_origin",
    "voice",
    "async_status",
}

MESSAGE_KEYS = {
    "id",
    "author",
    "create_time",
    "update_time",
    "content",
    "status",
    "end_turn",
    "weight",
    "metadata",
    "recipient",
    "channel",
}


@pytest.fixture
def clock() -> list[float]:
    return [100.0]


@pytest.fixture
def site(clock: list[float]) -> Site:
    return Site(email=EMAIL, password="p", reply_delay_s=1.0, reply_steps=2, clock=lambda: clock[0], wall=lambda: WALL)


def unpack(payload: bytes) -> dict[str, object]:
    with zipfile.ZipFile(io.BytesIO(payload)) as opened:
        return {name: json.loads(opened.read(name)) for name in opened.namelist()}


def active_path(conversation: dict[str, object]) -> list[dict[str, object]]:
    """Walk `parent` from `current_node` to the root: the reading three parsers use."""
    mapping = conversation["mapping"]
    assert isinstance(mapping, dict)
    path: list[dict[str, object]] = []
    node = mapping[conversation["current_node"]]
    while node is not None:
        path.append(node)
        node = mapping[node["parent"]] if node["parent"] is not None else None
    return list(reversed(path))


def test_the_archive_is_a_flat_zip_with_conversations_and_user(site: Site) -> None:
    """Two members and nothing else: an empty member would claim a feature the mock does not have."""
    payload = archive.render(site.all_chats(), email=EMAIL, now=site.now())
    assert zipfile.is_zipfile(io.BytesIO(payload))
    files = unpack(payload)
    assert sorted(files) == ["conversations.json", "user.json"]
    assert files["conversations.json"] == []
    assert files["user.json"] == {"id": archive.user_id(EMAIL), "email": EMAIL}
    assert archive.user_id(EMAIL).startswith("user-")


def test_a_conversation_is_a_root_and_the_turns_chained_under_it(site: Site, clock: list[float]) -> None:
    chat = site.create_chat(SEED, session="s")
    clock[0] += 2
    site.rename(chat, "Notes on pooling")
    site.receive(chat, "and one more thing", session="s")
    clock[0] += 2

    (conversation,) = archive.conversations(site.all_chats(), now=site.now())
    assert set(conversation) == CONVERSATION_KEYS
    assert conversation["title"] == "Notes on pooling"
    assert conversation["conversation_id"] == chat.id
    assert conversation["id"] == chat.id
    assert conversation["create_time"] == WALL
    assert conversation["update_time"] == WALL + 4
    assert conversation["is_archived"] is False
    assert conversation["default_model_slug"] == "auto"

    path = active_path(conversation)
    root, *turns = path
    assert root["message"] is None
    assert root["parent"] is None
    assert len(turns) == 4
    for index, node in enumerate(turns):
        message = node["message"]
        assert isinstance(message, dict)
        assert set(message) == MESSAGE_KEYS
        assert message["id"] == node["id"]
        assert node["parent"] == path[index]["id"]
        assert node["children"] == ([path[index + 2]["id"]] if index + 2 < len(path) else [])
        assert message["create_time"] == WALL + index
        assert message["update_time"] == WALL + index
        assert message["status"] == "finished_successfully"
        assert message["end_turn"] is True
        assert message["weight"] == pytest.approx(1.0)
        assert message["recipient"] == "all"
        assert message["channel"] is None
        assert message["author"]["name"] is None
    assert [node["message"]["author"]["role"] for node in turns] == ["user", "assistant", "user", "assistant"]
    assert turns[1]["message"]["content"] == {"content_type": "text", "parts": ["MIGRATION-ACK aa000001 1/1"]}
    assert conversation["current_node"] == turns[-1]["id"]
    assert len(conversation["mapping"]) == 5


def test_an_empty_chat_has_a_root_and_no_children(site: Site) -> None:
    """A chat that has not answered yet still has a root, and the root is the current node."""
    chat = site.create_chat(SEED, session="s")
    site.stop(chat)
    chat.messages.clear()
    (conversation,) = archive.conversations(site.all_chats(), now=site.now())
    assert list(conversation["mapping"]) == [conversation["current_node"]]
    assert conversation["mapping"][conversation["current_node"]]["children"] == []


def test_a_chat_still_generating_contributes_only_its_finished_turns(site: Site, clock: list[float]) -> None:
    chat = site.create_chat(SEED, session="s")
    clock[0] += 1  # one step of two: the page shows a prefix, the archive does not
    (partial,) = archive.conversations(site.all_chats(), now=site.now())
    assert [node["message"]["author"]["role"] for node in active_path(partial)[1:]] == ["user"]
    assert partial["current_node"] == archive.node_id(chat.id, 0)
    clock[0] += 1
    (whole,) = archive.conversations(site.all_chats(), now=site.now())
    assert [node["message"]["author"]["role"] for node in active_path(whole)[1:]] == ["user", "assistant"]


def test_pasted_texts_are_parts_before_the_typed_text(site: Site) -> None:
    """`text` only: the pasted texts and the typed text are one message's `parts`."""
    chat = site.create_chat("here it is", pasted=[SEED], session="s")
    (conversation,) = archive.conversations(site.all_chats(), now=site.now())
    (user,) = active_path(conversation)[1:]
    assert user["message"]["content"] == {"content_type": "text", "parts": [SEED, "here it is"]}
    site.stop(chat)
    site.receive(chat, "", pasted=[SEED], session="s")
    (conversation,) = archive.conversations(site.all_chats(), now=site.now())
    assert active_path(conversation)[-1]["message"]["content"]["parts"] == [SEED]


def test_accepted_files_are_named_on_the_message_that_carried_them_and_carried_nowhere(site: Site) -> None:
    """The one gap this archive has (§55): a file is named, never carried."""
    site.accept_file("q3-chart.png", 3, session="s")
    site.accept_file("notes.txt", 5, session="s")
    chat = site.create_chat(SEED, session="s")
    payload = archive.render(site.all_chats(), email=EMAIL, now=site.now())
    files = unpack(payload)
    assert sorted(files) == ["conversations.json", "user.json"]
    (conversation,) = files["conversations.json"]  # type: ignore[misc]
    user, *_ = active_path(conversation)[1:]
    attachments = user["message"]["metadata"]["attachments"]
    assert [(entry["name"], entry["mime_type"], entry["size"]) for entry in attachments] == [
        ("q3-chart.png", "image/png", 3),
        ("notes.txt", "text/plain", 5),
    ]
    assert all(entry["id"].startswith("file-") for entry in attachments)
    assert len({entry["id"] for entry in attachments}) == 2
    assert all(entry["id"] != archive.node_id(chat.id, 0) for entry in attachments)


def test_a_message_without_files_has_no_attachments_key(site: Site) -> None:
    site.create_chat(SEED, session="s")
    (conversation,) = archive.conversations(site.all_chats(), now=site.now())
    assert active_path(conversation)[1]["message"]["metadata"] == {}


def test_the_same_chats_render_the_same_bytes(site: Site, clock: list[float]) -> None:
    """A link fetched twice downloads one archive."""
    site.accept_file("q3-chart.png", 3, session="s")
    site.create_chat(SEED, session="s")
    clock[0] += 2
    chats = site.all_chats()
    assert archive.render(chats, email=EMAIL, now=site.now()) == archive.render(chats, email=EMAIL, now=site.now())


def test_ids_are_real_uuids_and_stable() -> None:
    chat_id = "aa000001-0000-4000-8000-000000000000"
    assert uuid.UUID(archive.node_id(chat_id, 0)).version == 5
    assert archive.node_id(chat_id, 0) == archive.node_id(chat_id, 0)
    assert archive.node_id(chat_id, 0) != archive.node_id(chat_id, 1)
    assert archive.node_id(chat_id, "root") not in {archive.node_id(chat_id, 0), archive.node_id(chat_id, 1)}
    assert archive.user_id(EMAIL) == archive.user_id(EMAIL)
    assert archive.user_id(EMAIL) != archive.user_id("someone@example.invalid")
