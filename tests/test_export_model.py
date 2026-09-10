"""The export models: what survives parsing, and which messages get migrated."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from dataporter.export import load_export
from dataporter.export.model import (
    KNOWN_BLOCK_TYPES,
    ChatMessage,
    ContentBlock,
    Conversation,
    KnownContentBlock,
    TextBlock,
    ToolUseBlock,
    UnknownBlock,
)

BLOCKS: TypeAdapter[list[ContentBlock]] = TypeAdapter(list[ContentBlock])


def message(
    uuid: str,
    *,
    parent: str | None = None,
    index: int | None = None,
    minute: int = 0,
    sender: str = "human",
) -> dict[str, Any]:
    return {
        "uuid": uuid,
        "text": f"message {uuid}",
        "sender": sender,
        "index": index,
        "created_at": f"2024-05-01T09:{minute:02d}:00Z",
        "parent_message_uuid": parent,
    }


def conversation(messages: list[dict[str, Any]], **extra: Any) -> Conversation:
    data: dict[str, Any] = {
        "uuid": "conv-0001",
        "name": "A chat",
        "created_at": "2024-05-01T09:00:00Z",
        "updated_at": "2024-05-01T09:30:00Z",
        "chat_messages": messages,
    }
    data.update(extra)
    return Conversation.model_validate(data)


# --------------------------------------------------------------------------- #
# Content blocks
# --------------------------------------------------------------------------- #


def test_known_block_types_match_the_union() -> None:
    """The hand-written constant is what `_coerce_block` dispatches on, so it has
    to stay in step with the union it stands for."""
    members = get_args(get_args(KnownContentBlock)[0])
    tags = {get_args(member.model_fields["type"].annotation)[0] for member in members}
    assert tags == set(KNOWN_BLOCK_TYPES)


def test_an_unknown_block_survives_as_raw() -> None:
    original = {"type": "mcp_tool_use", "server": "reports", "arguments": {"q": 3}}
    (block,) = BLOCKS.validate_python([dict(original)])
    assert isinstance(block, UnknownBlock)
    assert block.type == "mcp_tool_use"
    assert block.raw == original


def test_a_known_tag_with_a_broken_payload_is_kept_whole() -> None:
    """`input` must be an object. Keeping the block beats failing the export."""
    (block,) = BLOCKS.validate_python([{"type": "tool_use", "input": 7}])
    assert isinstance(block, UnknownBlock)
    assert block.type == "tool_use"
    assert block.raw == {"type": "tool_use", "input": 7}


def test_a_block_that_is_not_an_object_survives() -> None:
    (block,) = BLOCKS.validate_python(["just a string"])
    assert isinstance(block, UnknownBlock)
    assert block.type == ""
    assert block.raw == {"value": "just a string"}


def test_a_block_with_no_type_survives() -> None:
    (block,) = BLOCKS.validate_python([{"text": "orphaned"}])
    assert isinstance(block, UnknownBlock)
    assert block.type == ""


def test_known_blocks_dispatch_exactly() -> None:
    blocks = BLOCKS.validate_python(
        [{"type": "text", "text": "hi"}, {"type": "tool_use", "name": "artifacts"}]
    )
    assert isinstance(blocks[0], TextBlock)
    assert isinstance(blocks[1], ToolUseBlock)


# --------------------------------------------------------------------------- #
# Tolerance and immutability
# --------------------------------------------------------------------------- #


def test_unknown_fields_survive_in_model_extra() -> None:
    block = TextBlock.model_validate({"type": "text", "text": "hi", "citations": [1]})
    assert block.model_extra == {"citations": [1]}
    # And they round-trip, which is what keeps `03`'s serialisation stable.
    assert "citations" in block.model_dump()


def test_models_are_frozen() -> None:
    chat = conversation([message("m1")])
    with pytest.raises(ValidationError):
        chat.name = "renamed"


def test_extras_are_frozen_too() -> None:
    block = TextBlock.model_validate({"type": "text", "text": "hi", "citations": []})
    with pytest.raises(ValidationError):
        block.citations = [1]


# --------------------------------------------------------------------------- #
# Timestamps
# --------------------------------------------------------------------------- #

# `04` renders `{created_at as YYYY-MM-DD HH:MM UTC}` into a golden string, so an
# un-normalised offset would print the wrong hour with the word UTC beside it.
TIMESTAMPS = [
    ("2024-05-01T09:00:00.000000Z", 9),
    ("2024-05-01T11:00:00+02:00", 9),
    ("2024-05-01T09:00:00", 9),
]


@pytest.mark.parametrize("raw, hour", TIMESTAMPS, ids=lambda value: str(value))
def test_timestamps_are_utc_aware(raw: str, hour: int) -> None:
    chat = conversation([{**message("m1"), "created_at": raw}])
    created = chat.chat_messages[0].created_at
    assert created.tzinfo is not None
    assert created.utcoffset() == timedelta(0)
    assert created == datetime(2024, 5, 1, hour, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# The active path
# --------------------------------------------------------------------------- #


def test_the_named_leaf_wins() -> None:
    chat = conversation(
        [
            message("m1", index=0, minute=0),
            message("m2", parent="m1", index=1, minute=1),
            message("m3", parent="m1", index=1, minute=2),
        ],
        current_leaf_message_uuid="m2",
    )
    assert [m.uuid for m in chat.active_path()] == ["m1", "m2"]
    assert [m.uuid for m in chat.off_path()] == ["m3"]


def test_without_a_named_leaf_the_latest_childless_message_wins() -> None:
    chat = conversation(
        [
            message("m1", minute=0),
            message("m2", parent="m1", minute=1),
            message("m3", parent="m1", minute=5),
        ]
    )
    assert [m.uuid for m in chat.active_path()] == ["m1", "m3"]


def test_a_named_leaf_that_does_not_exist_falls_back() -> None:
    """One dangling pointer must not make a whole export unreadable."""
    chat = conversation(
        [message("m1", minute=0), message("m2", parent="m1", minute=1)],
        current_leaf_message_uuid="does-not-exist",
    )
    assert [m.uuid for m in chat.active_path()] == ["m1", "m2"]


def test_an_empty_conversation_has_empty_paths() -> None:
    chat = conversation([])
    assert chat.active_path() == []
    assert chat.off_path() == []


def test_a_cycle_terminates() -> None:
    chat = conversation(
        [message("m1", parent="m2", minute=0), message("m2", parent="m1", minute=1)]
    )
    assert {m.uuid for m in chat.active_path()} == {"m1", "m2"}


def test_a_missing_parent_stops_the_walk() -> None:
    """Dropping an unknown-sender message severs its children; the rest survives."""
    chat = conversation(
        [message("m2", parent="gone", minute=1), message("m3", parent="m2", minute=2)]
    )
    assert [m.uuid for m in chat.active_path()] == ["m2", "m3"]


def test_a_repeated_uuid_keeps_the_first_and_sheds_the_rest() -> None:
    chat = conversation([message("m1", minute=0), message("m1", minute=1)])
    assert [m.uuid for m in chat.active_path()] == ["m1"]
    assert len(chat.off_path()) == 1


# --------------------------------------------------------------------------- #
# Ordering
# --------------------------------------------------------------------------- #

# The rule from `specs/impl/02-export-model.md`: by `index` when present *and*
# unique, else by `created_at`, tie-broken by array position. Each row lists
# (index, minute) in export order, and the uuids the rule should produce. Every
# row is a flat conversation so that membership is never in question.
ORDERING: list[tuple[str, list[tuple[int | None, int]], list[str]]] = [
    ("index present and unique", [(2, 2), (0, 0), (1, 1)], ["m1", "m2", "m0"]),
    ("index present but repeated", [(1, 2), (1, 0), (1, 1)], ["m1", "m2", "m0"]),
    ("index partly absent", [(0, 2), (None, 0), (2, 1)], ["m1", "m2", "m0"]),
    ("index absent", [(None, 2), (None, 0), (None, 1)], ["m1", "m2", "m0"]),
    ("created_at ties", [(None, 0), (None, 0), (None, 0)], ["m0", "m1", "m2"]),
]


@pytest.mark.parametrize("name, rows, expected", ORDERING, ids=lambda item: str(item))
def test_ordering(
    name: str, rows: list[tuple[int | None, int]], expected: list[str]
) -> None:
    # Chained, so all three are on the active path and only the ordering rule
    # decides what comes out.
    messages = [
        message(
            f"m{position}",
            parent=f"m{position - 1}" if position else None,
            index=index,
            minute=minute,
        )
        for position, (index, minute) in enumerate(rows)
    ]
    chat = conversation(messages)
    assert [m.uuid for m in chat.active_path()] == expected


# --------------------------------------------------------------------------- #
# The fixture
# --------------------------------------------------------------------------- #


def test_the_branch_fixture_yields_one_lineage_and_its_sibling(
    export_dir: Path,
) -> None:
    """`03` reads this as `branches_dropped:1`."""
    export = load_export(export_dir)
    branch = next(c for c in export.conversations if c.uuid.startswith("ee000005"))
    assert [m.uuid[-3:] for m in branch.active_path()] == ["0m1", "0m2", "0m3", "0m5"]
    assert [m.uuid[-3:] for m in branch.off_path()] == ["0m4"]


def test_every_message_is_on_exactly_one_path(export_dir: Path) -> None:
    """Off-path messages are counted, never dropped."""
    export = load_export(export_dir)
    for chat in export.conversations:
        active: list[ChatMessage] = chat.active_path()
        off: list[ChatMessage] = chat.off_path()
        assert len(active) + len(off) == len(chat.chat_messages)
        assert not {id(m) for m in active} & {id(m) for m in off}
