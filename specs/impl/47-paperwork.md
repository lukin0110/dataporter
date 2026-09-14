# 47 — The paperwork

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 06](../06-chatgpt-extraction.md) §69, §70; the amendment §63 makes
to brief 03 §35; the glossary edits of §60, §63 and §68
**Depends on:** [46](46-extraction-rehearsal.md)
**Enables:** `nothing yet` — the first run against chatgpt.com, which no slice can make
**Status:** Done

## Goal

Every document brief 06 changes, changed: the amendment, the glossary, the index, the
open decisions it settles, the limitations it adds, the record its first real run will
fill, the orval pass, and the sentences in four files that said nothing drives the mock
chatgpt.com. No code.

## In scope

- **The brief** ([`06-chatgpt-extraction.md`](../06-chatgpt-extraction.md)), written
  before `42` and amended once by `45`: §66 says the download is recorded as a move of
  the tool's own rather than as an observation, which is what it is.
- **Brief 03 §35**, amended in place with one clause: true of Claude; a source whose
  vendor requires the download to be made signed in fetches through the source session,
  slices `44` and `45`.
- **`CONTEXT.md`** (landed with the brief): **Archive** and **Fetch** added, `archive`
  dropped from the `_Avoid_` lists of **Export** and **Store**, **Rehearsal** widened to
  an extraction's protocol, **Surface**'s extraction sentence widened to every host a
  sign-in passes through, and the opening line naming a ChatGPT account.
- **`specs/README.md`**: the sixth brief in the table, the prose and the layout; the
  Examples row classifying brief 03's and brief 06's blocks golden (D4); M11 and its
  chain; the status rows; the sixth-brief paragraph saying what claims what; "a seventh
  starts at §72".
- **`docs/open-decisions.md`**: D1 and D4 moved to *Findings assessed and closed* with
  what settled each; the `_digest` finding notes its second caller.
- **`docs/LIMITATIONS.md`**: a section *The ChatGPT source (`43`–`45`)* — the auth host's
  screens, the Data controls path, whether the real link needs the session, the zip's
  name, the expiry and "already requested", composer drift, and the mock's files as gaps,
  each *unknown*; the refusal by `import` and the fetch opening a browser, each *by
  construction*.
- **`docs/extraction-02.md`**: the record of the first ask of a real ChatGPT account, in
  `extraction-01.md`'s discipline — §39's questions 1, 2 and 5 and §69's 7 to 13, each
  with a measure, an evidence line and one `*not yet run*` number; the table saying which
  three of the thirteen are somebody else's; a *What the page did* table for the map's
  rows; and `tests/test_extraction_doc.py` parametrised over both records, with one more
  check that the ChatGPT record names its source and carries no link.
- **`docs/orval-candidates.md`**, the third pass: `deep_get` adopted in
  `export/chatgpt.py`; `DOWNLOADED` → `pretty_bytes` a deliberate non-swap, verified by
  running both; C5 `unique` gains its fourth caller; C3 and C4 note no new caller and why.
- **`docs/chatgpt-ui-map.md`**'s footer names where the tool spells its selectors;
  **`docs/chatgpt-export-format.md`** names the reader that reads it and the slice to open
  after `40` when a real export is read; **`mock/README.md`** and **`README.md`** no longer
  say nothing drives the mock chatgpt.com — the README's *Backing an account up* gains
  the ChatGPT commands and what the fetch does differently, and *Rehearsing it* gains
  `--protocol extraction`.

## Out of scope

- The first run against chatgpt.com: a person's trip to a throwaway account, which fills
  `docs/extraction-02.md` and is what marks the map's rows *observed*.
- Reading a real ChatGPT export, which refreshes `docs/chatgpt-export-format.md` and then
  `43`.
- Filing the orval candidates upstream: the document is the deliverable.

## Design notes

- **A paperwork slice, as `37` and `41` were**, rather than each edit folded into the
  slice that caused it: the edits cross eleven documents and are reviewable as one
  change, and a slice that lands its code and its README in one pull request is a slice
  whose README is reviewed by nobody.
- **`extraction-02.md` mirrors `extraction-01.md`'s shape exactly**, down to the doc
  test, so that a person filling one knows how to fill the other and the build keeps
  both from looking finished while saying nothing.
- **D1 settled by option 1**, the glossary extended rather than the code renamed: the
  concept was real — the export as a file, kept byte for byte — and `snapshot.json`'s
  `archive` key is on disk in every store.

## Acceptance criteria

- `make check` is green: the two doc tests pass over both records, the spike-docs test
  accepts every new limitation's mark, and no test names the sentences this slice
  removed.
- `grep -rn "drives it yet\|nothing in the tool drives" README.md mock/README.md
  docs specs/impl` finds nothing; brief `05` keeps its sentence, since a brief is a record
  of intent and is never edited in passing.
- `docs/extraction-02.md` says `**Extraction run:** none.` and every number in it is
  `*not yet run*`.

## Risks

- **A document that says `Done` about a run nobody made.** Every claim about chatgpt.com
  in these documents is marked *reported*, *unknown* or *not yet run*; the one thing
  marked measured is the rehearsal, which is about the mock.
