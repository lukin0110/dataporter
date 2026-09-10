"""Rendering.

`04` owns the seed format; this module holds the tests that pin it, because `03`
cannot compute `chunk_count` or `estimated_seed_chars` without the rendering being
real. `04` adds the golden `part-NN.txt` files on top of these.
"""

from datetime import UTC, datetime

import pytest

from dataporter import render
from dataporter.export.model import ChatMessage, Conversation

WHEN = datetime(2024, 5, 3, 9, 0, tzinfo=UTC)


def message(
    uuid: str = "m1",
    *,
    sender: str = "human",
    text: str = "",
    content: list[object] | None = None,
    minute: int = 0,
) -> ChatMessage:
    return ChatMessage.model_validate(
        {
            "uuid": uuid,
            "sender": sender,
            "text": text,
            "content": content or [],
            "created_at": WHEN.replace(minute=minute),
        }
    )


def conversation(
    name: str = "A chat", uuid: str = "abcdef01-2222-4222-8222-x"
) -> Conversation:
    return Conversation.model_validate(
        {"uuid": uuid, "name": name, "created_at": WHEN, "updated_at": WHEN}
    )


def render_one(
    messages: list[ChatMessage], *, max_chars: int = 50_000, **kwargs: object
) -> render.RenderedConversation:
    return render.render_conversation(
        conversation(), messages, max_chars=max_chars, **kwargs
    )


# --------------------------------------------------------------------------- #
# Blocks
# --------------------------------------------------------------------------- #


def test_a_text_block_renders_verbatim() -> None:
    rendered = render.render_message(
        message(content=[{"type": "text", "text": "Hello\n\nthere"}])
    )
    assert rendered.text == "User (2024-05-03 09:00 UTC):\nHello\n\nthere"
    assert rendered.has_original_content


def test_an_artifact_tool_use_renders_as_a_fenced_block() -> None:
    rendered = render.render_message(
        message(
            sender="assistant",
            content=[
                {
                    "type": "tool_use",
                    "name": "artifacts",
                    "input": {
                        "title": "Shorter sum",
                        "language": "python",
                        "content": "total = sum(values)",
                    },
                }
            ],
        )
    )
    assert (
        "[Artifact: Shorter sum]\n```python\ntotal = sum(values)\n```" in rendered.text
    )
    assert rendered.has_original_content


def test_an_artifact_containing_a_fence_gets_a_longer_one() -> None:
    """A fence the artifact can close is a fence that spills the rest as prose."""
    rendered = render.render_message(
        message(
            content=[
                {
                    "type": "tool_use",
                    "name": "artifacts",
                    "input": {"title": "Doc", "content": "```py\nx = 1\n```"},
                }
            ]
        )
    )
    assert "````\n```py\nx = 1\n```\n````" in rendered.text


def test_other_tool_calls_are_summarised_and_counted() -> None:
    rendered = render.render_message(
        message(content=[{"type": "tool_use", "name": "web_search", "input": {}}])
    )
    assert "[Tool call: web_search]" in rendered.text
    assert rendered.limitations.tool_calls_summarised == 1
    assert not rendered.has_original_content


def test_thinking_is_omitted_and_token_budget_is_not_counted() -> None:
    rendered = render.render_message(
        message(
            content=[
                {"type": "thinking", "thinking": "hmm"},
                {"type": "token_budget"},
                {"type": "text", "text": "Yes"},
            ]
        )
    )
    assert "hmm" not in rendered.text
    assert rendered.limitations.thinking_omitted == 1
    assert rendered.limitations.unknown_blocks == 0


def test_a_tool_result_is_a_placeholder_and_not_original_content() -> None:
    """`03`'s `no_representable_text` example: characters, but nothing the user saw."""
    rendered = render.render_message(
        message(content=[{"type": "tool_result", "content": "created"}])
    )
    assert "[Tool result omitted]" in rendered.text
    assert not rendered.has_original_content


def test_an_unknown_block_is_named_and_counted() -> None:
    rendered = render.render_message(
        message(content=[{"type": "mcp_tool_use", "server": "reports"}])
    )
    assert "[Unsupported content: mcp_tool_use]" in rendered.text
    assert rendered.limitations.unknown_blocks == 1


def test_an_empty_content_list_falls_back_to_the_message_text() -> None:
    """`02` allows either to be the populated one."""
    rendered = render.render_message(message(text="Only in text"))
    assert "Only in text" in rendered.text
    assert rendered.has_original_content


def test_a_message_with_neither_text_nor_content_has_nothing_to_migrate() -> None:
    rendered = render.render_message(message())
    assert rendered.text == "User (2024-05-03 09:00 UTC):"
    assert not rendered.has_original_content


# --------------------------------------------------------------------------- #
# Attachments
# --------------------------------------------------------------------------- #


INLINE = render.AttachmentRender(
    file_name="q3.txt",
    file_type="text/plain",
    file_size=61,
    klass="inline",
    extracted_content="Q3 revenue: flat.",
)
UPLOAD = render.AttachmentRender(
    file_name="q3.png", file_type=None, file_size=None, klass="upload"
)
MISSING = render.AttachmentRender(
    file_name="q3.png",
    file_type=None,
    file_size=None,
    klass="unsupported",
    reason="bytes_not_in_export",
)


def test_an_inline_attachment_reproduces_its_text() -> None:
    rendered = render.render_message(message(text="See this"), [INLINE])
    assert (
        "[Attachment: q3.txt (text/plain, 61 bytes)]\n<<<\nQ3 revenue: flat.\n>>>"
        in rendered.text
    )


def test_an_upload_and_an_unsupported_attachment_render_as_one_line_each() -> None:
    rendered = render.render_message(message(text="See these"), [UPLOAD, MISSING])
    assert "[File: q3.png — attached to this chat]" in rendered.text
    assert "[File: q3.png — not reproduced: bytes_not_in_export]" in rendered.text


def test_an_inline_attachment_alone_is_original_content() -> None:
    """The user saw the file's text, even though the turn carried no prose."""
    assert render.render_message(message(), [INLINE]).has_original_content
    assert not render.render_message(message(), [UPLOAD]).has_original_content


# --------------------------------------------------------------------------- #
# The envelope
# --------------------------------------------------------------------------- #


def test_a_single_part_seed_has_the_header_and_the_final_footer() -> None:
    rendered = render_one([message(text="Hi")])
    text = rendered.chunks[0]
    assert text.startswith(
        "This is a migrated conversation.\n\nOriginal conversation:\nA chat\n"
    )
    assert "Part 1 of 1\n" in text
    assert "Do not summarise it. Reply with exactly one line:\n" in text
    assert text.endswith("MIGRATION-ACK abcdef01 1/1\n")


def test_an_untitled_conversation_says_so() -> None:
    blank = Conversation.model_validate(
        {"uuid": "abcdef01-x", "name": "  ", "created_at": WHEN, "updated_at": WHEN}
    )
    text = render.render_conversation(blank, [message(text="Hi")], max_chars=50_000)
    assert "Original conversation:\n(untitled)\n" in text.chunks[0]


def test_later_parts_replace_the_header_with_a_continuation_line() -> None:
    messages = [message(f"m{i}", text="x" * 400, minute=i) for i in range(10)]
    rendered = render_one(messages, max_chars=1_200)
    assert len(rendered.chunks) > 1
    assert rendered.chunks[1].startswith(
        f"Migrated conversation abcdef01, part 2 of {len(rendered.chunks)}, continued."
    )
    assert "This is a migrated conversation." not in rendered.chunks[1]


def test_every_part_but_the_last_asks_the_reader_to_wait() -> None:
    messages = [message(f"m{i}", text="x" * 400, minute=i) for i in range(10)]
    rendered = render_one(messages, max_chars=1_200)
    total = len(rendered.chunks)
    for position, chunk in enumerate(rendered.chunks, start=1):
        assert chunk.endswith(f"MIGRATION-ACK abcdef01 {position}/{total}\n")
        expected = "More parts" if position < total else "Continue to preserve"
        assert expected in chunk


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #


def test_parts_stay_within_the_budget() -> None:
    messages = [message(f"m{i}", text="x" * 300, minute=i) for i in range(20)]
    rendered = render_one(messages, max_chars=2_000)
    assert len(rendered.chunks) > 1
    assert all(len(chunk) <= 2_000 for chunk in rendered.chunks)


def test_a_message_larger_than_a_part_splits_at_paragraphs() -> None:
    body = "\n\n".join("para " + "y" * 200 for _ in range(10))
    rendered = render_one([message(text=body)], max_chars=1_200)
    assert len(rendered.chunks) > 1
    assert "(continued)\n" in rendered.chunks[1]


def test_a_split_message_belongs_to_no_part() -> None:
    """`04` puts `chunk_message_uuids` on `SeedChunk.message_uuids`; a fragment is
    not the message, so a half-delivered message is claimed by neither part."""
    body = "\n\n".join("para " + "y" * 200 for _ in range(10))
    rendered = render_one([message("split", text=body)], max_chars=1_200)
    assert all(uuids == [] for uuids in rendered.chunk_message_uuids)


def test_whole_messages_are_attributed_to_their_part() -> None:
    messages = [message(f"m{i}", text="x" * 300, minute=i) for i in range(6)]
    rendered = render_one(messages, max_chars=2_000)
    flat = [uuid for group in rendered.chunk_message_uuids for uuid in group]
    assert flat == [f"m{i}" for i in range(6)]


def test_an_indivisible_paragraph_is_cut_rather_than_left_unpastable() -> None:
    rendered = render_one([message(text="z" * 5_000)], max_chars=1_000)
    assert len(rendered.chunks) > 1


def test_rendering_is_byte_identical_across_calls() -> None:
    messages = [message(f"m{i}", text=f"turn {i}", minute=i) for i in range(5)]
    assert render_one(messages).chunks == render_one(messages).chunks


# --------------------------------------------------------------------------- #
# Counters
# --------------------------------------------------------------------------- #


def test_limitation_slugs_omit_zeros_and_keep_a_fixed_order() -> None:
    limitations = render.Limitations(
        branches_dropped=1,
        thinking_omitted=0,
        tool_calls_summarised=2,
        unknown_blocks=3,
    )
    assert limitations.slugs() == [
        "branches_dropped:1",
        "tool_calls_summarised:2",
        "unknown_blocks:3",
    ]


def test_counters_sum_across_the_conversation() -> None:
    messages = [
        message("m1", content=[{"type": "thinking", "thinking": "a"}], minute=0),
        message(
            "m2",
            content=[
                {"type": "thinking", "thinking": "b"},
                {"type": "text", "text": "Yes"},
            ],
            minute=1,
        ),
    ]
    rendered = render_one(messages, branches_dropped=2)
    assert rendered.limitations.thinking_omitted == 2
    assert rendered.limitations.slugs() == ["branches_dropped:2", "thinking_omitted:2"]


def test_a_conversation_of_placeholders_carries_no_original_content() -> None:
    messages = [message(content=[{"type": "tool_result", "content": "x"}])]
    assert not render_one(messages).has_original_content


SHORT_IDS = [
    ("cc000003-3333-4333-8333-333333333333", "cc000003"),
    ("abcdef01-2222-4222-8222-x", "abcdef01"),
    ("ab-cd", "abcd"),
]


@pytest.mark.parametrize(("uuid", "expected"), SHORT_IDS, ids=lambda value: str(value))
def test_the_short_id_is_the_first_eight_characters_without_dashes(
    uuid: str, expected: str
) -> None:
    assert render.short_id(uuid) == expected
