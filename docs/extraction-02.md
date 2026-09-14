# Extraction 02 — the first ask of a ChatGPT account

**Kind:** Experiment record — what was measured, not what was designed. Produced by
[`47`](../specs/impl/47-paperwork.md), for
[brief 06](../specs/06-chatgpt-extraction.md) §69.
**Answers:** [§39](../specs/03-extraction-and-backup.md)'s questions 1, 2 and 5, and
[§69](../specs/06-chatgpt-extraction.md)'s questions 7 to 13, with numbers.
**Extraction run:** none.
**Source account:** unknown. **Tool version:** unknown. **Chrome version:** unknown.

Every number below carries a mark: `*measured on <date>*` when a run produced it,
`*not yet run*` when none has. It is the discipline
[`extraction-01.md`](extraction-01.md) follows for Claude, and for the same reason: a
question nobody answered has to look different from one answered badly. The extraction
rehearsal ([`rehearsal-03.md`](rehearsal-03.md)) is not a run of this document: a mock
answers none of these questions about the site (§56).

§39 asks six questions and §69 seven more. Ten of them are this document's; three belong
to the fetch's arithmetic and to import, which is where their evidence is:

| § | Question | Answered here | Where the rest live |
| --- | --- | --- | --- |
| 1 | Does the ask work, in each mode, and does an email or a text arrive? | yes | — |
| 2 | Does the archive the tool fetches match, byte for byte, the one a person downloads? | yes | — |
| 3 | Does an import of the snapshot produce the same dry run as an import of the archive? | no | no importer yet (ADR 0005) |
| 4 | What does the account hold that the archive does not? | no | `snapshot.json`'s `gaps`, and `docs/chatgpt-export-format.md` once refreshed |
| 5 | How long does the link live, and what does the tool say when it has died? | yes | — |
| 6 | Does a second extraction produce a second snapshot and leave the first byte-identical? | no | the store, and `snapshots`; rehearsed in `rehearsal-03.md` |
| 7 | Does the real link need the session — would a browserless fetch have been refused? | yes | — |
| 8 | What is the redirect chain from the emailed link to the bytes, host by host? | yes | — |
| 9 | What is the zip's file name, by length and suffix? | yes | — |
| 10 | Where is the Data controls page, and is it the shape the mock serves? | yes | — |
| 11 | What does the auth host show, step by step, and does the walk get through it? | yes | — |
| 12 | How long did the export take to arrive, against the documented "up to 7 days"? | yes | — |
| 13 | What does the site show when an export is already requested, and when a link has expired? | yes | — |

Nothing in this file may carry an account identifier, an email address, a line of a
conversation or a link (§38, §66, §70). The account is named by its label; the link is
named by nothing at all, because it is a credential to the whole archive for as long as it
lives.

## How it is run

```text
dataporter login --source chatgpt --account spike       # the source account, two hosts
dataporter extract --source chatgpt --account spike     # the ask
#   … the vendor emails or texts a link, to a person …
dataporter extract --source chatgpt --account spike --link '<url>'   # the fetch, in the browser
dataporter snapshots
```

The source account is a throwaway one with something in it — a few chats, one with a
file — and nothing else (§17). Attended first, then again with `--non-interactive` and
the credentials in the environment. The same trip is what turns the sign-in and export
rows of [`chatgpt-ui-map.md`](chatgpt-ui-map.md) from `*reported*` and `*unknown*` into
observations, and what refreshes [`chatgpt-export-format.md`](chatgpt-export-format.md)
from a real archive.

## Questions

### Q1 — Does the ask work, in each mode, and does an email or a text arrive?

**Measure:** asks that ended `Export requested` ÷ asks made, run attended and again with
`--non-interactive`, and whether a message arrived for each, and by which channel.
**Evidence:** the exit code, `ask.json` in the account home, the moves in the trace and
the records in its `logs/actions.jsonl`, and a person's inbox or phone.
**Number:** not yet run. *not yet run*

### Q2 — Does the fetched archive match the one a person downloads?

**Measure:** the SHA-256 in `snapshot.json` against `sha256sum` of the same link opened by
hand in the signed-in browser.
**Evidence:** `snapshot.json` (`archive.sha256`, `archive.bytes`) and the hand download.
**Number:** not yet run. *not yet run*

### Q5 — How long does the link live, and what does the tool say when it has died?

**Measure:** hours between the message and the first fetch that is refused, and the exact
line the tool prints then.
**Evidence:** `ask.json`'s `asked_at`, the message's own timestamp, and the stderr of the
late fetch — expected to be `link refused: HTTP <code>` or `the link led to a page`, exit
`2`, with the ask left open to try again.
**Number:** not yet run. *not yet run*

### Q7 — Does the real link need the session?

**Measure:** the status a browserless request for the same link is answered with, made
by hand with no cookie, against the status the signed-in tab's document response
carried in the trace.
**Evidence:** the trace's `response` line for the fetch, and the hand request's status.
**Number:** not yet run. *not yet run*

### Q8 — What is the redirect chain from the link to the bytes?

**Measure:** the hosts the fetch's trace records between the navigation to the link and
the download's move, in order.
**Evidence:** the `navigation` and `request` lines of the fetch's trace, each a host and
`<link>` (§66).
**Number:** not yet run. *not yet run*

### Q9 — What is the zip's file name, by length and suffix?

**Measure:** `filename_chars` and `suffix` on the fetch's `download` move.
**Evidence:** the trace.
**Number:** not yet run. *not yet run*

### Q10 — Where is the Data controls page, and is it the shape the mock serves?

**Measure:** whether the tool's navigation to `/settings/data-controls` arrived on a page
with the three controls, or where it landed instead; whether the page is a document or a
dialog.
**Evidence:** the ask's trace: the `navigation` line's path, the sketch of the page, and
the `export-button` and `export-confirm` moves or their absence.
**Number:** not yet run. *not yet run*

### Q11 — What does the auth host show, and does the walk get through it?

**Measure:** the hosts and paths of the sign-in's navigations and the `login-button`,
`email-step` and `password-step` moves, attended and unattended; where the unattended walk
stopped, if it did, and with which reason.
**Evidence:** the `login` trace, and the exit `3` line if any.
**Number:** not yet run. *not yet run*

### Q12 — How long did the export take to arrive?

**Measure:** hours between `ask.json`'s `asked_at` and the message's timestamp.
**Evidence:** `ask.json`, and the message.
**Number:** not yet run. *not yet run*

### Q13 — What does the site show when an export is already requested, and when a link has expired?

**Measure:** the ask's exit code and line when asked again while one is processing, and
the sketch of the page then; the fetch's line for a link past its 24 hours.
**Evidence:** the second ask's trace and stderr; the late fetch's stderr.
**Number:** not yet run. *not yet run*

## What the page did

One row per thing the run met, so that the map's rows are corrected from something written
down rather than from memory.

| Observation | What was seen | Mark |
| --- | --- | --- |
| the landing page's way in | — | *not yet run* |
| the auth host's screens, in order | — | *not yet run* |
| the path where the export is asked for | — | *not yet run* |
| how many presses one ask took | — | *not yet run* |
| how the page said the request was accepted | — | *not yet run* |
| the hosts between the link and the bytes | — | *not yet run* |
| a second ask while one was open, at the vendor's end | — | *not yet run* |

## What was not observed

An ask against one account is not evidence about two. Until a run fills the tables above,
everything this tool does on chatgpt.com rests on the mock's shape of the map's
*reported* and *unknown* rows — which is why `docs/LIMITATIONS.md` carries the auth
host's screens, the Data controls path, the zip's name and whether the link needs the
session at all as `*unknown*`, and why nothing here turns a row *observed*.
