# 70 — The sign-in screen, at the address that was asked for

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 03](../03-extraction-and-backup.md) §35, §36,
[brief 07](../07-claude-sign-in.md) §77
**Depends on:** [07](07-browser-session.md), [31](31-source-session-and-ask.md),
[51](51-export-page-address.md), [62](62-waiting-for-the-export-panel.md)
**Enables:** [71](71-the-mock-grows-a-sign-in-screen.md), which turned this `Done`
**Status:** Done

## Goal

Teach the tool the second way claude.ai says "signed out".

`export_page.signed_out` knows one: a redirect whose path starts `/login` (the `signed
out` row of [`docs/claude-ui-map.md`](../../docs/claude-ui-map.md), *observed on
2026-09-15*). There is another, and it is the one an ask meets. A signed-out request for
`/new#settings/data-privacy-controls` is **not** redirected: the application renders its
sign-in screen at that address, so `kind_of` reads `/new`, answers `NEW_CHAT`, and
`signed_out()` — whose second clause is dead for Claude, which sets
`signed_out_at_root=False` — answers `False`.

What follows is the failure this slice removes. `sign_in_to_source` returns as if the
session were good, `request_export` polls a page with no button for the whole of
`timeouts.ask_s`, and the ask reports `the export panel did not appear on
/new#settings/data-privacy-controls within 60s` with a *guessed* remedy appended and exit
`1`. Sixty seconds, the wrong code, and the right answer buried in a maybe.
`extract.py`'s own comment has named this gap since `62`.

## In scope

- **`browser/probe.py`** — `PageState` gains one field:

  ```python
  sign_in_showing: bool = False
  ```

  computed in the page from selectors the caller passes in. `page_state_js`,
  `page_view_js` and `page_report_js` take a `sign_in: Sequence[str] = ()`, which becomes
  a `const signIn` beside `expect`; the state object answers

  ```js
  sign_in_showing: signIn.length > 0 && signIn.every((s) => document.querySelector(s) !== null),
  ```

  `querySelector` and not `visible`: both signals are present-but-invisible by design (see
  Design notes). `probe`, `page_view` and `page_report` take the same keyword and default
  to `()`, which is `False` — so every existing caller keeps the answer it had.

- **`browser/session.py`** — `current_state(..., sign_in: Sequence[str] = ())`, passed
  through to `probe`.

- **`sources/base.py`** — `Source.sign_in_selectors`, a property returning the two
  `selectors` entries that are set, in a fixed order, and `()` for a source that declares
  neither.

- **`sources/claude.py`** — the two constants and their entries in `selectors`:

  ```python
  SIGN_IN_ATTESTATION_SELECTOR = '[data-client-attestation-channel="send_magic_link"]'
  SIGN_IN_FORM_SELECTOR = 'form:has([data-testid="email"]):has([data-testid="continue"])'
  ```

- **`browser/export_page.py`** — `signed_out` gains one disjunct:

  ```python
  if state.kind is probing.PageKind.LOGIN or state.sign_in_showing:
      return True
  ```

- **`extract.py`** — `sign_in_to_source` passes `source.sign_in_selectors` to
  `current_state`, and `sign_in_or_record` wraps it so that the trace is told
  `ExitCode.NOT_AUTHENTICATED` on the path that raises `AuthError`: `watched` records what
  the body assigned, and a body that raises assigns nothing. **Both** commands that open a
  source session inside a `watched` go through it — the ask, and
  `extract_skills._collect` — because they fail here the same way and a trace of one that
  said how its run ended while the other did not would be the odd one out.

- **`CONTEXT.md`** — a new term under *Extraction and backup*:

  > **Sign-in screen**:
  > The vendor's sign-in page rendered in place of the page that was asked for, at that
  > page's own address. The second way a site says signed out: a redirect changes the URL
  > and this does not, so only the page's own markup tells them apart.
  > _Avoid_: login page, signed-out page, sign-in surface

- **[`docs/spike/claude-sign-in-screen-2026-09-18.html`](../../docs/spike/claude-sign-in-screen-2026-09-18.html)**
  — the evidence, trimmed to the head and the sign-in card, with `data-ion-ip-country` and
  `data-ion-served-at` removed and every script, style and marketing section cut. The file
  says at the top that it is a trim and what was taken out.

- **`docs/claude-ui-map.md`** — `sign-in form` becomes *observed on 2026-09-18*, and a new
  `sign-in screen in place` row joins it citing the same artefact.

## Out of scope

- **The bot check.** A Cloudflare interstitial is a different page from a sign-in screen,
  and the `captcha or security challenge` row stays *unknown*. `62` left it undone and this
  slice does not pick it up.
- **`probe.logged_in`.** Unchanged. On a sign-in screen the composer is absent, so it is
  already `False` for every caller that reads it, and redefining it would change the
  meaning of a field recorded in every trace and in `08`'s JSON object.
- **ChatGPT.** Its two selector entries are absent, so `sign_in_showing` is `False` for it
  and `signed_out_at_root` goes on answering the question. Nobody has read a signed-out
  ChatGPT export page, and a guessed selector is a claim.
- **The `link sent` screen.** The rule below does not match it, deliberately — see Design
  notes.

## Design notes

**Two signals, both positive, both structural.** The rule is a conjunction:
`[data-client-attestation-channel="send_magic_link"]` **and**
`form:has([data-testid="email"]):has([data-testid="continue"])`. A magic-link *sender* is
mounted, and a form holds the address field together with the control that submits it.
Both are things that exist only where a sign-in can be started, so the check cannot be
made true by a redesign of the *export* page — which is the failure direction that
matters. A redesign of the *sign-in* page makes it false instead, and a missed sign-out
costs a minute and the message the tool prints today.

Rejected, and why:

- **`<title>Sign in - Claude`** and the `description` meta. The page is `lang="es-419"` and
  every visible word on it is Spanish, while both of these are English. Depending on that
  inconsistency is depending on a bug, and `REQUESTED_SELECTOR` is already this repo's
  cautionary tale about matching on words.
- **The absence of a composer, or of the export button.** An absence-check is generous by
  construction: every page that is not the one expected satisfies it, so a reordered panel
  would be reported as a signed-out account. `sources/claude.py` says at length what a
  selector that is too generous does — it does not fail, it fabricates.
- **`[data-testid="login-with-google"]` alone.** Specific, but a settings page could
  plausibly grow a "connect Google" row carrying the same id. It is in the artefact and not
  in the rule.

**Presence, not visibility.** The attestation container is `aria-hidden` and sized to zero,
so the prelude's `visible()` rejects it. `querySelector` is what the rule uses, and the
artefact marks both signals in place so the next reader can see why.

**The rule matches the first step of the sign-in and not the `link sent` step.** That
screen keeps `continue` and replaces `email` with `code`, so the form half does not match
it — as `claude-sign-in-link-sent.html` shows. That is correct for what this is for: an
extraction never enters an address, so the screen it meets is the first one. A rule
widened to `form:has([data-testid="continue"])` would cover both and would be exactly the
generosity the paragraph above rejects.

**The selectors live on the `Source`, and the reading lives in the probe.** The `Source` is
where "what this vendor's pages look like" already lives (`42`), and the probe is where
"one CDP evaluate answers the whole DOM question" already lives. Passing the selectors in
keeps both true and adds no round trip: `sign_in_showing` rides the evaluate that was
already being made.

**One field, not a new `PageKind`.** `kind_of` is a pure function of the URL, and traces,
sketches, the mock and `08`'s contract all record what it returns. A content-aware `LOGIN`
would change the meaning of every `kind` ever recorded; a new boolean changes nothing that
already exists and is the fact `signed_out()` actually wants.

## Acceptance criteria

1. A fake export page carrying both signals: `export_page.signed_out(state, CLAUDE)` is
   `True`, and `extract.ask` raises `AuthError` whose detail is
   `not logged in — run: dataporter login --source claude --account …`, exit `3`, without
   pressing anything. `tests/test_ask.py`.
2. The same page missing **either** signal: `sign_in_showing` is `False`, `signed_out` is
   `False`, and the ask goes on to press the button exactly as it does today.
3. The same markup, served to a **real Chrome** and met by the **shipped tool**: the ask
   exits `3`, names the remedy, and leaves a two-line trace — a header and an end, no move
   and no sketch, because it pressed nothing. *Measured on 2026-09-18 against the mock
   claude.ai, Chrome/153.0.8010.48; the record is*
   [`docs/rehearsal-05.md`](../../docs/rehearsal-05.md)*, and `71` is the slice that
   measured it.*
4. A source with no sign-in selectors — ChatGPT — has `sign_in_selectors == ()` and
   `sign_in_showing` is `False` on every page. `tests/test_sources.py`.
5. `PageState` validates and defaults the new field — so `08`'s JSON object, which is this
   model, carries it without anything else changing. `tests/test_browser_probe.py`.
6. An ask that stops signed out leaves a trace whose last line is `end` with `exit: 3`.
   `tests/test_ask.py::test_an_ask_that_stops_signed_out_says_so_in_its_trace`.
7. `CONTEXT.md` holds the **Sign-in screen** term, and no other file in `specs/` or `src/`
   uses "sign-in surface" for it.
8. `make check-all` passes, except the one pre-existing macOS-only Hermes environment test.

## Risks

- **The selectors are one account's page on one day.** Both were read off the artefact
  committed with this slice and nothing else; `claude-sign-in-link-sent.html` corroborates
  the attestation container from 2026-09-15, and nothing corroborates the form. If
  claude.ai renames either test id the check goes quiet and the tool is back to the
  sixty-second timeout — which is the failure it has today, not a new one.
- **`:has()` is Chrome 105+.** Every browser in `CANDIDATE_EXECUTABLES` is well past it,
  and a browser that did not support it would throw inside `querySelector`; the expression
  would answer nothing and the probe would read `False`. Worth knowing, not worth guarding.
- **`send_magic_link` may not be unique to the sign-in screen.** It is absent from every
  signed-in page anybody has looked at, which is two. The conjunction is what makes that
  survivable: the form has to be there too.
