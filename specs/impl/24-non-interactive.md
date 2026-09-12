# 24 — Non-interactive mode

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §8 (as amended by this slice), §12
**Depends on:** [23](23-library-operations.md), [07](07-browser-session.md),
[09](09-hermes-runner.md), [11](11-skill.md), [12](12-import-loop.md),
[14](14-human-intervention.md)
**Enables:** unattended runs — a cron job, a CI step, a machine with no display
**Status:** Done

## Goal

A run that never waits for a person. Under `--non-interactive` Chrome has no window, a
signed-out session is signed in from credentials the operator handed the CLI, and a page
only a person can clear is recorded as §12's pause and exited on rather than waited for.
The sign-in uses the agentic browser for what an agent is good at — getting past a banner
to the form — and this process for what must be exact and must stay secret: typing the
credentials. The agent never holds them.

It is not a way to sign in to an account that has no password: an emailed code, a passkey,
a CAPTCHA or a challenge is reported and paused on, never guessed at.

## In scope

- **The brief's §8 amended**, explicitly, with the original sentence quoted and the five
  slices it touched named; §12 gains the sentence about running off a terminal.
- **Configuration** (`config.py`): `non_interactive: bool` (`--non-interactive`,
  `DATAPORTER_NON_INTERACTIVE=1`); `[auth]` with `email` and `password: SecretStr`
  (`DATAPORTER_AUTH__EMAIL`, `DATAPORTER_AUTH__PASSWORD`; `--email`, `--password-file` on the root
  callback — a file's first line, never a value on argv); `browser.headless: bool | None`
  (`None` follows the mode; `Settings.headless` is the one answer); `timeouts.signin_s`
  (`120`). `config.toml` may carry neither `auth` nor `non_interactive`: `_TomlWithoutSecrets`
  refuses the file with `auth and non_interactive belong in the environment or on the
  command line, not in config.toml`, exit `2`. `Settings.credentials` is both halves or
  `None`. `log.FORBIDDEN_FIELDS` gains `email`, `secret`, `credentials`.
- **The agent's half** (`signin.py`): one `hermes -z` task in `20`'s shape (injectable
  `HermesRunner`, `run_raw`, `last_result_object`, own result model). The prompt names
  the login URL and the helper prefix and carries no credential; the procedure is to
  navigate to `https://claude.ai/login`, clear a banner once, take the email path and never
  Google, Apple, SSO or a passkey, and stop when an email or password input is visible.
  `FormResult`: `outcome` `form_ready` | `needs_human` | `failed`, `fields`, `url`,
  `needs_human_reason`, `error`. A code prompt with no password field is `needs_human` /
  `auth_required`. `SKILL.md` gains one scoped paragraph beside `20`'s; rule 5 and the
  login-expiry row stay verbatim.
- **This process's half** (`browser/login_form.py`): `fill_and_submit(session,
  credentials, *, timeout_s)` — up to three rounds of: read which field is showing
  (`LOGIN_FIELDS_JS`, tag `dataporter:login_fields`), focus it and select what it holds
  (`focus_field_js`, tag `dataporter:focus_field`, the selector a `const` on its own line), insert
  the value through `Input.insertText`, `Page.press_enter()` (the one CDP primitive added:
  `Input.dispatchKeyEvent` keyDown/keyUp), and wait for the page to become signed in or a
  different form. The email goes in once. `FillResult(signed_in, filled, rounds, blocked)`
  with `blocked` one of `no_tab`, `no_form`, `field_not_focused`, `no_progress`,
  `code_or_challenge`. `LOGIN_SURFACE` is `MIGRATION_SURFACE` plus `/login(/.*)?`, passed
  to `helpers.driving` by this module only; every helper the agent can run still refuses
  `/login`.
- **Orchestration** (`signin.SignIn.perform`): agent, then fill, then `signed_in` re-probed
  in process — the agent's word never decides. `SignInOutcome(signed_in, reason, detail,
  filled)`, `reason` in `intervention.REASON_PHRASES`' words or `hermes failed`.
  `ensure_signed_in(settings, session)` is the guard every run makes: interactively `12`'s
  `AuthError(SIGNED_OUT)`; unattended one `perform`, then `AuthError("automatic sign-in
  stopped: <reason> — run: dataporter login")`. `require_credentials` raises
  `UsageError` with `--non-interactive needs credentials: set DATAPORTER_AUTH__EMAIL and
  DATAPORTER_AUTH__PASSWORD, or pass --email and --password-file`, before any browser, from
  `login`, `import` (not `--dry-run`), `resume`, `verify` and `followup`.
- **The importer**: `_require_signed_in` → `ensure_signed_in` (preflight and the mid-run
  relaunch), counting a sign-in it made as `auto_signins`; in `_migrate`, an
  `auth_required` ask in the mode is put to `_sign_in()` first and only a failure goes on
  to `_intervene`; in `_cleared` (the `resume` path) the same, before the re-probe. The
  two intervention counters move from `_pause` to `_intervene`. `run.json` gains
  `auto_signins`; the report gains `Automatic sign-ins:` after `Human interventions:`,
  printed only when non-zero.
- **`intervention.Unattended`**: `ask` prints the block and returns `False` without
  touching stdin; `retry` likewise; `note` to stderr. `block(request, unattended=True)`
  swaps two lines: `Browser:      no window — non-interactive run; clear it, then run:
  dataporter resume` and `Paused for a person (non-interactive); run:
  dataporter resume`. `Importer` picks it when the mode is on and nothing was
  passed.
- **`login`** in the mode: `ensure_signed_in` instead of the prompt and the wait, the
  same `Logged in. …` line, Chrome closed so the cookie jar flushes. **`launcher.launch`**
  appends `--headless=new` when `Settings.headless`; `--no-sandbox` is never implicit.
  **`doctor`**'s Chrome line says `, headless` when it is.
- **Tests**: `test_config.py` (dumps show `**********`, the TOML refusal, flag/env
  halves); `test_login_form.py` (`LoginForm` fake with stages, every `blocked`, the
  values in no expression, and a real headless Chromium filling
  `fixtures/pages/login-form.html` — a two-step form — and landing on `/new`);
  `test_signin.py` (the two halves, every reason, the secret in the prompt / env / argv
  of no Hermes call and in `Input.insertText` params only, `ScriptedSignIn` performing
  the skill's paragraph); `test_unattended.py` (the block, `Unattended` never reading
  stdin, the mid-run expiry cleared and counted, the pause at exit `5`, `resume` signing
  in itself, the preflight sign-in, exit `2` without credentials, the CLI variants of
  `login`, and a walk of every workspace file, transcript and printed byte after a run
  that signed in twice); `test_hermes_client.py` (`DATAPORTER_AUTH__*` in the parent, absent
  from the child); the tripwire rescoped to the four-module seam.

## Out of scope

- Reading a mailbox for an emailed code, solving a CAPTCHA, or any sign-in that is not
  email and password. `docs/LIMITATIONS.md` records it *by construction*.
- A session cookie as a credential. Rejected for this slice: it is a second mechanism
  behind the same model, and the brief's §2 asks for the normal user interface.
- Observing the real sign-in form. The selectors are guesses like every row of
  `docs/claude-ui-map.md`, and the new `sign-in form` row is *unknown* until somebody
  looks.

## Design notes

- **The agent reaches the form; this process types into it.** The first design put the
  typing in a `browser sign-in` helper the agent would invoke, with the secret passed
  through the Hermes environment. Rejected: anything a helper spawned from Hermes's
  terminal tool can read — an env var, an inherited descriptor — the model can read too,
  by `printenv` or `/proc/self/fd`. "Never through the model" is only true by
  construction if the secret never enters the agent's process tree, so `hermes_env`
  stays as `09` built it and no helper subcommand exists.
- **`--password-file`, not `--password`.** A value on the command line is in `ps` and in
  the shell's history, which is where an unattended run's host keeps them. The
  environment and a file are the two channels.
- **A login expiry is `13`-shaped, not `14`-shaped.** A sign-in the tool makes itself is a
  recovery: nobody was asked, the conversation is tried again from its last step, and
  §19's primary metric — conversations migrated without a person — stays honest. That is
  why the counter is separate and why the intervention counters moved to where the ask
  is actually put.
- **Exit `3` at the start, `5` mid-run.** Nothing has been asked of anyone at the
  preflight, so a sign-in that fails there is `12`'s exit `3` with `login` as the remedy.
  Mid-run a chat may exist and a step be half done, so the failure is §12's pause with
  the `auth_required` record on disk, and `resume --non-interactive` tries the sign-in
  itself before looking at the page.
- **Headless follows the mode.** A window is what §12 hands a person; without a person it
  is a display requirement and nothing else. `browser.headless` exists for the operator
  who wants to watch an unattended run, or run headless attended.
- **The tripwire was rescoped, not removed.** Outside the four seam modules the old rule
  holds; inside them, no string constant may carry a value and no log call may pass a
  forbidden field. That is the checkable form of the amended §8.

## Acceptance criteria

- `DATAPORTER_NON_INTERACTIVE=1 DATAPORTER_AUTH__EMAIL=… DATAPORTER_AUTH__PASSWORD=… dataporter
  import <export> --limit 1` in the fake world, with the page a sign-in form and the fake
  Hermes answering `form_ready`, exits `0` with `auto_signins == 1` and
  `human_interventions == 0`; with the agent answering `needs_human` it exits `5` with an
  `auth_required` pause, and `resume` in the same mode signs in and finishes; without
  credentials it exits `2` before `launcher.launch` is called.
- `login --non-interactive` prints `Logged in. …` and closes Chrome; when the sign-in
  stops it exits `3` with `error: automatic sign-in stopped: <reason> — run:
  dataporter login`.
- After any of those runs, no file under the workspace, no Hermes transcript, no log
  record and nothing printed contains the email or the password; every Hermes call's
  argv and environment are free of both; the secret appears in the CDP trace only as
  `Input.insertText` parameters.
- `[auth]` or `non_interactive` in `config.toml` is exit `2` with the message.
- `test_the_secret_stays_in_the_credentials_seam` passes; the migration surface still
  refuses `/login`; rule 5 of the skill is byte-identical.
- The real-Chromium test fills `login-form.html` through both steps and lands on `/new`.
- `report.block` is byte-identical at `auto_signins == 0`.

## What `29` changed

The first rehearsal (`docs/rehearsal-01.md`) ran this code against a sign-in form
that submits by navigating, and found one defect: `_await_change` read the fields
of a page that was mid-navigation — blank, for a few milliseconds — and reported
`code_or_challenge`, which is the one answer that stops an unattended run for a
person. A page that has not settled is now "not yet" rather than an answer
(`SETTLED_JS`), and the `LoginForm` fake grew a `loading_for` to model it.

## Risks

- `10`'s Q1 — whether `hermes -z` attaches to our Chrome at all — is still *unknown*. The
  agent's half inherits it; the deterministic half does not, and is what a spike can
  exercise first (`login_form.fill_and_submit` against a hand-navigated tab).
- The real claude.ai sign-in form is unobserved, and an account without a password login
  is the common case. The `auth_required` pause is the designed answer, not a failure
  mode; if the form's selectors differ, `LOGIN_FIELDS_JS` is the one-line edit and the
  `sign-in form` row of the UI map is where the observation goes.
- Headless Chrome may be what trips a bot check that headed Chrome would not.
  `browser.headless = false` runs the mode with a window for exactly that experiment.
