# 06 — Migration state

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §7, §6 Phase 4 (resume)
**Depends on:** [01](01-foundation.md)
**Enables:** [12](12-import-loop.md), [14](14-human-intervention.md), [18](18-progress-output.md), [19](19-report.md)
**Status:** Not started

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
    "attachments": { "uploaded": 1, "inline": 0, "unsupported": 1 },
    "error": null,
    "limitations": ["thinking_omitted:3"],
    "updated_at": "2026-09-10T14:03:11Z"
  }
  ```

  The first three keys are the brief's; the rest are extensions. `destination` is
  `{"conversation_id": null}` until known. `error` is
  `{"category": "...", "detail": "...", "retry_recommended": true|false|null}` or `null`.
- `status` ∈ `pending | running | completed | partial | failed` — the five in §7, no
  others. Transitions:

  ```text
  pending ──> running ──> completed
                     ├──> partial      (chat exists; not everything landed)
                     └──> failed       (no chat, or abandoned before identify)
  partial / failed ──> running         (--retry-partial / --retry-failed / resume)
  completed ──> running                (--force only; old id kept in run.json)
  running ──> pending | partial        (crash recovery at startup, see below)
  ```

- `<workspace>/run.json` — run-level record, kept out of `state.json` so that file stays
  §7-shaped: `schema_version`, `export_fingerprint`, `runs[]` (started, ended, exit code,
  selection), counters `browser_actions`, `retries`, `human_interventions`, a `paused`
  record (`14`) or `null`, and `previous_destinations` for `--force` re-runs.
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
