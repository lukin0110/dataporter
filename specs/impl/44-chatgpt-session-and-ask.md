# 44 — The ChatGPT source session and the ask

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 06](../06-chatgpt-extraction.md) §60, §61, §62, §65, §67, §70
**Depends on:** [42](42-source-seam.md), [43](43-chatgpt-archive.md),
[24](24-non-interactive.md), [31](31-source-session-and-ask.md)
**Enables:** [45](45-fetch-through-the-session.md), [46](46-extraction-rehearsal.md)
**Status:** Done

## Goal

`login`, `session status` and `session logout` for `--source chatgpt`; the extraction
surface across two hosts; the export page driven straight to its path and asked on with
two clicks; and the unattended sign-in as a walk the tool makes itself, with no agent.
Every step a move, so a ChatGPT run leaves what a Claude run leaves (§67).

## In scope

- **The session commands** (`browser/session.py`, through `42`'s seam): `whose(settings)`
  answers the root of chatgpt.com, `Log in to ChatGPT in the browser window that just
  opened.` and both hosts for `--source chatgpt --account LABEL`; `login` opens the root,
  waits interactively as it does for Claude, and stores the profile under
  `<accounts>/chatgpt/<label>/browser-profile/`. No CLI change: `31`'s options carry it.
- **The walls** (`browser/sites.py`, from `43`'s source): the extraction surface is
  `^https://chatgpt\.com/(|auth/login|auth/callback|settings/data\-controls)(\?.*)?$|^https://auth\.openai\.com/.*$`;
  the sign-in's is the same without the export page. The root is admitted because a
  signed-out request and the sign-in's return both land there and `login` opens there;
  a chat is created by a submit, and nothing on this path makes one (§65).
- **The walk** (`browser/chatgpt_login.py`, new): `walk(settings, session, source,
  credentials) -> login_form.FillResult`. Read the landing (`landing_js`, tagged
  `dataporter:chatgpt_landing`: a visible **Log in**, or a composer); a composer is
  already signed in; no **Log in** stops with `no_login_button`; otherwise click it
  through `export_page.click_js` and record the move `login-button`; wait up to
  `timeouts.signin_s` for a tab on the surface with a field on it, else `no_email_step`;
  then `login_form.fill_and_submit` with the sign-in's surface and the settings, which
  types the email, presses Enter, types the password, presses Enter — and reports a code
  prompt or a refused password as it always has. `signin.SignIn.perform` dispatches on
  `source.unattended_signin`: `walk` here, `agent` to `24`'s Hermes half; the proof
  (`browser_session.signed_in` on the source's root and hosts) and the outcome are the
  same for both. `signin.BLOCKED_REASONS` maps the two new reasons to `auth_required`,
  exit `3`, `automatic sign-in stopped: authentication required — run: dataporter login`.
- **Every step a move** (`helpers.record_step`, new, beside `record_move`): the ask's
  two clicks, the walk's one, and the sign-in's two submits (`email-step`,
  `password-step`, recorded by `login_form.fill_and_submit` when given `settings`) each
  write one `actions.jsonl` line and one trace move — selector and URL, never a value;
  no sketch after a submit, since it navigates and the watch sketches where it lands.
  `24`'s Claude sign-in gains the same two moves.
- **The ask** (`extract.ask`, `43`'s not-yet guard removed): `login`'s path through the
  seam, then `export_page.request_export(…, source=CHATGPT)`: straight to
  `/settings/data-controls`, **Export**, **Confirm export**, the status. Signed out is
  the root without a composer (`signed_out_at_root`). The block, golden:

  ```text
  ChatGPT extraction — work

  Export requested 2026-09-30 18:12 UTC.
  ChatGPT will email or text a download link to the account's address.
  It can take up to 7 days. When it arrives:

    dataporter extract --source chatgpt --account work --link <url>
  ```

- **Tests** (`tests/fake_chatgpt_pages.py`, new; `tests/test_chatgpt_ask.py`, `slow`):
  a `FakeChatgptSite` whose tab crosses from the landing page to the auth host and back,
  with an export page in three stages, answering every tagged expression and recording
  every click, typed value, expression and navigation; the walk is one click and two
  fields and starts no Hermes; no expression carries a credential; a signed-in landing is
  already done; no **Log in**, a code step and a refused password each need a person
  with `authentication required`; the ask walks in, presses twice and prints the block
  byte for byte; a signed-in profile asks without typing; interactively the prompt is
  ChatGPT's and the ask waits; no credentials is exit `2` before any browser; a page
  that never says requested is exit `1` and no `ask.json`; the trace header names
  `chatgpt` and `chatgpt.com` and its moves are `login-button`, `email-step`,
  `password-step`, `export-button`, `export-confirm` with their selectors and paths, the
  action log the same five, and no secret in either; `login --source chatgpt --account
  work` through the command opens the root and stores its own profile. Live
  (`tests/test_browser_helpers.py`, `requires_a_browser`): a real Chrome reads the
  landing fixture's **Log in** and the Data controls fixture's three stages with the
  ChatGPT selectors.

## Out of scope

- The fetch through the session: `45`. `--link` still exits `69`.
- The profile-menu route to Data controls; a code prompt, a CAPTCHA, a banner on the
  auth host: exit `3`, named *unknown* in `LIMITATIONS.md` (`47`).
- Claude's unattended sign-in as a walk (§71).

## Design notes

- **Straight to the path.** The map marks the path *unknown* and the menu walk would be
  three more *unknown* clicks; one string is one correction.
- **Reuse `fill_and_submit`; press Enter, not Continue.** The map says Enter submits, and
  `login_form` is the only module allowed a credential value. `CONTINUE_SELECTOR` is in
  the source's table so every sketch counts it on the real page.
- **The auth host admitted whole.** Rejected: `/log-in(/.*)?` only, which would make the
  first real run's evidence a refusal at the wall rather than a sketch of the real page;
  the wall's work on that host is done by `login_form` finding a field or stopping.
- **No Hermes on this path.** A backup that needs an API key is one people stop running
  (`31`'s own note), and the mock's sign-in has a fixed shape to walk. The cost is that
  the auth host's screens are the tool's to keep right, which is the map's discipline.
- **`record_step` beside `record_move`** rather than one function: a helper's move
  carries its printed outcome, sanitised; a step of the tool's own carries a selector and
  a URL and nothing to sanitise.

## Acceptance criteria

- The fake-world tests above pass; `make check` is green with every Claude golden test
  unchanged.
- `login --source chatgpt --account work` creates `<accounts>/chatgpt/work/browser-profile/`
  and `login --account a` for Claude prints what it printed before.
- Unattended: one `Input.insertText` per field, values only as CDP parameters, one click,
  no Hermes subprocess; exit `2` without credentials; exit `3` on the three variants.
- The ask prints the block byte for byte, two clicks, no typing; the trace header says
  `chatgpt`/`chatgpt.com`; `actions.jsonl` holds the five steps.
- The two surfaces refuse each other's pages and `/c/<id>`.
- *(Live, `46`'s.)* The extraction rehearsal signs in to the mock chatgpt.com through the
  walk and asks; that is what turns this slice `Done`.
  Met on 2026-09-14: the extraction rehearsal (`46`, [`docs/rehearsal-03.md`](../../docs/rehearsal-03.md)) signed in to the mock chatgpt.com through the walk and asked, twice; `Done`.

## Risks

- **The real auth host may not be `auth.openai.com`** for every account (SSO), and its
  screens are *unknown*: exit `3` with a sketch in the trace, which is the intended
  evidence (§69).
- **Composer drift on chatgpt.com.** `probe.logged_in` on a signed-in root depends on the
  composer selector matching the redesigned composer (the map's highest-risk row); a
  signed-in root without a match reads as signed out, the walk finds no **Log in**, and
  the run stops with `no_login_button` — honest, and a `LIMITATIONS.md` bullet.
