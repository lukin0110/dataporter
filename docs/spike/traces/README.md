# Traces of real runs

The traces a run against claude.ai — or, later, a source's real site — left, kept as
evidence (brief [`04`](../../../specs/04-trace.md) §49). A trace is what the browser went
through, in outline: the moves the helpers made, what the page did in between, and a
sketch of what it showed — its controls by role and label, everything else by shape.
It carries no message, no title, no address, no query value and no credential by
construction (§46), and the tool's guard refuses any line that would.

## What may be committed here

- A trace of `login`, `import`, `verify`, `followup`, `doctor` or `extract` run against
  the real site, copied from `logs/trace-<ts>.jsonl` in the workspace or the account
  home, **read end to end by the person committing it**. The reading is a check, not a
  redaction: a trace that turns out to carry something it should not is a bug in the
  tool, fixed there first, and the trace is not committed until it is.
- Named `<command>-<YYYY-MM-DD>.jsonl` — `login-2026-09-20.jsonl` — and never edited
  after. A trace is a record of what was; a trimmed one is a different document.
- With the reason for a missing `end` line in the commit message, when there is one: a
  run that was killed leaves no last line, and that is worth a sentence.

## What may not

- A rehearsal's trace. It is the mock's own baseline, and it lives under the rehearsal's
  root and in `docs/rehearsal-NN.md`'s table; a trace of the mock committed here would
  correct the mock against itself.
- A trace anyone has trimmed, reordered or hand-edited.
- Anything from an account that is not a throwaway (`spike/README.md`'s rule).

## How a trace is cited

By file and line: `docs/spike/traces/login-2026-09-20.jsonl:14`. A row of
[`claude-ui-map.md`](../../claude-ui-map.md) marked `*observed on <date>*` from a trace
carries the citation in its *Observed signal* column, with the sketch's own words — the
role and the label — and nothing paraphrased. The mock's citations
(`mock/src/claudemock/uimap.py`) may name the same file and line. `tests/test_spike_docs.py`
keeps every citation pointing at a file that exists and a line it has, and every trace
here free of a forbidden field, at commit time.
