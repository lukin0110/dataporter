# Section numbers continue across briefs

Brief `01`'s sections §1–§19 are cited as `§N` throughout the slices, the documents and
the tests. When a second brief was written we decided that it continues the numbering —
`02` starts at §20 — so that `§N` stays one global identifier and every `Implements: §N`
line keeps its meaning. Briefs are numbered by file; sections are numbered across the set.
A third brief starts where `02` ends.

## Considered

- Restarting each brief at §1 and citing `02§N`. Every citation becomes two-part, and the
  sentence in `specs/README.md` that says section numbers are permanent identifiers stops
  being true.
