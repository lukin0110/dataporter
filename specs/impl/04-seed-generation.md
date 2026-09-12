# 04 — Seed generation

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §3 (initial-chat strategy), §6 Phase 2, §15 (structural fidelity of the seed)
**Depends on:** [03](03-classification.md)
**Enables:** [05](05-dry-run.md), [11](11-skill.md), [12](12-import-loop.md)
**Status:** Done

## Goal

Render each migratable conversation into one or more migration seeds: deterministic text
that a new Claude chat receives as its first message(s), preserving title, order, roles,
timestamps and attachment references, and ending with an acknowledgement request the
verifier can check for.

## In scope

- The rendering below **already exists**, in `dataporter/render.py`, landed with `03`:
  `03` cannot compute `no_representable_text`, `estimated_seed_chars` or `chunk_count`
  without it, and `03` comes first. `render_conversation` returns the parts, the messages
  fully contained in each and the limitation counts. What is left for this slice is the
  artefacts: the models below, each part's sha256, the files, the command and the golden
  tests. The format is still this slice's to change — `03` measures whatever it says — but
  it is changed in `render.py` and not restated here.
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

- Chunking: `seed.max_chars` (default `50000`, owned by `10`; declared in `config.py` by
  `03`, which needs a chunk budget to report a chunk count). Split at message
  boundaries so each chunk's `text` ≤ `max_chars`. A single message longer than the budget
  is split at paragraph boundaries; each fragment after the first is prefixed
  `(continued)` on its own line. `Seed.chunks[*].total` is `N`.
- Determinism: the same `Conversation` and settings produce byte-identical chunks. No
  timestamps of generation, no random ids.
- `dataporter seeds <export> [--only UUID]... [--out DIR]` writes
  `<out>/<uuid>/part-{i:02d}.txt` (default `<workspace>/seeds/`) and prints one line per
  conversation: `{short_id}  parts={N}  chars={total}` — no titles. A conversation the
  plan (`03`) will not migrate gets no files and one `skipped {short_id}: {reason}` line
  on stderr; an unknown `--only` uuid is exit `2`; nothing written at all is exit `4`.

## Out of scope

- Delivering the seed to the browser (`08`), deciding chat-level limits (`10`).

## Design notes

- The brief calls the format an implementation detail to be evaluated experimentally (§3).
  This is the first candidate; `20` evaluates it and this file changes if it loses.
- `render.py` renders an artifact inside a fence longer than any run of backticks the
  artifact itself contains, so an artifact about Markdown cannot close its own block.
- The acknowledgement line turns "did Claude accept the seed" into a string match instead
  of a judgement call. It is also what lets `17` verify a chat after the fact.
- Thinking blocks are omitted rather than included because they are not part of what the
  user saw; the count is reported so the omission is visible (§15 semantic over structural).

Resolved while building:

- **The seed is built from the plan's own rendering.** `Planner.render_conversation` is
  public and `SeedGenerator` calls it, so the `chunk_count` the dry run prints and the
  number of `part-NN.txt` files on disk are the same number by construction rather than by
  two renderers agreeing. For the same reason the migratability rules are not restated
  here: `plan.blocking_reason` decides, and a conversation `05` calls unmigratable cannot
  acquire a seed file that says otherwise.
- **The last part is packed against its own footer.** The final footer is 62 characters
  longer than "more parts follow", and the chunker measured a group with whichever footer
  matched its provisional position — so a part filled to within 62 characters of the budget
  went over the moment it turned out to be the last one. Packing now measures every
  candidate as though it were final. The cost is that an earlier part can sit one footer's
  difference under the budget; the alternative was a part that does not fit the composer.
  Found by this slice's budget criterion, fixed in `render.py`, pinned by a sweep in
  `test_render.py` because it only bites inside those 62 characters.
- **Stale parts are deleted before new ones are written.** A conversation that needed three
  parts and now needs two would otherwise leave a `part-03.txt` for `11`'s prompt to list
  and `12` to paste: a fragment of a seed nobody generated. `12` rewrites seeds on every
  attempt, so this is the common path, not an edge case.
- **The conversation uuid is checked before it is joined to a directory.** It is export
  data being used as a path component, exactly like the `file_name` `03` checks. A uuid
  that is not a single ordinary component is skipped with `unsafe_conversation_id` rather
  than sanitised into something else — two conversations must never share a directory.
- **Parts are written UTF-8 with `\n` endings, untranslated.** `SeedChunk.sha256` is the
  hash `08` compares a paste against; on Windows the default newline translation would
  make every hash describe bytes that are not the ones in the file.
- **No sidecar JSON next to the parts.** `message_uuids`, `ack` and `sha256` live on the
  in-memory `Seed` that `12` already holds. A second file on disk would be a second
  contract to keep in step with the first, and nothing reads it.
- **`seeds` writes only what it can write, and says why for the rest.** Skips go to stderr
  because stdout is one line per written seed and `05` owns the full accounting; an
  operator who named one conversation by uuid is still owed the reason nothing appeared.
  `--only` with an unknown uuid is an operator mistake (exit `2`), not an empty selection,
  and an empty selection is exit `4` — the table's "nothing to do".
- **Selection is in export order, whatever order `--only` was typed in.** Two runs of the
  same command print the same lines and write the same files. `06` owns selection properly.
- **`--quiet` suppresses the per-conversation lines.** They are progress output, and the
  command's result is the files it wrote.

## Acceptance criteria

- Golden files: each fixture conversation renders to a stored expected `part-01.txt`
  (and `part-02.txt` for the long one with `max_chars` forced to `4000`); the test compares
  bytes. They live in `tests/fixtures/seeds/{default,max-4000}/<uuid>/` and are regenerated
  by writing the fixture export, never hand-edited to make a test pass: a change to them is
  a change to what a destination chat receives.
- Every chunk ends with `MIGRATION-ACK {short_id} {i}/{N}\n` and `sha256` matches its text.
- No chunk exceeds `max_chars` unless it holds exactly one fragment that is itself longer
  than the budget after paragraph splitting (the test asserts this exception is the only
  one).
- Rendering the branch fixture includes only the active path.

## Risks

- Claude may not reply with the exact acknowledgement line. `17` treats a response that
  *contains* the line as acknowledged, and `20` measures how often even that fails.
