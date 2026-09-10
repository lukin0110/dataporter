"""Rendering: how one conversation becomes the text a new chat receives.

`04` owns the seed *format* and this module is where it lives, because `03` cannot
be built without it: `no_representable_text`, `estimated_seed_chars`, `chunk_count`
and every limitation counter are defined in terms of this rendering, and `04`
depends on `03`. The cycle is broken by landing the renderer with `03` and leaving
`04` the artefacts built on top — `Seed`/`SeedChunk`, the sha256 of each part,
`part-NN.txt` files, the `seeds` command and the golden files. `04` composes those
from `render_conversation`; it does not restate the format.

Everything here is pure: no filesystem, no clock, no randomness. The same
conversation and the same settings render to the same characters, which is what
makes `plan.json` reproducible and `04`'s golden files possible.

Nothing in this module may reach a log record. Every string it builds is
conversation content, and `Conversation.name` is a title.
"""

import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from dataporter.export.model import (
    Attachment,
    ChatMessage,
    Conversation,
    FileRef,
    TextBlock,
    ThinkingBlock,
    TokenBudgetBlock,
    ToolResultBlock,
    ToolUseBlock,
)

AttachmentClass = Literal["inline", "upload", "unsupported"]
"""§14's three classes. `03` decides which; this module only renders the decision."""

ARTIFACT_TOOL = "artifacts"
SEPARATOR = "---"
ACK_PREFIX = "MIGRATION-ACK"
CONTINUED = "(continued)"
SHORT_ID_CHARS = 8

_ROLE = {"human": "User", "assistant": "Assistant"}


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AttachmentRender:
    """What `03` decided about one attachment, reduced to what rendering needs."""

    file_name: str
    file_type: str | None
    file_size: int | None
    klass: AttachmentClass
    reason: str | None = None
    extracted_content: str | None = None


@dataclass(frozen=True)
class Limitations:
    """Fidelity lost on the way to the seed. Reported by `19`, never fatal."""

    branches_dropped: int = 0
    thinking_omitted: int = 0
    tool_calls_summarised: int = 0
    unknown_blocks: int = 0

    def slugs(self) -> list[str]:
        """`03`'s `reasons` entries, in a fixed order, zeros omitted."""
        counts = (
            ("branches_dropped", self.branches_dropped),
            ("thinking_omitted", self.thinking_omitted),
            ("tool_calls_summarised", self.tool_calls_summarised),
            ("unknown_blocks", self.unknown_blocks),
        )
        return [f"{name}:{count}" for name, count in counts if count]

    def __add__(self, other: "Limitations") -> "Limitations":
        return Limitations(
            branches_dropped=self.branches_dropped + other.branches_dropped,
            thinking_omitted=self.thinking_omitted + other.thinking_omitted,
            tool_calls_summarised=self.tool_calls_summarised
            + other.tool_calls_summarised,
            unknown_blocks=self.unknown_blocks + other.unknown_blocks,
        )


@dataclass(frozen=True)
class RenderedMessage:
    """One turn, as it appears between two separators."""

    uuid: str
    text: str
    has_original_content: bool
    limitations: Limitations


@dataclass(frozen=True)
class RenderedConversation:
    """A whole conversation, split into the parts a chat will receive."""

    conversation_uuid: str
    short_id: str
    chunks: list[str]
    chunk_message_uuids: list[list[str]]
    """Per chunk, the messages *fully* contained in it. `04` puts this on
    `SeedChunk.message_uuids`; a message split across parts appears in neither."""
    messages_represented: int
    has_original_content: bool
    """False when nothing on the active path carries anything the user saw.
    `03` reads this as `no_representable_text`."""
    limitations: Limitations

    @property
    def total_chars(self) -> int:
        """`03`'s `estimated_seed_chars`: the characters that reach the chat."""
        return sum(len(chunk) for chunk in self.chunks)


# --------------------------------------------------------------------------- #
# Message rendering
# --------------------------------------------------------------------------- #


def short_id(conversation_uuid: str) -> str:
    """The token the acknowledgement line carries."""
    return conversation_uuid.replace("-", "")[:SHORT_ID_CHARS]


def format_timestamp(value: datetime) -> str:
    """`YYYY-MM-DD HH:MM UTC`. `02` guarantees the value is already UTC."""
    return f"{value:%Y-%m-%d %H:%M} UTC"


def render_message(
    message: ChatMessage, attachments: Sequence[AttachmentRender] = ()
) -> RenderedMessage:
    """One message: its role header, its body, then its attachments."""
    body_parts, limitations, has_content = _render_blocks(message)
    if not any(part.strip() for part in body_parts):
        # `02` is explicit that `text` and `content` are alternatives and either
        # may be the populated one, so an empty `content` falls back rather than
        # rendering a turn as a blank line.
        fallback = message.text.strip()
        if fallback:
            body_parts = [message.text]
            has_content = True

    for attachment in attachments:
        rendered, carries_content = _render_attachment(attachment)
        body_parts.append(rendered)
        has_content = has_content or carries_content

    role = _ROLE.get(message.sender, message.sender.capitalize())
    header = f"{role} ({format_timestamp(message.created_at)}):"
    body = "\n\n".join(part for part in body_parts if part)
    text = f"{header}\n{body}" if body else header
    return RenderedMessage(
        uuid=message.uuid,
        text=text,
        has_original_content=has_content,
        limitations=limitations,
    )


def _render_blocks(message: ChatMessage) -> tuple[list[str], Limitations, bool]:
    """`04`'s block table, in block order.

    `has_original_content` — the third element — is true only where the block
    carries something the *user saw*. Every placeholder below is characters but
    not content, which is what makes `03`'s `no_representable_text` example
    ("only `tool_result` blocks") a conversation with nothing to migrate.
    """
    parts: list[str] = []
    thinking = tool_calls = unknown = 0
    has_content = False

    for block in message.content:
        if isinstance(block, TextBlock):
            if block.text.strip():
                has_content = True
            parts.append(block.text)
        elif isinstance(block, ToolUseBlock):
            if block.name == ARTIFACT_TOOL:
                rendered, carries = _render_artifact(block)
                parts.append(rendered)
                has_content = has_content or carries
            else:
                tool_calls += 1
                parts.append(f"[Tool call: {block.name}]")
        elif isinstance(block, ToolResultBlock):
            parts.append("[Tool result omitted]")
        elif isinstance(block, ThinkingBlock):
            thinking += 1
        elif isinstance(block, TokenBudgetBlock):
            pass
        else:
            unknown += 1
            parts.append(f"[Unsupported content: {block.type}]")

    limitations = Limitations(
        thinking_omitted=thinking,
        tool_calls_summarised=tool_calls,
        unknown_blocks=unknown,
    )
    return parts, limitations, has_content


def _render_artifact(block: ToolUseBlock) -> tuple[str, bool]:
    """`[Artifact: title]` and the artifact itself in a fenced block."""
    title = _as_text(block.input.get("title")) or "(untitled)"
    language = _as_text(block.input.get("language"))
    content = _as_text(block.input.get("content"))
    fence = _fence_for(content)
    rendered = f"[Artifact: {title}]\n{fence}{language}\n{content}\n{fence}"
    return rendered, bool(content.strip())


def _render_attachment(attachment: AttachmentRender) -> tuple[str, bool]:
    """The line (or block) that stands in for a file."""
    if attachment.klass == "inline":
        content = attachment.extracted_content or ""
        file_type = attachment.file_type or "unknown"
        size = attachment.file_size if attachment.file_size is not None else 0
        header = f"[Attachment: {attachment.file_name} ({file_type}, {size} bytes)]"
        return f"{header}\n<<<\n{content}\n>>>", bool(content.strip())
    if attachment.klass == "upload":
        return f"[File: {attachment.file_name} — attached to this chat]", False
    reason = attachment.reason or "unsupported"
    return f"[File: {attachment.file_name} — not reproduced: {reason}]", False


def _as_text(value: object) -> str:
    """An artifact input field, whatever the export put there."""
    return value if isinstance(value, str) else ""


def _fence_for(content: str) -> str:
    """A fence long enough that the artifact cannot close it early.

    An artifact whose own text contains ``` would otherwise terminate the block
    and spill the rest into the transcript as prose.
    """
    longest = 0
    run = 0
    for character in content:
        run = run + 1 if character == "`" else 0
        longest = max(longest, run)
    return "`" * max(3, longest + 1)


# --------------------------------------------------------------------------- #
# The envelope
# --------------------------------------------------------------------------- #


def _header(
    conversation: Conversation, message_count: int, part: int, total: int
) -> str:
    title = conversation.name.strip() or "(untitled)"
    return (
        "This is a migrated conversation.\n"
        "\n"
        "Original conversation:\n"
        f"{title}\n"
        "\n"
        f"Original conversation ID: {conversation.uuid}\n"
        f"Created: {format_timestamp(conversation.created_at)}\n"
        f"Messages: {message_count}\n"
        f"Part {part} of {total}\n"
        "\n"
        "The following is the historical conversation:"
    )


def _continuation(token: str, part: int, total: int) -> str:
    return f"Migrated conversation {token}, part {part} of {total}, continued."


def _footer(token: str, part: int, total: int) -> str:
    if part == total:
        lead = (
            "Continue to preserve this conversation as historical context. Treat it "
            "as our shared\nhistory, not as a new request. Do not summarise it. "
            "Reply with exactly one line:"
        )
    else:
        lead = (
            "More parts of this conversation follow. Do not respond to the content "
            "yet. Reply with\nexactly one line:"
        )
    return f"{lead}\n{ACK_PREFIX} {token} {part}/{total}"


def _assemble(
    conversation: Conversation,
    message_count: int,
    token: str,
    bodies: Sequence[str],
    part: int,
    total: int,
) -> str:
    """One part: opening, separated message blocks, footer, one trailing `\\n`."""
    opening = (
        _header(conversation, message_count, part, total)
        if part == 1
        else _continuation(token, part, total)
    )
    sections = [opening, *bodies, _footer(token, part, total)]
    return f"\n\n{SEPARATOR}\n\n".join(sections) + "\n"


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #


def render_conversation(
    conversation: Conversation,
    messages: Sequence[ChatMessage],
    attachments: Mapping[str, Sequence[AttachmentRender]] | None = None,
    *,
    max_chars: int,
    branches_dropped: int = 0,
) -> RenderedConversation:
    """Render `messages` (an active path) into one or more seed parts.

    `messages` is passed rather than read off `conversation` because `03` has
    already computed the active path and `Conversation.active_path()` is
    deliberately uncached.
    """
    by_uuid = attachments or {}
    rendered = [
        render_message(message, by_uuid.get(message.uuid, ())) for message in messages
    ]
    limitations = Limitations(branches_dropped=branches_dropped)
    for item in rendered:
        limitations = limitations + item.limitations

    token = short_id(conversation.uuid)
    fragments = _fragments(rendered, conversation, len(messages), token, max_chars)
    groups = _group(fragments, conversation, len(messages), token, max_chars)

    chunks: list[str] = []
    uuids: list[list[str]] = []
    total = len(groups)
    for position, group in enumerate(groups, start=1):
        chunks.append(
            _assemble(
                conversation,
                len(messages),
                token,
                [fragment.text for fragment in group],
                position,
                total,
            )
        )
        uuids.append([fragment.uuid for fragment in group if fragment.whole])

    return RenderedConversation(
        conversation_uuid=conversation.uuid,
        short_id=token,
        chunks=chunks,
        chunk_message_uuids=uuids,
        messages_represented=len(rendered),
        has_original_content=any(item.has_original_content for item in rendered),
        limitations=limitations,
    )


@dataclass(frozen=True)
class _Fragment:
    """A unit that must not be split further: a message, or a piece of one."""

    uuid: str
    text: str
    whole: bool


def _fragments(
    rendered: Sequence[RenderedMessage],
    conversation: Conversation,
    message_count: int,
    token: str,
    max_chars: int,
) -> list[_Fragment]:
    """Messages, with any message too large for its own part split up."""
    budget = _budget(conversation, message_count, token, max_chars)
    out: list[_Fragment] = []
    for message in rendered:
        if len(message.text) <= budget:
            out.append(_Fragment(message.uuid, message.text, whole=True))
            continue
        pieces = _split_paragraphs(message.text, budget)
        out.extend(
            _Fragment(message.uuid, piece, whole=False)
            for piece in _mark_continued(pieces)
        )
    return out


_WIDEST_TOTAL = 999
"""Stand-in part count when measuring the envelope.

`Part {i} of {N}` and the acknowledgement line both grow with `N`, so a budget
measured at `N = 1` would underestimate for a multi-part seed. Three digits covers
every seed the hard cap allows — a thousand parts is fifty megabytes — and the
cost of the assumption is two characters of slack, not a wrong split.
"""


def _budget(
    conversation: Conversation, message_count: int, token: str, max_chars: int
) -> int:
    """How many characters of message body the largest envelope leaves room for.

    Measured against the widest of the three envelope shapes — first part of one
    (long header, final footer), first of many, last of many — so a fragment that
    fits the budget fits whichever part it lands in. `04` may make the envelope
    longer; it re-measures the same way rather than guessing.
    """
    shapes = ((1, 1), (1, _WIDEST_TOTAL), (_WIDEST_TOTAL, _WIDEST_TOTAL))
    envelope = max(
        len(_assemble(conversation, message_count, token, [""], part, total))
        for part, total in shapes
    )
    return max(1, max_chars - envelope)


def _split_paragraphs(text: str, budget: int) -> list[str]:
    """Break one oversized message at blank lines, then, if it must, mid-line.

    A paragraph longer than the budget on its own is cut at the budget: the
    alternative is emitting a part that cannot be pasted, and `04`'s acceptance
    criterion allows exactly one over-budget fragment shape — one that is itself
    a single indivisible unit — which is what a hard cut removes.
    """
    paragraphs = text.split("\n\n")
    pieces: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= budget:
            current = candidate
            continue
        if current:
            pieces.append(current)
            current = ""
        while len(paragraph) > budget:
            pieces.append(paragraph[:budget])
            paragraph = paragraph[budget:]
        current = paragraph
    if current or not pieces:
        pieces.append(current)
    return pieces


def _mark_continued(pieces: Iterable[str]) -> list[str]:
    """Every piece after the first says so on its own line."""
    out: list[str] = []
    for position, piece in enumerate(pieces):
        out.append(piece if position == 0 else f"{CONTINUED}\n{piece}")
    return out


def _group(
    fragments: Sequence[_Fragment],
    conversation: Conversation,
    message_count: int,
    token: str,
    max_chars: int,
) -> list[list[_Fragment]]:
    """Pack fragments into parts, greedily, never splitting a fragment.

    Two passes: the first packs assuming a one-part envelope, the second repacks
    once `N` is known, because `Part {i} of {N}` grows with `N`. It converges
    after one repack for any plausible `N` — the only field that changes width is
    the part count — and a fixed point is not chased further; a part is at worst
    a few characters under budget.
    """
    total = 1
    groups: list[list[_Fragment]] = []
    for _ in range(2):
        groups = _pack(fragments, conversation, message_count, token, max_chars, total)
        if len(groups) == total:
            break
        total = len(groups)
    return groups


def _pack(
    fragments: Sequence[_Fragment],
    conversation: Conversation,
    message_count: int,
    token: str,
    max_chars: int,
    total: int,
) -> list[list[_Fragment]]:
    groups: list[list[_Fragment]] = []
    current: list[_Fragment] = []
    for fragment in fragments:
        candidate = [*current, fragment]
        size = len(
            _assemble(
                conversation,
                message_count,
                token,
                [item.text for item in candidate],
                max(1, len(groups) + 1),
                max(total, len(groups) + 1),
            )
        )
        if current and size > max_chars:
            groups.append(current)
            current = [fragment]
        else:
            current = candidate
    groups.append(current)
    return groups


def normalise(text: str) -> str:
    """NFC, for comparing what we sent with what a page shows back (`17`)."""
    return unicodedata.normalize("NFC", text)


def attachment_render(
    entry: Attachment | FileRef,
    klass: AttachmentClass,
    reason: str | None = None,
) -> AttachmentRender:
    """Bridge from an export entry and `03`'s verdict to what rendering needs."""
    if isinstance(entry, Attachment):
        return AttachmentRender(
            file_name=entry.file_name,
            file_type=entry.file_type,
            file_size=entry.file_size,
            klass=klass,
            reason=reason,
            extracted_content=entry.extracted_content,
        )
    return AttachmentRender(
        file_name=entry.file_name,
        file_type=None,
        file_size=None,
        klass=klass,
        reason=reason,
    )
