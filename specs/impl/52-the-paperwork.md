# 52 — The paperwork

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 07](../07-claude-sign-in.md) §75, §76, §78; the `docs/LIMITATIONS.md`
rewrite §72 promised
**Depends on:** [49](49-the-mock-signs-in-by-link.md), [50](50-the-login-that-waits.md),
[53](53-login-link.md)
**Enables:** nothing yet
**Status:** Built

## Goal

Make the tool say, everywhere it speaks, what brief 07 made true: Claude has no unattended
sign-in, a credential is never a key to a Claude account, and a signed-out Claude session
stops a run with `login` — spelled with the account's flags — as the remedy. Then rewrite
the limitations and the operator's documents so that none of them still promises a
password.

## In scope

- **`Source.unattended_signin` gains `none`**, and Claude is `none`. `signin.mode_of`,
  `signin.can_sign_in` and `signin.gate` read it: `gate` is the door `import`, `resume`,
  `verify` and `followup` ask at instead of `require_credentials`, and it asks nothing of
  a source with no sign-in of its own. `SignIn.perform` on such a source performs nothing
  and answers `auth_required`; `ensure_signed_in` on such a source, unattended, raises
  `AuthError` with `signed_out_line` — the same rule as the interactive one, because the
  remedy is the same person. `Importer._machine_can_clear` is false for it, so a login
  expiry mid-run is §12's pause (exit `5`) and never a Hermes task.
- **The remedy carries the account.** `session.signed_out_line(settings)` is `not logged
  in — run: dataporter login`, plus ` --source <source> --account <label>` for a source
  account; `status`, `ensure_signed_in` and the extract's signed-out stop print it.
  `SIGNED_OUT` stays as the destination's form, byte for byte.
- **The extract stops on a signed-out by-link profile** in either mode
  (`_sign_in_to_source`): `AuthError`, exit `3`, the line above. `61`'s "better refusal for
  a signed-out Claude profile" is this. The interactive wait with the old prompt is gone for
  Claude — it could only have been finished by clicking a link in a mail client, which
  shows a code and signs nothing in.
- **`24`'s agent half stays in the tree** (§76, Q21-A): `signin.SignIn`, its prompt, the
  scripted sign-in in the rehearsal's `hermes`, `login_form.fill_and_submit`. No source
  reaches it; `tests/conftest.py`'s `agent_signin` fixture hands it Claude for the length of
  a test, and every test of that half is marked with it.
- **`docs/LIMITATIONS.md`**: *password sign-in only* replaced by *no unattended Claude
  sign-in* and *the ChatGPT walk is password sign-in only*; a section *The sign-in by link*
  with the rows `50` and `53` earn — the pending sign-in's survival (*unknown*), the code
  page (*unknown*), two terminals and one browser, the unpinned host, the display, the mail
  host's hop; and the ask's *needs Hermes* row rewritten.
- **The operator's documents**: `README.md` (the run, the backup, *Running unattended*),
  `docs/runbook.md` (*Running unattended* and its exit codes), `docs/extraction-01.md`,
  `docs/spike/README.md`.
- **Tests**: `tests/test_unattended.py` — the mode needs no credentials for a Claude run; a
  signed-out session at the start names `login` and runs no Hermes task; a login expiry
  mid-run pauses for a person; the three doors ask no credentials. `tests/test_ask.py` — the
  interactive and unattended asks on a signed-out profile stop with the account's flags and
  drive nothing. `tests/test_source_session.py` — `session status --account` names its own
  `login`. `tests/test_signin.py` and the agent-path tests in `test_unattended.py` run under
  `agent_signin`.

## Out of scope

- **The code as a second door** (§80).
- **`session status` saying "a link is on its way"** (§80).
- **Deleting the agent half.** §76 keeps it; the cost is a fixture and a paragraph.

## Design notes

- **A third mode rather than a boolean.** `sign_in_by_link` says how a person signs in;
  `unattended_signin` says what the tool does without one. They are different questions
  with, today, one answer each, and a source could sign in by link *and* have an unattended
  walk on some other vendor — so the second field is not derived from the first.
- **The door opens rather than refusing.** `24` refused the mode without credentials
  before a browser started, because a run that would stop at the first form should not
  have started. For Claude the form never comes: the run either finds its profile signed in
  and needs nothing, or finds it signed out and no credential would have helped. Asking at
  the door would refuse every unattended Claude backup and migration for a key that opens
  nothing (`61` said so for `extract`; this says it for the rest).
- **The flags in the remedy.** `not logged in — run: dataporter login` was true when the
  only session was the destination's. With source accounts it names the wrong profile
  unless it names the account, and a cron job's log is read by somebody who was not there.

## Acceptance criteria

- `import --non-interactive` with no credentials on a signed-in destination runs
  (`test_the_mode_needs_no_credentials_for_a_claude_run`); on a signed-out one it is exit
  `3` with `not logged in — run: dataporter login` and no Hermes task
  (`test_a_signed_out_claude_session_at_the_start_names_login`).
- A login expiry mid-run in the mode is a pause, `auth_required`, no automatic sign-in
  (`test_a_login_expiry_mid_run_on_a_claude_account_pauses_for_a_person`).
- `extract` on a signed-out source profile, either mode, stops with the account's flags
  and clicks nothing (`test_an_interactive_ask_on_a_signed_out_profile_names_login`,
  `test_the_mode_on_a_signed_out_profile_names_login_with_the_account_s_flags`).
- `session status --account <label>` signed out prints the flags
  (`test_a_signed_out_source_account_names_its_own_login`).
- `docs/LIMITATIONS.md` no longer contains *password sign-in only* as Claude's rule.

## Risks

- **The dormant half rots.** It is covered only under a fixture that flips a frozen object;
  a future source that uses it will find tests but no production caller to learn from. §76
  chose that over deletion; git remembers either way.
- **A source added with `unattended_signin="agent"`** would reach `24`'s Hermes prompt,
  which names `claude.ai`'s login URL and skill. That prompt was Claude's; a second agent
  source would need its own.
