# The claude.ai UI map

**Kind:** Spike record — what was observed, not what was designed. Produced by
[`10`](../specs/impl/10-attach-spike.md).
**Answers:** Q4 (generation signals), Q5 (the chat URL), Q6 (the failure states), Q7
(rename), Q8 (the file input), Q10 (bot checks).
**Spike run:** none.
**Hermes version:** unknown. **Chrome version:** unknown.

This is the file that
[`browser/probe.py`](../src/dataporter/browser/probe.py) and
[`11`](../specs/impl/11-skill.md)'s skill are corrected against — and, since
[`26`](../specs/impl/26-mock-claude.md), the file the mock claude.ai is built
out of: every state the mock can show is a row below, cited in its `uimap.py`,
and a behaviour it needs that has no row here is added here first, marked
*unknown*. **A mock run never turns an *unknown* into an *observed***. Only a
person watching claude.ai does that. Every selector and label
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
when someone watched that exact signal appear.

| State | Signal the code looks for today | Observed signal | Mark |
| ----- | ------------------------------- | --------------- | ---- |
| `signed out` | path starts `/login`; a helper will not drive it at all — the login page is outside `helpers.MIGRATION_SURFACE`, so every helper answers `outside_migration_surface` and reports the URL | not yet looked at | *unknown* |
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
| `captcha or security challenge` | nothing — the code cannot see this yet | not yet looked at | *unknown* |
| `sign-in form` (`24`) | `login_form.LOGIN_FIELDS_JS`: a visible `input[type="email"], input[autocomplete="username"]` for the email step, a visible `input[type="password"], input[autocomplete="current-password"]` for the password step, Enter to submit each; anything else after the email — a code prompt, a challenge — is `code_or_challenge` and a pause. The agent's half (`signin.prompt`) is told to take the email path and never Google, Apple, SSO or a passkey, by looking | not yet looked at | *unknown* |
| `browser error page` | the tab's URL is no longer on `claude.ai`, so `chosen_tab` answers `no_claude_tab` | not yet looked at | *unknown* |
| `generation failed` | nothing — the code cannot see this yet | not yet looked at | *unknown* |
| `every message` | `[data-testid="user-message"], [data-testid="assistant-message"]`, visible, in document order — `17`'s `probe --messages` reads the whole transcript this way and reports a role, a length and which of the caller's own strings each turn contains | not yet looked at | *unknown* |
| `chat title` | the first visible match of `[data-testid="chat-menu-trigger"], [data-testid="conversation-title"], header h1, header h2`, else `document.title`; whitespace squashed, compared in the page against the caller's `--expect-title` | not yet looked at | *unknown* |
| `rename affordance` | nothing in the code: `17` asks Hermes to find "the chat's own menu" and its rename control by looking, because this document has no label to quote. What the tool checks is the row above — whether the title changed — never how it was changed. `26`'s mock serves the simplest shape that description admits — a menu that opens from the title trigger, a rename control in it, and a text field that takes a new name — and `27`'s scripted agent, which cannot look, drives that shape by id | not yet looked at | *unknown* |

Every selector in the middle column has exactly one spelling in the source, in
`probe.py`'s `_SELECTORS` and the two expression bodies beside it, so correcting a row here
is a one-line edit there.

## Notes

Timestamped observations land in [`spike/notes.jsonl`](spike/), one JSON object per line,
written by `spikes/spike.py`. Screenshots go in [`spike/`](spike/) with personal data
cropped. No message content, no titles and no account identifiers belong in either (§10).
