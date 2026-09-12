# 14 — Human intervention

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §12
**Depends on:** [12](12-import-loop.md) — and composes with [13](13-recovery.md),
which owns the other half of `Importer._migrate`
**Enables:** [19](19-report.md) (interventions counter)
**Status:** Done

## Goal

When Hermes cannot safely proceed, the run pauses with a clear ask, the human acts in the
visible browser window, and the run continues from the same conversation and step — it
never restarts.

## In scope

- On `HermesResult.outcome == "needs_human"`, `Importer` writes to `run.json`:

  ```json
  "paused": {
    "conversation_uuid": "…",
    "reason": "auth_required",
    "detail": "sign-in form shown at /login",
    "last_step": "open",
    "conversation_id": null,
    "since": "2026-09-10T14:03:11Z"
  }
  ```

  leaves the conversation `running`, increments `run.json.human_interventions`, and prints
  exactly:

  ```text
  Human intervention required

  Reason:       authentication required
  Conversation: 3f9c2a1e (12 of 127)
  Last step:    open
  Browser:      the Chrome window is open — complete the step there

  Press Enter to resume, or Ctrl-C to stop.
  ```

  Reason phrases, exact: `authentication required`, `CAPTCHA`, `security challenge`,
  `ambiguous UI state`, `unrecoverable browser error`, `confirmation required:
  <detail>`. Labels are padded to 14 characters.
- TTY: the tool blocks on Enter. On Enter it re-probes; if the reason was
  `auth_required` and `probe.logged_in` is still false it prints `still not logged in`
  and waits again. Then it re-runs the same conversation with `resume_from = last_step`
  and the recorded `conversation_id`, clears `paused`, and continues the selection.
- Non-TTY: prints the block, keeps `paused`, releases the lock, exits `5`.
  `hermes-claude-migrate resume` re-locks, re-probes, and continues exactly as the TTY
  path does; with no `paused` record it exits `4` `nothing to resume`.
- `--non-interactive` (`24`): `intervention.Unattended` answers every ask with no and never
  touches stdin — a terminal the run was started from is not a person. The block keeps
  its shape with two lines swapped: `Browser:      no window — non-interactive run;
  clear it, then run: hermes-claude-migrate resume` and, in place of the prompt, `Paused
  for a person (non-interactive); run: hermes-claude-migrate resume`. An `auth_required`
  ask in that mode is first put to the tool itself — a sign-in from the credentials,
  `13`-shaped, counted as `auto_signins` and never as an intervention — and only when
  that fails does it become this pause; `resume --non-interactive` tries the sign-in
  again before re-probing. The two intervention counters are bumped where the ask is
  put (`_intervene`), not where the record is written (`_pause`), so that a pause the
  tool cleared itself is written down but never counted as a person's.
- Ctrl-C at the prompt: `paused` stays, the conversation stays `running` (crash recovery in
  `06` will convert it on the next start), lock released, exit `5`.
- `confirmation_required`: the printed detail is Hermes's description of the action it
  wanted; the human either performs it in the window or not. Resuming never grants Hermes
  permission to do it — the skill rule (`11`) still applies; the human's action is what
  changes the page.
- Intervention budget: `run.max_interventions` (default `5`) per run; when exceeded the
  run stops with exit `1` and `too many interventions — see report`.

## Out of scope

- Waiting out a rate limit is not an intervention (`15`), unless the wait would exceed
  `pacing.max_rate_limit_wait_s`, in which case it becomes one with reason
  `confirmation required: rate limit until <time>`.

## Design notes

- The run resumes the *same* conversation from its *last successful step* (§12 "resume
  rather than restart") because the chat may already exist; restarting would duplicate
  it.
- The pause record is in `run.json`, not `state.json`, so the §7 file keeps its shape and
  the conversation's status is still one of the five.

Resolved while building:

- **Built beside `13` rather than on top of it, and then landed on top.** The declared
  dependency was about the retry policy, and a pause is not a retry: `13`'s own table
  routes `needs_human` to this slice, so it never enters that table. What `12` already
  had — a prompt carrying `resume_from` and a `conversation_id`, an entry recording
  both — is all the resume needs, so the work was done independently and rebased onto
  `13` once it merged. The two meet in exactly one place, `Importer._migrate`:

  | | `13` | `14` |
  | --- | --- | --- |
  | What it waits for | a backoff | a person |
  | What it retries | a failure another try could fix | a page only a person can clear |
  | Budget | `retries.max_attempts`, per conversation | `run.max_interventions`, per run |
  | Ends the run | `run.stop_after_consecutive_failures`, exit `1` | budget spent, exit `1`; nobody to ask, exit `5` |

  One `while` serves both. A `needs_human` result is `deferred`, so `Attempt.retryable`
  is false for it and `13` never retries one; the ask is put *before* the budget is
  consulted, so a conversation can still be unblocked by hand after its retries are gone.
- **An intervention is not an attempt, as far as `13` is concerned.** Every try
  increments §7's `attempts`, which is what `max_attempts` is measured against — so
  without a correction a conversation a person unblocked twice would have spent its
  retries on being helped, and `_exhausted` would write `retry_recommended: false` about
  a failure nothing had retried. `_migrate` discounts this run's interventions from the
  number it gives `13`, for all three of its uses: the budget, the backoff's index, and
  the `retry n/max` the waiting line prints (which otherwise reads `retry 4/3`). Only
  *this run's* — §7's count is cumulative and records no reason for each attempt, so an
  intervention in an earlier run is still counted against the budget in a later one,
  which errs towards trying less rather than more.
- **`resuming()` reads a `running` entry as well as a `partial` one.** A pause leaves the
  conversation `running`, and the next attempt has to continue its chat rather than open
  a second one. No other status can be `running` when an attempt begins — crash recovery
  runs first — so the two are the whole of "there is a chat to continue".
- **`recover()` takes a `keep`, and `resume` passes it.** See `06`. `import` does not, so
  the third acceptance criterion below holds: a pause a human walked away from is
  converted per `06` by the next `import`, which also prints
  `paused at <short id> — run: hermes-claude-migrate resume` on stderr so the record is
  not silently overtaken.
- **The pause is cleared by starting the conversation again, not by `resume` itself.**
  Either command can be the one that picks it up; the question the record asks is
  answered the moment something re-attempts the conversation it names. A `resume` over a
  conversation that finished another way clears the record and exits `4` rather than
  opening a second chat, which §17 has no way to undo.
- **`resume` does not re-print the block, and neither does a failed re-probe.** The
  operator running `resume` has already read the ask and is saying they acted; the
  handshake starts at the check. A re-probe that still finds a sign-in form prints
  `still not logged in` and waits again — one ask, however many Enters it takes — so a
  single pause is a single intervention against the budget.
- **The re-probe reads `logged_in`, which `13` points out is false for two pages.**
  `13` tells a missing composer from a login expiry by where the tab is, because
  `probe.logged_in` is `kind is not LOGIN and composer_present` and so false for both.
  For this gate the conjunction is the right test rather than a looseness to fix: the
  run is about to hand the tab back to Hermes, which needs a composer to type into, so
  "signed in but no composer" is not cleared either. The cost is that
  `still not logged in` is a slightly wrong description of that second page — accepted,
  because §12 fixes the phrase and the operator is looking at the window it describes.
  Note also that the `outside_migration_surface` refusal `13` reads the login page from
  belongs to the `browser` *helpers* Hermes calls; `browser_session.signed_in` probes
  in-process and is not subject to that guard, which is why this check can see a login
  page at all.
- **The ask goes to stdout, advisories to stderr.** The block and `still not logged in`
  are the thing being waited on and share the stream the Enter answers; the offer line
  and `too many interventions — see report` are not questions. Both are printed under
  `--quiet`, which suppresses progress and not questions. This is the one place the two
  slices differ cosmetically: `13`'s stop line is on the `Progress` protocol and goes to
  stdout, because it reports what became of the *migration* (conversations failed);
  `14`'s is on `Intervention` and goes to stderr, because it reports that the tool
  stopped asking. A reviewer who prefers one stream for both should say so — the seam is
  one line either way.
- **`(N of M)` counts the paused run's selection, not the tail `resume` inherits.** An
  operator told "conversation 1 of 2" by the command continuing "conversation 2 of 3" has
  been told the wrong thing twice, so `resume` continues the recorded selection from the
  paused conversation's index and keeps both numbers.
- **The exhausted run still writes its pause record.** The sixth ask is recorded rather
  than put to anyone, so `run.json.human_interventions` counts it and `resume` can still
  continue once whatever kept happening has been dealt with. Exit `1` rather than `5` is
  what says the run gave up instead of waiting.
- **`Intervention` is a protocol, like `12`'s `Progress`.** `Console` is the terminal —
  `isatty`, a blocking `readline`, EOF and `KeyboardInterrupt` all decided in one place —
  and a test drives six interventions without one. `18` can re-draw the ask without
  touching the loop.

## Acceptance criteria

- A fake Hermes returning `needs_human`/`auth_required` once, then `completed`: on a
  pseudo-TTY the block above is printed byte-exactly, an Enter resumes, the conversation
  ends `completed` with `attempts == 2`, `human_interventions == 1`, and the second prompt
  contains `resume_from: open`.
- The same with stdin not a TTY: exit `5`, `paused` present; `resume` completes the run.
- Ctrl-C at the prompt leaves `paused` and a `running` entry; the next `import` converts
  it per `06` and offers `resume`.
- Six interventions in one run stop it with exit `1`.

## Risks

- The human may fix the page in a way the skill does not expect (e.g. sends a message
  themselves). The `resume_from` re-probe and the `identify` step make the chat id the
  source of truth, not the assumed state.
