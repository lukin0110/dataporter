# Experiment 01 — the pilot

**Kind:** Experiment record — what was measured, not what was designed. Produced by
[`20`](../specs/impl/20-pilot.md).
**Answers:** [§18](../specs/01-initial-brief.md)'s six questions, with numbers.
**Pilot run:** none.
**Export:** unknown. **Tool version:** unknown. **Hermes version:** unknown.
**Chrome version:** unknown.

Every number below carries a mark: `*measured on <date>*` when a run produced it,
`*not yet run*` when none has. `tests/test_experiment_doc.py` enforces that each of §18's
six questions carries exactly one marked number, that the step checklist has a row for
every step of [`11`](../specs/impl/11-skill.md), and that the status line above stops
saying `none` as soon as any number claims a measurement. It is the same rule
[`10`](../specs/impl/10-attach-spike.md)'s documents follow, for the same reason: a
question nobody answered has to look different from one answered badly.

Nothing in this file may carry conversation content — not a title, not a message, not an
account identifier (§10). Conversations are named by their eight-character short id; the
probe replies this write-up grades live in `<workspace>/pilot/probes.json`, which stays
on the machine that ran the pilot.

## How it is run

```text
dataporter setup
dataporter doctor
dataporter login
dataporter import <export> --dry-run --pilot   # the selection, no account touched
dataporter import <export> --pilot             # the run
dataporter report                              # §16's block, and the failures
dataporter followup                            # the semantic probe, question 3
dataporter judge                               # optional: the `judge` extra
```

The destination is the throwaway account and nothing else (§17). `--pilot` chooses the
conversations itself, by category, and refuses `--only`, `--limit` and `--all` so that
the experiment's design cannot be edited at the command line by accident.

## The selection

What `--pilot` chose, and therefore what each number below is a number *about*. The
categories are `20`'s, in order; a category that chose nothing is a fact about the
export. Copy this from the run's own `Pilot selection:` block, which is also in
`run.json` under `runs[].selection.pilot`.

| # | Category | Conversation | Mark |
| --- | --- | --- | --- |
| 1 | shortest | — | *not yet run* |
| 2 | longest-one-part | — | *not yet run* |
| 3 | longest-multi-part | — | *not yet run* |
| 4 | code-both-roles | — | *not yet run* |
| 5 | inline-attachment | — | *not yet run* |
| 6 | second-attachment | — | *not yet run* |
| 7 | many-turns | — | *not yet run* |
| 8 | dropped-branch | — | *not yet run* |
| 9 | artifact | — | *not yet run* |
| 10 | newest | — | *not yet run* |

## Questions

### Q1 — Can Hermes reliably create chats?

**Measure:** conversations with a `conversation_id` ÷ conversations attempted.
**Evidence:** `report.json` (`totals.created`, `totals.partial`, `totals.failed`) and
`state.json` (`destination.conversation_id` per entry).
**Number:** not yet run. *not yet run*

### Q2 — Can it reliably submit large migration seeds?

**Measure:** parts acknowledged ÷ parts attempted, split by part size bucket
(< 10 k, 10–50 k, > 50 k characters).
**Evidence:** `state.json` (`chunks_acked` against `chunks_total`), `plan.json`
(`estimated_seed_chars`, `chunk_count`) and the seed files themselves for the bucket.
**Number:** not yet run. *not yet run*

### Q3 — Does Claude correctly understand the reconstructed history?

**Measure:** semantic probe pass rate — `pass` ÷ graded, over the table below.
**Evidence:** `<workspace>/pilot/probes.json`, one reply per `completed` conversation,
graded by hand in the table below and, optionally, by `dataporter judge`.
**Number:** not yet run. *not yet run*

### Q4 — How often does the browser agent require recovery?

**Measure:** `13` rows fired ÷ conversations, read out of the transcripts and the retry
counter.
**Evidence:** `report.json` (`totals.retries`), `run.json` (`retries`,
`rate_limit_waits`) and the per-conversation transcripts under `docs/spike/pilot/`.
**Number:** not yet run. *not yet run*

### Q5 — How much human intervention is required?

**Measure:** `human_interventions` ÷ conversations, with the reason each ask carried.
**Evidence:** `report.json` (`totals.human_interventions`), `run.json` (`paused`, and
the run records) and the `needs_human` reasons in the transcripts.
**Number:** not yet run. *not yet run*

### Q6 — What Claude UI limitations prevent faithful migration?

**Measure:** the `Limitations` section of the report, by name and count, plus anything
seen in a transcript that the report has no name for.
**Evidence:** `report.json` (`limitations`), `docs/LIMITATIONS.md` and
`docs/claude-ui-map.md`, which this run is also evidence for.
**Number:** not yet run. *not yet run*

## Semantic probe grades

One row per `completed` conversation. The hand grade is the one Q3 reports; the judge's
is recorded beside it because a disagreement between them is a finding about the judge,
which is why it is optional and why both columns are kept.

| Conversation | Hand grade | Why | Judge | Judge's reason | Mark |
| --- | --- | --- | --- | --- | --- |
| — | — | — | — | — | *not yet run* |

## Transcript review checklist

Applied to every Hermes session of the pilot: for each step of `11`'s table, was the
step's verify condition actually observed before the next act? `verified` counts the
sessions where it was, `skipped` the sessions where the step ran and the check did not.
A step no session reached is neither.

| Step | Verified | Skipped | Notes | Mark |
| --- | --- | --- | --- | --- |
| `open` | — | — | — | *not yet run* |
| `new_chat` | — | — | — | *not yet run* |
| `attach` | — | — | — | *not yet run* |
| `paste` | — | — | — | *not yet run* |
| `submit` | — | — | — | *not yet run* |
| `await` | — | — | — | *not yet run* |
| `ack` | — | — | — | *not yet run* |
| `identify` | — | — | — | *not yet run* |
| `rename` | — | — | — | *not yet run* |
| `verify` | — | — | — | *not yet run* |
| `done` | — | — | — | *not yet run* |

## What was not observed

Ten conversations are too few to meet everything the tool has code for, and `21` treats
what a pilot did not see as untested rather than as working. What this run never met
goes here — a rate limit, a CAPTCHA, a login expiry mid-run, a circuit breaker, an
export whose attachment bytes exist.

*not yet run*

## Seed format review

§3 leaves the seed format to be "evaluated experimentally", and this is the evaluation:
if Q3 scores below `pass` for more than two of the pilot's conversations,
[`04`](../specs/impl/04-seed-generation.md) gets a second candidate format and the
failing conversations are migrated again with it before `21` starts.

**Verdict:** not yet run. *not yet run*

## Transcripts

Every Hermes session of the pilot belongs under [`docs/spike/pilot/`](spike/pilot/), with
personal data removed before the file is saved — a transcript holds page snapshots, and a
page snapshot of claude.ai is somebody's conversation. That directory's README says what
to strip and what is safe to keep.
