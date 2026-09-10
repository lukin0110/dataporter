# 16 — Attachments

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §14
**Depends on:** [03](03-classification.md), [08](08-browser-helpers.md), [12](12-import-loop.md)
**Enables:** [19](19-report.md) (attachment figures)
**Status:** Not started

## Goal

Reproduce class 1 attachments inside the seed, upload class 2 attachments through the
normal claude.ai UI before the first part is submitted, and record every class 3
attachment with its reason. Nothing is silently ignored.

## In scope

- Class 1 (`inline`) is already rendered by `04`; this slice adds the per-attachment
  record so the report can count it.
- Class 2 (`upload`):
  - `Importer` passes the `AttachmentPlan.source_path` list to the prompt (`11`); the
    skill's `attach` step runs `browser attach --file …` once per file, in plan order,
    before `paste` of part 1;
  - the seed for part 1 references each as `[File: {name} — attached to this chat]`
    (`04`), so Claude can relate the file to the message it belonged to;
  - the helper (`08`) verifies the chip; the skill verifies the chip count equals the
    number of files before pasting;
  - an `attach` failure is not fatal: the skill records `{file_name, error}` in the
    result's `attachments_failed` list, continues without it, and the conversation ends
    `partial` with `error.category = unsupported`, detail `attachment upload failed:
    <name>`, `retry_recommended = true`.
- `HermesResult` gains `attachments_uploaded: list[str]` and `attachments_failed:
  list[{file_name, error}]`; `state.json` `attachments` becomes
  `{"uploaded": n, "inline": n, "unsupported": n, "failed": n}` with a `detail` list of
  `{file_name, klass, reason}` for everything not uploaded.
- `--skip-attachments`: class 2 entries are treated as class 3 with reason
  `skipped_by_flag`; recorded in `run.json.selection` so the report says they were
  skipped rather than unavailable.
- `--attachments-dir DIR`: where class 2 bytes are looked up (`03`); the default
  `<workspace>/attachments/` is created empty by `import` with a `README.txt` explaining
  the `<conversation-uuid>/<file_name>` layout, because the export itself is expected not to
  contain bytes (`02` confirms).
- Deduplication: identical bytes (SHA-256) referenced by several messages of one
  conversation are uploaded once; the seed references the same name.
- A conversation whose class 2 count exceeds `attachments.max_per_chat` uploads the first
  `max_per_chat` in message order and records the rest as `too_many_for_chat` (`03`).

## Out of scope

- Anything attached by claude.ai itself to assistant messages (artifacts are text, handled
  by `04`).

## Design notes

- Upload before paste, not after, because the composer's attachment chips belong to the
  message being composed; a file attached after submission would land on a new empty
  message.
- The tool does not try to fetch original bytes from the source account (§17, and the
  export is the only source). If the operator can supply them, the directory convention is
  how.

## Acceptance criteria

- Fixture run with one class 2 file present in `attachments/<uuid>/`: the prompt lists
  it, a fake Hermes reports it uploaded, state shows `uploaded: 1`, the seed's part 1
  contains the `attached to this chat` line.
- The same with the file missing: `unsupported: 1` with `bytes_not_in_export`, status
  `completed` (a class 3 attachment does not degrade the conversation — it was never
  migratable).
- A fake Hermes reporting `attachments_failed` for one file: status `partial`, reason as
  above, `retry_recommended == true`.
- `--skip-attachments`: no `attach` lines in the prompt; report says skipped.
- Report totals reconcile: `uploaded + inline + unsupported + failed == attachments found`.
- Real run: one PDF uploaded through the UI by Hermes shows as an attachment on the first
  message of the created chat.

## Risks

- claude.ai may reject a type or size the plan accepted. The helper's `upload_rejected`
  error carries the UI's own message so `03`'s accepted list can be corrected.
