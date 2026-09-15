# 60 — Download progress

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 03](../03-extraction-and-backup.md) §31 (amended),
[Brief 06](../06-chatgpt-extraction.md) §63 (amended)
**Depends on:** [30](30-store-and-snapshot.md), [45](45-fetch-through-the-session.md)
**Enables:** nothing yet
**Status:** Built

## Goal

Let a person follow a fetch while it runs, and tell them afterwards how long it took. A
real Claude fetch on 2026-09-15 ran for a minute and six seconds and printed nothing until
the block: the link serves a manifest and its parts, each downloaded in turn through the
source session, and the only word per file was a run-log record nobody sees without `-v`.
One line on stdout as each file lands, and the fetch's duration on the block's first line.

## In scope

- **The line** (`extract.DOWNLOADED_LINE`): `downloaded  {name}  {size}`. Lowercase, two
  spaces between columns, no full stop — `18`'s event lines and `verify`'s, because it is
  progress and not the block. `{size}` is orval's `pretty_bytes(n, "ds", precision=1)`:
  `716.0 B`, `23.1 KB`, `41.3 MB`. `{name}` is the file as the snapshot will hold it: the
  manifest fetch names `manifest.json` and then each part as the vendor's manifest names
  it, through `log.safe_token`; a fetch that serves one archive — ChatGPT through the
  session, the browserless `urllib` path — names `export.zip`, `store.ARCHIVE_NAME`. The
  line is printed the moment the file is on disk, before it is read or checked, from the
  same place as the `downloaded` run-log record (`extract._landed`).
- **The block** (`extract.DOWNLOADED`): `Downloaded {size} MB in {took}.` — the brief's
  line with the duration appended. `{took}` is orval's `pretty_duration` over whole seconds
  (`45s`, `1m 6s`, `1h 2m 5s`), the elapsed `time.monotonic` from `fetch`'s first
  statement to the block: browser launch, the sign-in and the wait for the person if
  there is one, every download, the parse and the filing. `--from` prints `Filed <name>.`
  as before; nothing was downloaded and nothing waited on. Golden, brief 03 §31:

  ```text
  Claude extraction — old-personal

  Downloaded 41.3 MB in 1m 6s.
  Conversations: 127     Projects: 4     Memories: 1
  Gaps: 38 files the export does not carry

  Snapshot: ~/.dataporter/store/claude/old-personal/2026-09-12T20-51-07Z

  ```

  and brief 06 §63's `Downloaded 12.4 MB in 1m 6s.` likewise.
- **`--quiet`**: drops the `downloaded` lines and nothing else. `extract` never received
  the flag before — it had no progress — and now takes `quiet` on `extract_command` and
  `fetch`, which `cli.extract` fills from `AppContext.quiet` as `import`, `seeds` and
  `resume` do. The login prompt is a prompt and stays; the block is the result and stays.
- **The clock seam**: `fetch(..., clock=time.monotonic)`, injectable for the reason
  `open_url` is, so a test can hand it `iter((0.0, 66.4)).__next__` and compare the block
  byte for byte. Nothing else reads the clock.
- **Tests** (`tests/test_extract.py`, `tests/test_chatgpt_fetch.py`): the §31 block with
  the line before it and `in 1m 6s.` on it, through the `urllib` path and the session
  path; the manifest walk printing three lines in order, named and sized; `quiet=True`
  leaving the block alone and the lines out; a vendor's name with a newline in it printing
  as one line, on stdout as in the run log.

## Out of scope

- **A size per part on the block, or a count of parts.** The block says what was filed
  and the lines say what arrived; a third accounting was not asked for.
- **A duration per file.** The lines say *that* a file landed and how big it is; which
  one was slow is in the trace's `download` moves, which carry `elapsed_ms` already.
- **A progress bar or a `waiting …` line during one download.** `18` has both for the
  import; a fetch is a handful of files, not a hundred and twenty conversations.

## Design notes

- **The store's name, not the vendor's, for a single archive.** The browser names the
  file by its guid, and `download.Downloaded` deliberately carries the suggested name's
  length and suffix and never the name (§66), which may carry the account's address; §67
  says nothing the tool writes about a ChatGPT account carries one. Stdout is something
  the tool writes — the rehearsal embeds it in its record — so the line says `export.zip`,
  which is true a moment later and is the word the `-v` `filed` line already uses.
  Rejected: printing the vendor's name through `safe_token`, which would need an
  amendment of §66 and §67 for the sake of one line; a nameless `the archive`, which
  gives the single-archive line a shape of its own for no gain.
- **The whole fetch, not the downloads.** `Downloaded … in 1m 6s.` counts from the
  command's start, which includes a browser starting and, interactively, a person signing
  in. That is the number on the shell prompt and the one a person compares it to; a
  download-only figure would be truer to the verb and would answer a question nobody
  asked. The line says `in`, not `download time`, and the slice says what it covers.
- **`pretty_bytes` on the line and not in the block.** `docs/orval-candidates.md` records
  why §31's `Downloaded` stays megabytes to one decimal: the unit is the brief's, and
  `0.0 MB` for a small archive is the golden string. A progress line is not in the brief,
  and a manifest of 245 bytes reading `0.0 MB` three times would say nothing; the line
  picks a unit so that it says something.
- **Whole seconds.** `pretty_duration(66.4)` spells `1m 6s 400ms`; `round` first, because
  a person reading a minute does not want the milliseconds and the trace has them.
- **The brief is amended rather than left.** §31's block and §63's are golden strings the
  README names, and the README's rule is that a slice may not quietly contradict one.
  The block's first line changed, so both briefs carry the new bytes and an amendment
  note under the block naming this slice, as §16 carries `19`'s.

## Acceptance criteria

- `make check-all` green on the coverage gate. (The macOS-only
  `test_the_child_really_sees_only_that` failure is pre-existing.)
- A fetch through `urllib` and a fetch through the session each print one
  `downloaded  export.zip  …` line and then the block, `Downloaded … in 1m 6s.` under a
  clock that says so; the bytes are compared, not searched.
- `index_and_files` prints `manifest.json` and then each part, in the order they landed,
  each with its size.
- `quiet=True`: no `downloaded` line, the block unchanged.
- The link is in no line the fetch prints — the existing tests grep the new line too.
- A real `dataporter extract --source claude --account <label> --link <url>` prints a
  line per file as it lands and the duration on the block. *unverified*

## Risks

- **orval's spelling is the golden string's.** `pretty_bytes` and `pretty_duration` are
  the dependency's, and a release that changed `1m 6s` to `1m6s` would move the block.
  The byte tests catch it, and `pyproject.toml` pins the floor; the answer then is to pin
  the ceiling or to spell the duration here.
- **A prompt between the lines.** Interactively, `Log in to Claude in the browser window
  that just opened.` is printed to stdout before any download and stays under `-q`; the
  first `downloaded` line follows it. A reader of a captured stdout sees prompt, lines,
  block, in that order, which is the order things happened.
