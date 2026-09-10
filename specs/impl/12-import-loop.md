# 12 — Import loop

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §6 Phase 3, §10 (execution command, no content printed)
**Depends on:** [04](04-seed-generation.md), [06](06-migration-state.md), [08](08-browser-helpers.md), [09](09-hermes-runner.md), [11](11-skill.md)
**Enables:** [13](13-recovery.md), [15](15-pacing.md), [16](16-attachments.md), [17](17-verification-and-title.md), [18](18-progress-output.md)
**Status:** Not started

## Goal

`hermes-claude-migrate import <export>` migrates conversations one at a time: plan, seed,
hand to Hermes, map the result to a §7 status, record it, move on. The first version does
one conversation correctly; `--limit` keeps a first real run small on purpose.

## In scope

- `dataporter/importer.py` — `Importer.run(export_path, selection) -> RunSummary`:
  1. **preflight**: lock the workspace (`06`); Hermes present and profile configured
     (`09`, else exit `6`); launch or adopt Chrome (`07`); `probe.logged_in` (else exit
     `3` with `run: hermes-claude-migrate login`); `close-extra-tabs`.
  2. **plan**: `Planner.plan` (`03`), written to `<workspace>/plan.json`; `state.json`
     entries created as `pending` for every conversation in the plan (unsupported ones are
     created as `failed` with `error.category = unsupported` and `retry_recommended =
     false`, so the report accounts for them without Hermes ever seeing them).
  3. **select** (`06`), then for each selected conversation:
     - `state.update(status="running", attempts+=1)`;
     - write seeds (`04`) to `<workspace>/seeds/<uuid>/`;
     - render the prompt (`11`) with `resume_from` = `open` (or the recorded `last_step`
       when retrying a `partial` with a known `conversation_id`);
     - `HermesRunner.run(...)` with `timeouts.hermes_run_s`;
     - map the result (table below), `state.update(...)`, append counters to `run.json`;
     - sleep `pacing.delay_between_conversations_s` (`15`; `20` here until then).
  4. **finish**: release the lock, print the summary (`18`), exit `0` if every selected
     conversation is `completed`, `1` otherwise.
- Result mapping:

  | `HermesResult.outcome` | `conversation_id` | State |
  | --- | --- | --- |
  | `completed` | set | `completed`, `last_step = done`, `chunks_acked = N` |
  | `completed` | missing | `partial`, `error.category = verification`, detail `no conversation id` |
  | `partial` | set | `partial`, `last_step` and `chunks_acked` from the result |
  | `failed` | any | `failed` if no id, else `partial`; `error` from the result |
  | `needs_human` | any | handed to `14`; until `14` lands: `partial`/`failed` as above with `error.category` from the reason |
  | `rate_limited` | any | handed to `15`; until then treated as `failed` with `rate_limit` |
  | exception (`HermesError`, `BrowserError`) | — | `failed` with that category; the run continues |

  `messages_represented` = messages in acked chunks (`04`'s `message_uuids`).
- A per-conversation exception never aborts the run. Only these do: lock lost,
  Chrome gone and not relaunchable (`BrowserError`, exit `6`), export fingerprint
  mismatch (exit `2`), circuit breaker (`15`).
- `--limit N` and `--only` as in `06`; `--dry-run` short-circuits after step 2 without
  writing (`05`).
- Stdout during the run: the `18` progress block only. Until `18` lands, one line per
  conversation: `{short_id}  {status}  ({done}/{total})`.

## Out of scope

- Retries and failure classification (`13`), pause/resume (`14`), pacing and rate-limit
  waits (`15`), attachments (`16`), rename and verification (`17`).

## Design notes

- Sequential by design (§6 Phase 3, §13). There is one browser, one tab and one operator
  who may need to intervene; concurrency would trade the reliability the experiment is
  measuring for speed it does not want.
- Unsupported conversations are written into state as `failed` rather than omitted so
  that `Created + Partial + Failed = Source conversations` in the report holds without a
  special case.
- Seeds are written on every attempt, not cached, because they are cheap and a changed
  setting must not silently reuse a stale seed.

## Acceptance criteria

- With a fake Hermes that returns `completed` and a fixed uuid, `import --limit 1` on the
  fixture creates one `completed` entry with that `conversation_id`, `messages_represented`
  equal to the fixture's active-path count, and exits `0`.
- A fake Hermes that raises on the second conversation: the run finishes all selected
  conversations, the second is `failed`, exit `1`.
- Re-running immediately after a fully successful run exits `4`.
- The real thing: one short fixture-like conversation in the throwaway account, created by
  a real Hermes run, appears in `state.json` as `completed` and opens at its
  `/chat/<uuid>` URL.
- Stdout of a full fixture run contains no fixture message text and no titles.

## Risks

- Hermes may report `completed` without the acks actually being present. `17` re-verifies
  from the page; until then `20` reads transcripts by hand.
