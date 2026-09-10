# 20 — Pilot experiment

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §18
**Depends on:** [19](19-report.md) (and therefore everything before it)
**Enables:** [21](21-scale-up.md)
**Status:** Not started

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

## Acceptance criteria

- `--pilot` on the fixture chooses the expected short ids for categories 1–5 and 7–9
  (fixture lacks class 2 and a tenth distinct conversation) — a unit test.
- `docs/experiment-01.md` exists with a number for all six questions and a hand grade
  for every completed conversation.
- The report for the pilot run reconciles (`19`) and its `Failures` section, if any, has
  a `retry=` verdict per line.
- Every pilot Hermes transcript is saved under `docs/spike/pilot/` with personal data
  removed, and the checklist totals are in the write-up.

## Risks

- Ten conversations may be too few to see a rate limit or a UI change. The write-up says
  what was *not* observed, and `21` treats those as untested.
