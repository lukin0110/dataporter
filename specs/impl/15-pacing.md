# 15 — Pacing and limits

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §13
**Depends on:** [12](12-import-loop.md)
**Enables:** [18](18-progress-output.md) (waits are visible), [20](20-pilot.md)
**Status:** Not started

## Goal

Make the run deliberately slow and bounded: the §13 parameters exist with conservative
defaults, rate limits are waited out as instructed rather than guessed, and the run stops
itself before it can do damage at scale.

## In scope

- Configuration, `config.toml` section names and defaults, all overridable by `HCM_…`
  environment variables and, where noted, CLI flags:

  ```toml
  [pacing]
  delay_between_conversations_s = 20     # --delay
  delay_between_parts_s = 5
  max_rate_limit_wait_s = 3600

  [retries]
  max_attempts = 3                       # --max-retries (attempts = retries + 1)
  backoff_s = [30, 120, 300]

  [timeouts]
  hermes_run_s = 900                     # --timeout
  response_s = 300
  login_s = 600
  browser_start_s = 30
  cdp_call_s = 20
  attach_s = 60

  [run]
  max_conversations = 10                 # --limit ; --all lifts it
  stop_after_consecutive_failures = 3
  max_interventions = 5
  ```

  `hermes-claude-migrate doctor` prints the effective values under a `pacing` line so the
  numbers in force are visible before a run.
- Rate limiting: on `HermesResult.outcome == "rate_limited"`:
  - if `retry_after_s` is known and ≤ `max_rate_limit_wait_s`: print
    `waiting 1740s (rate limit until 15:00 UTC)` and sleep, re-probing every 60 s so a lifted
    limit is noticed early; then re-run the same conversation from `last_step`;
  - if unknown: wait `backoff_s[attempt-1]`, then re-run; three unknown waits in a row
    become an intervention (`14`);
  - if longer than the cap: intervention with `confirmation required: rate limit until
    <time>`.
  Rate-limit waits count in `run.json.rate_limit_waits` and are neither retries nor
  interventions in the report unless escalated.
- Parts within a conversation wait `delay_between_parts_s` between the ack of one part and
  the paste of the next; conversations wait `delay_between_conversations_s` after any
  terminal status.
- Circuit breaker value from `13` lives here; also `auth`: one `auth_required`
  intervention that the human cannot resolve within `login_s` stops the run with exit `3`.
- `--all` is required to exceed `max_conversations`; `--limit` above it without `--all` is
  a usage error (exit `2`) with `use --all to migrate more than 10 conversations in one
  run`.

## Out of scope

- The visual form of waits (`18`) beyond the single line specified here.

## Design notes

- Defaults are chosen for a first real run of five to ten conversations (§18), not for
  throughput. Twenty seconds between conversations plus a 300 s response budget bounds a
  ten-conversation run to under an hour and keeps request rate far below anything a human
  could not produce by hand.
- "Wait as instructed" means parsing the UI's own time when it shows one; the parser and
  its test strings come from `docs/claude-ui-map.md`.

## Acceptance criteria

- Every key above is readable through `Settings`, overridable by environment and by the
  named flag; a test sets each three ways and asserts precedence.
- A fake Hermes returning `rate_limited` with `retry_after_s = 3` then `completed`: the
  wait line is printed, the conversation ends `completed`, `rate_limit_waits == 1`,
  `retries == 0`.
- With `max_rate_limit_wait_s = 2` and `retry_after_s = 3`: an intervention is raised
  instead.
- `--limit 11` without `--all` exits `2` with the message above.
- A run's wall-clock gaps between conversations are ≥ `delay_between_conversations_s`
  (fake clock).

## Risks

- The rate-limit text may not include a time. The unknown branch exists for that, and
  `20` records how often it was hit.
