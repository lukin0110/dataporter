# 19 — Report

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §16
**Depends on:** [13](13-recovery.md), [14](14-human-intervention.md), [16](16-attachments.md), [17](17-verification-and-title.md), [18](18-progress-output.md)
**Enables:** [20](20-pilot.md)
**Status:** Done

## Goal

The §16 block, byte-exact, plus the per-failure records the brief asks for and the
limitations that explain the fidelity actually achieved — written to `report.json` and
reproducible from the workspace alone.

## In scope

- Golden block, printed at the end of `import` and by `hermes-claude-migrate report`:

  ```text
  Claude migration complete

  Source conversations:       127
  Created:                    124
  Partial:                      2
  Failed:                       1

  Messages represented:      4,821
  Attachments migrated:         31

  Browser actions:           1,842
  Retries:                      17
  Human interventions:          2
  ```

  Rules: `label` + spaces + right-aligned value, line width
  `max(32, longest label + 1 + longest value)`, `,` separators, blank lines as shown.
  Definitions:

  | Line | Value |
  | --- | --- |
  | Source conversations | conversations in the plan |
  | Created | `status == completed` |
  | Partial / Failed | by status; `Created + Partial + Failed + Pending == Source`, and a `Pending:` line is added after `Failed:` only when it is non-zero |
  | Messages represented | Σ `messages_represented` over completed and partial |
  | Attachments migrated | Σ `attachments.uploaded + attachments.inline` |
  | Browser actions | lines in `logs/actions.jsonl`, with `run.json.browser_actions` as a floor |
  | Retries | `run.json.retries` |
  | Human interventions | `run.json.human_interventions` |

- After the block, when any conversation is `partial` or `failed`:

  ```text

  Failures and partial migrations:
    3f9c2a1e  failed    step=submit    generation: response never completed    retry=yes
    8a02c7d1  partial   step=await     verification: ack 2/2 missing           retry=yes
    c41d90aa  failed    step=-         unsupported: empty_conversation         retry=no
  ```

  Columns: two-space indent, `short_id`, two spaces, status padded to 9, a space, `step=` +
  last step padded to 10 (`-` when none), `category: detail` padded to the longest in the
  list plus 4, `retry=yes|no|unknown` from `error.retry_recommended`. This is §16's
  per-failure record: source conversation, status, last successful step, error, retry
  recommendation. An entry with no error record of its own — the `partial` crash recovery
  leaves behind — renders `-` in the error column.
- Then, when any limitation was recorded:

  ```text

  Limitations:
    timestamps_not_preserved    124
    thinking_omitted             41
    branches_dropped              3
    title_not_set                 2
  ```

  `06`'s breakdown rule, the one `inspect` prints its reasons with: name padded to the
  longest plus `summary.GUTTER`, count right-aligned in `summary.COUNT_WIDTH`, sorted by
  count descending then name. The count is conversations carrying the limitation, not
  occurrences of it: `04` writes `thinking_omitted:3` against one conversation and `19`
  folds that to the name, leaving the number where the conversation is. Every name is an
  entry under "The names `19` prints" in `docs/LIMITATIONS.md`.
- `<workspace>/report.json`:

  ```python
  class Report(BaseModel):
      generated_at: datetime
      export_fingerprint: str
      totals: ReportTotals          # the nine numbers above plus pending
      failures: list[FailureRecord] # uuid, short_id, status, last_step, category, detail, retry_recommended, destination_conversation_id
      limitations: dict[str, int]
      attachments: AttachmentTotals # found, inline, uploaded, unsupported, failed, skipped
      verification: dict[str, int]  # verified, failed, not_run
      runs: list[RunRecord]         # from run.json
  ```

  Rendered text is derived from this model; `report --json` prints it.
- `hermes-claude-migrate report` reads only `state.json`, `run.json`, `plan.json` and
  `logs/actions.jsonl`. No browser, no Hermes, and no writes: `import` is what writes
  `report.json`, at the end of a run and under the lock, and prints the same block last —
  `--quiet` included, for the reason `18`'s final block survives it. A workspace with no
  `plan.json` has never had a run in it, and `report` exits `2` saying so.
- Where the attachment numbers come from, now that `16` has landed: `found` is
  `plan.json`'s `totals.attachments`, the other five are sums of `state.json`'s
  `attachments` counts, and `skipped` is the subset of `unsupported` whose `detail` entry
  reads `skipped_by_flag` — `run.json`'s `selection.skip_attachments` is what says an
  operator asked for that rather than the bytes being missing. The four per-conversation
  counts already sum to that conversation's planned attachments, which is `16`'s
  reconciliation and the identity this slice's criteria name — over a workspace where
  every planned conversation has been attempted. A run that stopped short leaves the files
  of everything still `pending` on the other side of it, which is the same thing the
  `Pending:` line says about conversations.

## Out of scope

- Interpreting the numbers (`20`, `21`).

## Design notes

- The brief's §16 block is hand-aligned with one-space inconsistencies (three-digit values
  end at column 31, five-character values at 32). Width 32 is the smallest that fits every
  line; the rule reproduces the `Messages represented`, `Attachments migrated`, `Browser
  actions` and `Retries` lines exactly and pads the others by one space. Recorded here so
  nobody "fixes" it back and forth.
- Failure lines carry a short id, not a title (§10), and never content; the detail is the
  operator-facing `MigrationError.detail`. `18` cuts the same string at 60 characters
  because a redraw depends on the block's height; a report has no such constraint and §16
  asks for the error, so this prints the whole of it.
- The failure example in this file was hand-aligned the way the brief's block is: its
  second and third lines were one column wider than the rule makes them. Corrected above
  to the rule's own bytes, since this document is ours and a test compares against it.
- **`Browser actions` is the file, not the agent.** `12` decided against recording
  `HermesResult.actions` — what the agent believes it did — so the sum the original table
  named has no second term to add: the number is the records in `logs/actions.jsonl`,
  which our own helpers write. `run.json.browser_actions` is the same lines counted as
  they were written, and is used as a floor so that a log which was rotated or truncated
  cannot make a run look idler than it was.
- **`verified / failed / not_run` is counted over the chats that exist.** The population
  is the conversations with a destination id — one that never landed has nothing to read
  back, rather than a verification that has not happened yet — and `not_run` is the
  remainder, so the three sum to it. `failed` is the conversations whose *recorded* reason
  is the check: `17` writes a `verification` error only where the run left no reason of
  its own, so a chat that failed a step and then its check is counted under the step's
  category and listed among the failures with that category.
- **The report is built and written under the lock, and printed by the CLI.** `18` took
  the formatting out of `importer.py` and this slice puts none back: the loop hands a
  `Report` out on its `RunSummary` and `cli` renders it. The alignment itself is `06`'s —
  `summary.aligned_groups` for the block, `summary.breakdown_lines` for the limitations —
  so §9's block, §10's counters and §16's report cannot drift apart. The blank line that
  separates the report from §10's final block belongs to the CLI and not to the rendering:
  on a run there is always something above it, and `report` prints the same text with
  nothing above it at all.

## Acceptance criteria

- A golden test with the nine numbers above renders the block byte-for-byte.
- A workspace with two failures and one partial renders the failures section exactly as
  shown (fixture with those ids).
- `report` output is byte-identical across two invocations and after a `--json` round
  trip (`Report.model_validate_json` then render).
- `Created + Partial + Failed + Pending == Source conversations` and the attachment
  identity from `16` hold on the fixture and on the real run.
- No fixture message text or title appears in the text or JSON report.

## Risks

- `Browser actions` counts what our helpers recorded, which is every browser action Hermes
  can take — it has no other way to touch the page (§17) — so the risk the original
  wording named does not apply: nothing here depends on the agent self-reporting. What
  remains is that a helper whose record could not be written (a read-only workspace, which
  `08` warns about and carries on from) is an action the report does not count.
