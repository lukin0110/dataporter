# 03 — Classification

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §6 Phase 1 ("which conversations can be migrated and which contain unsupported data"), §14 (attachment classes)
**Depends on:** [02](02-export-model.md)
**Enables:** [04](04-seed-generation.md), [05](05-dry-run.md), [16](16-attachments.md)
**Status:** Not started

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
