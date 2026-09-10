# 02 — Export model

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §2 (import/parser), §6 Phase 1
**Depends on:** [01](01-foundation.md)
**Enables:** [03](03-classification.md), [04](04-seed-generation.md), [05](05-dry-run.md)
**Status:** Not started

## Goal

Turn a Claude data export into typed, immutable pydantic models — every conversation, every
message, every attachment reference, every unknown block kept — without ever writing to the
export.

## Prerequisite

A real export from the operator's source account is inspected before this slice is
written. `docs/export-format.md` records what is actually in it; the model below is the
shape reported by several independent parsers and is corrected from that observation.

## In scope

- `ExportSource.open(path)` accepts a `.zip` or an extracted directory. Zips are read with
  `zipfile` in mode `r` only; nothing is extracted to disk (JSON is read from the archive
  stream). Files expected: `conversations.json` (required), `users.json`, `projects.json`,
  `memories.json` (optional, read for counts only).
- `dataporter/export/model.py`, all models `frozen=True`, `extra="allow"` so unknown
  fields survive into `model_extra`:

  ```python
  class Export(BaseModel):
      conversations: list[Conversation]
      users: list[dict]            # opaque; only counted
      unsupported: list[UnsupportedItem]

  class Conversation(BaseModel):
      uuid: str
      name: str                    # "" allowed
      summary: str | None = None
      created_at: datetime
      updated_at: datetime
      account: dict | None = None
      chat_messages: list[ChatMessage]
      current_leaf_message_uuid: str | None = None

  class ChatMessage(BaseModel):
      uuid: str
      text: str
      content: list[ContentBlock]  # discriminated on "type"
      sender: Literal["human", "assistant"]
      index: int | None = None
      created_at: datetime
      updated_at: datetime | None = None
      attachments: list[Attachment] = []
      files: list[FileRef] = []
      files_v2: list[FileRef] = []
      parent_message_uuid: str | None = None

  # ContentBlock = Annotated[TextBlock | ToolUseBlock | ToolResultBlock | ThinkingBlock
  #                          | TokenBudgetBlock | UnknownBlock, Field(discriminator="type")]
  # TextBlock(type="text", text)            ToolUseBlock(type="tool_use", name, input)
  # ToolResultBlock(type="tool_result", content)   ThinkingBlock(type="thinking", thinking)
  # TokenBudgetBlock(type="token_budget")   UnknownBlock(type=<anything else>, raw: dict)

  class Attachment(BaseModel):
      file_name: str
      file_size: int | None = None
      file_type: str | None = None
      extracted_content: str | None = None

  class FileRef(BaseModel):
      file_name: str
      file_uuid: str | None = None
  ```

- `Conversation.active_path() -> list[ChatMessage]`: the messages to migrate. If
  `current_leaf_message_uuid` is set, walk `parent_message_uuid` from that leaf to the root.
  Otherwise the leaf is the message with the latest `created_at` that no other message names
  as parent. Messages off the active path are returned by `Conversation.off_path()` and
  counted, never dropped.
- Ordering inside the active path: by `index` when present and unique, else by
  `created_at`, tie-broken by array position. The rule is written in
  `docs/export-format.md`.
- `UnsupportedItem(path, reason, count)` for anything the parser recognises but cannot
  model: an unknown top-level file, a message with an unknown `sender`, a content block with
  an unknown `type` (also kept as `UnknownBlock`).
- Malformed input (`conversations.json` missing, not a JSON array, truncated zip) raises
  `ExportError` with the file name and, for JSON, the byte offset. Never a raw `ZipError`,
  `JSONDecodeError` or `ValidationError`.
- Fixture `tests/fixtures/export-small/` (synthetic, no personal data) with six
  conversations: two-turn plain; forty-turn long; one with fenced code in both roles; one
  with an `attachments[]` entry carrying `extracted_content` and one `files[]` entry with no
  bytes; one with a `parent_message_uuid` branch (two leaves); one empty (`chat_messages: []`).
  Plus a message with an unknown block type and an unknown top-level file `extra.json`.
- `docs/export-format.md`: written from the real export. Records: file list, whether
  attachment bytes are present anywhere in the archive, timestamp format, observed content
  block types with one redacted example each, whether `index` and
  `current_leaf_message_uuid` exist, and the export's own date.

## Out of scope

- Deciding what is migratable (`03`); rendering anything for humans (`05`).

## Design notes

- Parse tolerantly, fail loudly: an unrecognised *value* becomes an `UnsupportedItem` and
  parsing continues; a structurally broken archive stops with `ExportError`.
- Branches are a real feature of the export (edits and regenerations create siblings).
  Migrating only the active path is a fidelity decision made here and reported by `19` as a
  limitation whenever `off_path()` is non-empty.
- `text` on a message is treated as a fallback: the `content` blocks are authoritative when
  present, because exports have been seen with empty `text` and populated `content`.

## Acceptance criteria

- The real export parses end to end; `Export.unsupported` lists every item not modelled.
- SHA-256 of every file in the fixture (and the zip itself) is identical before and after
  parsing.
- The branch fixture yields an `active_path()` of one leaf's lineage and `off_path()`
  containing the other sibling.
- An unknown block type survives as `UnknownBlock.raw` and appears in `unsupported`.
- A truncated zip raises `ExportError`, message names the archive.
- `docs/export-format.md` exists and every claim in it is marked *observed* or *assumed*.

## Risks

- The export shape changes between exports. The parser logs which optional fields it found
  (`index`, `current_leaf_message_uuid`, `files_v2`) so a shape drift is visible in the log
  of the first run that hits it.
