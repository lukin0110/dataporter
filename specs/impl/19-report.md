# 19 — Report

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §16
**Depends on:** [13](13-recovery.md), [14](14-human-intervention.md), [16](16-attachments.md), [17](17-verification-and-title.md), [18](18-progress-output.md)
**Enables:** [20](20-pilot.md)
**Status:** Not started

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
  | Browser actions | lines in `logs/actions.jsonl` + Σ `HermesResult.actions` recorded in `run.json` |
  | Retries | `run.json.retries` |
  | Human interventions | `run.json.human_interventions` |

- After the block, when any conversation is `partial` or `failed`:

  ```text

  Failures and partial migrations:
    3f9c2a1e  failed    step=submit    generation: response never completed    retry=yes
    8a02c7d1  partial   step=await     verification: ack 2/2 missing            retry=yes
    c41d90aa  failed    step=-         unsupported: empty_conversation          retry=no
  ```

  Columns: two-space indent, `short_id`, status padded to 9, `step=` + last step padded to
  10 (`-` when none), `category: detail` padded to the longest in the list plus 4,
  `retry=yes|no|unknown` from `error.retry_recommended`. This is §16's per-failure record:
  source conversation, status, last successful step, error, retry recommendation.
- Then, when any limitation was recorded:

  ```text

  Limitations:
    timestamps_not_preserved    124
    thinking_omitted             41
    branches_dropped              3
    title_not_set                 2
  ```

  Name padded to the longest plus 4, count right-aligned to width 5, sorted by count
  descending then name. Each limitation name is a heading in `docs/LIMITATIONS.md`.
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
  `logs/actions.jsonl`. No browser, no Hermes.

## Out of scope

- Interpreting the numbers (`20`, `21`).

## Design notes

- The brief's §16 block is hand-aligned with one-space inconsistencies (three-digit values
  end at column 31, five-character values at 32). Width 32 is the smallest that fits every
  line; the rule reproduces the `Messages represented`, `Attachments migrated`, `Browser
  actions` and `Retries` lines exactly and pads the others by one space. Recorded here so
  nobody "fixes" it back and forth.
- Failure lines carry a short id, not a title (§10), and never content; the detail is the
  operator-facing `MigrationError.detail`.

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

- `Browser actions` depends on Hermes self-reporting its tool calls. If `10` finds
  `hermes sessions export` usable, the count switches to the transcript and this file
  says so.
