# 10 — Attach spike and Claude UI map

**Kind:** Implementation spec — how this gets built. Living document. Time-boxed spike.
**Implements:** [Brief](../01-initial-brief.md) §4, §5, §11 (what "verify" concretely observes)
**Depends on:** [07](07-browser-session.md), [08](08-browser-helpers.md), [09](09-hermes-runner.md)
**Enables:** [11](11-skill.md) — and can change [11](11-skill.md)–[17](17-verification-and-title.md)
**Status:** Not started

## Goal

Find out, on the real claude.ai and the real Hermes, the facts that only observation can
settle, and write them down before the skill is written. One conversation, driven by hand
through our helpers first and by a throwaway Hermes prompt second. Nothing built here is
production code.

**No slice from `11` onward starts until the questions below have recorded answers.**

## In scope

The ten questions below, answered by observation, and the four documents that record the
answers. The code changes allowed are limited to defaults in `config.py`, selectors in
`07`'s `probe`, and the default paste method in `08`.

## Out of scope

- Anything that survives into the product beyond those defaults: the skill (`11`), the
  loop (`12`), recovery rules (`13`). Throwaway prompts and scripts stay under
  `spikes/`, excluded from the package.

## Questions to answer

1. Does a `-z` run in the `dataporter` profile attach to our Chrome via `browser.cdp_url`?
   If not, which rung of the fallback ladder works:
   - a. `browser.cdp_url` honoured in one-shot mode — *plan A*;
   - b. a long-lived `hermes serve` or ACP session where `/browser connect` is issued once
        and tasks are sent to it;
   - c. Hermes's own headed Chromium (`browser.headed: true`, `inactivity_timeout` raised
        to a day) with the login done inside it — loses the "our profile" property of `07`
        and needs `07` amended.
2. When attached, does `browser_navigate` reuse the existing claude.ai tab or open a new
   one? (Decides whether `close-extra-tabs` runs before every conversation.)
3. `paste --method insert_text` on the real composer: does the text land verbatim, does
   the UI convert it to a "pasted text" attachment, and at what size does anything break
   (try 5 k, 20 k, 50 k, 100 k, 200 k characters)? Same for `exec_command`.
4. What does the DOM show while Claude generates and when it stops (button labels,
   attributes, the last message container), and how long does a 50 k seed take?
5. What is the URL immediately after the first submit, and when does `/chat/<uuid>`
   appear?
6. What do these look like, if they can be provoked safely: the login redirect, a rate
   limit message, a generation error ("retry" affordance), a network drop, a JS dialog?
7. Is there a rename affordance for a chat, what is its label, and does the new title
   persist after reload?
8. Does the file input exist on `/new` before any text is typed, and does
   `DOM.setFileInputFiles` produce the attachment chip?
9. What is in `--usage-file`, and does `hermes sessions export` give the run's tool calls
   (for `Browser actions` in `19`)?
10. Does a fresh profile trigger a bot check or CAPTCHA on login?

## Method

- A throwaway destination account. Never the source account, never the operator's main
  account.
- Every observation is a note with a UTC timestamp, the Hermes version and Chrome version.
  Screenshots go in `docs/spike/` with any personal data cropped.
- Time box: two working days. Unanswered questions are recorded as `unknown` with what
  was tried.

## Design notes

- Hand first, Hermes second: driving the helpers by hand isolates "does the page accept
  this" from "does the agent do the right thing", so a failure has one cause.
- The fallback ladder is ordered by how much of `07` survives: rung a keeps everything,
  rung b keeps the profile but adds a long-lived process, rung c gives up our profile.
  The spike stops at the first rung that works.

## Deliverables

- `docs/hermes-attach.md` — answers to 1, 2, 9; the chosen rung; the exact profile config
  that worked, pasted verbatim from `hermes -p dataporter config show`.
- `docs/claude-ui-map.md` — answers to 4–8, 10, as a table of *state → observable signal*
  with the selectors or labels seen. Every row marked *observed on <date>*. This file is
  what `07`'s `probe` and `11`'s skill are corrected against.
- `docs/seed-limits.md` — answer to 3; sets `seed.max_chars` and the default
  `--method` in `08`; records the paste-to-attachment threshold if it applied.
- Updated defaults in `config.py` and updated `probe` selectors in `07`, with the
  acceptance tests of `07`/`08` still passing.
- `docs/LIMITATIONS.md` — seeded with every §15 property that the UI does not let us set
  (expected: original timestamps, message ids, model used).

## Acceptance criteria

- Each of the ten questions has an answer line in the docs above, `unknown` allowed.
- One conversation with two seed parts was created in the throwaway account by our helpers
  driven by hand, and its `/chat/<uuid>` reloaded shows both parts and both
  acknowledgements.
- One conversation was created by a Hermes `-z` run using only `browser_*` tools plus our
  helpers, and its result JSON validated as a `HermesResult`.
- `seed.max_chars` has a value with a recorded reason.

## Risks

- The honest outcome of question 1 may be rung c, which changes `07`. That is a finding,
  and it is why this comes before `11`.
- Provoking a rate limit costs quota on the throwaway account; do it last.
