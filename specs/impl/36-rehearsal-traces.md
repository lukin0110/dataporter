# 36 — The rehearsal's traces

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 04](../04-trace.md) §47 (the scripted agent's mark), §48
**Depends on:** [35](35-watch.md), [29](29-rehearsal.md)
**Enables:** [37](37-traces-as-evidence.md); a comparison of two traces (brief §51)
**Status:** Done

## Goal

The rehearsal runner gathers the trace every browser step leaves, names each after its
step, and the rehearsal record lists them with the two marks a reader needs — what the
certificate said and what the agent said — so that a record names its evidence and a
rehearsal's traces are the baseline a real run's are laid beside. The scripted `hermes`
says in its version line that it is the scripted agent, which is the one change the tool's
side of the line makes.

## In scope

- **Gathering** (`rehearsal/run.py`): `Runner.keep(outcome)` already writes
  `<root>/protocol/NN-<slug>.out` and `.err`; it now also moves every
  `logs/trace-*.jsonl` the workspace holds when the step ends — the protocol drives no
  source account, so nothing lands in an account home; the day it extracts, the
  accounts directory is the second place to look — to `<root>/traces/NN-<slug>.jsonl`,
  the same `NN` and slug as the protocol files, and records the path on the `Outcome`
  (`trace`) with how many it found (`traces`). A step leaves at most one; a second is
  filed too, as `NN-<slug>-2.jsonl`, and is a finding, `two traces for one step`. A step
  that drives no tab leaves none and the table says `—`.
- **The record** (`RECORD`): a new section after *The protocol*:

  ```text
  ## The traces

  Every step that drove a tab left one (§42); the runner filed them under
  `traces/`, named after the step. A rehearsal's traces are the baseline a real
  run's are compared against (§48).

  | Step | Trace | Lines | Certificate | Agent |
  | --- | --- | --- | --- | --- |
  | `login` | `traces/03-login.jsonl` | 19 | `claude.ai` | `hermes 1.0.0 (scripted agent)` |
  | `import --pilot` | `traces/06-import---pilot.jsonl` | 293 | `claude.ai` | `hermes 1.0.0 (scripted agent)` |
  | `import --dry-run` | — | — | — | — |
  ```

  One row per protocol step, in protocol order; `Lines` is the file's line count;
  `Certificate` is the `issuer` of the trace's first `certificate` observation, or `—`
  when there is none — the mock's is `claude.ai`, its own name, since a browser reports
  an issuer by its common name and a certificate signed by itself has its subject for
  an issuer; `Agent` is the header's `agent` value. Rendered from the files, not from
  prose, as the rest of the record is (`29`): `trace_row(root, step)`. The slug is
  `keep`'s own, so a step named `import --pilot` files as `06-import---pilot.jsonl`.
  `docs/rehearsal-01.md` is left as it is: a record is what was.
- **The mark** (`rehearsal/hermes.py`): `--version` prints `hermes 1.0.0 (scripted
  agent)`. `VERSION` stays `1.0.0`; the suffix is a constant beside it,
  `AGENT_SUFFIX = "(scripted agent)"`, and `versions_of`'s `agent` value is unchanged —
  the record already names the scripted agent by its own version, and this slice makes
  the trace's header say the same.
- **Tests**:
  - `tests/test_rehearsal.py` — `keep` moves a trace file left in a fake workspace to
    `traces/NN-<slug>.jsonl` and leaves `logs/` without it; a step with no trace gets a
    `—` row; two traces for one step is a finding; the table renders byte for byte from
    three fixture traces; the scripted `hermes --version` prints exactly
    `hermes 1.0.0 (scripted agent)\n`.
  - `tests/test_hermes_version.py` — `parse_version("hermes 1.0.0 (scripted agent)")`
    is `(1, 0, 0)`, and `at_least` holds.
- **Docs**: `README.md` (one sentence under *Rehearsing it*: where the traces land);
  `docs/rehearsal-01.md` untouched; the next rehearsal record, `docs/rehearsal-02.md`,
  is produced by running the rehearsal after `35` lands and is this slice's live
  evidence.

## Out of scope

- The runner's ledger block learning the sixth row: `32` decided the block stays §21's
  five until a rehearsal also extracts, and nothing here extracts.
- Comparing a rehearsal's traces with a real run's: brief §51. This slice produces the
  baseline and names it.
- The rehearsal running an extraction and gathering its trace from the account home:
  the day `32`'s out-of-scope item lands, `keep` already looks there.

## Design notes

- **Moved, not copied.** A trace left in the rehearsal's workspace would be found again
  by the next step's `keep` and filed twice; moving it is what makes "since the step
  began" trivially true. The workspace is the rehearsal's own and thrown away with
  `<root>`. Rejected: copying and remembering (state the runner would have to carry
  across steps).
- **Named after the step, not the command.** Two `import --all` steps leave two traces,
  and the protocol's numbering is what tells them apart everywhere else in the record.
  Rejected: the trace's own stamp (a reader would have to pair timestamps with rows).
- **The record shows the marks, not a verdict.** `Certificate` and `Agent` are the two
  columns because they are what ADR 0006 says a reader judges from; the record does not
  add a column saying "rehearsal", because the record's own header already says so and
  the trace does not. Rejected: a `Kind` column derived by the runner (the runner knows,
  but the point of the table is that the trace shows it).
- **The suffix is the scripted agent's and the parser ignores it.** `09`'s
  `parse_version` reads digits and stops; `hermes 1.0.0 (scripted agent)` parses as it
  did. The real Hermes prints whatever it prints, verbatim, and a reader who sees no
  suffix knows. Rejected: a different major version for the scripted agent (it would
  fail `doctor`'s minimum, or lie about being above it).

## Acceptance criteria

- `make check` is green.
- `python -m rehearsal.run --root /tmp/r --record docs/rehearsal-02.md` against a
  running mock leaves `/tmp/r/traces/` with one file per browser step of the protocol,
  each named `NN-<slug>.jsonl`, and none in `/tmp/r/workspace/logs/`.
- `docs/rehearsal-02.md` holds *The traces* with one row per protocol step; every row
  with a file says `hermes 1.0.0 (scripted agent)`, and every one that reached the site
  says `claude.ai` for its certificate, the self-signed mark; every step without a
  browser says `—`.
- The scripted `hermes --version` prints `hermes 1.0.0 (scripted agent)` and `doctor`
  against the scripted profile still passes its version check.

Every criterion above was met on 2026-09-13 by rehearsal 02 (`docs/rehearsal-02.md`),
run against the mock with a real Google Chrome 152 headless: eight of the eighteen steps
drove a tab and left a trace, filed `02-doctor--before-login.jsonl` through
`12-followup.jsonl`; every one of the eight says `hermes 1.0.0 (scripted agent)`, and
the six that reached the site carry one `certificate` line with `claude.ai` for issuer
and subject alike. The pilot's trace is 293 lines — 47 moves, 40 sketches, 93 request
and response pairs, 11 navigations, 6 URL changes in place, and `end` — and the run
the drill killed left 17 with no `end`, as §42 says it should. No trace holds the
sign-in email, the password or a line of a message. `doctor` passed its version check
against the suffixed line, and the twelve pass criteria all held.

## Risks

- **A trace the runner did not expect.** A step that opens two browsers — `doctor`
  attaches and then a helper task runs — could leave two traces if `33` wired it as
  two commands. `33`'s rule is one trace per command invocation, and the finding
  `two traces for one step` is what surfaces a wiring mistake.
- **The certificate column reads as the site's own name.** The mock's certificate is
  self-signed, and a browser reports an issuer by its common name, so the column says
  `claude.ai` for the mock — the same string a reader might expect of the real site.
  The mark is the *equality* of issuer and subject, and the record's intro says so; a
  reader who skims the column alone could still be misled, which is why `37`'s evidence
  rule keeps a rehearsal's traces out of the repository.
