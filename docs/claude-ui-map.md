# The claude.ai UI map

**Kind:** Spike record — what was observed, not what was designed. Produced by
[`10`](../specs/impl/10-attach-spike.md).
**Answers:** Q4 (generation signals), Q5 (the chat URL), Q6 (the failure states), Q7
(rename), Q8 (the file input), Q10 (bot checks).
**Spike run:** none.
**Hermes version:** unknown. **Chrome version:** unknown.

This is the file that
[`browser/probe.py`](../src/dataporter/browser/probe.py) and
[`11`](../specs/impl/11-skill.md)'s skill are corrected against. Every selector and label
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
  unknown. Not attempted. If the answer is no, `17` cannot make the title a verified step
  and equivalent titles move to [`LIMITATIONS.md`](LIMITATIONS.md).
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
| `signed out` | path starts `/login` | not yet looked at | *unknown* |
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
| `rate limited` | nothing — the code cannot see this yet | not yet looked at | *unknown* |
| `generation failed` | nothing — the code cannot see this yet | not yet looked at | *unknown* |
| `rename affordance` | nothing — `17` has not been built | not yet looked at | *unknown* |

Every selector in the middle column has exactly one spelling in the source, in
`probe.py`'s `_SELECTORS` and the two expression bodies beside it, so correcting a row here
is a one-line edit there.

## Notes

Timestamped observations land in [`spike/notes.jsonl`](spike/), one JSON object per line,
written by `spikes/spike.py`. Screenshots go in [`spike/`](spike/) with personal data
cropped. No message content, no titles and no account identifiers belong in either (§10).
