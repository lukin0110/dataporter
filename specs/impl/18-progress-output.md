# 18 — Progress output

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §10
**Depends on:** [06](06-migration-state.md), [12](12-import-loop.md)
**Enables:** [19](19-report.md)
**Status:** Not started

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
- `hermes-claude-migrate status` prints lines 5–10 (bar and counters) from state alone.
- Counters are read from `state.json` on every redraw, so a resumed run continues from
  its real numbers instead of restarting at zero.

## Out of scope

- The end-of-run report (`19`).

## Design notes

- The brief's §10 block is self-consistent (every counter line is 13 wide), so the rule
  reproduces it exactly, including `91/127` → 14 filled cells.
- Waits get their own visible line because §13 makes the run slow on purpose; a silent
  two-minute gap would look like a hang.

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
