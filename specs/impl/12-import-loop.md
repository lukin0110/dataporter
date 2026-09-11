# 12 — Import loop

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §6 Phase 3, §10 (execution command, no content printed)
**Depends on:** [04](04-seed-generation.md), [06](06-migration-state.md), [08](08-browser-helpers.md), [09](09-hermes-runner.md), [11](11-skill.md)
**Enables:** [13](13-recovery.md), [15](15-pacing.md), [16](16-attachments.md), [17](17-verification-and-title.md), [18](18-progress-output.md)
**Status:** Done

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
     - `HermesRunner.run(...)` with `timeouts.hermes_task_s` (`09`'s name for it);
     - map the result (table below), `state.update(...)`, append counters to `run.json`;
     - sleep `pacing.delay_between_conversations_s` (`15`; `importer.DELAY_BETWEEN_CONVERSATIONS_S`,
       twenty seconds, here until then).
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

Resolved while building:

- **`partial` versus `failed` is one question: is there a chat.** The table above answers
  it row by row; the code answers it once, with `landed = conversation_id is not None`,
  and the two agree everywhere except where a row names a status outright (`completed`
  with an id, `rate_limited`). That also settles the row the table left implicit: an
  exception raised while *resuming* a conversation that already has a chat records
  `partial`, not `failed`, because §7's `failed` means there is nothing at the
  destination to go and look at. `importer.interpret` is the whole table as a pure
  function of a result and that one fact, and `test_importer.py` parametrises it.
- **`retry_recommended` is read off the error class, never decided here.** `01` made
  `transient` a property of the category precisely so `13` and `19` would not have to
  guess; `importer.retry_recommended` is that lookup, and the three "per instance" rows
  come back `None`, which `19` prints as `retry=unknown`. The one hard-coded value is the
  `false` the spec asks for on `unsupported`.
- **The preflight is the local half of `doctor`, not all of it.** `doctor`'s first five
  checks — Hermes on `PATH`, the profile, its model, its configuration, the skill — are
  local and take milliseconds; the two that run a real `hermes -z` take a minute each and
  prove what the migration is about to prove with work that counts. `doctor.LOCAL_LABELS`
  names the five and `doctor.local_failure` runs them, and because `checks` is a
  generator, stopping at the fifth is also what keeps the preflight from launching a
  browser of its own.
- **The browser is checked before each conversation, not after each failure.** A dead
  Chrome found before a run costs one HTTP call; found after one costs a Hermes task that
  had nowhere to go. A browser that cannot be started again is the run-ending
  `BrowserError` the spec names (exit `6`).
- **A browser that comes back goes through the preflight's checks again.** The relaunch
  and the preflight share `_open_browser`, so both prove the session and run
  `close-extra-tabs`: a Chrome that died may never have written the profile that kept it
  signed in, and one restarted over the same `--user-data-dir` can restore the tabs it had
  open — which is the `ambiguous_tab` `08` exists to clear. A session found signed out
  ends the run with exit `3` wherever it is noticed, because every conversation left would
  fail the same way; `14` is where that becomes a pause the operator can resolve without
  losing the run. Raised by Copilot in review on #20.
- **`browser_actions` counts our own records.** `run.json`'s counter is the number of new
  lines in `<workspace>/logs/actions.jsonl`, which our helpers write, and not
  `HermesResult.actions`, which is what the agent believes it did — `09` already says
  which of the two `19` should prefer. The agent's number is logged at debug and goes no
  further.
- **The plan written to `plan.json` is the whole export**, even under `--only` or
  `--limit`: §10's "conversations found" is a property of the export, `19` accounts for
  every conversation in it, and a plan whose shape changed with the flags would not be a
  record of anything. (`--dry-run` still plans the selection only — that is `05`'s
  block, answering "what would this run do".)
- **`--retry-failed` can select an unsupported conversation, and it is skipped without a
  Hermes run.** It is `failed` in `state.json` like any other failure, so selection
  cannot tell it apart; the loop can, from the plan, and it records nothing new rather
  than rendering a prompt for a conversation that has no seed. The same guard catches a
  conversation whose uuid cannot be a directory name (`04`), which the plan does not
  check: it becomes one `failed` entry with category `unsupported`, and nothing is
  written outside the workspace.
- **`--pilot` is refused, not ignored.** `01` left `--force-unlock`, `--retry-*` and
  `--skip-attachments` accepted and inert, and this slice makes the first three real;
  `--skip-attachments` stays inert because nothing uploads anything until `16`, so it
  already describes what happens. `--pilot` cannot be inert: it asks for a *different
  selection*, and accepting it while running the ordinary one would migrate a set of
  conversations nobody asked for. It exits `69` with `not implemented in this build:
  import --pilot` until `20`.
- **An empty selection is a `RunSummary` with exit `4`, not an exception.** `06` makes it
  exit `4`; making it a return value means the run record in `run.json` is still
  appended and completed with that code, so "the run that did nothing" is as visible
  afterwards as any other.
- **The progress line is `18`'s, minus its detail column.** `{short_id}  {status}
  ({done}/{total})` is exactly `18`'s non-TTY event line without the `partial`/`failed`
  detail, and the final block is `06`'s counters — so when `18` lands it replaces a
  `Progress` implementation rather than a print statement. `--quiet` suppresses the event
  lines and not the final block, which is `18`'s rule, and `done` counts the unsupported
  entries as done from the first line because they are `failed` before the loop starts.
- **The pacing delay is a constant and a seam, not a setting.** `importer.pause` is one
  function and `DELAY_BETWEEN_CONVERSATIONS_S` is one number; `15` replaces both with
  `pacing.*`. A pacing parameter exposed in `config.toml` before there is any evidence
  about what the destination account tolerates is a parameter an operator would tune
  wrongly, and `15` is the slice that will have the evidence.
- **`AuthError` gets its own clause in the CLI.** `01` predicted it: "`auth` and `browser`
  map to codes of their own, and the slice that adds that behaviour adds its clause." A
  run that finds itself signed out raises it from wherever it noticed and the CLI turns
  it into exit `3` with `07`'s own words, which now live in `browser.session` so that
  `session status` and the import loop cannot drift apart.
- **A run id is built, not trusted.** `<short id>-<attempt>` names the three files `09`
  writes per run, and the short id comes off an export we do not control, so anything
  that is not a letter or a digit is dropped before it becomes a filename. `09` checks
  the result as well; this makes that check something that cannot fire.
- **Usage is read on every path.** A Hermes run that timed out still spent tokens, so
  `--usage-file` is read in a `finally` rather than after a successful result, and an
  absent or empty file adds nothing (`09`).

## Acceptance criteria

- With a fake Hermes that returns `completed` and a fixed uuid, `import --limit 1` on the
  fixture creates one `completed` entry with that `conversation_id`, `messages_represented`
  equal to the fixture's active-path count, and exits `0` — `test_importer.py`.
- A fake Hermes that raises on the second conversation: the run finishes all selected
  conversations, the second is `failed`, exit `1` — `test_importer.py`.
- Re-running immediately after a fully successful run exits `4` — `test_importer.py`.
- The real thing: one short fixture-like conversation in the throwaway account, created by
  a real Hermes run, appears in `state.json` as `completed` and opens at its
  `/chat/<uuid>` URL — **unverified**: it needs an installed Hermes and an account, like
  `09`'s and `11`'s first criteria. `20` is where it is checked.
- Stdout of a full fixture run contains no fixture message text and no titles, and neither
  does the run log — `test_importer.py`.

## Risks

- Hermes may report `completed` without the acks actually being present. `17` re-verifies
  from the page; until then `20` reads transcripts by hand.
- Every failure is terminal in this slice: there is no retry, no pause and no rate-limit
  wait, so a run against a busy account records failures a later run has to be asked to
  retry by hand. `13`, `14` and `15` are those three, and each has a row in the mapping
  table pointing at it.
- The loop is proven against a fake Hermes that answers instantly and a modelled page.
  What it cannot show is a run whose Hermes takes half an hour, a browser that dies
  mid-task, or an account that rate-limits after the fourth conversation. `20` is the
  first time any of those is observed.
