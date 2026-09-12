# 31 — The source session and the ask

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 03](../03-extraction-and-backup.md) §31 (the ask), §35, §36, §38,
§39
**Depends on:** [30](30-store-and-snapshot.md), [07](07-browser-session.md),
[24](24-non-interactive.md)
**Enables:** extraction end to end — an ask, an email, a fetch, a snapshot
**Status:** Not started

## Goal

A second signed-in browser session, for a source account, kept apart from the
destination's; and the one action the tool takes in it: going to where claude.ai lets a
user ask for their data, pressing the button, and recording that it did. Both modes, no
model. The fetch that follows is `30`'s.

## In scope

- **An account on the session commands** (`cli.py`, `browser/session.py`): `login`,
  `session status` and `session logout` gain `--source SRC` (default `claude`) and
  `--account LABEL`, applied through `config.with_account`. Absent, they mean the
  destination and their output is byte-identical to today. Brief §35 writes `--account`
  alone; a label is scoped by its source here because a source "knows how to sign in"
  (§34) and the day ChatGPT lands, `login` needs to know which sign-in page to open.
  `session_app`'s help becomes `Inspect or end a browser session.`; `AuthSettings`'
  docstring says the credentials belong to the account the invocation signs in to.
- **Where the source profile lives** (`config.py`): `Settings.browser_profile_dir` is
  `account_home / "browser-profile"` when an account is set, else
  `workspace / "browser-profile"` as today. No signature in `launcher` or `session`
  changes; `launcher.launch(settings, url)` stays the seam the tests substitute.
  `ensure_profile` calls `ensure_gitignore(settings.workspace)` only when the profile is
  under the workspace. `login`, `status` and `logout` call
  `log.enable_run_log(settings.logs_dir)`. One `browser.cdp_port`: a destination Chrome
  still on it is `PortInUse`, exit `2`, with the existing message. Sessions are
  sequential, and the README says so.
- **The extraction surface** (`browser/export_page.py`, new): `EXPORT_PAGE_URL` and
  `EXTRACTION_SURFACE = Surface(host=CLAUDE_HOST, allowed=…)`, permitting
  `/login(/.*)?` and the export page's path and nothing else — not `/new`, not
  `/chat/…`. The path is *unknown* until observed; the placeholder is
  `/settings/data-privacy-controls`, spelled once, here. The signed-in probe for the ask
  uses the export page as its URL through `session.current_state(session, url)` and
  `wait_for_login(session, url=…)`, so `/new` never enters this surface. The surface is
  passed to `helpers.driving` by this module and nothing else. The page's selectors live
  in this module's own `_SELECTORS`, injected as `probe.py` injects its own, never
  appended to `probe`'s prelude: every migration expression would otherwise carry them.
- **The page mechanics** (`export_page.py`): `EXPORT_PAGE_JS`, tagged
  `dataporter:export_page`, reports `{button: bool, dialog: bool, confirm: bool,
  requested: bool}` — the export button is visible; a `[role=dialog]` is open; its
  confirm button is visible; the page shows the request was accepted. `click_js(selector)`,
  beside `login_form.focus_field_js`, is `Runtime.evaluate` of `element.click()` on the
  first visible match, tagged `dataporter:click`. A JavaScript dialog
  (`probe.pending_dialogs`) is never answered: the ask stops with `blocked: js_dialog`.
- **The ask** (`extract.ask(settings, *, sink)`, filling `30`'s not-implemented mode):
  1. `ask.json` exists → `StoreError` `an ask is already open for claude/<label>, made
     <asked_at>; fetch it with --link, or drop it with --abandon`, exit `2`, before any
     browser starts.
  2. Non-interactive → `signin.require_credentials(settings)` first, as `login` does.
  3. `launcher.launch(settings, EXPORT_PAGE_URL)`; `browser.close()` in a `finally`.
  4. Signed out: interactively, `LOGIN_PROMPT` and `wait_for_login` against the export
     page for `timeouts.login_s`; unattended, `signin.ensure_signed_in`, which is `24`'s
     agent half — an unattended ask on a signed-out profile needs Hermes, a signed-in one
     does not, and the README says which.
  5. Press the export button; if a dialog opens, press its confirm button; poll
     `EXPORT_PAGE_JS` for `requested` up to `timeouts.ask_s` (new, `60.0`, `gt=0`).
     Neither button visible, or no `requested` in time → exit `1` with `export button not
     found on <path>` or `no confirmation that the export was requested`, and no
     `ask.json`.
  6. Write `ask.json` with `O_EXCL`, `asked_at` the moment the button was pressed, to the
     second. Print the block, brief §31:

     ```text
     Claude extraction — old-personal

     Export requested 2026-09-12 20:51 UTC.
     Claude will email a download link to the account's address.
     When it arrives:

       dataporter extract --source claude --account old-personal --link <url>

     ```

  Every action goes to the account home's `logs/actions.jsonl` through
  `helpers.record_action`, with the page's URL and the click's selector and never its
  text.
- **Safety** (§36): the source session never imports — `import_command` and
  `resume_command` never call `with_account`, and a test proves it from `cli.py`'s AST;
  the ask navigates inside `EXTRACTION_SURFACE` only, guarded before attach and on the
  live URL as `driving` guards; the only synthesized inputs are the two clicks, and
  `Input.insertText` is never sent from this path.
- **The UI map** (`docs/claude-ui-map.md`): four rows, all `*unknown*`, "not yet looked
  at": `export page` (the path), `export button`, `export confirmation`, `export
  requested`. `docs/spike/README.md` gains the steps that observe them.
- **The record**: `docs/extraction-01.md`, in the experiment documents' discipline, holds
  brief §39's answers to questions 1, 2 and 5 with numbers, once a real account has been
  asked. Until then the slice is `Built`, not `Done`.
- **Tests**:
  - `tests/fake_export_page.py` — a `FakePage` with stages `settings → confirm →
    requested`, answering `EXPORT_PAGE_JS` by its tag, reading the selector back from a
    `click_js` expression with `js_const`, recording every click; a variant that opens a
    JavaScript dialog; a variant with no button.
  - `tests/test_source_session.py` (`slow`) — `login --account a` creates
    `<accounts>/claude/a/browser-profile/` and never touches `<workspace>/browser-profile/`;
    `session status --account a` and `session logout --account a` act on it; without an
    account every session command's output is byte-identical to today; a destination
    Chrome on the port makes `login --account a` exit `2`.
  - `tests/test_ask.py` (`slow`, the fake Chrome substituted for `launcher.launch` as
    `test_browser_session.py` does) — the happy path writes `ask.json` and prints the
    block byte for byte, and the fake recorded exactly two clicks and no
    `Input.insertText`; an open ask is refused before launch; signed out and unattended
    with no credentials exits `3` with `MISSING_CREDENTIALS`; the JavaScript dialog exits
    `1` and writes no `ask.json`; no button exits `1`; `requested` never arriving exits
    `1`. Every branch is covered by the fake, so the coverage gate never rests on a
    browser.
  - `tests/test_browser_helpers.py` — `driving` with `EXTRACTION_SURFACE` refuses
    `https://claude.ai/new` and a `/chat/<uuid>`; `MIGRATION_SURFACE` refuses the export
    page.
  - Live tier: `tests/fixtures/pages/settings-export.html` served at the export page's
    path, under `requires_a_browser`, for the click and the `requested` signal in a real
    Chrome.
  - `tests/test_operations.py` — parity for `extract` (the ask) and the session commands
    with an account; `tests/test_cli.py` — the new options on the command surface.

## Out of scope

- The fetch, the store, the manifest, `snapshots`, and import from a snapshot:
  [30](30-store-and-snapshot.md).
- A second `cdp_port` for concurrent sessions, reading the account through its pages, the
  inbox, and a mock export page for a rehearsal: brief §40.
- Answering a JavaScript dialog. Its kind is unknown; unbuilt code is not uncovered code.

## Design notes

- **The tool presses the button; no Hermes.** A backup that needs an API key is a backup
  people stop running, and a cron job has no model. The cost is that the export page's
  selectors are ours to keep right, which is the UI map's existing discipline for every
  other page. Rejected: a Hermes skill for the ask, which survives a page change but
  makes every backup a model call; the person clicking in the window, which would make an
  unattended ask impossible.
- **`with_account` rather than a `profile` parameter.** `launcher.launch(settings, url)`
  is substituted in some forty test sites and by `world.py`; `browser_profile_dir` is read
  by `status`, `logout`, `doctor`, `verify` and `followup`; and "the source session never
  imports" becomes a property of who calls `with_account`, checkable by reading `cli.py`.
- **`--source` on the session commands.** Brief §35 left it out; a label that means one
  account on Claude and another on ChatGPT is a trap, and the sign-in page is the
  source's.
- **One port, sequential sessions.** `launcher.adopt` keys "is this browser ours" on the
  port and the browser id; a second port would be a second identity for nothing this
  brief needs. The refusal is the existing `PortInUse` message.
- **`/new` stays out of the extraction surface.** `signed_in` probes whatever URL it is
  given; giving it the export page keeps the wall at two doors — the sign-in page and
  the export page — which is what §36 says.
- **Minute precision on the line, seconds in the file.** `Export requested 2026-09-12
  20:51 UTC.` is for the eye; `ask.json` keeps seconds because the stamp does and the
  fetch needs them.

## Acceptance criteria

- `login --account a` then `session status --account a` in the fake world exits `0` with
  `logged in`, and the destination's `session status` still exits `3` with the
  instruction line.
- `extract --source claude --account a` against the fake export page exits `0`, writes
  `ask.json` with `asked_at` to the second, prints the block byte for byte, and the fake
  recorded exactly two clicks and no `Input.insertText`.
- The same command again exits `2` with the open-ask line and starts no browser;
  `--abandon` then a new ask exits `0`.
- `DATAPORTER_NON_INTERACTIVE=1` with no credentials on a signed-out profile exits `3`
  with `MISSING_CREDENTIALS`; on a signed-in profile it exits `0` and no sign-in was
  attempted.
- `driving` under `EXTRACTION_SURFACE` refuses `https://claude.ai/new` and
  `/chat/<uuid>` with `outside_migration_surface`; under `MIGRATION_SURFACE` it refuses
  the export page.
- After any run, no run-log record, no `actions.jsonl` record and no stdout or stderr line
  carries an email, a title or any content.
- *(Manual: it needs a real account.)* Brief §39's questions 1, 2 and 5 answered with
  numbers in `docs/extraction-01.md`, and the four UI map rows turned
  `*observed on <date>*`.

## Risks

- **Every row is unknown.** The export page's path, its button, whether a confirmation
  follows and what "requested" looks like are all unobserved. The slice ships against the
  placeholder and the fake; the first real ask is what corrects the four rows, and the
  code is written so that a correction is a one-line edit in `export_page.py`.
- **A rate limit on asking.** Claude may refuse a second export request within some
  window. The `requested` signal would not arrive, the ask exits `1`, and the person reads
  the page. Named in `LIMITATIONS.md` until observed.
- **The sign-in agent under cron.** An unattended ask on a profile whose session has
  expired needs Hermes for `24`'s sign-in half. A cron job without Hermes gets exit `3`
  and the `login` instruction, which is the right failure but a silent one until someone
  reads the log.
