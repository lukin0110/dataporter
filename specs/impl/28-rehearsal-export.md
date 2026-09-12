# 28 — The rehearsal export

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 02](../02-claude-mock.md) §24
**Depends on:** [02](02-export-model.md), [03](03-classification.md),
[04](04-seed-generation.md)
**Enables:** [29](29-rehearsal.md)
**Status:** Done

## Goal

A purpose-built export a rehearsal migrates, generated character by character, in
which no real conversation appears. It covers the five kinds §18 names and as
many of `20`'s selection categories as can be built, and it is sized so that a
complete run in one mode takes minutes at rehearsal pacing.

## In scope

`rehearsal/export.py`, and `python -m rehearsal.export <root>`, which writes
`<root>/export/` and `<root>/attachments/`:

| short id | what it is | the category it covers |
| --- | --- | --- |
| `a1000001` | a short conversation | the common case |
| `b2000002` | 22 turns, ~69,000 rendered characters | **two parts** at the tool's default 50,000-character budget |
| `c3000003` | fenced code blocks | code through a composer |
| `d4000004` | three attachments | §14's three classes, all in one conversation |
| `e5000005` | 40 turns | a long transcript |
| `f6000006` | no messages | the **unsupported** branch (`empty_conversation`) |

- `MIGRATABLE` names the five a rehearsal expects to end `completed`; §25's
  100 % is over exactly that tuple.
- The attachments are `rehearsal-notes.txt` (inlined by the export, class 1),
  `rehearsal-chart.png` (bytes written to `<root>/attachments/<uuid>/`, class 2)
  and `rehearsal-archive.zip` (a type `accepted_types` does not carry, class 3).
- The bytes live **beside** the export rather than in it, because that is what
  class 2 is: the export names a file it does not contain.
- The long conversation is expressed as "how much text", not "how many parts": if
  `10` moves `seed.max_chars`, this export stops being two parts and a test says
  so rather than a rehearsal quietly passing without exercising the path.

## Out of scope

- Anything read from a real export. §23: no real account, no real export, ever.
- Branches, thinking blocks, tool calls and the other things `03` counts as
  limitations. The one limitation a rehearsal does provoke is
  `timestamps_not_preserved`, which every conversation carries.
- An export large enough to measure throughput. That is the full run's subject.

## Design notes

- **Its content is the rehearsal itself.** The turns talk about seeds,
  acknowledgements and the composer. It is the one subject that cannot leak
  anything, and it makes a transcript read on a mock page obviously synthetic.
- **`f6000006` is empty rather than unreadable.** `03`'s `empty_conversation` is
  the one unsupported reason that needs nothing but an absence, so the export
  does not have to carry a broken message to reach the branch.
- **The class 2 file is not a real PNG.** Nothing renders it: the mock takes the
  bytes and counts them, and the tool checks that a chip carrying the name
  appeared. The PNG signature is there so a person can see what it stands for.

## Acceptance criteria

- `inspect` reports 6 found, 5 migratable, 1 unsupported (`empty_conversation`),
  and — with `--attachments-dir` — 1 inline, 1 upload, 1 unsupported.
- `seeds` writes two parts for `b2000002` and one for each of the others.
- The same command run twice produces byte-identical files.

## Risks

- **It is the only export a rehearsal has ever migrated.** Anything about real
  exports that `02` gets wrong, this cannot find. `docs/export-format.md` and
  `10`'s open question about attachment bytes are where that lives.
