# 16 — Attachments

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §14
**Depends on:** [03](03-classification.md), [08](08-browser-helpers.md), [12](12-import-loop.md)
**Enables:** [19](19-report.md) (attachment figures)
**Status:** Done

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

Resolved while building:

- **`--skip-attachments` is a setting (`attachments.skip`), not a flag the loop carries.**
  The decision has to reach `03`, because a file nobody is going to upload is class 3 and
  the seed has to say `not reproduced: skipped_by_flag` rather than promise a chip
  (`04`'s `attached to this chat` line). Carrying the flag only as far as the prompt
  would have produced seeds that describe a chat that was never going to exist. It is
  `with_skip_attachments` beside `with_attachments_dir`, and `False` leaves the settings
  alone so that `skip = true` in an operator's `config.toml` is not overridden by the
  flag's absence.
- **Deduplication is on content, and the seed then uses the uploaded name.** The plan
  hashes each class 2 file (`AttachmentPlan.sha256`) and marks the second entry with the
  same digest `duplicate_of: <the first name>`. The duplicate stays class 2 — the file
  *is* in the chat, as one chip, and the message it belongs to refers to that chip — so
  both entries count as `uploaded` and the reconciliation still holds. Two differently
  named copies of the same bytes therefore both render as the uploaded name, which is a
  deliberate consequence of the rule this spec states rather than an accident: the chat
  has one chip, and the seed must not name a second one. A duplicate consumes no
  `max_per_chat` slot, because the cap is a limit on uploads and a duplicate uploads
  nothing; `03`'s own note is updated to match.
- **A planned upload the run did not mention is `failed: not_reported`, never
  `uploaded`.** The counts are evidence: what the workspace records as being in the
  account is what the run said it saw a chip for. The alternative — assuming a listed
  file was attached because the run said `completed` — would put a number in `19`'s
  report that nothing checked.
- **`retry_recommended` is written `true` at the raise site**, which is the second place
  in the tool where the field is not read off the error class (`_record_failure` is the
  first). The category is `unsupported` because that is §14's word for a file the
  destination would not take; the *transience* is not the category's, though — an upload
  refused once may well work on the next attempt, and `13` reads this field as the retry
  decision. What ends up on disk after the budget is spent is `false`, by `13`'s rule,
  which is a statement about the attempts rather than about the upload.
- **A run with no part left to paste attaches nothing.** On a resume where every part is
  acknowledged there is no message being composed, so a chip would belong to nothing and
  a "successful" upload would be a file sitting in a composer that is never submitted.
  The skill records each file as `nothing_to_attach_to` instead, which is honest and
  which `13`'s budget bounds.
- **The chip count is a helper, not a snapshot.** `browser attachments --file … --file …`
  answers with the names it found in one `Runtime.evaluate`, so the skill's "as many chips
  as files" check describes one moment; a per-file loop could agree with a page that
  never existed. It reuses `chip_not_found` rather than adding a word to `08`'s error
  vocabulary.
- **`state.json`'s `attachments.detail` lists everything that is not an upload**, inline
  attachments included. They are the ones §14 calls reproduced, so their `reason` is
  `null`; what the list is for is the promise that nothing is silently ignored, and an
  entry that is missing because it went well is a list an operator cannot count against
  the plan.
- **A conversation that is never migrated still accounts for its files** (`not_attempted`),
  so `uploaded + inline + unsupported + failed == attachments found` holds for every entry
  `state.json` has rather than only for the ones a run reached.
- **The `README.txt` is written only into the default directory.** A directory an operator
  named with `--attachments-dir` is theirs, and leaving a file in it would be litter.

## Acceptance criteria

- Fixture run with one class 2 file present in `attachments/<uuid>/`: the prompt lists
  it, a fake Hermes reports it uploaded, state shows `uploaded: 1`, the seed's part 1
  contains the `attached to this chat` line.
- The same with the file missing: `unsupported: 1` with `bytes_not_in_export`, status
  `completed` (a class 3 attachment does not degrade the conversation — it was never
  migratable).
- A fake Hermes reporting `attachments_failed` for one file: status `partial`, reason as
  above, `retry_recommended == true` — the value the record is written with, which is what
  makes `13` attempt the conversation again; once the budget is spent `13` rewrites it
  `false`, so the test asserts the `true` where it is produced and the retry it caused.
- `--skip-attachments`: no `attach` lines in the prompt, every class 2 entry
  `skipped_by_flag`, and `run.json`'s selection records the flag — which is where `19`
  will read "skipped" from.
- Report totals reconcile: `uploaded + inline + unsupported + failed == attachments found`.
- Real run: one PDF uploaded through the UI by Hermes shows as an attachment on the first
  message of the created chat — **unverified**, like every criterion that needs a real
  Hermes and a real account (`09`, `11`). `20` is where it is checked; `docs/claude-ui-map.md`
  is still `*unknown*` on both the file input and the chip.

## Risks

- claude.ai may reject a type or size the plan accepted. The helper's `upload_rejected`
  error carries the UI's own message so `03`'s accepted list can be corrected.
