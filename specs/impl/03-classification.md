# 03 — Classification

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §6 Phase 1 ("which conversations can be migrated and which contain unsupported data"), §14 (attachment classes)
**Depends on:** [02](02-export-model.md)
**Enables:** [04](04-seed-generation.md), [05](05-dry-run.md), [16](16-attachments.md)
**Status:** Done

## Goal

Decide, offline and deterministically, which conversations are migratable and into which
of the three §14 classes every attachment falls — and produce the `MigrationPlan` that the
dry run prints and the import loop executes.

## In scope

- `dataporter/plan.py`:

  ```python
  class AttachmentPlan(BaseModel):
      message_uuid: str
      file_name: str
      file_type: str | None
      file_size: int | None
      klass: Literal["inline", "upload", "unsupported"]   # §14 classes 1, 2, 3
      reason: str | None            # required when unsupported
      source_path: Path | None      # set when klass == "upload"

  class ConversationPlan(BaseModel):
      uuid: str
      migratable: bool
      reasons: list[str]            # why not, or limitations even if migratable
      message_count: int            # active path
      off_path_count: int
      attachments: list[AttachmentPlan]
      estimated_seed_chars: int
      chunk_count: int              # from 04's chunker, computed here for the plan

  class MigrationPlan(BaseModel):
      export_fingerprint: str       # sha256 of conversations.json bytes; `02` computes
                                    # it during the parse and carries it on `Export.fingerprint`
      conversations: list[ConversationPlan]
      totals: PlanTotals            # conversations, messages, attachments, migratable, unsupported
  ```

- Migratability rules, evaluated in order, first failing rule wins:

  | Reason | Rule |
  | --- | --- |
  | `empty_conversation` | active path has zero messages |
  | `no_representable_text` | no message on the active path yields any text after `04`'s rendering (e.g. only `tool_result` blocks) |
  | `seed_over_hard_cap` | rendered seed exceeds `seed.hard_max_chars` (default `400000`) even after chunking |

  Anything else is migratable. Limitations that do not block migration are appended to
  `reasons` and surface in the report (`19`): `branches_dropped:<n>`,
  `thinking_omitted:<n>`, `tool_calls_summarised:<n>`, `unknown_blocks:<n>`.
- Attachment classes:

  | Class | `klass` | Rule |
  | --- | --- | --- |
  | 1 directly reproducible | `inline` | `Attachment.extracted_content` is non-empty — reproduced inside the seed |
  | 2 reproducible by upload | `upload` | bytes exist at `<attachments-dir>/<conversation-uuid>/<file_name>` or `<attachments-dir>/<file_name>`, size ≤ `attachments.max_bytes` (default `30_000_000`), type in `attachments.accepted_types` (default: `pdf, txt, md, csv, json, png, jpg, jpeg, gif, webp, py, js, ts, html, xml, yaml, docx, xlsx`), and count per chat ≤ `attachments.max_per_chat` (default `20`) |
  | 3 unsupported | `unsupported` | otherwise, with reason `bytes_not_in_export`, `too_large`, `type_not_accepted` or `too_many_for_chat` |

  `--attachments-dir` defaults to `<workspace>/attachments/`. `files[]` and `files_v2[]`
  entries are class 2 candidates; `attachments[]` entries are class 1 candidates first,
  class 2 second.
- `Planner.plan(export, settings) -> MigrationPlan`, pure: same export and settings give
  byte-identical `plan.json`.

## Out of scope

- Writing `plan.json` to the workspace (`12`), printing it (`05`), uploading (`16`).

## Design notes

- The plan is computed once and executed, never recomputed mid-run, so counts in the dry
  run, the progress block and the report are the same numbers.
- The hard cap exists because a chat's context is finite; chunking (`04`) spreads a seed
  across messages but not across context. The default is generous and `10` may lower it.
- Attachment limits are the operator's observed claude.ai limits at the time of writing,
  marked *assumed* until `10` and `16` confirm them.

Resolved while building:

- **`04`'s renderer lands with this slice, in `render.py`.** `no_representable_text`,
  `estimated_seed_chars`, `chunk_count` and every limitation counter are defined in terms of
  `04`'s rendering table, and `04` depends on `03`. Something had to move. Estimating the
  sizes here and letting `04` replace them was rejected: it puts two renderers in flight and
  breaks the one property this slice exists to provide — that the dry run, the progress block
  and the report quote the same numbers. So `render.py` holds the block table, the attachment
  lines, the envelope and the chunker, and `04` keeps the artefacts built on them:
  `Seed`/`SeedChunk`, each part's sha256, `part-NN.txt`, the `seeds` command and the golden
  files. The format is still `04`'s to change; `03` measures whatever it says.
- **"No representable text" means no *original* content, not no characters.** The spec's own
  example — a conversation of `tool_result` blocks — renders as `[Tool result omitted]`,
  which is characters. `RenderedMessage.has_original_content` is true only for a non-blank
  `text` block, an artifact with content, a non-blank fallback `ChatMessage.text` or a
  non-blank inline attachment; every placeholder is text that reproduces nothing.
- **Attachment types are matched on the file name's extension.** The table above lists
  extensions, but the export carries a MIME type on `attachments[]` (`text/plain`) and
  nothing at all on `files[]`, so a MIME match would be undecidable for exactly the entries
  class 2 is about. The name is authoritative and a small MIME table covers a name with no
  suffix.
- **Class 3 reasons are decided in a fixed order: `type_not_accepted`,
  `bytes_not_in_export`, `too_large`, `too_many_for_chat`.** It runs from what is knowable
  without touching a disk to what is knowable only after finding the file, and it puts the
  one reason an operator can act on — supply the bytes — after the one no directory can fix,
  so nobody hunts for a file that would be refused on arrival.
- **`max_per_chat` is a conversation-wide cap on uploads only.** Applied last, over the
  entries that survived every other rule, in document order: the first N stay `upload`, the
  rest become `too_many_for_chat`. An `inline` attachment is text inside the seed and never
  touches the file picker, so it does not consume the cap.
- **One `AttachmentPlan` per distinct file per message.** A real export carries the same file
  in `files[]` and `files_v2[]` — the fixture does — and counting it twice would show the
  operator two attachments where the UI showed one, then upload it twice. An entry whose
  `file_uuid` *or* whose name has already been seen on that message is dropped. That makes
  `totals.attachments` the number of planned attachments rather than the number of array
  entries, which is a correction owed to `05`.
- **Both path components are checked before they are joined.** `file_name` and the
  conversation uuid come from the export, so `../../etc/passwd` must not resolve out of the
  attachments directory — the finding `02`'s review raised against `ExportSource.read`. A
  rejected name is reported as `bytes_not_in_export`, because that is what it is.
- **An empty conversation reports no seed at all** (`estimated_seed_chars` and `chunk_count`
  both `0`) rather than the length of an envelope wrapped around nothing. Every other
  non-migratable conversation keeps its real numbers, because `seed_over_hard_cap` without
  the size that triggered it is not a reason anyone can act on.
- **`Planner` holds the settings** and `plan(export)` takes only the export; `build_plan(
  export, settings)` keeps the spec's call shape. Every private step needs the settings, and
  one planner replanning under different settings has no caller.
- **The envelope is measured against a three-digit part count.** `Part {i} of {N}` and the
  acknowledgement line both grow with `N`, so a budget measured at one part underestimates a
  multi-part seed and would split a message that did not need splitting. A thousand parts is
  fifty megabytes, well past the hard cap, so three digits costs two characters of slack.
- **An artifact gets a fence longer than any run of backticks inside it.** An artifact
  containing ``` would otherwise close its own block and spill the rest of the conversation
  into the transcript as prose.

## Acceptance criteria

- The fixture plan has exactly one `unsupported` conversation (`empty_conversation`) and
  the branch conversation is migratable with `branches_dropped:1`.
- The fixture attachment with `extracted_content` is `inline`; the `files[]` entry with no
  bytes is `unsupported` with `bytes_not_in_export`; dropping a file at
  `attachments/<uuid>/<name>` flips it to `upload` with `source_path` set.
- Two plans of the same export serialise to identical JSON.
- `totals.migratable + totals.unsupported == totals.conversations`.

## Risks

- Rules may be too strict or too lax for the real export. The unsupported list is printed
  by `inspect` with reasons so the operator sees exactly what would be skipped and why.
