# Extraction 01 — the first ask

**Kind:** Experiment record — what was measured, not what was designed. Produced by
[`31`](../specs/impl/31-source-session-and-ask.md).
**Answers:** [§39](../specs/03-extraction-and-backup.md)'s questions 1, 2 and 5, with
numbers.
**Extraction run:** none.
**Source account:** unknown. **Tool version:** unknown. **Chrome version:** unknown.

Every number below carries a mark: `*measured on <date>*` when a run produced it,
`*not yet run*` when none has. It is the discipline
[`experiment-01.md`](experiment-01.md) follows and the one
[`10`](../specs/impl/10-attach-spike.md)'s documents follow, for the same reason: a
question nobody answered has to look different from one answered badly.

§39 asks six questions. Three of them are this document's — the ones the *ask* answers —
and three belong to the fetch and to import, which is where their evidence is:

| § | Question | Answered here | Where the rest live |
| --- | --- | --- | --- |
| 1 | Does the ask work, in each mode, and does an email arrive? | yes | — |
| 2 | Does the archive the tool fetches match, byte for byte, the one a person downloads? | yes | — |
| 3 | Does an import of the snapshot produce the same dry run as an import of the archive? | no | a dry run of each, compared by hand |
| 4 | What does the account hold that the archive does not? | no | `snapshot.json`'s `gaps` |
| 5 | How long does the link live, and what does the tool say when it has died? | yes | — |
| 6 | Does a second extraction produce a second snapshot and leave the first byte-identical? | no | the store, and `snapshots` |

Nothing in this file may carry an account identifier, an email address or a line of a
conversation (§38). The account is named by its label; the link is named by nothing at
all, because it is a credential to the whole archive for as long as it lives.

## How it is run

```text
dataporter login --account spike           # the source account, its own profile
dataporter extract --account spike         # the ask
#   … the vendor emails a link, to a person …
dataporter extract --account spike --link '<url>'
dataporter snapshots
```

The source account is a throwaway one with something in it, and nothing else (§17). The
same trip is what turns the four export rows of [`claude-ui-map.md`](claude-ui-map.md)
from `*unknown*` into observations; [`spike/README.md`](spike/) has the steps.

## Questions

### Q1 — Does the ask work, in each mode, and does an email arrive?

**Measure:** asks that ended `Export requested` ÷ asks made, run attended and again with
`--non-interactive`, and whether an email arrived for each.
**Evidence:** the exit code, `ask.json` in the account home, the two records in its
`logs/actions.jsonl`, and a person's inbox.
**Number:** not yet run. *not yet run*

### Q2 — Does the fetched archive match the one a person downloads?

**Measure:** the SHA-256 in `snapshot.json` against `sha256sum` of the same link
downloaded by hand in a browser.
**Evidence:** `snapshot.json` (`archive.sha256`, `archive.bytes`) and the hand download.
**Number:** not yet run. *not yet run*

### Q5 — How long does the link live, and what does the tool say when it has died?

**Measure:** hours between the email and the first fetch that is refused, and the exact
line the tool prints then.
**Evidence:** `ask.json`'s `asked_at`, the email's own timestamp, and the stderr of the
late fetch — which is expected to be `link refused: HTTP <code>`, exit `2`, with the ask
left open to try again.
**Number:** not yet run. *not yet run*

## What the page did

One row per thing the ask met, so that the four `*unknown*` rows of the UI map are
corrected from something written down rather than from memory.

| Observation | What was seen | Mark |
| --- | --- | --- |
| the path where the export is asked for | — | *not yet run* |
| how many presses one ask took | — | *not yet run* |
| how the page said the request was accepted | — | *not yet run* |
| how long that took | — | *not yet run* |
| a second ask while one was open, at the vendor's end | — | *not yet run* |

## What was not observed

An ask against one account is not evidence about two, and one vendor is not evidence
about sources in general. Until a run fills the tables above, everything this tool does
on the export page rests on the placeholders in
[`browser/export_page.py`](../src/dataporter/browser/export_page.py) — which is why `31`
is `Built` and not `Done`, and why `docs/LIMITATIONS.md` carries the rate limit on asking
as `*unknown*`.
