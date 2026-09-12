# 05 — Dry run and inspect

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §9
**Depends on:** [04](04-seed-generation.md)
**Enables:** [12](12-import-loop.md), [18](18-progress-output.md)
**Status:** Done

## Goal

Make the tool useful before it can touch a browser: `import --dry-run` prints the §9 block
byte-exactly from the plan, and `inspect` prints the same block plus the reasons behind the
unsupported count. Nothing is written anywhere, nothing is contacted.

## In scope

- `hermes-claude-migrate import <export> --dry-run` prints exactly:

  ```text
  Conversations found:    127
  Messages:             4,821
  Attachments:             36

  Migratable:             124
  Unsupported:              3
  ```

  Rule: each line is `label` + spaces + `value`, right-aligned so that the line is
  `max(27, longest label + 1 + longest value)` characters wide; values use `,` thousands
  separators; the blank line separates the two groups. Exit `0`.
- `hermes-claude-migrate inspect <export>` prints the same block, then a blank line and,
  when `Unsupported` is non-zero, one line per reason sorted by count descending then name:

  ```text
  Unsupported reasons:
    empty_conversation      2
    seed_over_hard_cap      1
  ```

  followed by a blank line and:

  ```text
  Attachments:
    inline          31
    upload           0
    unsupported      5
  ```

  Reason and class columns are padded to the longest label plus two spaces; counts are
  right-aligned to width 5. Both breakdowns are indented two spaces under their header,
  and all three attachment classes are always listed, zeros included.
- `--json` on `inspect` prints `MigrationPlan.model_dump_json(indent=2)` and nothing else.
- `--dry-run` combined with `--limit`, `--only`, `--retry-failed`, `--retry-partial`
  applies the selection (`06`) before counting, so the dry run shows what *this* run would
  do. `--dry-run` never writes `plan.json`, `state.json` or `seeds/`.
- `Messages` counts active-path messages of all conversations found; `Attachments` counts
  `MigrationPlan.totals.attachments` — one entry per distinct file per message, since `03`
  drops a `files_v2[]` entry that repeats a `files[]` one. Counting the raw arrays instead
  would print two attachments where the operator's UI showed one file.
- `inspect` needs `--attachments-dir` too, which `01` gave only to `import`: whether a file
  is class 2 or class 3 depends on it, and `inspect` is the command that explains the
  unsupported list. This slice adds the flag and turns it into an `attachments.dir`
  override; `03` declared the setting but wired no flag, because every command that would
  read one still exits `69`.

## Out of scope

- The live progress block (`18`), the report (`19`).

## Design notes

- The brief's §9 example was hand-aligned and internally inconsistent by one to three
  spaces (`Conversations found: 127` was 24 wide, `Messages:             4,821` is 27).
  One rule cannot reproduce both. The rule above reproduces the `Messages` and
  `Attachments` lines byte-for-byte and is the only rule that can be tested, so it is the
  golden rule, and §9 was amended to the rule's bytes — the amendment note sits under the
  block. `tests/test_summary.py` compares the rendered block against the brief itself.
- Counting from the plan, not the export, keeps the dry run, progress and report numbers
  identical by construction.

Resolved while building:

- **The two breakdown examples were hand-aligned as well**, in two different ways, and
  neither matched the rule stated beside them (`empty_conversation` was 11 spaces from its
  count, `inline` 7, where the rule gives 6 and 11). The rule wins for the same reason it
  wins in §9 — it is the thing a test can hold — and the blocks above are now what the
  code prints.
- **Counts in the breakdowns get thousands separators too**, and `width 5` is a minimum
  rather than a field: an export with 12,000 inline attachments should widen its own line,
  not print `12000` because five columns was the number in the spec.
- **The reason counted is the blocking one only.** `ConversationPlan.reasons` leads with
  the blocking reason and continues with limitation slugs (`thinking_omitted:3`), which
  describe a conversation that *is* being migrated. Counting the whole list would print
  causes that sum to more than `Unsupported`.
- **`inspect` on an export with no conversations prints zeros and exits `0`**, where
  `import --dry-run` on an empty selection exits `4`. `inspect` answers a question about a
  file and "it holds nothing" is an answer; a dry run reports what a run would do, and a
  run with nothing to do is the table's `4`.
- **`--limit` truncates after `--only`, and a negative `--limit` is exit `2`.** `[:-1]`
  would otherwise quietly drop the last conversation of the selection.
- **`--retry-failed` and `--retry-partial` are accepted and change nothing yet.** With no
  `state.json` every conversation is pending, so the widening they describe is empty; `06`
  gives them their meaning without changing this slice's counting.
- **The dry-run block is printed even under `--quiet`.** `-q` suppresses progress output;
  this block is the command's entire result.
- **`--attachments-dir` is applied as a copy of the loaded settings**, not as a reload with
  an init override: `attachments.dir` is one field of a nested model, and rebuilding
  `Settings` from `attachments={"dir": ...}` would drop whatever else an operator's
  `config.toml` set under `[attachments]`.
- **No `log.enable_run_log`, on either command.** It creates `<workspace>/logs/`, and a
  dry run that leaves a workspace next to the export has already broken "nothing is
  written anywhere".

## Acceptance criteria

- A golden test renders a plan with totals 127 / 4,821 / 36 / 124 / 3 and asserts the
  output equals the block above byte-for-byte, and a second test asserts that the two
  well-formed lines of the brief's own §9 block come back unchanged — the rule is measured
  against `01-initial-brief.md` itself, not against a copy of it.
- A plan with a six-digit message count widens every line consistently (test with
  `1,234,567`).
- `--dry-run` with an injected `BrowserSession` and `HermesRunner` that raise on any call
  completes without raising; the workspace directory does not exist afterwards. Neither
  class exists until `07` and `09`, so the standing test raises from
  `socket.socket.connect`, `subprocess.run` and `subprocess.Popen` instead — the
  capabilities those objects would use — and asserts the workspace was never created. The
  criterion is restated with the real objects when they land.
- Running `inspect` twice on the fixture gives identical bytes.
- Scanning `inspect` output for any string that appears only inside fixture message bodies
  or titles finds nothing, and every line it prints matches a pattern of labels this slice
  owns, reason slugs and counts — so a future column of export data fails the test rather
  than passing a string scan the fixture happens not to trip.

## Risks

- None beyond format drift; the golden tests hold the line.
