# 69 — The preflight: no session, no browser

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §8, [brief 03](../03-extraction-and-backup.md) §35,
[brief 08](../08-signing-out.md) §86
**Depends on:** [07](07-browser-session.md), [31](31-source-session-and-ask.md),
[63](63-everything-but-the-logs.md), [66](66-extract-skills.md)
**Enables:** [70](70-the-sign-in-screen.md)
**Status:** Done

## Goal

Seven commands need a session that already exists. When an account was never signed in
there is nothing on disk to be signed in *with*, and that is answerable from the
filesystem — so they answer it there, instead of launching Chrome, waiting out `SETTLE_S`
for a tab that will never hold an app, and asking the vendor a question the vendor cannot
help with.

`session status` has done exactly this since `07`: *"No profile and no browser: there is
nothing that could be signed in, and starting Chrome to be told so would cost ten seconds
and a window."* This slice gives that check a name and hands it to the other seven.

Nothing an operator reads changes. It is the same `SIGNED_OUT_LINE` and the same exit
`3`, arrived at sooner and without a window opening and closing on the way.

## In scope

- **`browser/session.py`** — two functions, beside `signed_out_line`:

  ```python
  def never_signed_in(settings: Settings) -> bool: ...
  def require_session(settings: Settings) -> None: ...
  ```

  `never_signed_in` is `not settings.browser_profile_dir.exists()` and nothing else.
  `require_session` raises `AuthError(detail=signed_out_line(settings))` when it is true,
  which `cli.py:217` already turns into `error: <detail>` on stderr and exit `3` — **unless
  something could still make the session**, which is `settings.non_interactive and
  signin.can_sign_in(settings)`. See the Design notes.

- **`status`** — its inline disk test becomes the same call:

  ```python
  if running is None and never_signed_in(settings):
  ```

  It keeps its own shape — a returned `StatusOutcome`, a bare line on stdout, exit `3` —
  because `status` was *asked* whether the session is signed in and answering "no" is a
  success. The other six were asked to do something and could not.

- **Seven call sites.** Each calls `require_session(settings)` as early as it can without
  changing what the command would otherwise report:

  | Command | Where |
  | --- | --- |
  | `extract` (ask) | `extract.ask`, first statement, before `enable_run_log` |
  | `extract --link` (fetch) | `extract.fetch`, before `enable_run_log`, **only** when `source.link_serves_manifest or source.fetch_needs_session` |
  | `extract-skills` | `extract_skills.extract_skills_command`, after the `has_skills` refusal, before `enable_run_log` |
  | `import` | `importer.import_command`, inside `if not request.dry_run:`, beside `signin.gate` |
  | `resume` | `importer.resume_command`, beside `signin.gate` |
  | `verify` | `verify.verify_all`, after the `NOTHING_TO_DO` return, before `lock.acquire()` |
  | `followup` | `followup`, after the `NOTHING_TO_DO` return, before `lock.acquire()` |

- **The README** — the paragraph that already says a lapsed Claude session stops a run with
  exit `3` gains the other half: an account that was never signed in stops with the same
  line and the same code *before a browser opens*.

## Out of scope

- **A session that exists and has lapsed.** The directory is there, the cookie is not, and
  only the vendor can say so. That is [70](70-the-sign-in-screen.md), which is also what
  covers every account home that has ever had a browser (see Risks).
- **`extract` no longer offering a sign-in at all.** Deferred with the ChatGPT work: for
  Claude `sign_in_to_source` already refuses, and the window it can still open is
  ChatGPT's alone.
- **`doctor`.** It answers a signed-out session with a failed *environment* check and exit
  `6`; that is its own bug and its own slice.
- **`login`, `login --link`, `logout`.** `login` is the command that creates the profile
  and `logout` is the command that removes it; a preflight on either is a command that
  refuses to do its own job.

## Design notes

**The test is the directory, and nothing cleverer.** A cookie store could be read and a
"signed in at" record could be written, and both were rejected. Reading Chrome's cookie
database breaks the promise ADR 0008 makes — the tool never learns what the cookie is —
and a record of our own is a second source of truth that goes stale the first time a
session lapses. The directory is the one fact that is honest without a browser: it is
`logout`'s unit (§83), it is what `status` already tests, and it needs nothing kept.

**It answers less than it looks like it answers.** `launcher.ensure_profile` does
`mkdir(parents=True, exist_ok=True)` on every launch, so any command that ever opened a
browser — a `login` that timed out, a `doctor` — leaves the directory behind for good, and
only `logout` removes it. So this check fires for an account home that has never had a
browser and never again after that. That is not a flaw to be engineered around; it is the
line between this slice and `70`, and the Risks section states it rather than the code
implying otherwise.

**Placement follows the log, not a rule about being first.** `logout` resolves the account
home before `enable_run_log` so that *"a refusal never leaves a log behind in a workspace
it was not about"* (`session.py`). The extract family writes its run log under the account
home, so its preflight goes before that call, for that reason. `import`, `resume`,
`verify` and `followup` write under `settings.workspace`, which is the thing they are
about either way, so theirs goes beside `signin.gate` or just before the browser —
and, for `verify` and `followup`, *after* the `NOTHING_TO_DO` return, because telling
somebody to sign in for work that does not exist is a worse answer than exit `4`.

**A session something else could make is not required.** Found while building, and it is
the one condition in the check beside the directory: under `--non-interactive`, a source
with an unattended sign-in walks its own form and ends with a profile it started without.
Refusing it for not having one already would break the only way a ChatGPT backup
bootstraps itself — and would report exit `3` where `signin.gate` reports the exit `2` and
the credentials the run actually needs. The division is `gate`'s own: *"for a source with
no unattended sign-in there is nothing to ask for, and the door is open. A signed-out
session is then `ensure_signed_in`'s to refuse."* This check is the other half of that
sentence, and it stands aside wherever `gate` speaks.

It is one condition inside `require_session` rather than seven at the call sites, so there
is one rule; `signin` is imported inside the function because `signin` imports this module,
which `observe` already does for `login_form`.

**The fetch is conditional and the others are not.** `fetch` has a browserless path — a
source whose link may be downloaded by `urllib` — and a preflight there would refuse a
fetch that needs no session at all. Both sources require one today, so the condition is
dead for the moment; it is written anyway because the alternative is a refusal that comes
true the day a source does not.

## Acceptance criteria

1. `never_signed_in` is the only place in `src/` that tests `browser_profile_dir.exists()`
   against a decision: `grep -rn "browser_profile_dir.exists" src/` returns exactly two
   lines, its own and `status`'s.
2. For each of the seven, called against a settings whose profile does not exist:
   `AuthError` is raised and no Chrome was launched — the `no_browser` fixture in
   `tests/test_preflight.py` makes `launcher.launch` an `AssertionError`. The detail is
   `not logged in — run: dataporter login --source claude --account work` for the four
   account-scoped commands and `not logged in — run: dataporter login` for the three
   workspace-scoped ones, byte for byte.
3. Through the CLI, covering both message shapes and the stream: `extract` and
   `extract-skills` put
   `error: not logged in — run: dataporter login --source claude --account work\n` on
   stderr with nothing on stdout, and `import` puts
   `error: not logged in — run: dataporter login\n` there; all exit `3`.
   `tests/test_cli.py`.
4. `extract.ask` and a session `extract.fetch` against a missing account home leave the
   account home itself absent — no `logs/`, no tree for a mistyped label.
5. `session status` is unchanged: stdout is
   `not logged in — run: dataporter login --source claude --account work\n`, no `error:`
   prefix, exit `3`, and
   `tests/test_source_session.py::test_a_signed_out_source_account_names_its_own_login`
   passes untouched.
6. `import --dry-run` against a missing profile does **not** refuse: a dry run opens no
   browser, so it has no session to require.
7. `resume` with nothing to resume, and `verify` and `followup` with nothing to do, exit
   `4` and not `3`.
8. Under `--non-interactive`, a source with an unattended sign-in is not refused for a
   missing profile: `tests/test_chatgpt_ask.py` and `tests/test_unattended.py` pass
   unchanged, credentials and all.
9. `logout` against a missing profile still reports `Nothing to remove: …` and exits `0`.
10. `make check-all` passes — 2173 tests, coverage 99.06% — except the one pre-existing
    macOS-only Hermes environment test, whose files this slice does not touch.

## Risks

- **It reads as a bigger promise than it is.** Somebody will take "the tool now refuses
  before opening a browser" to mean every signed-out run does, and it does not: one
  `login` that timed out is enough to leave the directory in place forever. The Goal and
  the Design notes both say so, and `70` is what makes the claim true.
- **A partially removed account home.** A `logout` that failed halfway leaves the
  directory without a usable session; the preflight passes and the probe answers. That is
  the right division and costs one browser launch.
- **A seventh call site drifts.** Nothing stops a future command from launching a browser
  without asking. The grep in criterion 1 catches a second inline copy of the test, not a
  missing call; `70` gives the same shape a second chance at the probe.
