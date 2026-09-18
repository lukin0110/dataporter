# The claude.ai UI map

**Kind:** Spike record — what was observed, not what was designed. Produced by
[`10`](../specs/impl/10-attach-spike.md).
**Answers:** Q4 (generation signals), Q5 (the chat URL), Q6 (the failure states), Q7
(rename), Q8 (the file input), Q10 (bot checks).
**Spike run:** 2026-09-15, one page read by hand — the sign-in page after the link was
sent, kept as [`spike/claude-sign-in-link-sent.html`](spike/claude-sign-in-link-sent.html);
no Hermes task was run, and no row of `10`'s own questions was observed.
**Hermes version:** unknown. **Chrome version:** unknown (the page was read in Chrome; its
version was not recorded).

This is the file that
[`browser/probe.py`](../src/dataporter/browser/probe.py) and
[`11`](../specs/impl/11-skill.md)'s skill are corrected against — and, since
[`26`](../specs/impl/26-mock-claude.md), the file the mock claude.ai is built
out of: every state the mock can show is a row below, cited in its `uimap.py`,
and a behaviour it needs that has no row here is added here first, marked
*unknown*. **A mock run never turns an *unknown* into an *observed***. Only a
person watching claude.ai does that — or a person who has read a trace of a run against
claude.ai (brief `04` §49) and cites it, by file and line, as the row's *Observed
signal*: the trace is the watching, kept. Every selector and label
below is either something a human watched the page do — `*observed on <date>*` — or the
informed guess `08` shipped with, which is `*unknown*` until somebody looks. Nothing here
is a design decision; when the map and the code disagree, the map wins and the code
changes.

## Answers

- **Q4 — What does the DOM show while Claude generates and when it stops, and how long
  does a 50 k seed take?**
  unknown. Not attempted: needs a throwaway destination account and a headed Chrome. The
  signals `probe` watches today are in the table below; the duration belongs in
  `timeouts.response_s`, which is 300 s on no evidence at all.
  *unknown*
- **Q5 — What is the URL immediately after the first submit, and when does `/chat/<uuid>`
  appear?**
  unknown. Not attempted. `probe.kind_of` treats `/` and `/new` as a new chat and only
  `/chat/<uuid>` as a conversation, so a submit that leaves the URL at `/new` for a while
  means `12` must poll for the id rather than read it once.
  *unknown*
- **Q6 — What do the login redirect, a rate limit, a generation error, a network drop and
  a JS dialog look like?**
  unknown. Not attempted. Provoke the rate limit last: it costs quota on the throwaway
  account. Each one that is provoked gets a row in the table below and a recovery rule in
  [`13`](../specs/impl/13-recovery.md).
  *unknown*
- **Q7 — Is there a rename affordance for a chat, what is its label, and does the new
  title persist after reload?**
  unknown. Not attempted. `17` was built without the answer, and its risk section says how:
  the rename is delegated to Hermes and described by *affordance* rather than by selector
  ("the chat's own menu, its rename affordance"), which is something an agent finds by
  looking rather than a string this document would have to supply. `fidelity.rename_title`
  defaults to `true` on that basis; an operator whose account has no such affordance sets it
  to `false` and gets `title_not_set` for every conversation. What the *verification* looks
  at is in the two rows below, and the answer here is what decides whether they are ever
  read: a rename nobody can perform makes both of them moot and moves "equivalent titles"
  to [`LIMITATIONS.md`](LIMITATIONS.md) for good.
  *unknown*
- **Q8 — Does the file input exist on `/new` before any text is typed, and does
  `DOM.setFileInputFiles` produce the attachment chip?**
  unknown. Not attempted. `08`'s `attach` assumes both: it finds `input[type="file"]`
  without typing first, and it waits for a visible leaf element outside the composer whose
  text contains the file name.
  *unknown*
- **Q10 — Does a fresh profile trigger a bot check or CAPTCHA on login?**
  unknown. Not attempted. `07`'s `login` hands the window to a human for up to ten
  minutes, so a challenge a human can solve is survivable; one that appears mid-run is a
  `needs_human_reason` of `captcha`.
  *unknown*

## State → observable signal

What we look for today, and what the page really does. The middle column is the code as it
stands; the right-hand column is what replaces it. A row is only `*observed on <date>*`
when someone watched that exact signal appear, or read it in a committed trace and cites
it beside the signal — `docs/spike/traces/<file>.jsonl:<line>` — in the sketch's own
words, the role and the label, and nothing paraphrased. A trace's sketch (brief `04` §45) counts
the middle column on a real page: its `selectors` object says how many elements each of
these selectors found, by the constant's name, visible or not.

| State | Signal the code looks for today | Observed signal | Mark |
| ----- | ------------------------------- | --------------- | ---- |
| `signed out` | path starts `/login`; a helper will not drive it at all — the login page is outside `helpers.MIGRATION_SURFACE`, so every helper answers `outside_migration_surface` and reports the URL | the redirect is recorded now: `docs/spike/traces/login-2026-09-15.jsonl:4` is `url_changed` to `/logout` with `query: ["involuntary", "returnTo"]`, and `:11` is a `GET /login` document with `query: ["from", "reauth", "returnTo"]` — `/new` does not land on `/login`, it is sent there by way of `/logout`. The page found there is `docs/spike/claude-sign-in-link-sent.html` | *observed on 2026-09-15* |
| `involuntary sign-out` | nothing — no code names this state, and none needs to: both hops are inside the sign-in's wall's sibling, and what the tool sees at the end of them is the `signed out` row above. It is here because it is the shape of a session lapsing *mid-run*, which brief 02 §21 lists among what a mock cannot show | `docs/spike/traces/login-2026-09-15.jsonl:4` — `url_changed` `/logout`, `query: ["involuntary", "returnTo"]`; then `:9`, a `POST /api/auth/logout`; then `:11`, a `GET /login` document with `query: ["from", "reauth", "returnTo"]`. The sketch at `:5` shows the `/logout` page is the marketing footer and not an app screen | *observed on 2026-09-15* |
| `new chat` | path is `/` or `/new` | not yet looked at | *unknown* |
| `conversation` | path matches `/chat/<uuid>` | not yet looked at | *unknown* |
| `composer present` | a visible `div[contenteditable="true"]` | not yet looked at | *unknown* |
| `composer empty` | `blockText(composer).length === 0` | not yet looked at | *unknown* |
| `can submit` | a visible `button` whose `aria-label` contains `Send`, not disabled | not yet looked at | *unknown* |
| `generating` | a visible `button` whose `aria-label` contains `Stop` | not yet looked at | *unknown* |
| `generation finished` | the last message stops growing for three one-second polls | not yet looked at | *unknown* |
| `human turn` | `[data-testid="user-message"]` | not yet looked at | *unknown* |
| `assistant turn` | `[data-testid="assistant-message"]` | not yet looked at | *unknown* |
| `modal in the way` | a visible `[role="dialog"]` | not yet looked at | *unknown* |
| `JS dialog in the way` | a `Page.javascriptDialogOpening` with no matching close | not yet looked at | *unknown* |
| `upload target` | `input[type="file"]`, visible or not | not yet looked at | *unknown* |
| `upload accepted` | a visible leaf element outside the composer containing the file name | not yet looked at | *unknown* |
| `every upload accepted` | the same test over a list of names in one evaluate — `16`'s check that the composer carries as many chips as the conversation has files, made once before the first paste | not yet looked at | *unknown* |
| `rate limited` | `probe.rate_limited`: a disabled Send beside a composer that is not empty. An enabled Send is "not limited"; an empty composer is neither answer, because an idle new chat looks the same. The banner itself is not read — it is text | not yet looked at | *unknown* |
| `captcha or security challenge` | nothing — the code cannot see this yet. What one looks like was recorded on 2026-09-15: a headless Chrome asking for the export page is served a Cloudflare interstitial — a `script` from `challenges.cloudflare.com`, a `ray-id` footer, obfuscated class names, forty-seven nodes — that never resolves, where the same profile headed loads the app. A structural check for that script would let the ask say "a bot check is in the way" in a poll instead of waiting out `timeouts.ask_s`, and it would read no text; `62` leaves it undone | the markers were read on a real account by listing element ids, classes and script hosts — never text, so nothing of the account is in them — but nothing was committed under `spike/`, so this row stays unmarked as `51`'s do | *unknown* |
| `sign-in form` (`24`, `50`) | `login_form.LOGIN_FIELDS_JS`: a visible `input[type="email"], input[autocomplete="username"]` for the email step; the password step `24` wrote — `input[type="password"], input[autocomplete="current-password"]` — is kept for a source that has one, and claude.ai has none (brief 07 §72): what follows the address is the `link sent` row below, which `login_form` reports as `code_or_challenge` and types nothing into. The agent's half (`signin.prompt`) is told to take the email path and never Google, Apple, SSO or a passkey, by looking; no source uses it since `52` | the email step itself has not been read off the page — the artefact below was captured after the address had gone in | *unknown* |
| `link sent` (`50`) | `login_form.CODE_SELECTOR`: a visible `input[data-testid="code"], input[autocomplete="one-time-code"]` on a `/login` path, read as a boolean beside the other two fields; `login` prints its link-sent line on the first sight of it and restarts its clock. Read on a sign-in page only: a match anywhere else is not this row | `docs/spike/claude-sign-in-link-sent.html`: still at `/login`, `lang="es-419"`, a `form` holding `input[data-testid="code"][autocomplete="one-time-code"][inputmode="numeric"]`, a `button[type="submit"][data-testid="continue"]`, two `button[type="button"]` for resending and changing the address, and two hidden `[data-client-attestation="hcaptcha-invisible"]` containers, one on the channel `send_magic_link`. Its own words say a link opened elsewhere shows a code to be typed here. Read in Spanish, which is the point: none of it is a word | *observed on 2026-09-15* |
| `link requested` (`50`) | nothing — evidence for the trace, never a decision: the watch records the request as any other on the host | `docs/spike/traces/login-2026-09-15.jsonl:33` — a `POST /api/auth/send_magic_link` with no query, preceded at `:31` by a `GET /api/auth/login_methods` carrying `query: ["email", "source"]`. The request is seen now, in a committed trace; what it carries is not, because a trace records a path and the names of a query and never a value (§46), so the attestation ADR 0008 names is still unread | *observed on 2026-09-15* |
| `sign-in link` (`53`) | `claude.SIGN_IN_LINK_PATH`: the link lands on `/magic-link`, a door in the sign-in's wall, and the tab is pointed at the link with `Page.navigate` and no wall, as the fetch's is (`45`). The token is in the fragment, which `46`'s guard never records; the page reads it and posts it itself | `docs/spike/traces/login-link-2026-09-15.jsonl:3` — a `GET /magic-link` `document` with `query: []`, reached by `Page.navigate` from `:2`'s `sign-in-link` move (`ok: true`); the token is in a fragment, which a trace never records. The page's own script is `docs/spike/claude-sign-in-link-sent.html`. The emailed address — whether it is this URL or a mail host's redirect to it — is still unseen | *observed on 2026-09-15* |
| `signed in by the link` (`53`) | the `new chat` row: the probe's `logged_in` on whatever the link redirects to | `docs/spike/traces/login-link-2026-09-15.jsonl:22` — a `POST /api/auth/verify_magic_link`, answered `200` at `:23`, and at `:27` `url_changed` to `/new`: the page redeems the token itself, 2.1 s after the link was spent. `:28` sketches that `/new` as the signed-in app, in the account's own language: buttons labelled `Buscar`, `Enviar mensaje` and `Escribe tu mensaje para Claude`, which is the composer the probe reads | *observed on 2026-09-15* |
| `link opened elsewhere` (`53`) | the `link sent` row seen again after the navigation — the tab back on `/login` with the code field showing — is `signin_link.CODE_PROMPT`, exit `3`; anything else inside `timeouts.signin_s` is `NOT_ACCEPTED` | the page's own words say the link, opened where the pending sign-in is not, *shows* a code rather than signing in; what that page looks like — and whether the tab comes back to `/login` at all — has not been seen, so the code path recognises the one shape it knows and reports the rest as not accepted | *unknown* |
| `browser error page` | the tab's URL is no longer on `claude.ai`, so `chosen_tab` answers `no_claude_tab` | not yet looked at | *unknown* |
| `generation failed` | nothing — the code cannot see this yet | not yet looked at | *unknown* |
| `every message` | `[data-testid="user-message"], [data-testid="assistant-message"]`, visible, in document order — `17`'s `probe --messages` reads the whole transcript this way and reports a role, a length and which of the caller's own strings each turn contains | not yet looked at | *unknown* |
| `chat title` | the first visible match of `[data-testid="chat-menu-trigger"], [data-testid="conversation-title"], header h1, header h2`, else `document.title`; whitespace squashed, compared in the page against the caller's `--expect-title` | not yet looked at | *unknown* |
| `export page` (`31`, `51`) | the address `export_page.EXPORT_PAGE_PATH` names: `/new#settings/data-privacy-controls`, a settings dialog over the app rather than a path of its own. `31`'s `/settings/data-privacy-controls` was a placeholder and served nothing. It is also the whole of `EXTRACTION_SURFACE` beside `/login`, and because a wall matches a URL as a string the fragment keeps that wall as narrow as it was: `/new` itself is not admitted | `51` changed the code on a person's reading of a real account; no artefact is committed under `spike/`, so this row cannot be marked yet | *unknown* |
| `export button` (`51`, `62`) | a visible `[data-perf-screen="data-privacy-controls"] [data-settings-row] button[data-cds="Button"]`, clicked with `element.click()` on the first visible match. Matched by position because the panel offers nothing better: no test id, the rows' ids are React's and regenerated each render, and the only thing distinguishing Export from the five *Manage* rows under it is its words. Every row above it holds a switch, so the Export button is the panel's first. **It is not there when the document is:** polled on a real account, the panel renders about **2.9 s** after the navigation — `readyState` is `complete` at ~1.4 s with 143 nodes and nothing to click, and the button arrives with the app's 670 — so `62` waits for it rather than reading once | the timing was measured by polling the tool's own JS and clicking nothing, but the run left no artefact under `spike/`, and the selector itself is still on `51`'s reading | *unknown* |
| `export confirmation` (`31`, `52`) | the `Export data` row does not ask for anything: it opens a **second screen** at `/new#settings/data-privacy-controls/export-data`, inside the same settings dialog, carrying a description, a `Conversations from` period, a list of what the export will include, and the button that asks — a visible `[data-testid="export-confirm-button"]`. `view.dialog` is true throughout, because the settings panel is itself a `[role="dialog"]` | a person read the screen's markup on a real account; no artefact under `spike/`, as above | *unknown* |
| `export period` (`52`) | the second screen offers `Conversations from`: `All` (checked), `30 days`, `90 days`, `Custom`, as a `[role="radiogroup"]`. The ask touches none of it and relies on `All` being the default. If that default ever changes, a backup starts filing partial snapshots while reporting success | read beside the row above | *unknown* |
| `export requested` (`31`, `51`, `53`) | a visible `[data-cds="Toast"] [role="dialog"] h2` whose trimmed text is exactly `Export started`: a toast, bottom right, with no test id in it and a heading `id` that is React's (`_r_6k_`) and regenerated each render. **The one signal read by its words as well as its shape**, because the container is the site's notification furniture and every toast — a copy confirmation, an error, a rename — shares it. `31`'s `[role="status"]` fallback is **removed** and matching the toast shape alone would be the same mistake in newer markup: on 2026-09-14 that generosity matched a live region before anything had been asked for — the run clicked the row, never reached `Export`, and wrote an `ask.json` for a request the vendor never received. The words are compared inside the page and only a boolean crosses the wire, so `probe`'s rule is kept. A reworded or non-English toast matches nothing, and the ask then waits out `timeouts.ask_s` and reports it could not confirm — wrong in the safe direction. Note a toast is itself a `[role="dialog"]`, so `view.dialog` is true while one is up | a person read the toast's markup on a real account; no artefact under `spike/`, as with the two rows above | *unknown* |
| `skills page` (`66`) | the address is a path of its own and not a fragment: `/customize/skills/mine` is the *Your skills* tab and `/customize/skills/discover` the other, and bare `/customize` redirects to the latter. A detail page is `/customize/skills/<id>` for a skill the account wrote and `/customize/skills/<name>` for one of Anthropic's. **Nothing the extraction needs is on it, and the tab is never sent there** — the two rows below are read from the export page, because this page's controls are labelled *View <name>* and *More actions for <name>* and a sketch keeps a control's label (§46). So the wall does not admit it, and it is here as the shape that was looked at and set aside, not as something the code drives | read by hand on the operator's own account, 2026-09-18, by listing paths and `data-testid` values and never text. Nothing is committed under `spike/`, both because that directory takes the throwaway account only and because, as `51`'s rows have it, a reading with no artefact does not mark a row | *unknown* |
| `skills list` (`66`) | `GET /api/organizations`, answered with a list whose first entry's `uuid` is the organisation every other skills address hangs under; then `GET /api/organizations/<org>/skills/list-skills`, no query, answered `200` with `{"skills": [...]}`. Each entry carries `id`, `name`, `display_name`, `description`, `creator_type`, `enabled`, `source`, `backing_plugin_id`, `skill_directory`, `is_shared` and `owner`. It is a **superset of what the tab paints**: the account read on 2026-09-18 answered fourteen entries where *Your skills* rendered five, so the filter below is what decides the set, not the page. The address is the one claude.ai's own app asks for on sign-in — `docs/spike/traces/login-2026-09-15.jsonl:79` has it in a committed trace, path only | the response shape was read on the operator's own account, 2026-09-18; field *names* and the two `creator_type` values are all that is written down, no value of the account's own. No artefact under `spike/`, as the row above | *unknown* |
| `skill authorship` (`66`) | `creator_type`, whose observed values are `anthropic` and `user`. **Created by you is `user`** — a value and not a word, so the filter carries no language. The page says the same thing structurally: the *Your skills* tab groups rows under `[data-testid="yours-section-createdByYou-header"]` and `[data-testid="yours-section-anthropic-header"]`, and the first is **absent, not empty**, on an account that wrote none. A skill the account wrote may still sit in a plugin — the one read on 2026-09-18 had `source: "plugin"` and a `backing_plugin_id` beside `creator_type: "user"` — so plugin membership is recorded and never filtered on | read as the row above. The two values are the whole of what was observed: whether a third exists for a shared or organisation-authored skill is unseen, and a `creator_type` the code does not know must be treated as not-ours rather than ours | *unknown* |
| `skill download` (`66`) | `GET /api/organizations/<org>/skills/download-dot-skill-file`, `query: ["skill_id", "include_blocked"]`, answered `200` with `content-type: application/zip` and a body beginning `PK\x03\x04`. `include_blocked` is optional: omitted, the same bytes came back. **There is an address, and the menu item is not what serves it** — *Download* fetches this address, wraps the bytes in a `Blob` and hands them to an `<a download="<name>.skill">` with a `blob:` href, which is presentation and not the source. So a fetch navigates the signed-in tab to the address and `45`'s capture takes it, and the tool clicks nothing in a source account for skills | the address was found by instrumenting `window.fetch` on the operator's own account, 2026-09-18, and then called on its own to confirm it stands without the page. Only the path, the query names, the status and the content type are written down. No artefact under `spike/`, as the rows above | *unknown* |
| `skill name` (`66`) | `name` is already path-safe: the *Duplicate* dialog states the rule in its own words — lowercase letters, numbers and hyphens — and `display_name` is the free-text one beside it. So the name a file is called after is the vendor's constrained field and a slug of it is close to identity; the collision suffix `66` specifies is for the case the rule does not hold rather than the common one. The file the page names is `<name>.skill`, a zip by its magic | the rule was read off the dialog on the operator's own account, 2026-09-18. Whether the vendor enforces it server-side, and whether two skills may share a `name`, is unseen — so the suffix stays | *unknown* |
| `skill menu` (`66`) | the detail page's control is `button[aria-label="More options for <name>"]` and a row's is `More actions for <name>`, both carrying the skill's name in the label. **Its items depend on authorship**: a skill of Anthropic's offered *Try in chat*, *Duplicate* and *Remove* only, and one the account wrote offered *Edit with Claude*, *Rename*, *Replace* and *Download* as well — so *Download* is absent exactly where `skill authorship` says the skill is not ours. The items are `[role="menuitem"]` with no test id, distinguished only by their words and their icon's `d`; the composition is not stable either, since the same menu read on two days differed by an item. **Nothing in the code reads this row** — `skill download` made it unnecessary — and it is written down so that a later reader knows the menu was looked at and set aside | read on the operator's own account, 2026-09-18. `element.click()` does drive these items: an earlier reading here recorded it as inert, which was a confirm dialog being mistaken for a no-op | *unknown* |
| `rename affordance` | nothing in the code: `17` asks Hermes to find "the chat's own menu" and its rename control by looking, because this document has no label to quote. What the tool checks is the row above — whether the title changed — never how it was changed. `26`'s mock serves the simplest shape that description admits — a menu that opens from the title trigger, a rename control in it, and a text field that takes a new name — and `27`'s scripted agent, which cannot look, drives that shape by id | not yet looked at | *unknown* |

Every selector in the middle column has exactly one spelling in the source, in
`probe.py`'s `_SELECTORS` and the two expression bodies beside it — or, for the four
`31` rows, in
[`browser/export_page.py`](../src/dataporter/browser/export_page.py)'s own `_SELECTORS`
and the path constant above them, and for the sign-in rows in
[`browser/login_form.py`](../src/dataporter/browser/login_form.py)'s three selectors and
[`sources/claude.py`](../src/dataporter/sources/claude.py)'s `SIGN_IN_LINK_PATH` — so
correcting a row here is a one-line edit there.
The four export rows are the ones nobody can observe from a destination account: they
need a *source* account and `dataporter extract --account <label>`, which is why
[`spike/README.md`](spike/) lists them as their own steps. `32`'s mock serves those four
rows at the placeholder path with the placeholder selectors, re-typed on its side of ADR
0003's line — so correcting a row here is one edit in `export_page.py` and one in the
mock — and hands out its link at a `/__mock/` address on its own host, which is not a
row because a download is not something a page shows.

## Notes

Timestamped observations land in [`spike/notes.jsonl`](spike/), one JSON object per line,
written by `spikes/spike.py`. Screenshots go in [`spike/`](spike/) with personal data
cropped. Traces of runs against claude.ai go in [`spike/traces/`](spike/traces/), read end
to end before they are committed, and are cited by file and line. No message content, no
titles and no account identifiers belong in any of them (§10).
