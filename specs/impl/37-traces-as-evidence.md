# 37 — Traces as evidence

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 04](../04-trace.md) §49, §50 (the mock as a reader)
**Depends on:** [36](36-rehearsal-traces.md), [10](10-attach-spike.md) (the UI map),
[26](26-mock-claude.md) (the mock's citations)
**Enables:** the first `*observed on <date>*` in `docs/claude-ui-map.md`
**Status:** Not started

## Goal

The paperwork that lets a trace of a real run do what it is for: a place in the repository
for such a trace, the one-clause widening of the UI map's rule that lets a person cite it,
a page in the mock's README that says how the mock reads one without importing anything,
and a test that keeps every committed trace clean and every citation pointing at a file.
No tool code changes.

## In scope

- **The evidence directory** (`docs/spike/traces/README.md`, new; `docs/spike/README.md`
  gains a row): what may be committed here — a trace of a run against claude.ai or a
  source's real site, read end to end by the person committing it, named
  `<command>-<YYYY-MM-DD>.jsonl` (`login-2026-09-20.jsonl`), never edited after; what
  may not — a rehearsal's trace (the mock's own baseline, kept under the rehearsal's
  root and not here), a trace with an `end` line missing its reason in the commit
  message, a trace anyone has trimmed by hand. How a citation is spelled:
  `docs/spike/traces/login-2026-09-20.jsonl:14`, file and line.
- **The rule** (`docs/claude-ui-map.md`, the header paragraph and the line above the
  table): after "Only a person watching claude.ai does that." add: "A person who has
  read a trace of a run against claude.ai (brief `04`, §49) may mark a row from it,
  citing the trace by file and line; the trace is the watching, kept." The *Observed
  signal* column of a row marked from a trace holds the citation and the sketch's own
  words — the role and the label — and nothing paraphrased.
- **The mock as a reader** (`mock/README.md`, a section *Reading a trace*): the four
  kinds of line and what each means to the mock, in the mock's own words; that a
  `sketch`'s `controls` are the labels the mock's pages should carry and its
  `selectors` the counts its markup should produce; that `request` and `response` lines
  are the traffic its page script should make and the pace it should make it at; that
  `certificate` is how a reader tells its own traces from the site's; and that it
  imports nothing — the shape is read from brief `04` and the files
  ([ADR 0003](../../docs/adr/0003-the-mock-is-a-separate-project.md)).
  `mock/src/claudemock/uimap.py`'s docstring gains one sentence: a row's
  `WHAT_THE_MOCK_DOES` line may name the trace and line it was corrected from.
- **Tests**:
  - `tests/test_spike_docs.py` — every citation matching `docs/spike/traces/<name>.jsonl`
    in `docs/claude-ui-map.md` names a file that exists, and its `:N` a line the file
    has; every `docs/spike/traces/*.jsonl` begins with a line whose first key is
    `"trace":1` and no line of it carries a forbidden field name at any depth
    (`log.forbidden_names` over each parsed line) — the guard, once more, at commit
    time; and a row marked `*observed on <date>*` in the UI map whose *Observed signal*
    cites no screenshot, no note and no trace is a failure.
  - `mock/tests/test_uimap.py` — unchanged in what it enforces; a citation in
    `WHAT_THE_MOCK_DOES` that names a `docs/spike/traces/` file is allowed and not
    checked from the mock's side (no import, no path into the tool's tree).
- **Docs**: the three above, and `README.md`'s trace paragraph gains the sentence that
  a real trace may be committed and cited.

## Out of scope

- The first real trace itself, and the first row marked from it: a person's trip to a
  throwaway account, `docs/spike/README.md`'s steps, with `33`–`35` built. This slice is
  the paperwork it needs and is `Done` when it has been used once.
- A mock that reads traces directly: brief §51.
- Correcting the mock's pages from a trace: that is Claude Code's job, per row, with
  the mock's own tests and `test_uimap.py` holding the line; not a slice.

## Design notes

- **The trace is the watching, kept.** §21's rule exists so that a mock run cannot
  launder a guess into an observation, and it still cannot: a rehearsal's trace shows
  the mock's certificate and stays out of `docs/spike/traces/`, and the test refuses a
  row marked with no evidence behind it. What changes is only that a person may watch
  through the tool's record rather than over its shoulder. Rejected: keeping the rule
  verbatim (the trace would then be evidence nobody may use); letting the runner mark
  rows (the door ADR 0006 refuses).
- **Committed traces are guarded again at test time.** The tool's guard runs when the
  trace is written; the test runs when the trace is committed, on the bytes in the
  repository, so a trace produced by an older build or edited by hand is caught by the
  same list of names. Rejected: trusting the writer (a guard that runs once is a
  promise; one that runs in CI is a check).
- **The mock's README is the mock's reader.** ADR 0003 forbids an import across the
  line; a document is not an import, and a reader that has to be told what a `sketch`
  is should be told in the project that reads it. Rejected: a shared `trace-format.md`
  in a third place (two projects, one brief, and the brief is the format).

## Acceptance criteria

- `make check` is green, and `tests/test_spike_docs.py` fails when a citation names a
  missing file, when a committed trace holds a forbidden key, or when an `*observed*`
  row cites nothing.
- `docs/claude-ui-map.md`'s rule reads as above and `mock/README.md` has *Reading a
  trace*.
- `docs/spike/traces/README.md` exists and `docs/spike/README.md`'s table has its row.
- *(Live: it needs a real account and a real site.)* One trace of `dataporter login`
  against claude.ai is committed under `docs/spike/traces/`, and at least one row of the
  UI map — `signed out` is the likely first — reads `*observed on <date>*` with the
  trace as its citation. That is what turns this slice `Done`.

## Risks

- **A trace read too quickly.** The guard cannot catch content inside a legal label. The
  committing person reads the file; `34`'s first risk says what to look for (a control
  named after a conversation). A second reader on the pull request is the second check.
- **A row marked from a trace of the wrong site.** A trace of the mock committed by
  mistake has `claude-mock` in its certificate line; the test could refuse that issuer
  by name, and does not, because the tool's tree must not know the mock's name either
  (ADR 0001). The README's rule and the reviewer are the check.
