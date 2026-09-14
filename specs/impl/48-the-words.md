# 48 — The words

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 07](../07-claude-sign-in.md) §72; the glossary edits of §73 and §78;
the decision [ADR 0008](../../docs/adr/0008-the-sign-in-stays-in-the-browser.md) records
**Depends on:** [47](47-paperwork.md)
**Enables:** `49` onward — every slice of brief 07, none of which is written yet
**Status:** Done

## Goal

The documents brief 07 stands on, before any of it is built: the glossary words it uses,
the brief itself, the decision that keeps the sign-in in the browser, and this index. No
code, and no claim about claude.ai that nobody has checked.

## In scope

- **`CONTEXT.md`**: **Link** widened to the two kinds a person hands over — the **export
  link** that downloads the archive and the **sign-in link** that signs the account in,
  spent by driving the source session to it rather than by fetching it — and **Attestation**
  added, for what a vendor requires of a browser to prove it is one.
- **The brief** ([`07-claude-sign-in.md`](../07-claude-sign-in.md)), §72–§80: the goal and
  the diagram, the two commands and their two golden blocks (§73), what the tool never sees
  (§74), the destination needing nothing new (§75), what a cron job loses (§76), the export
  page's real address (§77), what a vendor can make a person's step (§78), the mock (§79),
  and what is deliberately left (§80).
- **[ADR 0008](../../docs/adr/0008-the-sign-in-stays-in-the-browser.md)**: the sign-in
  happens in the browser because `send_magic_link` requires an hCaptcha attestation and a
  cleared Cloudflare cookie. What was considered — Claude as an API source, lifting the
  cookie, clearing the challenge — and the consequences.
- **`specs/README.md`**: the seventh brief in the table, the prose and the layout; the
  Examples row classifying §73's blocks golden; M12 and its chain; the status rows for
  `48`–`52`; the seventh-brief paragraph; and "an eighth starts at §81".

## Out of scope

- The mock's side of it, which is `49`, and the commands, which are `50`.
- `31`'s wrong `export_page_path`, which is `51`.
- `docs/LIMITATIONS.md`'s *password sign-in only*, rewritten by `52` once the thing that
  replaces it exists. A limitation is removed when it stops being true, not when a brief
  says it will.

## Design notes

- **The words come first, not last.** `37`, `41` and `47` were paperwork slices at the end
  of their briefs, because they recorded what had been built. This one is at the start
  because `specs/README.md`'s own working rule puts it there: a term a document needs and
  the glossary lacks is added to `CONTEXT.md` first.
- **This slice was written twice.** Its first version carried an `API source` glossary term,
  an `Ask` widened to cover a sign-in the tool made itself, a `Source session` redefined to
  be a profile *or* a stored credential, and an ADR 0008 titled *Claude is an API source*.
  All of it was withdrawn when the first captured request turned out to carry an hCaptcha
  token: a browserless sign-in is not possible, so none of those words describe anything.
  What is left is the two words that survive contact with the real site.
- **`sign-in link`, and `magic link` is not in the `_Avoid_` list.** The first version put it
  there, on the repository's habit of preferring the plain word. Then the endpoint turned
  out to be `/api/auth/send_magic_link` — it is the vendor's own term, not a synonym
  somebody reached for — so the glossary names it rather than steering away from it.
- **`Attestation` is a glossary word and not an implementation note.** What it *is* changes
  with whatever a vendor deploys; that a step behind one belongs to a person does not, and
  that is the part documents need a word for.
- **ADR 0008 records the withdrawn design rather than hiding it.** The API-source shape was
  decided, written down and reversed four days later. Its appeal survives the refutation,
  so the next person to have the idea should find the reason it fails rather than the idea
  missing.

## Acceptance criteria

- `make check` is green.
- Every word brief 07 uses that names a domain thing is defined in `CONTEXT.md`: no document
  introduces *API source*, *sign-in ask* or *session credential* as a term.
- `specs/README.md`'s working rule says `07` starts at §72 and an eighth starts at §81, and
  the status table has a row for every slice `48`–`52`.
- No file under `src/` or `mock/` changes in this slice.

## Risks

- **A brief written from one captured request.** `send_magic_link` is the only call anyone
  has looked at. It is enough to settle the shape — a browser is required, therefore the
  browser does it — and not enough to say anything about the export ask, which §80 leaves
  open rather than guessing at.
- **An attestation that spreads.** If Claude puts one in front of the export click too, the
  ask becomes a person's step as well, and §78's rule already says what happens then: the
  window opens and the run says so. That is a worse tool to use and still an honest one.
