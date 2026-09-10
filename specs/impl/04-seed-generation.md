# 04 — Seed generation

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §3 (initial-chat strategy), §6 Phase 2, §15 (structural fidelity of the seed)
**Depends on:** [03](03-classification.md)
**Enables:** [05](05-dry-run.md), [11](11-skill.md), [12](12-import-loop.md)
**Status:** Not started

## Goal

Render each migratable conversation into one or more migration seeds: deterministic text
that a new Claude chat receives as its first message(s), preserving title, order, roles,
timestamps and attachment references, and ending with an acknowledgement request the
verifier can check for.

## In scope

- `dataporter/seed.py`:

  ```python
  class SeedChunk(BaseModel):
      index: int                 # 1-based
      total: int
      text: str
      sha256: str                # of text, UTF-8
      message_uuids: list[str]   # messages fully contained in this chunk
      ack: str                   # exact line Claude is asked to reply with

  class Seed(BaseModel):
      conversation_uuid: str
      short_id: str              # first 8 hex chars of the uuid
      chunks: list[SeedChunk]
      messages_represented: int
      limitations: list[str]     # thinking_omitted:n, tool_calls_summarised:n, ...
  ```

- Seed format, exact. Braces are substitutions; everything else is literal. Lines are
  `\n`-terminated, no trailing whitespace, file ends with one `\n`.

  ```text
  This is a migrated conversation.

  Original conversation:
  {title or "(untitled)"}

  Original conversation ID: {uuid}
  Created: {created_at as YYYY-MM-DD HH:MM UTC}
  Messages: {message_count}
  Part {i} of {N}

  The following is the historical conversation:

  ---

  User ({YYYY-MM-DD HH:MM UTC}):
  {rendered message}

  ---

  Assistant ({YYYY-MM-DD HH:MM UTC}):
  {rendered message}

  ---

  {footer}
  ```

  Footer for the last (or only) part:

  ```text
  Continue to preserve this conversation as historical context. Treat it as our shared
  history, not as a new request. Do not summarise it. Reply with exactly one line:
  MIGRATION-ACK {short_id} {i}/{N}
  ```

  Footer for every earlier part:

  ```text
  More parts of this conversation follow. Do not respond to the content yet. Reply with
  exactly one line:
  MIGRATION-ACK {short_id} {i}/{N}
  ```

  Parts after the first start with `Migrated conversation {short_id}, part {i} of {N},
  continued.` in place of the block from `This is a migrated conversation.` through
  `The following is the historical conversation:`.

- Message rendering, per content block, in block order:

  | Block | Rendering |
  | --- | --- |
  | `text` | verbatim |
  | `tool_use` named `artifacts` | `[Artifact: {input.title}]` then the artifact content in a fenced block; language from `input.language` when present |
  | other `tool_use` | `[Tool call: {name}]` — counted as `tool_calls_summarised` |
  | `tool_result` | `[Tool result omitted]` |
  | `thinking` | omitted — counted as `thinking_omitted` |
  | `token_budget` | omitted, not counted |
  | unknown | `[Unsupported content: {type}]` — counted as `unknown_blocks` |

  If `content` is empty, `text` is used. Attachments, after the message body:

  ```text
  [Attachment: {file_name} ({file_type}, {file_size} bytes)]
  <<<
  {extracted_content}
  >>>
  ```

  Class 2: `[File: {file_name} — attached to this chat]`. Class 3:
  `[File: {file_name} — not reproduced: {reason}]`.

- Chunking: `seed.max_chars` (default `50000`, owned by `10`). Split at message
  boundaries so each chunk's `text` ≤ `max_chars`. A single message longer than the budget
  is split at paragraph boundaries; each fragment after the first is prefixed
  `(continued)` on its own line. `Seed.chunks[*].total` is `N`.
- Determinism: the same `Conversation` and settings produce byte-identical chunks. No
  timestamps of generation, no random ids.
- `hermes-claude-migrate seeds <export> [--only UUID]... [--out DIR]` writes
  `<out>/<uuid>/part-{i:02d}.txt` (default `<workspace>/seeds/`) and prints one line per
  conversation: `{short_id}  parts={N}  chars={total}` — no titles.

## Out of scope

- Delivering the seed to the browser (`08`), deciding chat-level limits (`10`).

## Design notes

- The brief calls the format an implementation detail to be evaluated experimentally (§3).
  This is the first candidate; `20` evaluates it and this file changes if it loses.
- The acknowledgement line turns "did Claude accept the seed" into a string match instead
  of a judgement call. It is also what lets `17` verify a chat after the fact.
- Thinking blocks are omitted rather than included because they are not part of what the
  user saw; the count is reported so the omission is visible (§15 semantic over structural).

## Acceptance criteria

- Golden files: each fixture conversation renders to a stored expected `part-01.txt`
  (and `part-02.txt` for the long one with `max_chars` forced to `4000`); the test compares
  bytes.
- Every chunk ends with `MIGRATION-ACK {short_id} {i}/{N}\n` and `sha256` matches its text.
- No chunk exceeds `max_chars` unless it holds exactly one fragment that is itself longer
  than the budget after paragraph splitting (the test asserts this exception is the only
  one).
- Rendering the branch fixture includes only the active path.

## Risks

- Claude may not reply with the exact acknowledgement line. `17` treats a response that
  *contains* the line as acknowledged, and `20` measures how often even that fails.
