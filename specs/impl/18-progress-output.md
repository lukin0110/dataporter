# 18 — Progress output

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §10
**Depends on:** [06](06-migration-state.md), [12](12-import-loop.md)
**Enables:** [19](19-report.md)
**Status:** Done

## Goal

The §10 block, byte-exact, updated in place on a terminal and as a readable event stream
when piped — with no conversation content, ever.

## In scope

- Golden block:

  ```text
  Claude migration

  127 conversations found

  [██████████████░░░░░░] 91/127

  Completed: 89
  Partial:    1
  Failed:     1
  Pending:   36
  ```

  Rules:
  - line 3 is `{total} conversation found` when `total == 1`, else `conversations found`;
    `total` is the number of conversations in the plan (all found, not only selected);
  - the bar is 20 cells: `filled = floor(done / total × 20)` cells of `█` (U+2588) and the
    rest `░` (U+2591), where `done = completed + partial + failed`; then one space and
    `{done}/{total}`; numbers use `,` thousands separators;
  - the four counter lines are `label` + spaces + right-aligned value, line width
    `max(13, longest label + 1 + longest value)`; `Pending = total − done`;
  - blank lines exactly as shown; every line `\n`-terminated.
- TTY mode (stdout is a terminal): the header (lines 1–4) is printed once; the six-line
  block (bar, blank, four counters) is redrawn after every state change by moving the
  cursor up six lines (`\x1b[6F`) and rewriting; a seventh, transient line carries waits —
  `waiting 120s (retry 2/3, generation)`, `waiting 1740s (rate limit until 15:00 UTC)`,
  `waiting 20s (pacing)` — and is cleared (`\x1b[2K`) when the wait ends. The intervention
  block from `14` is printed below and the progress block is redrawn after resume.
- Non-TTY mode: the header once, then one line per event, then the final block once:

  ```text
  3f9c2a1e  completed  (12/127)
  8a02c7d1  partial    (13/127)  generation: response never completed
  waiting 120s (retry 2/3, generation)
  ```

  Status is padded to 10 characters; the detail column appears only for `partial` and
  `failed`. No ANSI sequences are emitted when stdout is not a TTY or when `--quiet` is
  given; `--quiet` suppresses the event lines but not the final block.
- `dataporter status` prints the four counter lines from state alone. `06`
  shipped it without the bar — one that is drawn once is a picture of a number the line
  under it already gives — and owns `summary.counters_lines`; whether `status` grows a
  bar here is this slice's call, and the header and redraw are this slice's either way.
  **Settled: it does not.** `06`'s reason still holds, and a `status` that printed a bar
  would be a second block to keep in step with §10's for no question it answers.
- Counters are read from `state.json` on every redraw, so a resumed run continues from
  its real numbers instead of restarting at zero.

## Out of scope

- The end-of-run report (`19`).

## Design notes

- The brief's §10 block is self-consistent (every counter line is 13 wide), so the rule
  reproduces it exactly, including `91/127` → 14 filled cells.
- Waits get their own visible line because §13 makes the run slow on purpose; a silent
  two-minute gap would look like a hang.
- `progress.py` owns the strings and the two modes; `12`'s `Progress` protocol moved
  there with them, the way `14`'s `Intervention` lives beside `Console`. The loop names
  moments and hands over counts; nothing in `importer.py` formats a line any more.
- The protocol grew three methods and one argument, and each is a thing only the loop
  knows: `start` (the header, once, from the entries `12` writes before the first
  conversation), `interrupted`/`resumed` (`14` is about to print where the redraw would
  land, and has finished), and the entry's own `ErrorRecord` on `conversation`, which is
  what the detail column renders. The pair redraws the *same* numbers — the conversation
  that paused is still running — so a resumed block cannot disagree with the one the ask
  scrolled up.
- Status padded to 10 with a single space after it is what reproduces both of the spec's
  example lines; the detail column is `{category}: {detail}`, folded to one line and cut
  at 60 characters. `19` prints the whole record from `state.json`; a terminal gets as
  much of it as fits on a line, and an unbounded string from Hermes cannot break the one
  thing the redraw depends on — that the block is exactly six lines high.
- `--quiet` prints no header. §10's rule is that `-q` keeps the final block, and a run
  that announces itself and then says nothing for an hour is not what `-q` was asked for
  — `13`'s stop line and the block (bar included) are what a quiet run says.
- The wait line is rubbed out by the next thing drawn rather than by the wait ending.
  The loop announces a wait before sleeping through it (`12`'s shape, kept), so "the
  wait is over" is not a moment anything reports; what an operator must never see is the
  line still there under a block that has moved on, and clearing it inside the draw is
  what guarantees that.

## Acceptance criteria

- A golden test with counts 89 / 1 / 1 out of 127 renders the block above byte-for-byte.
- `done == total` renders 20 `█`; `done == 0` renders 20 `░`; a 6-digit total widens the
  counter lines consistently.
- On a pseudo-TTY the stream contains exactly one header and `\x1b[6F` before every
  redraw; on a pipe it contains no `\x1b`.
- Scanning both modes' output for fixture message text or titles finds nothing.
- Interrupting after 3 of 5 and resuming: the first redraw after resume shows `3/5`.

## Risks

- Cursor-movement redraws break on terminals narrower than the widest line or when
  something else writes to stdout. Only this module writes to stdout during a run
  (`01`'s log goes to stderr and the file), and the block is at most 33 columns wide.
