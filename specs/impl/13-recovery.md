# 13 — Recovery

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §11 (detect and recover from the listed failures)
**Depends on:** [12](12-import-loop.md)
**Enables:** [19](19-report.md)
**Composes with:** [14](14-human-intervention.md) — this slice hands `needs_human` to it
(see the table below); neither gates the other, and both share `Importer._migrate`
**Status:** Done

## Goal

Every failure the brief lists in §11 has a written detection signal, an in-run recovery
Hermes attempts, a classification when recovery fails, and a tool-side retry policy. No
failure is handled by "sleep and hope".

## In scope

- The *Recovery* section of `SKILL.md` (`11`), one row per §11 item, quoted from
  `docs/claude-ui-map.md` for the signals:

  | Failure (§11) | Detection | In-run recovery (Hermes, at most once per step) | If still failing → result |
  | --- | --- | --- | --- |
  | failed click | after the click the verify condition is unchanged | re-snapshot, find the element again by role/label, click once more | `failed` (`partial` if a chat exists), category `ui`, `last_step` = the step |
  | missing composer | `probe.composer_present == false` on `/new` or on the run's chat | reload that URL; wait 5 s; re-probe | `failed` (`partial` if a chat exists), `ui` |
  | unexpected dialog | `probe.dialogs` non-empty, or snapshot shows `[role=dialog]` | if it is a JS dialog: `browser_dialog(dismiss)`; if a page modal with a close/dismiss control: click it once; never click anything labelled delete, confirm, upgrade, allow | `needs_human`, reason `ambiguous_ui` |
  | login expiry | a helper answers `outside_migration_surface` with a `url` under `/login`, or a snapshot shows a sign-in form | none | `needs_human`, reason `auth_required` |
  | rate limiting | a message matching the UI map's rate-limit text; Send disabled beside a composer that is not empty | none | `rate_limited`, `retry_after_s` parsed from the text when present |
  | generation failure | error banner or a retry affordance after submit; `await-response` returns no assistant message | click the retry affordance once; `await` again | `partial` if some parts acked, else `failed`; category `generation` |
  | network error | `probe` errors (`no_claude_tab`, `unknown_target`), Chrome error page, `browser_navigate` fails | reload once after 5 s | `failed` (`partial` if a chat exists), `network` |
  | page navigation | URL leaves `/new` or the run's `/chat/<id>` unexpectedly | navigate back to the run's chat (or `/new` if no id yet) | `failed` (`partial` if a chat exists), `navigation` |
  | Claude UI change | expected element absent, no rule above applies | one attempt to reach the goal by reasoning over the snapshot, verified the same way | `needs_human`, reason `ambiguous_ui` |
  | CAPTCHA / security challenge | UI map signals | none | `needs_human`, `captcha` / `security_challenge` |

  Plus the row that is not a §11 failure but is the answer to a helper error with a
  recovery of its own: `ambiguous_tab` → `close-extra-tabs` once, then repeat the call;
  and `outside_migration_surface` anywhere but `/login` → `failed` (`partial` if a
  chat exists), `safety`, never retried.
- Tool-side policy in `Importer` (`12`), driven by `01`'s `transient` flag and the
  result:

  | Result | Policy |
  | --- | --- |
  | `failed`/`partial` with a transient category | retry the conversation after backoff `retries.backoff_s[attempt-1]` (default `[30, 120, 300]`) until `attempts == retries.max_attempts` (default `3`); a `partial` retry resumes from `last_step` in the existing chat |
  | `failed`/`partial` with a non-transient category | record; do not retry; `retry_recommended = false` |
  | `failed`/`partial` with an unknown transience (`ui`, `browser`, `verification`) | record; do not retry; `retry_recommended = null` |
  | `HermesError` (timeout, bad JSON) | counts as transient; same budget |
  | `HermesUsageError` (exit `2`, not installed) | category `hermes` but never transient; not retried |
  | `needs_human` | `14`; not a retry |
  | `rate_limited` | `15`; not a retry |

  Every retry increments `run.json.retries` and logs `{event: "retry", conversation_id,
  attempt, category, backoff_s}`. Backoff waits are shown on stdout as
  `waiting 120s (retry 2/3, generation)` so a quiet run is not a stuck run.
- `error.retry_recommended` in state: `true` if the category is transient and attempts
  remain, `false` if non-transient or exhausted, `null` when the category is `ui` or
  `browser` with unknown transience.
- Configuration: `[retries] max_attempts`, `backoff_s`, and
  `[run] stop_after_consecutive_failures`, through the ladder `01` built. `15` owns the
  values.
- Circuit breaker: after `run.stop_after_consecutive_failures` (default `3`)
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

Resolved while building:

- **The login page is outside the migration surface, so `probe.kind == login` is
  unreachable through our own helper.** `08`'s wall is applied to the tab's URL before
  any CDP call, and `https://claude.ai/login` does not match `MIGRATION_SURFACE`; a probe
  of an expired session therefore answers `{"ok": false, "error":
  "outside_migration_surface", "url": "https://claude.ai/login…"}` and never reports a
  `kind`. That refusal *is* the signal — it carries the URL — and it is what the skill's
  login row now names. `docs/claude-ui-map.md`'s `signed out` row says so. The
  alternative, punching a hole in the wall so `probe` could read the login page, was
  rejected: the wall is one line and worth more than the convenience.
- **Missing composer and login expiry are two rows, told apart by where the tab is.**
  `probe.logged_in` is false for both — it is `kind is not login and composer_present` —
  so the discriminator is the URL, not the flag. `12`'s preflight still treats a
  composer-less page as signed out (exit `3`), and rightly: it runs before there is a
  run, so there is no run URL to compare against and no conversation to fail.
- **`retry_recommended is True` is the whole retry decision.** `01` made `transient` a
  property of the error class so that `13` would not have to guess, and `12` already
  writes that property into every error record — off the class for a result, off the
  *instance* for an exception, which is the one place the two differ
  (`HermesUsageError`). Reading the field rather than re-deriving it means the number
  `19` prints and the decision the loop makes cannot disagree.
- **An unknown transience is not retried, and stays unknown.** `ui`, `browser` and
  `verification` are `01`'s three "per instance" rows. Retrying them would force the
  record to `false` once the budget ran out, which contradicts this slice's own rule for
  the field; and the skill has *already* spent a recovery on exactly those failures in
  the page, which is where a failed click or a missing composer is actually recoverable.
  An operator who disagrees has `--retry-failed`.
- **The budget is measured against §7's cumulative `attempts`, not a per-run counter.**
  So a conversation that has already had three goes gets one more per invocation rather
  than three more — an operator asking for it again is never silently refused, and a
  conversation nobody asked about is never tried a fourth time on its own.
- **Every `failed` row is really `failed` *or* `partial`, and the skill now says so.**
  The table this slice inherited wrote `failed` flat for the click, composer,
  network, navigation and surface rows, but `12` already resolved the question
  once for the whole tool: `partial` versus `failed` is "is there a chat", because
  §7's `failed` means there is nothing at the destination to go and look at. An
  agent told to report `failed` after part one had landed would erase from the
  record a chat that `14` resumes and `19` counts. The skill states the rule once
  and each affected row carries the condition; only the generation-failure row had
  it before. (Raised by Copilot in review on #22.)
- **`needs_human` and `rate_limited` are marked in the mapping table itself.**
  `Mapped.deferred` is set by `interpret`, so `12`'s table and `13`'s policy are one
  table read twice rather than two branches on `result.outcome` that can drift.
- **The breaker counts conversations the loop attempted, `failed` only, same category.**
  A `partial` left a chat at the destination, and an unsupported entry selected by
  `--retry-failed` was never handed to Hermes; neither is evidence that the next
  conversation would fail, which is the only thing the count is for. A limit of `0`
  switches the breaker off.
- **The backoff schedule repeats its last value** rather than running off the end, so a
  shortened `backoff_s` means shorter waits and not *no* waits.
- **Waits and the stop line went on the `Progress` protocol**, not into a `print` in the
  loop: `18` replaces an implementation of that protocol, and its golden strings then
  have one place to live. `waiting` is progress and `-q` suppresses it; `stopping` is
  what became of the run and is printed under `-q`, like the counters block.
- **The log record is keyed by `conversation_id`, a short id, and not by the uuid** the
  spec's sketch named — every other record this module writes is, and §10 is easier to
  keep when the log and the terminal read alike.
- **Three rows cannot be tested against a page.** Rate limiting, CAPTCHA and security
  challenge are recognised by reading claude.ai's own words in a snapshot; every row of
  `docs/claude-ui-map.md` for them still says `*unknown*`, and a scripted agent has no
  judgement to exercise. Their result mapping is tested instead, and the acceptance
  criteria below say which rows are which. `20` is the first time anybody sees the pages.
- **`fake_agent` grew the deterministic half of the table.** It was written for `11` as a
  reader with no judgement in it; `13` gives it the detections that are fields of a probe
  object or `error` strings of a helper answer, and the one recovery each row allows. It
  records which row fired, so a test asserts not only the outcome but that the outcome
  came from the row it was meant to. What it still cannot do is decide — which is exactly
  the part `20` measures.

## Acceptance criteria

- One test per row of the table, in `tests/test_recovery.py`:
  - the eight rows a page can show — failed click, missing composer, unexpected dialog,
    login expiry, generation failure, network error, page navigation, Claude UI change —
    each driven by a fixture page through the real helpers and the scripted agent, each
    producing the result in the last column, and each asserting which recovery fired;
  - the three rows that rest on reading a snapshot — rate limiting, CAPTCHA, security
    challenge — tested at their result mapping: the state, the category, and that no
    retry is spent on them;
  - plus `ambiguous_tab`, whose recovery is `close-extra-tabs` and whose run then
    completes.
- A fake Hermes returning `failed`/`network` twice then `completed`: the conversation ends
  `completed` with `attempts == 3`, `run.json.retries == 2`, and the two backoff waits
  are logged and printed.
- A fake Hermes returning `failed`/`unsupported`: no retry, `retry_recommended == false`.
- A fake Hermes returning `failed`/`network` for ever: three attempts, then
  `retry_recommended == false` because the budget is spent.
- Three consecutive `network` failures stop the run with exit `1` and the message above;
  the remaining selected conversations are still `pending`.
- Nothing a recovery prints is content, at any verbosity — `test_recovery.py`.
- The real thing: a failure provoked in the throwaway account recovers or classifies as
  the table says — **unverified**, like `12`'s last criterion. `20` is where each row
  that fires is recorded.

## Risks

- Signals in the table go stale when claude.ai changes. Every row cites the UI map row it
  came from, and `20` records which rows fired.
- A scripted agent cannot misread the table; a real one can. The rows that are prose
  rather than a field — "never click anything labelled delete, confirm, upgrade, allow",
  "one attempt to reach the goal by reasoning over the snapshot" — are unmeasured until
  `20`.
- The three snapshot-only rows have no signal anybody has observed, so a rate limit may
  be classified as `ambiguous_ui` and become a `needs_human` where `15` should have
  waited. `20` counts how often that happens, and `docs/claude-ui-map.md` is where the
  answer lands.
