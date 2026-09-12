# 15 — Pacing and limits

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §13
**Depends on:** [12](12-import-loop.md) — and composes with [13](13-recovery.md) and
[14](14-human-intervention.md), whose waits and asks it joins in `Importer._migrate`
**Enables:** [18](18-progress-output.md) (waits are visible), [19](19-report.md)
(`rate_limit_waits`), [20](20-pilot.md)
**Status:** Done

## Goal

Make the run deliberately slow and bounded: the §13 parameters exist with conservative
defaults, rate limits are waited out as instructed rather than guessed, and the run stops
itself before it can do damage at scale.

## In scope

- Configuration, `config.toml` section names and defaults, all overridable by `DATAPORTER_…`
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
  hermes_task_s = 1800                   # --timeout
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

  `dataporter doctor` prints the effective values as its first line, before
  the ten checks, so the numbers in force are visible before a run — and visible even
  when the chain below them is broken:

  ```text
  pacing                    ok  (delay 20s, parts 5s, attempts 3, timeout 1800s, limit 10, rate-limit cap 3600s)
  ```
- Rate limiting: on `HermesResult.outcome == "rate_limited"`:
  - if `retry_after_s` is known and ≤ `max_rate_limit_wait_s`: print
    `waiting 1740s (rate limit until 15:00 UTC)` and sleep, re-probing every 60 s so a lifted
    limit is noticed early; then re-run the same conversation from `last_step`;
  - if unknown: print `waiting 30s (rate limit, no time given)`, wait
    `backoff_s[wait - 1]`, then re-run;
  - if longer than the cap: intervention with `confirmation required: rate limit until
    <time>`;
  - on the third consecutive refusal of one conversation, whether or not it named a
    time: intervention with `confirmation required: rate limited 3 times with no time
    given`, or `… 3 times, now until 15:00 UTC`. The count is per conversation and is
    spent by the ask.
  Rate-limit waits count in `run.json.rate_limit_waits` and are neither retries nor
  interventions in the report unless escalated.
- Parts within a conversation wait `delay_between_parts_s` between the ack of one part and
  the paste of the next; conversations wait `delay_between_conversations_s` after any
  terminal status, between one conversation and the next.
- Circuit breaker value from `13` lives here; also `auth`: one `auth_required`
  intervention that the human cannot resolve within `login_s` stops the run with exit `3`
  and `still not logged in after 600s — stopping`, keeping the pause record so `resume`
  can continue once the account is signed in.
- `--all` is required to exceed `max_conversations`; `--limit` above it without `--all` is
  a usage error (exit `2`) with `use --all to migrate more than 10 conversations in one
  run`. `--all` on its own is no limit at all.

## Out of scope

- The visual form of waits (`18`) beyond the single line specified here.
- Which signal on the page *is* a rate limit, and which is a limit that has lifted.
  `docs/claude-ui-map.md` owns both rows and still records them as `*unknown*`; `20` is
  where somebody watches them.

## Design notes

- Defaults are chosen for a first real run of five to ten conversations (§18), not for
  throughput. Twenty seconds between conversations plus a 300 s response budget bounds a
  ten-conversation run to under an hour and keeps request rate far below anything a human
  could not produce by hand.
- "Wait as instructed" means parsing the UI's own time when it shows one; the parser and
  its test strings come from `docs/claude-ui-map.md`.

Resolved while building:

- **The parsing is the agent's, and this slice consumes a number.** The spec above
  assumed a parser here. There is no page text in this process to parse: `11` already
  gives the skill the rate-limit row and asks it to report `retry_after_s` "set to the
  seconds the page names, when it names any", and `09`'s result contract carries the
  field. So `15` owns the *policy* around the number — wait it, cap it, guess when it is
  absent, escalate — and the wording that turns it into a time an operator can read. When
  `20` watches a real limit, the strings it produces correct the skill's row, not a
  parser here.
- **`hermes_run_s` is `timeouts.hermes_task_s`, and it is 1800 rather than 900.** The
  name was `09`'s and landed first; the number is this slice's to own and 900 is too
  small for what `09` then built. One conversation's run is a multi-part seed where every
  part waits on generation with a 300 s budget, so three parts alone can reach 900 before
  any recovery. Half an hour is the number a `--timeout` flag exists to shorten.
- **A rate limit that interrupted a chat is `partial`, not `failed`.** `13` wrote
  `Status.FAILED` into that row of `interpret`, which was harmless while nothing tried
  the conversation again. It stops being harmless here: `resuming()` reads a `failed`
  entry as "there is no chat", so the attempt after the wait would open a second chat for
  the same source conversation — the one mistake §17 has no way to undo. The row now
  reads `landed` like every other, and `13`'s test says so.
- **A wait is not a retry, and a person is not a retry.** Both spend an attempt in §7's
  cumulative `attempts` and neither is a failure tried again, so `_migrate` discounts
  them from the number it gives `13`'s budget — `14` already did this for asks, and the
  counter is the other half of it: `run.json.retries` now counts only the attempt that
  follows a backoff. `19` reports `retries`, `rate_limit_waits` and `human_interventions`
  apart, and before this the same event could land in two of them. The rule an operator
  can check is the acceptance criterion below: a conversation rate limited once and then
  completed has `rate_limit_waits == 1` and `retries == 0`.
- **The three-strikes rule covers the named refusals too, which the spec above left
  open.** It was written for the page that will not say *when*, where each wait is
  `13`'s backoff and therefore a guess. But a limit that names a time and then names a
  later one has no end either: the first version of this loop, given a fake Hermes that
  answered `rate_limited` forever, waited and re-ran forever, and a tool that sits still
  indefinitely has stopped being one. So the counter counts refusals rather than
  guesses, and the third is an ask whatever the page said. Per conversation, because the
  loop that waits is per conversation and the escalation hands *that* conversation to a
  person; a run where two conversations were each refused twice is not a run being
  stonewalled. Spent by the ask, so a conversation somebody unblocked gets the same
  patience again rather than an ask on its very next refusal.
- **The escalations are `confirmation_required`, not a seventh reason.** §12 fixes six
  `needs_human` reasons and a wait too long to make is not a new kind of blocked page. It
  is also the one reason whose printed phrase carries a detail, which is what lets the
  ask say *which* wait is being asked about — `confirmation required: rate limit until
  15:00 UTC`. Resuming grants nothing: the operator decides whether to sit the wait out,
  and the conversation is attempted again from its last successful step either way.
- **The wait is sliced at sixty seconds, and the early exit is honest about what it can
  see.** An hour that cannot be cut short is an hour spent on a limit that may have
  lifted in ten minutes, so `_wait_out` sleeps in slices and reads the page between them.
  What it reads is `probe.rate_limited`, which has three answers rather than two: the
  skill's own signal — a send control disabled beside a composer that is not empty — is
  "still limited"; an enabled send control is "not limited"; and an empty composer with
  nothing to send is `None`, because that is exactly what an idle new chat looks like and
  reading it as a lifted limit would end a wait the account asked for on no evidence. A
  `None` waits the whole time, which is the safe direction and the common one.
- **Only the `auth_required` ask has a deadline.** It is the one reason whose resolution
  this process can check — five of the six are cleared by a person's word, and a probe
  cannot tell a solved CAPTCHA from a page that was never blocked. The deadline is read
  where the human's answer comes back, not while the prompt is blocked on the terminal:
  `Console.ask` is a blocking `readline` and nothing here can interrupt one. So it bounds
  a stalemate — Enter, still signed out, Enter again — rather than a person who walked
  away, which is `Console`'s case and already ends in exit `5`. The pause record stays
  either way, so exit `3` is still a run `resume` continues.
- **`--all` rather than a bigger `--limit`.** `run.max_conversations` is both a default
  and a ceiling: §17's whole posture is that this tool modifies a real account
  sequentially and slowly, and a mistyped `--limit 120` is not recoverable the way a
  mistyped `--limit 12` is. The flag makes exceeding it deliberate. `--all --limit 11` is
  allowed, because an operator who typed both knows the ceiling exists.
- **`--delay`, `--max-retries` and `--timeout` are `None`-defaulted, like `--limit`.** A
  literal default in the signature would outrank an operator's `config.toml`, which is
  the precedence ladder backwards. `with_pacing` copies the nested models rather than
  reloading with an init override, for the reason `with_attachments_dir` does: handing
  `Settings` a `pacing={...}` would replace the whole table and drop the keys the flag
  says nothing about.
- **`--max-retries` is retries and `max_attempts` is attempts.** They differ by one on
  purpose: §13 words it as "maximum retries" and an operator thinks in "how many more
  goes", while `13`'s budget counts the goes themselves. `--max-retries 0` is one
  attempt.
- **`delay_between_parts_s` travels in the prompt.** The per-part loop happens inside one
  Hermes run, so the only process that can put a gap between one part's acknowledgement
  and the next part's paste is the agent making them. The prompt gains a
  `delay between parts:` field (`11`) and the skill gains the sentence that spends it.
  The skill's `version` stays `0.1.0`: the renderer and the installed skill ship in one
  package and `setup` overwrites, so there is no window in which a new field could meet
  an old skill.
- **`doctor`'s pacing line is not a `Check` that `checks()` yields.** It cannot fail, and
  `checks()` is a generator whose contract is "stop at the first failure". `pacing_check`
  renders it and the command prints it first, which is also what makes it visible when
  the chain below is broken.

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
- An `auth_required` pause that is still not signed in after `login_s` ends the run with
  exit `3`, leaving `paused` in `run.json`.
- A fake Hermes that answers `rate_limited` forever does not run forever: the third
  refusal of a conversation is an ask, and the run ends when the asks run out.

## Risks

- The rate-limit text may not include a time. The unknown branch exists for that, and
  `20` records how often it was hit.
- The early exit from a wait rests on a signal nobody has watched
  (`docs/claude-ui-map.md`, the `rate limited` row). It is the safe direction — a wrong
  `None` costs a wait that was going to be made anyway — but a wrong `False` would submit
  into a limit still in force. `20` is where the row stops being a guess.
