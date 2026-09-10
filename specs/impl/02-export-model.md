# 02 — Export model

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §2 (import/parser), §6 Phase 1
**Depends on:** [01](01-foundation.md)
**Enables:** [03](03-classification.md), [04](04-seed-generation.md), [05](05-dry-run.md)
**Status:** In progress

## Goal

Turn a Claude data export into typed, immutable pydantic models — every conversation, every
message, every attachment reference, every unknown block kept — without ever writing to the
export.

## Prerequisite

A real export from the operator's source account is inspected before this slice is
written. `docs/export-format.md` records what is actually in it; the model below is the
shape reported by several independent parsers and is corrected from that observation.

**Unmet.** No export was available when this was built. The parser was written to the
model below and `docs/export-format.md` marks every factual claim *assumed*, with the
procedure that converts them to *observed*. That is why this slice is `In progress` and
not `Done`: the first acceptance criterion ("the real export parses end to end") is the
one criterion still open, and everything else is met.

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

Resolved while building:

- **The `ContentBlock` sketch above cannot be built as written.** A pydantic v2
  discriminated union requires every member's discriminator to be a `Literal`, so
  `UnknownBlock(type: str)` cannot be a member of `Field(discriminator="type")`. The
  catch-all therefore sits *in front of* the union as a `BeforeValidator`, with the five
  known blocks kept behind a real tagged union in a `TypeAdapter`. A plain (smart) union
  was rejected: `UnknownBlock` is `extra="allow"` with one `str` field, so it structurally
  matches almost any mapping and member order would silently decide whether a slightly-off
  `text` block is text. Deciding in front of the union keeps dispatch exact and buys one
  thing the union could not: a *known* tag whose payload will not validate is also kept
  whole, counted as `malformed_block:<tag>`.
- **`ExportSource` lives in `export/source.py`, the models in `export/model.py`.** The
  split makes "the model layer performs no I/O and never raises `ExportError`" checkable
  with `grep`, which matters because `03`, `04` and `05` build `Conversation` objects in
  memory in their own tests and must never need a filesystem.
- **`Export` gains `fingerprint`** — the sha256 of `conversations.json` as read. `03`
  declares `MigrationPlan.export_fingerprint` but `Planner.plan(export, settings)` receives
  only the `Export`, so without it the planner would have to re-open the archive it was
  handed a parse of.
- **`ChatMessage.text` and `.content` both default.** The design note above says either may
  be empty and the other authoritative; requiring both would make an export that omits one
  fatal, which is the opposite of parsing tolerantly. A message with neither is `03`'s
  `no_representable_text`, which is where that judgement belongs.
- **`index` uniqueness is evaluated across the active path, not the conversation.** A
  regenerated sibling legitimately carries the same `index` as the message it replaces, so
  a conversation-wide check would disqualify `index` exactly when branches exist. The
  fixture's branch conversation has two siblings both at `index: 3` and proves it.
- **The parent walk decides membership; the ordering rule decides order.** Where a
  lineage's timestamps disagree with its parent chain, the ordering rule wins, because that
  is the rule this slice pins and `docs/export-format.md` publishes.
- **A dangling `current_leaf_message_uuid` is not an error.** It falls back to the derived
  leaf and logs `export leaf not found`. One bad pointer must not make a whole export
  unreadable, and there is nothing un-modelled here for an `UnsupportedItem` to describe —
  it is shape drift, which is what the log is for. Cycles and missing parents are handled
  the same way.
- **`UnsupportedItem`s are aggregated by `(path, reason)` and sorted.** `path` is the member
  name for a top-level file and `conversations.json:<conversation-uuid>` for anything
  inside; a per-block path would make `count` structurally always 1. Reasons are stable
  slugs — `unknown_file`, `unparsable_file`, `unknown_sender:<value>`,
  `unknown_block_type:<tag>`, `malformed_block:<tag>`, `untyped_block`,
  `duplicate_message_uuid` — with the token from the export sanitised, since it reaches
  `report.json`.
- **A conversation that fails validation is fatal; a malformed *optional* file is not.**
  The models are already maximally tolerant, so what still fails is a missing required
  field — structural drift the operator must see before migrating 127 conversations, and
  skipping it silently would make `05`'s "Conversations found" undercount. `users.json` and
  friends decide nothing, so they degrade to `unparsable_file` and an empty list.
- **`JSONDecodeError.pos` is a character offset, not a byte offset**, and the two diverge as
  soon as the file contains anything non-ASCII. The bytes are decoded explicitly first so
  the offset can be converted; that also gives a non-UTF-8 archive its own message.
- **`str(ValidationError)` leaks content.** It appends `input_value='…'`, which `19` would
  print verbatim into the report. Only `loc` and `msg` are used, and a test asserts the
  offending value never appears in `detail`.
- **A `.zip` suffix counts as well as the magic bytes.** `zipfile.is_zipfile` reads the
  end-of-central-directory record, which is exactly what a truncated archive has lost, so
  dispatching on it alone would tell the operator their `.zip` "is not a zip". An archive
  whose members sit under a single wrapping directory is also accepted.
- **`cli.py` gained an `ExportError` clause** rather than waiting for `05`. `_RootGroup`
  mapped everything but `ConfigError` to exit `70`, so a malformed export would have
  reached the operator as `internal error: ExportError`. Exit `2`, matching
  `require_export`'s existing message and `01`'s "usage or configuration error" row. Only
  this category: `auth` and `browser` map to codes of their own, and the slice that adds
  that behaviour adds its clause.
- **`Conversation.updated_at` stays required**, per the block above, but it is the field
  most likely to make a real export fatal. If it does, the fix is `| None = None` plus a
  shape-drift log, not a change to the tolerance model.
- **`read(member)` checks membership, never joins a bare path.** The directory backend
  would otherwise resolve `../` outside the export, and an absent member would fail
  differently in a directory than in an archive. The two backends are interchangeable or
  they are not worth having.
- **Never log a model or a dump of one.** `ToolResultBlock` has a field literally named
  `content` and `Conversation.name` is the title, so either in an `extra` mapping trips
  `ContentGuard`. The shape record carries counts, file names and block *type* tokens.

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
