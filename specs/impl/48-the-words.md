# 48 — The words

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 07](../07-claude-sign-in.md) §72; the glossary edits of §73, §74 and
§77; the decision [ADR 0008](../../docs/adr/0008-claude-is-an-api-source.md) records
**Depends on:** [47](47-paperwork.md)
**Enables:** `49` onward — every slice of brief 07, none of which is written yet
**Status:** Done

## Goal

The documents brief 07 stands on, before any of it is built: the glossary words it uses,
the brief itself, the decision that lets Claude off §63's rule, and this index. No code,
and no claim about claude.ai that nobody has checked.

## In scope

- **`CONTEXT.md`**: **Ask** widened to a request a vendor answers by emailing a link, with
  the **export ask** and the **sign-in ask** named under it; **Link** widened the same way,
  with the **export link** and the **sign-in link**, and `magic link` added to its
  `_Avoid_` list; **Source session** redefined as the signed-in session the tool keeps —
  a profile where the source is driven in a browser, the vendor's credential where it is
  asked directly; **Export page** noting that an API source has none; and **API source**
  added.
- **The brief** ([`07-claude-sign-in.md`](../07-claude-sign-in.md)), §72–§80: the goal and
  the diagram, the two commands and their two golden blocks (§73), what the tool holds and
  what never sees it (§74), the destination's planted cookie (§75), what a cron job loses
  (§76), the ask without a page (§77), the three shapes and the guard (§78), the mock
  without a door (§79), and what is deliberately left (§80).
- **[ADR 0008](../../docs/adr/0008-claude-is-an-api-source.md)**: Claude is an API source;
  what was considered — redeeming in Chrome, and planting the cookie — and the consequences,
  including that §63 is unchanged for every source driven in a browser and that ADR 0001
  stands.
- **`specs/README.md`**: the seventh brief in the table, the prose and the layout; the
  Examples row classifying §73's blocks golden; M12 and its chain; the status rows for
  `48`–`58`; the seventh-brief paragraph saying what claims what; and "an eighth starts at
  §81".

## Out of scope

- Every shape of every request: `*unknown*` until somebody watches claude.ai make them
  (§78), and pinned by the slice that builds each one.
- The mock's side of it, which is `49` and `50`.
- `docs/LIMITATIONS.md`'s *password sign-in only*, rewritten by `58` once the thing that
  replaces it exists. A limitation is removed when it stops being true, not when a brief
  says it will.

## Design notes

- **The words come first, not last.** `37`, `41` and `47` were paperwork slices at the end
  of their briefs, because they recorded what had been built. This one is at the start
  because `specs/README.md`'s own working rule puts it there: a term a document needs and
  the glossary lacks is added to `CONTEXT.md` first, and every slice from `49` on is a
  document that needs these five.
- **Ask and Link were widened, not duplicated.** A sign-in loop and an export loop are the
  same shape — a request, an email, a single-use address a person hands back — and both
  commands spell it `--link`. Rejected: keeping `Ask` and `Link` meaning the export alone
  and coining a second pair of words for the sign-in, which would have given the tool two
  vocabularies for one mechanism and made *the link* ambiguous in every sentence that used
  it.
- **`sign-in link`, not `magic link`.** The vendor's word is *magic link* and it is what a
  person will search for; the glossary's word is the plain one, as it is everywhere else
  (`sign-in page`, `sign-in paths`), and *magic link* goes in the `_Avoid_` list where the
  other synonyms go.
- **ADR 0008 rather than a clause in the brief.** All three of the tests are met: it
  reverses a rule stated positively in §63, a reader will wonder why Claude alone is
  reached directly, and there were two real alternatives — redeem in Chrome, or plant the
  cookie — one of which is taken for the destination in §75.
- **The brief says `*unknown*` three times and means it.** Brief 07 is written before
  anyone has watched claude.ai sign a person in, which is unusual here: `06` was written
  against a mock that had been built from a UI map. §78 carries the admission rather than
  burying it, so that a slice which needs a shape can see it is blocked.

## Acceptance criteria

- `make check` is green, and the spike-docs test accepts §78's three `*unknown*` marks.
- Every word brief 07 uses that names a domain thing is defined in `CONTEXT.md`: no
  document introduces *magic link*, *API session* or *session token* as a term.
- `specs/README.md`'s working rule says `07` starts at §72 and an eighth starts at §81, and
  the status table has a row for every slice `48`–`58`.
- No file under `src/` or `mock/` changes in this slice.

## Risks

- **A brief written ahead of the observation.** §78's shapes are unknown, so §73's blocks
  and §77's claim about the data-controls fragment are the only things about the real site
  this brief asserts, and the fragment is marked *reported* with its date. If the shapes
  come back very different — a redirect chain, a second factor, a token that is not a
  cookie — §73's commands survive and §74's discipline survives, and what changes is `52`.
- **A glossary widened for one source.** *Ask* and *Link* now cover two loops; if Gemini's
  sign-in turns out to be neither, the words widen again or the third kind gets its own,
  and §80 says so rather than pretending the question is settled.
