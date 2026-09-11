# 20 — Pilot experiment

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §18
**Depends on:** [19](19-report.md) (and therefore everything before it)
**Enables:** [21](21-scale-up.md)
**Status:** In progress — the instruments are built and tested; the experiment has not
been run. `docs/experiment-01.md` exists and says so, and
`tests/test_experiment_doc.py` keeps it saying so until a number replaces a mark.

## Goal

Run the finished tool on five to ten deliberately chosen conversations from the real
export into the throwaway destination account, and answer the six §18 questions with
numbers and transcript evidence. Nothing scales up until this is written up.

## In scope

- `hermes-claude-migrate import <export> --pilot`: selects from the migratable plan, in
  this order, skipping duplicates, until ten are chosen or the categories run out:
  1. the shortest conversation (fewest active-path messages, ≥ 2);
  2. the longest by seed characters that fits in one part;
  3. the longest that needs ≥ 2 parts;
  4. one whose messages contain a fenced code block in both roles;
  5. one with a class 1 attachment;
  6. one with a class 2 attachment (if the operator supplied bytes), else another class 1;
  7. one with ≥ 10 turns;
  8. one with a dropped branch;
  9. one with an artifact;
  10. the newest conversation.
  `--pilot` prints the chosen short ids and categories, then runs exactly as `import`
  does with `--limit 10`. The selection is written to `run.json.selection.pilot`.
- Evaluation record `docs/experiment-01.md`, one section per §18 question, each with a
  number and the evidence path:

  | § 18 question | Measure |
  | --- | --- |
  | 1 Can Hermes reliably create chats? | conversations with a `conversation_id` ÷ attempted |
  | 2 Can it reliably submit large seeds? | parts acked ÷ parts attempted, split by part size bucket (< 10 k, 10–50 k, > 50 k chars) |
  | 3 Does Claude understand the reconstructed history? | semantic probe pass rate (below) |
  | 4 How often does the agent require recovery? | `13` rows fired ÷ conversations, from transcripts |
  | 5 How much human intervention? | `human_interventions` ÷ conversations, with reasons |
  | 6 Which UI limitations prevent faithful migration? | the `Limitations` section of the report, plus anything seen in transcripts |

- Semantic probe (question 3): after the pilot run, for each `completed` conversation, a
  Hermes task sends one follow-up question in the migrated chat —
  `In one sentence, what did we discuss in this conversation?` — and returns Claude's
  reply. The reply is graded:
  - by hand, recorded as `pass` / `weak` / `fail` with a one-line reason in
    `experiment-01.md`; and, optionally,
  - by `hermes-claude-migrate judge` (the `judge` extra, `pydantic-ai`): an `Agent` with
    `output_type=FidelityVerdict(score: Literal["pass","weak","fail"], reason: str)` given
    the source seed and the reply, using the same Anthropic key Hermes uses via
    `ANTHROPIC_API_KEY`. Its verdicts are recorded next to the hand grades; disagreement
    is itself a finding.
  Sending this one extra message to a chat this run created is inside the §17 boundary;
  the skill's rules are extended by one sentence saying so.

  The probe is a command of its own, `hermes-claude-migrate followup [--only UUID]...`,
  because it runs after the migration and over a different population (§7's `completed`
  entries, not a selection of the export). It writes `<workspace>/pilot/question.txt` —
  the question, pasted by `08`'s helper byte for byte — and
  `<workspace>/pilot/probes.json`, one record per conversation with the reply in it.
  `judge` reads that file and writes its verdicts back into it. Neither ever prints a
  reply: `followup` prints `<short id>  answered  chars=N`, `judge` prints
  `<short id>  <score>`.
- A transcript review checklist, applied to every Hermes session of the pilot: for each
  step in `11`'s table, was the verify condition actually observed before the next act?
  Counted as `verified` / `skipped` per step; totals go in `experiment-01.md`.
- Seed format review (§3 "evaluated experimentally"): if question 3 scores below
  `pass` for more than two of the pilot conversations, `04` gets a second candidate
  format and the pilot is re-run on the failing ones before `21`.

## Out of scope

- The full export (`21`).

## Design notes

- Selection is automatic so the pilot is reproducible on another export; `--only` remains
  for a hand-picked set.
- The semantic probe is the one place an LLM judges anything, and it is optional and
  paired with a human grade, because the metric the brief cares about (§19) is counted,
  not judged.

Resolved while building:

- **A category names its conversation even when an earlier category already took it.**
  "Skipping duplicates" is about the *run set*, not about the record: the run migrates
  each conversation once, and `run.json.selection.pilot` still says that the longest
  conversation is also the one with ten turns. A record that printed `-` for the seventh
  category because the third got there first would hide the one fact a write-up needs in
  order to read the numbers — which conversations are carrying more than one category.
  Two categories are exceptions, and both are in §20's own wording: `6` asks for
  *another* class 1 when there is no class 2, and `10` is the filler that rounds the
  pilot up to ten, so each skips what is already chosen. On the fixture this is exactly
  what "the fixture lacks class 2 and a tenth distinct conversation" comes to.
- **"≥ 10 turns" is ten messages on the active path.** The export calls each message a
  turn and so does the page `17` reads back; five questions and five answers is the
  conversation this category is looking for. Counting exchanges would have made the
  category mean "twenty messages", which no wording here asks for.
- **`--pilot` refuses `--only`, `--limit` and `--all`.** `12` made the flag a refusal
  rather than an inert option because a flag that chooses a different set cannot be
  quietly ignored; the same argument applies in reverse once it is implemented, and one
  of the two would have to lose. The other flags — `--force`, `--retry-*`,
  `--skip-attachments`, `--attachments-dir`, the pacing three — still compose: they
  change what happens to the chosen conversations, not which ones they are.
- **The selection reaches the run as `--only`'s field.** `state.select` resolves it,
  which means a pilot re-run on a workspace that already migrated those conversations
  migrates them again, exactly as `--only` does. That is the existing meaning of naming
  conversations explicitly, and the seed-format re-run above wants it; a pilot that is
  not a re-run belongs in a fresh workspace.
- **`--pilot --dry-run` prints the selection and then §9's block**, changing nothing.
  It is how the categories are inspected against a real export before ten chats are
  created, and it is what the acceptance test below drives.
- **The probe reply passes through Hermes's output tokens, and nothing else ever does.**
  A seed never does (`specs/README.md`, division of labour) and `11` forbids quoting a
  message, so this is an exception and is written down as one in `followup.py` and in
  one sentence of the skill's *Rules*. The alternative — a helper that returns page text
  — was rejected: it would put a way of reading any message on the page into the hands
  of every step of every migration, to save quoting three dozen characters out of a chat
  this tool created in a throwaway account. The reply is a workspace file from the moment
  it arrives (`<workspace>/pilot/probes.json`), like a seed, and reaches neither stdout
  nor the log.
- **The judge's `pydantic-ai` import is dynamic.** It is an extra, so a static import
  would be an unresolved import on every machine that did not install it — including the
  one `make check` runs `ty` on. `importlib.import_module` asks the question at the only
  moment it can be answered, and what comes back is validated through `FidelityVerdict`
  rather than trusted. A missing extra and a missing `ANTHROPIC_API_KEY` are both exit
  `6`, the environment row, and each says what to do.
- **The write-up exists before the experiment does, and is marked.** `10`'s spike
  documents set the pattern: a question nobody answered has to look different from one
  answered badly, so every number in `experiment-01.md` carries `*not yet run*` or
  `*measured on <date>*`, and `tests/test_experiment_doc.py` refuses a document that
  claims a measurement while its status line still says no pilot has run. This is why
  the slice can be `In progress` with everything built and nothing measured: the code is
  testable here, the numbers are not.

## Acceptance criteria

- `--pilot` on the fixture chooses the expected short ids for categories 1–5 and 7–9
  (fixture lacks class 2 and a tenth distinct conversation) — a unit test.
  *Met:* `tests/test_pilot.py`, at `seed.max_chars = 4000`, which is the size that
  separates categories 2 and 3 on this fixture; at the default size nothing needs two
  parts and category 3 chooses nothing, which is a second test.
- `docs/experiment-01.md` exists with a number for all six questions and a hand grade
  for every completed conversation.
  *Partly met:* the record exists, every question has a measure, an evidence path and one
  marked number, and the grade table is there. The numbers themselves need a run.
- The report for the pilot run reconciles (`19`) and its `Failures` section, if any, has
  a `retry=` verdict per line.
  *Inherited:* both are `19`'s own criteria and its tests hold them for any workspace —
  what is left for the pilot is to paste the block into the write-up and check that the
  reasons on those lines are understood rather than merely printed, which is `21`'s gate.
- Every pilot Hermes transcript is saved under `docs/spike/pilot/` with personal data
  removed, and the checklist totals are in the write-up.
  *Prepared:* `docs/spike/pilot/README.md` says what is stripped and what is kept, and a
  test fails if transcripts appear beside a README that still says there are none.

## Risks

- Ten conversations may be too few to see a rate limit or a UI change. The write-up says
  what was *not* observed, and `21` treats those as untested.
- The probe adds one message to every migrated chat. It is inside §17's boundary and the
  skill says so, but it is the one place where a bug in this slice would write to the
  account rather than read from it — which is why it asks once, never retries the
  question, and stops rather than looking for another way in.
