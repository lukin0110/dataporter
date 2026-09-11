# 06 — Migration state

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §7, §6 Phase 4 (resume)
**Depends on:** [01](01-foundation.md)
**Enables:** [12](12-import-loop.md), [14](14-human-intervention.md), [18](18-progress-output.md), [19](19-report.md)
**Status:** Done

## Goal

The local migration state exactly as §7 shapes it, written atomically after every change,
locked against concurrent runs, and rich enough that a killed run resumes rather than
restarts.

## In scope

- `<workspace>/state.json` — top-level object keyed by source conversation id, each value:

  ```json
  {
    "title": "Example conversation",
    "status": "completed",
    "destination": { "conversation_id": "9b1f...-..." },
    "attempts": 1,
    "last_step": "verify",
    "chunks_acked": 2,
    "chunks_total": 2,
    "messages_represented": 38,
    "attachments": {
      "uploaded": 1,
      "inline": 0,
      "unsupported": 1,
      "failed": 0,
      "detail": [{ "file_name": "notes.csv", "klass": "unsupported",
                   "reason": "bytes_not_in_export" }]
    },
    "error": null,
    "limitations": ["thinking_omitted:3", "timestamps_not_preserved"],
    "verified_at": "2026-09-10T14:03:19Z",
    "updated_at": "2026-09-10T14:03:11Z"
  }
  ```

  The first three keys are the brief's; the rest are extensions. `destination` is
  `{"conversation_id": null}` until known. `error` is
  `{"category": "...", "detail": "...", "retry_recommended": true|false|null}` or `null`.
  `verified_at` is `17`'s and is `null` until a verification passes: the timestamp says
  the destination chat was read back off the page and held every part and every
  acknowledgement, which is a different claim from `status: completed` — that one is the
  agent's. A verification that fails clears it and leaves the entry `partial`.
  `limitations` carries `04`'s rendering slugs first and then `17`'s observations of the
  destination — `timestamps_not_preserved` always, `title_not_set` when the chat is not
  called what the source conversation was called.
  `attachments` grew its fourth count and its `detail` list in `16`: `failed` is a class 2
  file the upload itself refused, and `detail` carries one entry per attachment that is not
  in the chat as an upload, so the four counts always add up to the number of attachments
  `plan.json` found for that conversation.
- `status` ∈ `pending | running | completed | partial | failed` — the five in §7, no
  others. Transitions:

  ```text
  pending ──> running ──> completed
                     ├──> partial      (chat exists; not everything landed)
                     └──> failed       (no chat, or abandoned before identify)
  partial / failed ──> running         (--retry-partial / --retry-failed / resume)
  completed ──> running                (--force only; old id kept in run.json)
  completed ──> partial                (17 only: the page does not hold what was claimed)
  running ──> pending | partial        (crash recovery at startup, see below)
  ```

- `<workspace>/run.json` — run-level record, kept out of `state.json` so that file stays
  §7-shaped: `schema_version`, `export_fingerprint`, `export_path` (`14`), `runs[]`
  (started, ended, exit code, selection — including `16`'s `skip_attachments`), counters
  `browser_actions`, `retries`,
  `human_interventions`, a `paused` record (`14`) or `null`, and `previous_destinations`
  for `--force` re-runs.
- `StateStore`: `load()`, `update(uuid, **fields)`, `bump_counter(name)`; every mutation
  writes the whole file to `state.json.tmp` then `os.replace`. JSON is indented, keys in
  insertion order, so the file is diffable by hand.
- Lock: `<workspace>/.lock` containing the PID and start time, taken with `O_EXCL`. A
  second run exits `2` with `workspace locked by pid 4242 since 14:01:07 — use
  --force-unlock if that process is gone`. `--force-unlock` removes a lock whose PID is not
  alive.
- Crash recovery at startup: any `running` entry becomes `partial` if
  `destination.conversation_id` is set, otherwise `pending`; `attempts` is kept; the
  event is logged and counted as `interrupted` in `run.json`.
- Selection, applied in this order: `--only UUID` (repeatable, also accepts the 8-char
  short id) restricts to those; otherwise `pending` entries; `--retry-failed` adds `failed`;
  `--retry-partial` adds `partial`; `--force` adds `completed`; `--limit N` (default from
  `run.max_conversations`, `10`) truncates in export order. Empty selection → exit `4`
  `nothing to do`.
- Export fingerprint mismatch between `run.json` and the export given → exit `2`
  `workspace belongs to a different export`; `--new-workspace` is not offered, the
  operator picks another `--workspace`.
- `hermes-claude-migrate status` prints the counters block from `18` (no bar) from state
  alone; `--json` dumps `state.json` merged with `run.json` counters.

## Out of scope

- Who sets `last_step` and how (`11`, `12`); the pause protocol (`14`).

## Design notes

- Titles are stored because §7 shows them. They are never printed by `status`, progress or
  the report (§10); `state.json` is the operator's file to open on purpose.
- Keeping run-level data in `run.json` rather than a `_meta` key means `state.json` can be
  validated against the §7 shape with no exceptions.
- `--force` never deletes anything at the destination (§17); it creates another chat and
  remembers the old id.

Resolved while building:

- **`status` prints the counters with no bar, and `18` has to reconcile.** `18` currently
  says `status` prints "lines 5–10 (bar and counters)". A bar that is drawn once is a
  picture of a number the line under it already gives, and `status` is a question about a
  finished or interrupted run rather than a view of one in flight. The counters live in
  `summary` beside the §9 block, because they are the same alignment rule with a different
  floor (`13` instead of `27`); `18` builds the header, the bar and the redraw on top of
  `counters_lines` rather than restating the rule.
- **An atomic write flushes twice, not once.** The file's own bytes, and then the
  directory entry `os.replace` rewrote — without the second, a power loss can leave the
  new contents on disk while the name still points at the old ones. The directory flush
  is best effort (a directory cannot be opened for reading on Windows), which costs
  nothing this spec promises: `os.replace` is atomic either way, so the SIGKILL criterion
  above holds regardless. Raised in review on `11`.
- **`run.json` records the export's path as well as its fingerprint.** §8 gives `resume`
  no arguments, so the run it continues has to be able to re-read the export the paused
  run was migrating. The fingerprint says *which* export the workspace belongs to and the
  path says where it was last seen; the path is refreshed on every run, because an export
  that has moved is still the same export and the fingerprint is what proves it. A
  workspace with no path recorded is reported by `resume` rather than guessed around.
  Raised while building `14`.
- **Crash recovery takes a `keep`.** `recover()` converts every `running` entry, which is
  right for a killed run and wrong for a paused one: `14`'s pause leaves a conversation
  `running` on purpose, and converting it would both inflate `interrupted` and — for a
  pause that never reached a chat — turn it back into a `pending` conversation that starts
  over, which is the one thing §12 forbids. `resume` passes the paused uuid; `import` does
  not, so a pause a human walked away from is still recovered per this spec.
- **`run.json` gains an `interrupted` counter.** The spec says crash recovery is "counted
  as `interrupted` in `run.json`" without naming a field. It is one of `COUNTERS`, so
  `bump_counter` reaches it and `19` can read it the same way as the other three.
- **An illegal transition is exit `70`, not exit `2`.** The §7 table is now a constant
  (`TRANSITIONS`) that `update` enforces, but no operator input can violate it — only our
  own code calls `update` — so it raises `ValueError` and lands in `01`'s internal-error
  guard rather than telling an operator to fix something they did not do. The same goes
  for an update naming a field an entry does not have. Every *operator* mistake here (a
  locked workspace, another export's workspace, an unknown `--only`, an unreadable state
  file) is a `StateError`, and the CLI has one clause that turns those into exit `2`.
- **`ensure(uuid, **fields)` joins `load`, `update` and `bump_counter`.** `12` re-creates
  every planned conversation as `pending` at the start of every run; with only `update`
  that would reset a finished migration on resume. `ensure` inserts and returns, or
  returns what is already there and writes nothing.
- **`--limit` truncates `--only` too**, exactly as written: the default is
  `run.max_conversations`, so `--only` naming twelve conversations migrates ten of them
  unless `--limit` says otherwise. `--only` picks *which*, `--limit` picks *how many*, and
  the alternative — a default that quietly does not apply on some paths — is worse than a
  number an operator can see in `run.json.runs[].selection`.
- **`--only` takes the short id everywhere.** `resolve_only` is shared with `04`'s `seeds`,
  which until now accepted full uuids only. Two commands with one `--only` that mean
  different things by it is a trap, and the short id is what an operator has in front of
  them: it is what a failure line prints.
- **`import --dry-run` reads `state.json` and `run.json`, and still writes nothing.** `05`
  promised the selection would apply "before counting" once `06` existed, so a dry run
  against a workspace where four conversations are `completed` now counts what is left.
  Reading is not writing: no directory is created, and `05`'s "a dry run leaves no
  workspace behind" test still passes.
- **`--force-unlock` is accepted by `import` and does nothing yet.** `12` is the first code
  that takes the lock and a dry run never does, so the flag is inert exactly as `05` left
  `--retry-failed` and `--retry-partial`. The behaviour behind it — break a lock whose pid
  is not alive, refuse one whose pid is — is built and tested at the `WorkspaceLock` level.
- **The lock's `since` is UTC**, like every other timestamp this tool writes. The message
  is the spec's, so it carries no zone marker; an operator comparing it against a wall
  clock in another zone will see an offset rather than a wrong number.
- **`status` on a workspace nothing has run in prints zeros and exits `0`.** `05` settled
  the same question for `inspect`: a command that answers a question answers it, and
  "nothing has happened here" is an answer. Exit `4` stays what it is — a *run* with
  nothing to do.
- **`PauseRecord` is typed here** rather than left as an untyped object for `14`, so
  `run.json` has one schema and `status --json` cannot emit something no model describes.
  `14` still owns what goes in it.
- **`status --json` is `{"state": …, "counters": …}`** — `state.json` verbatim under one
  key, the four status tallies and the four `run.json` counters under the other. Merging
  them into one flat object would put a counter name in the same namespace as a
  conversation uuid.

## Acceptance criteria

- A test kills the process (SIGKILL) between `tmp` write and `os.replace`; the previous
  `state.json` is intact and parses.
- A `running` entry with a destination id becomes `partial` on next start; one without
  becomes `pending`.
- Selection tests: `--retry-failed` selects only `failed`; `--only` with a short id
  resolves; `--limit 1` on 3 pending selects the first in export order.
- Two concurrent runs on one workspace: the second exits `2` with the locked message.
- `state.json` validates against a schema that allows only the keys listed above; a test
  asserts no fixture message body appears in it.

## Risks

- A schema change to `state.json` after real runs exist would strand operators.
  `run.json.schema_version` is checked at startup and a mismatch exits `2` with the
  migration instruction rather than guessing.
- `O_EXCL` creates the lock file and the pid is written into it a moment later. A second
  run that reads it inside that window sees an empty file and is told the lock is
  unreadable — which is still a refusal, so it cannot proceed; only a *third* run passing
  `--force-unlock` in the same window could break a live lock. One operator, one machine
  and one browser make that hypothetical, and closing it properly means `link()` rather
  than the `O_EXCL` this spec asks for.
