r"""§10's block: what a migration looks like while it is running.

Everything the loop needs in order to *say* something already existed — `12`
gave it a `Progress` seam and a line per conversation, `06` gave it the four
counters. This slice is the picture those numbers go into: the §10 block, drawn
once as a header and then redrawn in place under it, or written down a pipe as
one line per event and one block at the end.

Four decisions are the whole module:

- **One rule, two modes.** `block_lines` builds the six lines that change and
  `header_lines` the four that do not, and both modes print the same strings.
  What differs is when: a terminal rewrites the six with `CURSOR_UP`, a pipe
  prints them once at the end. Nothing is formatted twice, so the two cannot
  drift.
- **The counters are `06`'s.** `summary.counters_lines` owns the alignment and
  `status_counts` owns the arithmetic — `Pending = total − done` included. This
  module adds the bar above them and the header above that, and reads both from
  `state.json` on every redraw, which is what makes a resumed run continue from
  its real numbers instead of restarting at zero.
- **The block is six lines high and stays that way.** `CURSOR_UP` is `\x1b[6F`
  and the redraw depends on the cursor sitting one line below the block, so the
  transient wait line is written without a newline and rubbed out with
  `CLEAR_LINE` before anything else is printed. Anything that writes below the
  block on purpose — `14`'s ask, `13`'s stop line — says so (`interrupted`), and
  the next block is drawn fresh rather than over somebody else's words.
- **No ANSI where nothing can read it.** A pipe and `--quiet` take the same
  path, so a redirected run is a readable log and a quiet one is four lines and
  a bar.

§10's other half is the one this module is most easily broken by: no
conversation content, ever. What reaches stdout here is a short id, a status
word, counts, a category and `ErrorRecord.detail` — which is `13`'s own words
about a failure, condensed to one line and capped, never a title and never a
message.
"""

import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import IO, Protocol

from dataporter import summary
from dataporter.errors import Category
from dataporter.state import ErrorRecord, Status

TITLE = "Claude migration"
"""Line 1, and the only word this block spends on saying what it is."""

FOUND_ONE = "{total} conversation found"
FOUND_MANY = "{total} conversations found"
"""Line 3. The count is the plan's, so it is every conversation in the export
and not the selection this run was given — `--limit 1` against an export of 127
still found 127."""

BAR_CELLS = 20
FILLED = "█"
EMPTY = "░"
"""The bar: 20 cells, `filled = floor(done / total × 20)`, U+2588 and U+2591."""

BLOCK_HEIGHT = 6
"""Bar, blank, four counters. `CURSOR_UP` is this number and they move together."""

CURSOR_UP = f"\x1b[{BLOCK_HEIGHT}F"
"""Up `BLOCK_HEIGHT` lines, to column 1 (`F`, not `A`), ready to overwrite."""

CLEAR_LINE = "\r\x1b[2K"
"""Rub out the transient wait line and put the cursor back at its start.

The carriage return is not decoration: `\\x1b[2K` blanks the line and leaves the
cursor where it was, which for a line written without a newline is the far end
of it.
"""

STATUS_WIDTH = 10
"""What the status column is padded to in the event line, plus one space before
the counts — which is what puts `(12/127)` two columns after `completed` and four
after `partial`, exactly as `18` writes them."""

GUTTER = "  "
"""Between the short id and the status, and before the detail column."""

DETAIL_STATUSES = frozenset({Status.PARTIAL, Status.FAILED})
"""The two outcomes that owe an explanation. A `completed` line is its own."""

DETAIL_MAX = 60
"""How much of an error detail an event line carries.

`19` prints the whole of it from `state.json`; this is a terminal, and a helper
that answered with a paragraph would wrap the line rather than inform anybody.
"""

ELLIPSIS = "…"

WAITING = "waiting {seconds:g}s ({reason})"
"""§13's gaps, as `12` first wrote them: `waiting 120s (retry 2/3, generation)`,
`waiting 1740s (rate limit until 15:00 UTC)`, `waiting 20s (pacing)`."""

STOPPING = "stopping: {failures} consecutive failures ({category}) — see report"
"""`13`'s circuit breaker. Not progress, so `--quiet` does not suppress it."""


# --------------------------------------------------------------------------- #
# The strings
# --------------------------------------------------------------------------- #


def found_line(total: int) -> str:
    """`127 conversations found`, and `1 conversation found` at one."""
    template = FOUND_ONE if total == 1 else FOUND_MANY
    return template.format(total=summary.number(total))


def header_lines(total: int) -> list[str]:
    """Lines 1–4: the title, a blank, the count, a blank.

    Printed once per run. Everything under it is redrawn; nothing in it is.
    """
    return [TITLE, "", found_line(total), ""]


def done(counts: Mapping[str, int]) -> int:
    """Conversations this workspace is finished with, in §10's sense.

    Summed from the three terminal counters rather than taken as
    `total − pending`, which is how `status_counts` derives `pending` in the
    first place. The two agree by construction; this is the direction `18`
    states the rule in.
    """
    return counts["completed"] + counts["partial"] + counts["failed"]


def filled_cells(finished: int, total: int) -> int:
    """`floor(done / total × 20)`, and no cells at all for an empty plan.

    Integer arithmetic rather than `int(finished / total * BAR_CELLS)`: a float
    division can land a hair under a whole number where the exact ratio is that
    number, and `int` would then draw a cell fewer than the rule asks for.
    """
    if total <= 0:
        return 0
    return finished * BAR_CELLS // total


def bar_line(counts: Mapping[str, int]) -> str:
    """`[██████████████░░░░░░] 91/127`."""
    finished, total = done(counts), counts["total"]
    filled = filled_cells(finished, total)
    cells = f"{FILLED * filled}{EMPTY * (BAR_CELLS - filled)}"
    return f"[{cells}] {summary.number(finished)}/{summary.number(total)}"


def block_lines(counts: Mapping[str, int]) -> list[str]:
    """Return the six lines that change: the bar, a blank, `06`'s four counters."""
    return [bar_line(counts), "", *summary.counters_lines(counts)]


def block(counts: Mapping[str, int]) -> str:
    """Return the whole §10 block, header and all, newline-terminated.

    What a golden test compares against the brief, and what no mode prints in one
    piece: a terminal prints the header once and the rest many times, a pipe
    prints the header first and the rest last.
    """
    lines = [*header_lines(counts["total"]), *block_lines(counts)]
    return "".join(f"{line}\n" for line in lines)


def detail_of(error: ErrorRecord | None) -> str:
    """Return `generation: response never completed` — the category, then what it said.

    One line and at most `DETAIL_MAX` characters of it: the detail is Hermes's
    description of a failure, and a run's progress output is a place where an
    unbounded string from somewhere else does not belong.
    """
    if error is None:
        return ""
    condensed = " ".join(error.detail.split())
    if not condensed:
        return str(error.category)
    if len(condensed) > DETAIL_MAX:
        condensed = f"{condensed[: DETAIL_MAX - 1]}{ELLIPSIS}"
    return f"{error.category}: {condensed}"


def event_line(
    short_id: str,
    status: Status,
    counts: Mapping[str, int],
    error: ErrorRecord | None = None,
) -> str:
    """One conversation's outcome: `3f9c2a1e  completed  (12/127)`.

    The detail column is `partial` and `failed` only. A `completed` line with an
    empty column would invite the reading that something was left unsaid, and
    every other status has nothing to say.
    """
    counted = f"({summary.number(done(counts))}/{summary.number(counts['total'])})"
    line = f"{short_id}{GUTTER}{status:<{STATUS_WIDTH}} {counted}"
    detail = detail_of(error) if status in DETAIL_STATUSES else ""
    return f"{line}{GUTTER}{detail}" if detail else line


def wait_line(seconds: float, reason: str) -> str:
    return WAITING.format(seconds=seconds, reason=reason)


def stop_line(failures: int, category: Category) -> str:
    return STOPPING.format(failures=failures, category=category)


# --------------------------------------------------------------------------- #
# Where it goes
# --------------------------------------------------------------------------- #


class Progress(Protocol):
    """Where a run's progress goes.

    `Reporter` is the implementation `12` waited for; a test can pass anything with
    these methods and read a list instead.
    """

    def start(self, counts: Mapping[str, int]) -> None:
        """Print the header, once, before the first conversation."""
        ...

    def conversation(
        self,
        short_id: str,
        status: Status,
        counts: Mapping[str, int],
        error: ErrorRecord | None = None,
    ) -> None: ...

    def waiting(self, seconds: float, reason: str) -> None:
        """Announce a wait the run is about to make: `13`'s backoff, `15`'s rate limit."""
        ...

    def interrupted(self) -> None:
        """Something else is about to write below the block — `14`'s ask."""
        ...

    def resumed(self) -> None:
        """Put the block back under it, now that it has finished writing."""
        ...

    def stopping(self, failures: int, category: Category) -> None:
        """`13`'s circuit breaker, ending the run before the selection does."""
        ...

    def finish(self, counts: Mapping[str, int]) -> None: ...


@dataclass
class Reporter:
    """§10 on a terminal, and the same numbers down a pipe.

    `stream` is resolved at every write rather than captured in the constructor,
    because `sys.stdout` is what a test replaces and what a shell redirects, and
    a reporter built before either would print somewhere nobody is looking.
    """

    stream: IO[str] | None = None
    quiet: bool = False

    _counts: Mapping[str, int] | None = field(default=None, init=False, repr=False)
    """The last numbers drawn, so `resumed` can put the same block back without
    re-reading a state file that has not changed."""

    _block: bool = field(default=False, init=False, repr=False)
    """A block is on screen with the cursor directly under it, so the next draw
    may go over it. `False` means the next one is printed fresh."""

    _waiting: bool = field(default=False, init=False, repr=False)
    """The transient seventh line is on screen and owes a `CLEAR_LINE`."""

    # -- what mode this is -------------------------------------------------- #

    @property
    def out(self) -> IO[str]:
        return self.stream if self.stream is not None else sys.stdout

    @property
    def redrawing(self) -> bool:
        """Is anybody watching a cursor? `--quiet` says no whatever the stream is.

        A stream that raises on `isatty` — a closed pipe, a detached handle — is
        answered the same way a pipe is: print lines, emit no escape sequence.
        """
        if self.quiet:
            return False
        try:
            return self.out.isatty()
        except (OSError, ValueError):
            return False

    # -- the seam ----------------------------------------------------------- #

    def start(self, counts: Mapping[str, int]) -> None:
        """Print the header, and on a terminal the first block under it.

        Suppressed entirely by `--quiet`: a header is not an event line, but a
        run asked to be quiet that announces itself and then says nothing for an
        hour is not what `-q` was asked for.
        """
        if self.quiet:
            return
        self._write("".join(f"{line}\n" for line in header_lines(counts["total"])))
        if self.redrawing:
            self._draw(counts)

    def conversation(
        self,
        short_id: str,
        status: Status,
        counts: Mapping[str, int],
        error: ErrorRecord | None = None,
    ) -> None:
        if self.redrawing:
            self._draw(counts)
            return
        if self.quiet:
            return
        self._line(event_line(short_id, status, counts, error))

    def waiting(self, seconds: float, reason: str) -> None:
        """Print the seventh line, on a terminal; an ordinary line down a pipe.

        Progress, so `-q` suppresses it — but it is the reason the line exists: a
        run that is quiet because it is waiting has to look different from one
        that is quiet because it is stuck, at every verbosity that prints
        anything at all.
        """
        if self.quiet:
            return
        if not self.redrawing:
            self._line(wait_line(seconds, reason))
            return
        self._clear_wait()
        self._write(wait_line(seconds, reason))
        self._waiting = True

    def interrupted(self) -> None:
        """`14` is about to print its ask where the block's redraw would land."""
        self._clear_wait()
        self._block = False

    def resumed(self) -> None:
        """Draw the block again, under whatever was printed over it.

        The same numbers: the conversation that paused is still running, so
        nothing has changed since the last draw and re-reading `state.json` would
        only be a chance to disagree with it.
        """
        if self._counts is not None and self.redrawing:
            self._draw(self._counts)

    def stopping(self, failures: int, category: Category) -> None:
        """`13`'s stop line, under the block.

        Printed under `--quiet` for the reason `finish` is: it is not a report of
        progress, it is what became of the run.
        """
        self._clear_wait()
        self._line(stop_line(failures, category))
        self._block = False

    def finish(self, counts: Mapping[str, int]) -> None:
        """Report the last numbers: redrawn in place, or printed once at the end.

        Printed under `--quiet` for the reason `status` is: `-q` suppresses
        progress, and this is what the run amounts to.
        """
        self._draw(counts)

    # -- the terminal ------------------------------------------------------- #

    def _draw(self, counts: Mapping[str, int]) -> None:
        """Draw the six lines: over the ones already there, or under everything else.

        The wait line goes first wherever one is still up: it sits on the line
        the cursor has to come back to, and drawing over it would leave its tail
        showing past the end of whatever is drawn next.
        """
        self._clear_wait()
        over = CURSOR_UP if self._block and self.redrawing else ""
        self._write(over + "".join(f"{line}\n" for line in block_lines(counts)))
        self._counts = counts
        self._block = self.redrawing

    def _clear_wait(self) -> None:
        if not self._waiting:
            return
        self._write(CLEAR_LINE)
        self._waiting = False

    def _line(self, text: str) -> None:
        self._write(f"{text}\n")

    def _write(self, text: str) -> None:
        """Write and flush.

        The flush is what makes the wait line appear: it carries no newline, and
        a terminal's line buffering would otherwise hold it back for exactly as
        long as the wait it is announcing.
        """
        stream = self.out
        stream.write(text)
        stream.flush()
