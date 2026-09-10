# 13 — Recovery

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §11 (detect and recover from the listed failures)
**Depends on:** [12](12-import-loop.md)
**Enables:** [14](14-human-intervention.md), [19](19-report.md)
**Status:** Not started

## Goal

Every failure the brief lists in §11 has a written detection signal, an in-run recovery
Hermes attempts, a classification when recovery fails, and a tool-side retry policy. No
failure is handled by "sleep and hope".

## In scope

- The *Recovery* section of `SKILL.md` (`11`), one row per §11 item, quoted from
  `docs/claude-ui-map.md` for the signals:

  | Failure (§11) | Detection | In-run recovery (Hermes, at most once per step) | If still failing → result |
  | --- | --- | --- | --- |
  | failed click | after the click the verify condition is unchanged | re-snapshot, find the element again by role/label, click once more | `failed`, category `ui`, `last_step` = the step |
  | missing composer | `probe.composer_present == false` on `/new` | reload `/new`; wait 5 s; re-probe | `failed`, `ui` |
  | unexpected dialog | `probe.dialogs` non-empty, or snapshot shows `[role=dialog]` | if it is a JS dialog: `browser_dialog(dismiss)`; if a page modal with a close/dismiss control: click it once; never click anything labelled delete, confirm, upgrade, allow | `needs_human`, reason `ambiguous_ui` |
  | login expiry | `probe.kind == login`, or a snapshot shows a sign-in form | none | `needs_human`, reason `auth_required` |
  | rate limiting | a message matching the UI map's rate-limit text; Send disabled with a quota notice | none | `rate_limited`, `retry_after_s` parsed from the text when present |
  | generation failure | error banner or a retry affordance after submit; `await-response` returns no assistant message | click the retry affordance once; `await` again | `partial` if some parts acked, else `failed`; category `generation` |
  | network error | `probe` errors, Chrome error page, `browser_navigate` fails | reload once after 5 s | `failed`, `network` |
  | page navigation | URL leaves `/new` or the run's `/chat/<id>` unexpectedly | navigate back to the run's chat (or `/new` if no id yet) | `failed`, `navigation` |
  | Claude UI change | expected element absent, no rule above applies | one attempt to reach the goal by reasoning over the snapshot, verified the same way | `needs_human`, reason `ambiguous_ui` |
  | CAPTCHA / security challenge | UI map signals | none | `needs_human`, `captcha` / `security_challenge` |

- Tool-side policy in `Importer` (`12`), driven by `01`'s `transient` flag and the
  result:

  | Result | Policy |
  | --- | --- |
  | `failed`/`partial` with a transient category | retry the conversation after backoff `retries.backoff_s[attempt-1]` (default `[30, 120, 300]`) until `attempts == retries.max_attempts` (default `3`); a `partial` retry resumes from `last_step` in the existing chat |
  | `failed`/`partial` with a non-transient category | record; do not retry; `retry_recommended = false` |
  | `HermesError` (timeout, bad JSON) | counts as transient; same budget |
  | `needs_human` | `14`; not a retry |
  | `rate_limited` | `15`; not a retry |

  Every retry increments `run.json.retries` and logs `{event: "retry", uuid, attempt,
  category, backoff_s}`. Backoff waits are shown on stdout as `waiting 120s (retry 2/3,
  generation)` so a quiet run is not a stuck run.
- `error.retry_recommended` in state: `true` if the category is transient and attempts
  remain, `false` if non-transient or exhausted, `null` when the category is `ui` or
  `browser` with unknown transience.
- Circuit breaker hook: after `run.stop_after_consecutive_failures` (default `3`)
  conversations in a row end `failed` with the same category, the run stops cleanly
  (state consistent, lock released) with exit `1` and the message
  `stopping: 3 consecutive failures (network) — see report`. `15` owns the value.

## Out of scope

- The human handshake (`14`), rate-limit waiting (`15`).

## Design notes

- "At most once per step" for in-run recovery keeps a single conversation from consuming
  a run; the tool-side budget is where persistence lives, and it is per conversation so
  one pathological chat cannot exhaust everything.
- A `partial` retry resumes in the same chat rather than creating a new one, because a
  half-migrated chat plus a full second copy is worse for the destination account than a
  completed single chat (§17: do not spray the account with duplicates).

## Acceptance criteria

- Fixture pages for each row (a dialog, a login form, a rate-limit notice, an error
  banner) drive a stubbed Hermes run and produce the result in the last column — one test
  per row.
- A fake Hermes returning `failed`/`network` twice then `completed`: the conversation ends
  `completed` with `attempts == 3`, `run.json.retries == 2`, and the two backoff waits
  are logged and printed.
- A fake Hermes returning `failed`/`unsupported`: no retry, `retry_recommended == false`.
- Three consecutive `network` failures stop the run with exit `1` and the message above;
  the remaining selected conversations are still `pending`.

## Risks

- Signals in the table go stale when claude.ai changes. Every row cites the UI map row it
  came from, and `20` records which rows fired.
