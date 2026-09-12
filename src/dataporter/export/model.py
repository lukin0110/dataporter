"""The Claude data export, as typed immutable models.

This module holds types and one rule — which messages a conversation actually
migrates — and nothing else. It performs no I/O and never raises `ExportError`;
`source.py` is the only place a library exception becomes one. `03`, `04` and `05`
build these objects in memory in their own tests, so keeping the filesystem out of
here is a property worth being able to check with `grep`.

## Tolerance

Two settings on every model carry the spec's "parse tolerantly, fail loudly":

- `extra="allow"`, so a field the export grew since this was written survives in
  `model_extra` instead of being dropped.
- `frozen=True`, because `03`, `04` and `12` all read the same objects and none of
  them may edit what the export said. It is shallow — `chat_messages.append()`
  still works — and it generates a `__hash__` that raises at call time because the
  fields are lists, so key on `.uuid` and never put a model in a set.

An unrecognised content block becomes an `UnknownBlock` that keeps the original
object verbatim in `raw`. `04` renders it as `[Unsupported content: {type}]` and
`source.py` records it as an `UnsupportedItem`; nothing is ever silently lost.

## Two traps when logging from here

`ToolResultBlock` has a field literally named `content` and `Conversation.name` is
the title, so a `model_dump()` in an `extra=` mapping trips `log.ContentGuard`
(raises in tests, drops the record in production). Never log a model or a dump —
log counts, uuids under `conversation_id`, and block *type* tokens.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated, Any, Literal

from orval import to_utc
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
)

from dataporter import log

_logger = log.get_logger(__name__)


# --------------------------------------------------------------------------- #
# Shared base
# --------------------------------------------------------------------------- #


class ExportModel(BaseModel):
    """Base for every export model: immutable, and tolerant of new fields."""

    model_config = ConfigDict(frozen=True, extra="allow")


def _utc(value: datetime) -> datetime:
    """Normalise a timestamp to tz-aware UTC.

    Enforced rather than merely asserted because `04` renders
    `{created_at as YYYY-MM-DD HH:MM UTC}` into a byte-compared golden string: a
    `+02:00` value arriving unnormalised would render two hours off with the
    literal text `UTC` beside it. A naive value is assumed UTC rather than
    rejected — the assumption is written down in `docs/export-format.md` and
    logged, which beats failing a whole export over a missing suffix.

    `orval.to_utc` does the normalising; the warning stays here because orval has
    no hook for one. Its naive test is broader than `tzinfo is None` — a `tzinfo`
    whose `utcoffset` returns `None` is naive too, and `astimezone` would have
    read that as *system-local* time. Nothing in an export produces such a value,
    so this is a narrowing of a hole rather than a bug fixed.
    """
    if value.tzinfo is None:
        _logger.warning("export naive timestamp")
    return to_utc(value)


UtcDatetime = Annotated[datetime, AfterValidator(_utc)]


# --------------------------------------------------------------------------- #
# Content blocks
# --------------------------------------------------------------------------- #


class TextBlock(ExportModel):
    """Prose. `04` renders it verbatim."""

    type: Literal["text"] = "text"
    text: str = ""


class ToolUseBlock(ExportModel):
    """A tool call. `04` reads `input.title` and `input.language` for artifacts."""

    type: Literal["tool_use"] = "tool_use"
    name: str = ""
    input: dict[str, Any] = {}


class ToolResultBlock(ExportModel):
    """A tool's output. `04` renders `[Tool result omitted]` and never reads it,
    so its shape is deliberately unconstrained."""

    type: Literal["tool_result"] = "tool_result"
    content: Any = None


class ThinkingBlock(ExportModel):
    """Extended thinking. `04` omits it and counts the omission."""

    type: Literal["thinking"] = "thinking"
    thinking: str = ""


class TokenBudgetBlock(ExportModel):
    """Bookkeeping. Omitted and not counted."""

    type: Literal["token_budget"] = "token_budget"


class UnknownBlock(ExportModel):
    """A block this build does not model.

    `raw` is the original object verbatim — not `model_extra`, because the
    acceptance criterion is that an unknown block survives *as* `raw`.
    """

    type: str = ""
    raw: dict[str, Any] = {}


KnownContentBlock = Annotated[
    TextBlock | ToolUseBlock | ToolResultBlock | ThinkingBlock | TokenBudgetBlock,
    Field(discriminator="type"),
]

KNOWN_BLOCK_TYPES: frozenset[str] = frozenset(
    {"text", "tool_use", "tool_result", "thinking", "token_budget"}
)
"""The tags `KnownContentBlock` dispatches on.

Written out rather than derived from the union so that a member disappearing
fails a test instead of quietly widening what counts as "known".
"""

_KNOWN_BLOCKS: TypeAdapter[KnownContentBlock] = TypeAdapter(KnownContentBlock)


def _coerce_block(value: Any) -> Any:
    """Resolve one raw content block. Never raises.

    A pydantic discriminated union cannot carry a catch-all member — every
    member's discriminator must be a `Literal` — so the fallback sits *in front
    of* the union rather than inside it. A plain (smart) union was rejected:
    `UnknownBlock` is `extra="allow"` with one `str` field, so it structurally
    matches almost any mapping and member order would silently decide whether a
    slightly-off `text` block is text. Deciding here keeps dispatch exact.

    A *known* tag whose payload will not validate is kept whole as an
    `UnknownBlock` too; `source.py` records that as `malformed_block:<tag>`.
    """
    if isinstance(value, ExportModel):  # already validated, e.g. a re-validation
        return value
    if not isinstance(value, Mapping):
        return UnknownBlock(type="", raw={"value": value})
    raw: dict[str, Any] = {str(key): item for key, item in value.items()}
    tag = raw.get("type")
    if isinstance(tag, str) and tag in KNOWN_BLOCK_TYPES:
        try:
            return _KNOWN_BLOCKS.validate_python(raw)
        except ValidationError:
            return UnknownBlock(type=tag, raw=raw)
    return UnknownBlock(type=tag if isinstance(tag, str) else "", raw=raw)


ContentBlock = Annotated[
    TextBlock
    | ToolUseBlock
    | ToolResultBlock
    | ThinkingBlock
    | TokenBudgetBlock
    | UnknownBlock,
    BeforeValidator(_coerce_block),
]


# --------------------------------------------------------------------------- #
# Attachments
# --------------------------------------------------------------------------- #


class Attachment(ExportModel):
    """A file whose text the export inlined. `03` calls this attachment class 1
    when `extracted_content` is non-empty."""

    file_name: str = ""
    file_size: int | None = None
    file_type: str | None = None
    extracted_content: str | None = None


class FileRef(ExportModel):
    """A file the export names but does not carry. `03`'s class 2 candidate."""

    file_name: str = ""
    file_uuid: str | None = None


# --------------------------------------------------------------------------- #
# Messages and conversations
# --------------------------------------------------------------------------- #


class ChatMessage(ExportModel):
    """One turn.

    `text` and `content` both default: the export has been seen with an empty
    `text` and a populated `content`, and requiring both would make an export that
    omits one fatal — the opposite of parsing tolerantly. A message with neither
    is `03`'s `no_representable_text`, which is where that judgement belongs.
    """

    uuid: str
    text: str = ""
    content: list[ContentBlock] = []
    sender: Literal["human", "assistant"]
    index: int | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime | None = None
    attachments: list[Attachment] = []
    files: list[FileRef] = []
    files_v2: list[FileRef] = []
    parent_message_uuid: str | None = None


class Conversation(ExportModel):
    """One chat, including the branches we do not migrate.

    `name` is the title. It is content: it never reaches a log record.
    """

    uuid: str
    name: str = ""
    summary: str | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    account: dict[str, Any] | None = None
    chat_messages: list[ChatMessage] = []
    current_leaf_message_uuid: str | None = None

    def active_path(self) -> list[ChatMessage]:
        """The messages to migrate, root first."""
        return self._split()[0]

    def off_path(self) -> list[ChatMessage]:
        """Everything else, in export order. Counted by `19`, never dropped."""
        return self._split()[1]

    # Not a `cached_property`: pydantic v2 keeps field storage in `__dict__` and
    # these models are unhashable in practice (list fields), so neither caching
    # mechanism is available. `_split` is O(n) over a handful of messages, and
    # `03` caches its result beside the plan if that ever matters.
    def _split(self) -> tuple[list[ChatMessage], list[ChatMessage]]:
        by_uuid: dict[str, ChatMessage] = {}
        positions: dict[str, int] = {}
        for position, message in enumerate(self.chat_messages):
            # First occurrence of a repeated uuid wins; the later ones fall off
            # the path and `source.py` records them as `duplicate_message_uuid`.
            by_uuid.setdefault(message.uuid, message)
            positions.setdefault(message.uuid, position)

        leaf = self._leaf(by_uuid, positions)
        lineage: list[ChatMessage] = []
        seen: set[str] = set()
        cursor = leaf
        while cursor is not None and cursor.uuid not in seen:
            seen.add(cursor.uuid)
            lineage.append(cursor)
            parent = cursor.parent_message_uuid
            if parent is None or parent == cursor.uuid:
                break
            if parent not in by_uuid:
                # Expected: dropping an unknown-sender message severs its
                # children, and a real export has roots naming a synthetic parent.
                _logger.warning(
                    "export parent missing", extra={"conversation_id": self.uuid}
                )
                break
            cursor = by_uuid[parent]

        active = _ordered(lineage, positions)
        on_path = {message.uuid for message in active}
        off = [
            message
            for message in self.chat_messages
            if message.uuid not in on_path or message is not by_uuid[message.uuid]
        ]
        return active, off

    def _leaf(
        self, by_uuid: Mapping[str, ChatMessage], positions: Mapping[str, int]
    ) -> ChatMessage | None:
        """The message the active path ends at, or `None` for an empty chat."""
        named = self.current_leaf_message_uuid
        if named is not None:
            if named in by_uuid:
                return by_uuid[named]
            # Shape drift, not un-modelled data: one dangling pointer must not
            # make a whole export unreadable, and there is nothing here for
            # `UnsupportedItem` to describe. Fall back and say so in the log.
            _logger.warning(
                "export leaf not found", extra={"conversation_id": self.uuid}
            )

        parented = {
            message.parent_message_uuid
            for message in by_uuid.values()
            if message.parent_message_uuid is not None
        }
        candidates = [
            message for message in by_uuid.values() if message.uuid not in parented
        ]
        if not candidates:
            if not by_uuid:
                return None
            # Every message is someone's parent, so the graph has a cycle.
            _logger.warning(
                "export message cycle", extra={"conversation_id": self.uuid}
            )
            candidates = list(by_uuid.values())
        return max(candidates, key=lambda m: (m.created_at, positions[m.uuid]))


def _ordered(
    messages: Sequence[ChatMessage], positions: Mapping[str, int]
) -> list[ChatMessage]:
    """By `index` when present and unique, else `created_at`, then array position.

    Uniqueness is evaluated across the path rather than the whole conversation: a
    regenerated sibling legitimately carries the same `index` as the message it
    replaces, so a conversation-wide check would disqualify `index` exactly when
    branches exist — which is when ordering matters most.

    The parent walk decides *membership*; this decides *order*. Where the two
    disagree, this wins, because this is the rule the spec pins and the one
    `docs/export-format.md` publishes.
    """
    indexed = [
        (message.index, positions[message.uuid], message)
        for message in messages
        if message.index is not None
    ]
    if len(indexed) == len(messages) and len({item[0] for item in indexed}) == len(
        messages
    ):
        return [
            item[2] for item in sorted(indexed, key=lambda item: (item[0], item[1]))
        ]
    return sorted(messages, key=lambda m: (m.created_at, positions[m.uuid]))


# --------------------------------------------------------------------------- #
# The export
# --------------------------------------------------------------------------- #


class UnsupportedItem(ExportModel):
    """Something the parser recognised but could not model.

    Aggregated by `(path, reason)` and sorted by `source.py`, so `count` means
    what it says on a four-thousand-conversation export and two loads of the same
    export serialise identically — which `03` requires of `plan.json`.
    """

    path: str
    reason: str
    count: int = 1


class Export(ExportModel):
    """One parsed export."""

    conversations: list[Conversation] = []
    users: list[dict[str, Any]] = []
    """Opaque. Only counted."""
    unsupported: list[UnsupportedItem] = []
    fingerprint: str = ""
    """SHA-256 of `conversations.json` as read.

    Not in the spec's type block. `03` needs `MigrationPlan.export_fingerprint`
    but `Planner.plan(export, settings)` receives only this object, so without it
    the planner would have to re-open the archive it was handed a parse of.
    """

    projects: int = 0
    memories: int = 0
    """How many entries `projects.json` and `memories.json` held.

    Counts and never contents, because nothing migrates either: `05`'s block
    does not print them and `03`'s plan does not read them. `30` needs them for
    a snapshot's manifest, and taking them off the same parse that produced the
    conversations is what keeps the manifest's numbers and the dry run's numbers
    the same numbers.
    """


def file_entries(export: Export) -> int:
    """How many files the export *refers* to, across every message.

    `attachments`, `files` and `files_v2` together, which is what `30` records
    as the snapshot's one gap: a Claude export names the files a conversation
    carried and ships none of their bytes. One function rather than two
    accumulators, because `source._log_shape` logs the same number and two
    spellings of it are two numbers waiting to disagree.
    """
    return sum(
        len(message.attachments) + len(message.files) + len(message.files_v2)
        for conversation in export.conversations
        for message in conversation.chat_messages
    )
