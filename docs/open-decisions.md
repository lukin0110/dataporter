# Open decisions

**Kind:** Running record of decisions nobody has made yet. Not a backlog of work — a
list of questions where more than one answer is defensible and picking one is somebody's
call rather than a slice's.

Each entry says what is at stake, what the options are, what happens while nobody
decides, and **what settles it**: an ADR, an amendment to a brief, an edit to
[`CONTEXT.md`](../CONTEXT.md), or a line in an implementation spec. An entry leaves this
file when one of those lands, and the entry says which.

Entries are cited by their identifier (`D1`), the way
[`orval-candidates.md`](orval-candidates.md)'s are, so a code comment or a spec line can
point at the question it is waiting on.

Everything below was read off the files named, at `79746c8`. A line number is where it
was; the claim is what it said.

| | Question | Raised by | Blocking? |
| --- | --- | --- | --- |
| [D1](#d1--the-glossary-against-the-code) | `archive`, `snapshot` and `URL`: three words the glossary forbids and the code uses | `/code-review` of `30`–`31` | no |
| [D2](#d2--what-timeoutsask_s-covers) | Does `timeouts.ask_s` bound the poll, or the whole ask? | `/code-review` of `31` | no |
| [D3](#d3--33s-workspace-beside-the-snapshot) | §33 says a snapshot's import writes its workspace beside it; `30` refuses to | `/code-review` of `30` | no |
| [D4](#d4--are-brief-03s-blocks-golden) | Brief `03`'s output blocks were never classified golden or illustrative | `/code-review` of `30`–`31` | no |

None of the four blocks a merge: each is a question about words, budgets or paperwork,
and the code does something defensible today. They are here so that "defensible today"
does not quietly become "decided".

## D1 — The glossary against the code

[`CONTEXT.md`](../CONTEXT.md) defines **Export** and **Store** with `_Avoid_: archive`,
**Probe** with `_Avoid_: snapshot`, and **Link** with `_Avoid_: URL`. The working rule in
[`specs/README.md`](../specs/README.md) is "Words come from `CONTEXT.md`. A term a
document needs and the glossary lacks is added there first." Three sets of names break
it:

| Word | Where | Whose |
| --- | --- | --- |
| `archive` | `store.py:72` `ARCHIVE_NAME`, `:172` `class Archive`, `:220` `Snapshot.archive`, `:290` "A verified archive, ready to be filed", `:329` `file_archive`; `extract.py:123` `NOT_AN_ARCHIVE`, `:124` `NOT_A_ZIP_FILE`; [`adr/0005`](adr/0005-snapshots-are-vendor-native.md) "the vendor's own archive" | `30` |
| `snapshot` (of a stale target list) | `cdp.py:369`, `helpers.py:21`, `helpers.py:480` | `07`, `08` |
| `URL` | `extract.py:115` `LINK_NOT_HTTPS`, `cli.py:647` `--link metavar="URL"` | `30` |

The `snapshot` ones are the interesting half: they were written before `30` made
*Snapshot* a domain term, and they are correct English about a CDP target list. The
collision arrived with the glossary entry, not with the code.

**Options.**

1. **Extend the glossary.** Add **Archive** — the vendor's own file, as it sits inside a
   snapshot — which is a real concept the glossary lacks: "the export inside the
   snapshot" is not the same thing as either. Then scope the two `_Avoid_` lists to say
   *archive* is not a synonym for an export or for a store, rather than a forbidden word.
   Cheapest, and it makes `adr/0005`'s own sentence legal.
2. **Rename.** `ARCHIVE_NAME` → `EXPORT_FILENAME`, `Archive` → `ExportFile`,
   `file_archive` → `file_export`, and the two operator-facing strings. A sweep across
   `store.py`, `extract.py`, `cli.py`, the ADR and the tests that name them; `snapshot.json`'s
   `archive` key is written to disk, so a manifest version would have to move with it.
3. **Nothing, deliberately** — record here that the glossary's `_Avoid_` lists are advice
   about prose and not about identifiers. That is a decision too, and it would make the
   working rule weaker than it reads.

While nobody decides, the code stays as it is and the review finds it again.

**Settled by:** an edit to `CONTEXT.md` (option 1 or 3), or a slice (option 2).

## D2 — What `timeouts.ask_s` covers

`31`'s spec, step 5: "poll `EXPORT_PAGE_JS` for `requested` up to `timeouts.ask_s`". The
code sets one deadline at `export_page.py:252`, before `_bring_to_export_page`, so
arriving at the page and waiting for the page's answer share one budget: a slow
navigation shortens the poll.

That was deliberate — one number for "how long an ask may take" is easier to reason about
than two, and a navigation that never lands is not a case the poll should still be paying
for — but it is not what the spec says, and nothing wrote the reason down until this
file.

**Options.**

1. **Amend `31`.** One sentence in *In scope* saying the deadline covers the whole of
   `request_export`, navigation included. No code changes.
2. **Split the budget.** A separate, shorter wait for the navigation (the page load is a
   page load; `timeouts.verify_s` is the existing precedent at 30 s), leaving `ask_s` for
   the poll alone, as the spec reads. Two numbers, and the spec stands.

**Settled by:** a line in [`specs/impl/31-source-session-and-ask.md`](../specs/impl/31-source-session-and-ask.md),
with or without the code change.

## D3 — §33's "workspace beside the snapshot"

Brief `03` §33: "An import from a snapshot writes its workspace beside the snapshot, as
it does beside an export today." `30` does the opposite — `store.refuse_workspace_inside`
(`store.py:570`, called from `importer` and `seed.py:278`) refuses a workspace *inside* a
snapshot, because a snapshot is finished by definition and `state.json` and a signed-in
browser profile are exactly what must never appear in one.

The reasoning is in `30`'s design notes and is convincing. The problem is procedural: the
working rule says a slice "may not quietly contradict the brief; that requires an
amendment", and the brief is unamended. §33 still tells a reader something the tool
refuses to do.

**Options.**

1. **Amend §33** to say a snapshot's import writes its workspace anywhere but inside the
   snapshot, naming `30` as the slice that found it. The brief is stable, not immutable —
   amending it explicitly is the rule, not the exception.
2. **Drop the guard** and let §33 stand as written. Nobody has argued for this.

**Settled by:** an amendment to [`specs/03-extraction-and-backup.md`](../specs/03-extraction-and-backup.md) §33.

## D4 — Are brief `03`'s blocks golden?

[`specs/README.md`](../specs/README.md)'s "Examples" row says the output blocks in §9,
§10 and §16 are golden strings and brief `02`'s are illustrative. Brief `03` is not
classified at all — and meanwhile `30` and `31` both pin its §31 and §33 blocks as golden
and compare bytes against them (`tests/test_extract.py`, `tests/test_ask.py`,
`tests/test_store.py`).

So the practice has already answered the question and the table has not. A later brief
will copy whatever that row says.

**Options.** Say brief `03`'s blocks are golden (what the tests already assume), or say
they are illustrative and loosen three test modules. The first is one edit; the second
undoes work for nothing.

**Settled by:** the Examples row of `specs/README.md`. While it says nothing, the tests
are the only statement of it.

## Review findings not acted on

Not decisions so much as judgement calls with nobody assigned. From the same
`/code-review`, against `67b5613...79746c8`; each is a smell, not a defect, and none
changes behaviour.

| Finding | Where |
| --- | --- |
| Three spellings of one `O_EXCL` open: `extract.py:255` and `:553` against `store.py:516` `_open_exclusive`, with `0o600` written twice beside `store.py:504` `SNAPSHOT_MODE` | `30`, `31` |
| `extract.py:638` `_digest` re-implements the chunked hash inside `store.py:479` `_copy`, and imports `store.COPY_CHUNK` to do it | `30` |
| `extract.py:684` `_display` re-joins `root / source / account / stamp`, which is `Store.directory` (`store.py:321`) | `30` |
| `export_page.py` `_wait_until` is a third deadline-and-poll loop beside `session.py:115` and `helpers.py:656` | `31` |
| `store.py:624` `list_command` is the only operation not named after its command (`snapshots`) | `30` |
| `cli.py` `Account` and `AccountOption` differ only in whether the option is required, and neither name says so | `31` |
| `(source, account, stamp)` travel together through `Store.directory`, `Filing`, `Snapshot`, `SnapshotRow` and `_display` — a type wanting to be born | `30` |

The first three are the same shape: `extract` re-derives what `store` already knows. If
any of these is worth doing, it is one tidying slice and not seven edits.
