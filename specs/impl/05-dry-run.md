# 05 — Dry run and inspect

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §9
**Depends on:** [04](04-seed-generation.md)
**Enables:** [12](12-import-loop.md), [18](18-progress-output.md)
**Status:** Not started

## Goal

Make the tool useful before it can touch a browser: `import --dry-run` prints the §9 block
byte-exactly from the plan, and `inspect` prints the same block plus the reasons behind the
unsupported count. Nothing is written anywhere, nothing is contacted.

## In scope

- `hermes-claude-migrate import <export> --dry-run` prints exactly:

  ```text
  Conversations found: 127
  Messages:             4,821
  Attachments:             36

  Migratable:           124
  Unsupported:             3
  ```

  Rule: each line is `label` + spaces + `value`, right-aligned so that the line is
  `max(27, longest label + 1 + longest value)` characters wide; values use `,` thousands
  separators; the blank line separates the two groups. Exit `0`.
- `hermes-claude-migrate inspect <export>` prints the same block, then a blank line and,
  when `Unsupported` is non-zero, one line per reason sorted by count descending then name:

  ```text
  Unsupported reasons:
    empty_conversation           2
    seed_over_hard_cap           1
  ```

  followed by a blank line and:

  ```text
  Attachments:
    inline       31
    upload        0
    unsupported   5
  ```

  Reason and class columns are padded to the longest label plus two spaces; counts are
  right-aligned to width 5.
- `--json` on `inspect` prints `MigrationPlan.model_dump_json(indent=2)` and nothing else.
- `--dry-run` combined with `--limit`, `--only`, `--retry-failed`, `--retry-partial`
  applies the selection (`06`) before counting, so the dry run shows what *this* run would
  do. `--dry-run` never writes `plan.json`, `state.json` or `seeds/`.
- `Messages` counts active-path messages of all conversations found; `Attachments` counts
  `attachments[] + files[] + files_v2[]` entries of all conversations found.

## Out of scope

- The live progress block (`18`), the report (`19`).

## Design notes

- The brief's §9 example is hand-aligned and internally inconsistent by one to three
  spaces (`Conversations found: 127` is 24 wide, `Messages:             4,821` is 27).
  One rule cannot reproduce both. The rule above reproduces the `Messages` and
  `Attachments` lines byte-for-byte and is the only rule that can be tested, so it is the
  golden rule; the three deviating lines in the brief (`Conversations found`,
  `Migratable`, `Unsupported`, off by one to three spaces) are treated as typos.
- Counting from the plan, not the export, keeps the dry run, progress and report numbers
  identical by construction.

## Acceptance criteria

- A golden test renders a plan with totals 127 / 4,821 / 36 / 124 / 3 and asserts the
  output equals the block above byte-for-byte.
- A plan with a six-digit message count widens every line consistently (test with
  `1,234,567`).
- `--dry-run` with an injected `BrowserSession` and `HermesRunner` that raise on any call
  completes without raising; the workspace directory does not exist afterwards.
- Running `inspect` twice on the fixture gives identical bytes.
- Scanning `inspect` output for any string that appears only inside fixture message bodies
  or titles finds nothing.

## Risks

- None beyond format drift; the golden tests hold the line.
