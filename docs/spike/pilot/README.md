# Pilot transcripts

The Hermes sessions of the pilot run ([`20`](../../../specs/impl/20-pilot.md)), as
evidence for [`experiment-01.md`](../../experiment-01.md). The write-up holds the numbers;
this directory holds what they were read off.

**Sessions here:** none. The pilot has not been run.

| File | Where it comes from | Holds |
| ---- | ------------------- | ----- |
| `<short id>-attempt-N.txt` | `<workspace>/hermes/<run id>.stdout.txt` | one conversation's migration session: the agent's reasoning, its helper calls and their JSON answers, and the result object |
| `probe-<short id>.txt` | `<workspace>/hermes/probe-<short id>.stdout.txt` | the follow-up probe of `17`'s question 3, and the reply it collected |
| `checklist.md` | a human, reading the above | the per-step `verified` / `skipped` tally that the write-up's checklist totals come from |

## Before a transcript is committed

A Hermes transcript is **not** content-free the way the workspace's other files are: the
agent takes `browser_snapshot`s, a snapshot of claude.ai contains the conversation on the
page, and a probe transcript contains a reply in full. So every file here is edited by a
person before it is saved, and the rules are the ones `docs/spike/README.md` already sets
for this directory:

- **Remove every snapshot body.** Keep the fact that a snapshot was taken, the element
  refs the agent acted on and the step it was at; cut the page text.
- **Remove the reply.** A probe's answer is graded in `experiment-01.md` as `pass`,
  `weak` or `fail` with a reason in the reviewer's own words. The reply itself stays in
  `<workspace>/pilot/probes.json` on the machine that ran the pilot.
- **Remove account identifiers.** No email address, no account uuid, no sidebar listing
  of other chats. A destination chat uuid may stay: the account is a throwaway and the
  uuid is what ties a transcript to `state.json`.
- **Keep everything else.** Helper calls and their answers, timings, error strings,
  retries, `needs_human` reasons and the result object are the evidence, and a transcript
  trimmed past them cannot settle a disagreement about what happened.

Read the file back before committing it. The tool can keep content out of its own
records by construction; it cannot do that for a file a person edited by hand.
