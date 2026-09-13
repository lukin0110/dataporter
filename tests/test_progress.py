"""The §10 block, byte for byte, in both of the shapes a run can print it.

`18`'s acceptance criteria are the first five sections; the rest cover rules the
spec states that the brief's own example does not force — the singular line, an
empty plan, the detail column, and what `--quiet` keeps.

Two things are measured rather than described. The block is compared against the
brief itself, so a change to the rule that no longer reproduces §10 fails here
and not in a pilot; and the terminal mode is driven through a real pseudo-
terminal, because "is anybody watching a cursor" is the one question the whole
mode hangs on and a stub that answers it the way the test wants proves nothing.
"""

import os
import pty
import re
import termios
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from typing import IO

import pytest

from dataporter import intervention as intervening
from dataporter import progress, state
from dataporter.errors import Category
from dataporter.state import ConversationState, ErrorRecord, MigrationState, Status
from world import CONTENT, FIRST, LONG, THIRD, World, completed, result

BRIEF = Path(__file__).resolve().parents[1] / "specs" / "01-initial-brief.md"
"""§10's example block, which this slice's rule is measured against."""

BRIEF_COUNTS = {"total": 127, "completed": 89, "partial": 1, "failed": 1, "pending": 36}
"""The brief's §10 numbers: 91 of 127 done, 14 cells of 20."""

BRIEF_BLOCK = (
    "Claude migration\n"
    "\n"
    "127 conversations found\n"
    "\n"
    "[██████████████░░░░░░] 91/127\n"
    "\n"
    "Completed: 89\n"
    "Partial:    1\n"
    "Failed:     1\n"
    "Pending:   36\n"
)
"""§10, as the brief writes it. Unlike §9's block it is self-consistent, so the
rule reproduces every line of it."""

ESCAPE = re.compile(r"\x1b")


def counts(total: int, **tally: int) -> Mapping[str, int]:
    """Return Counts as `state.status_counts` shapes them, from the terminal ones.

    `pending` is derived here the way it is derived there, so a test cannot
    describe a workspace that could not exist.
    """
    finished = sum(tally.values())
    return {
        "total": total,
        "completed": tally.get("completed", 0),
        "partial": tally.get("partial", 0),
        "failed": tally.get("failed", 0),
        "pending": total - finished,
    }


# --------------------------------------------------------------------------- #
# Acceptance: the golden block
# --------------------------------------------------------------------------- #


def test_the_block_is_the_brief_s_own() -> None:
    """`18`'s first criterion: 89 / 1 / 1 of 127, byte for byte."""
    assert progress.block(BRIEF_COUNTS) == BRIEF_BLOCK
    assert BRIEF_BLOCK in BRIEF.read_text(encoding="utf-8")


def test_a_finished_run_fills_every_cell() -> None:
    assert progress.bar_line(counts(5, completed=5)) == f"[{'█' * 20}] 5/5"


def test_a_run_that_has_started_nothing_fills_none() -> None:
    assert progress.bar_line(counts(5)) == f"[{'░' * 20}] 0/5"


def test_a_six_figure_total_widens_the_block_consistently() -> None:
    """The counters widen together (`06`'s rule) and the bar keeps its 20 cells."""
    lines = progress.block(counts(200_000, completed=123_456, failed=7, partial=0)).splitlines()

    assert lines[2] == "200,000 conversations found"
    assert lines[4] == "[████████████░░░░░░░░] 123,463/200,000"
    assert lines[6:] == [
        "Completed: 123,456",
        "Partial:         0",
        "Failed:          7",
        "Pending:    76,537",
    ]


# --------------------------------------------------------------------------- #
# Acceptance: one header, one redraw per change, on a terminal
# --------------------------------------------------------------------------- #


@contextmanager
def terminal() -> Iterator[tuple[IO[str], Callable[[], str]]]:
    r"""Yield a real pseudo-terminal to write to, and a way to read back what arrived.

    `ONLCR` is switched off first: a terminal in its default mode rewrites every
    `\n` on its way through as `\r\n`, and this slice's whole subject is which
    bytes reach a screen.

    Both ends are UTF-8 by name rather than by locale. The block is drawn in
    U+2588 and U+2591, and `os.fdopen` would otherwise encode them with whatever
    `locale.getencoding()` says — ASCII under `LC_ALL=C` with UTF-8 mode off,
    where writing the bar raises instead of testing anything.
    """
    main, follower = pty.openpty()
    attributes = termios.tcgetattr(follower)
    attributes[1] &= ~termios.ONLCR  # oflag
    termios.tcsetattr(follower, termios.TCSANOW, attributes)
    os.set_blocking(main, False)
    stream = os.fdopen(follower, "w", encoding="utf-8")
    written: list[str] = []

    def read() -> str:
        """Everything written so far. Drains, because a pty buffer is finite."""
        stream.flush()
        while True:
            try:
                chunk = os.read(main, 65536)
            except BlockingIOError:
                break
            written.append(chunk.decode("utf-8"))
        return "".join(written)

    try:
        yield stream, read
    finally:
        stream.close()
        os.close(main)


def test_a_terminal_gets_one_header_and_a_redraw_per_change() -> None:
    """`18`'s third criterion, on the stream a real terminal would see."""
    with terminal() as (stream, read):
        reporter = progress.Reporter(stream=stream)
        reporter.start(counts(3))
        reporter.conversation("aa000001", Status.COMPLETED, counts(3, completed=1))
        reporter.conversation("bb000002", Status.COMPLETED, counts(3, completed=2))
        reporter.finish(counts(3, completed=2, failed=1))
        printed = read()

    assert printed.count(progress.TITLE) == 1
    assert printed.count("3 conversations found") == 1
    # The first block is printed under the header; the three after it go over it.
    assert printed.count(progress.CURSOR_UP) == 3
    assert printed.endswith("".join(f"{line}\n" for line in progress.block_lines(counts(3, completed=2, failed=1))))


def test_a_pipe_gets_no_escape_sequence() -> None:
    """The other half of the same criterion."""
    stream = StringIO()
    reporter = progress.Reporter(stream=stream)
    reporter.start(counts(3))
    reporter.conversation("aa000001", Status.COMPLETED, counts(3, completed=1))
    reporter.waiting(120.0, "retry 2/3, generation")
    reporter.finish(counts(3, completed=1, failed=2))

    assert not ESCAPE.search(stream.getvalue())


# --------------------------------------------------------------------------- #
# Acceptance: nothing either mode prints is content
# --------------------------------------------------------------------------- #


def test_neither_mode_prints_anything_from_the_export(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """`18`'s fourth criterion, over a real run in each mode.

    A failure as well as a completion, so the detail column is in the output
    being scanned and not only the ids and the counts.
    """
    world.retries(max_attempts=1)
    world.answers(completed(), result(outcome="failed", error={"category": "ui", "detail": "x"}))
    piped = StringIO()
    world.importer(progress=progress.Reporter(stream=piped)).run(world.export, state.Selection(limit=2))
    with terminal() as (stream, read):
        world.importer(progress=progress.Reporter(stream=stream)).run(
            world.export, state.Selection(limit=2, force=True)
        )
        drawn = read()

    captured = capsys.readouterr()
    for phrase in CONTENT:
        assert phrase not in piped.getvalue()
        assert phrase not in drawn
        assert phrase not in captured.out
        assert phrase not in captured.err


# --------------------------------------------------------------------------- #
# Acceptance: a resumed run continues from its real numbers
# --------------------------------------------------------------------------- #


def test_the_first_block_of_a_second_run_counts_what_the_first_one_did() -> None:
    """`18`'s fifth criterion: 3 of 5 on disk is `3/5` on the first draw.

    Read through `status_counts`, because that is what the loop hands over and
    where `Pending = total − done` is decided.
    """
    entries = {
        f"{index}": ConversationState(status=status)
        for index, status in enumerate([
            Status.COMPLETED,
            Status.COMPLETED,
            Status.PARTIAL,
            Status.PENDING,
            Status.PENDING,
        ])
    }
    on_disk = state.status_counts(MigrationState(root=entries))

    assert progress.bar_line(on_disk) == f"[{'█' * 12}{'░' * 8}] 3/5"


def test_a_second_run_of_the_same_workspace_starts_where_the_first_stopped(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same rule through the loop: the numbers come off `state.json`.

    Two of six are done before the first conversation of the first run finishes
    — the fixture's unsupported one is written as `failed` — so a second run's
    first line is the fourth of six rather than the first of anything.
    """
    world.run(limit=2)
    capsys.readouterr()

    world.run(limit=1)
    printed = capsys.readouterr().out

    assert printed.startswith("Claude migration\n\n6 conversations found\n\n")
    assert f"{THIRD[:8]}  completed  (4/6)\n" in printed


# --------------------------------------------------------------------------- #
# The header
# --------------------------------------------------------------------------- #


def test_one_conversation_is_singular() -> None:
    assert progress.found_line(1) == "1 conversation found"


def test_a_thousand_conversations_carry_a_separator() -> None:
    assert progress.found_line(1_284) == "1,284 conversations found"


def test_an_empty_plan_draws_an_empty_bar() -> None:
    """Nothing to divide by, and nothing to fill.

    `06` allows the state file that gets here: a workspace whose export had no
    conversations in it.
    """
    assert progress.bar_line(counts(0)) == f"[{'░' * 20}] 0/0"


# --------------------------------------------------------------------------- #
# The event line
# --------------------------------------------------------------------------- #


def test_the_status_column_is_padded() -> None:
    """`18`'s two example lines, which differ only in the status word."""
    done = counts(127, completed=12)
    assert progress.event_line("3f9c2a1e", Status.COMPLETED, done) == "3f9c2a1e  completed  (12/127)"
    assert progress.event_line(
        "8a02c7d1",
        Status.PARTIAL,
        counts(127, completed=12, partial=1),
        ErrorRecord(category=Category.GENERATION, detail="response never completed"),
    ) == ("8a02c7d1  partial    (13/127)  generation: response never completed")


def test_only_a_partial_or_a_failure_carries_a_detail() -> None:
    """A `completed` line has nothing to explain.

    Not even what the entry still holds from an attempt that was retried into success.
    """
    line = progress.event_line(
        "3f9c2a1e",
        Status.COMPLETED,
        counts(2, completed=1),
        ErrorRecord(category=Category.NETWORK, detail="connection reset"),
    )
    assert line == "3f9c2a1e  completed  (1/2)"


def test_a_partial_with_no_record_behind_it_says_only_that() -> None:
    """`17`'s edge: a chat the page says is missing a part is `partial`.

    Whether or not an attempt recorded an error — and a column with nothing in it is not
    a column.
    """
    line = progress.event_line("3f9c2a1e", Status.PARTIAL, counts(2, partial=1))

    assert line == "3f9c2a1e  partial    (1/2)"


def test_a_detail_that_says_nothing_leaves_the_category() -> None:
    line = progress.event_line(
        "3f9c2a1e",
        Status.FAILED,
        counts(2, failed=1),
        ErrorRecord(category=Category.UI),
    )
    assert line == "3f9c2a1e  failed     (1/2)  ui"


def test_a_long_detail_is_one_line_and_capped() -> None:
    """Hermes's words, on a terminal: folded to one line and cut to length.

    An unbounded string from somewhere else is the one way a line this module
    builds can stop being a line.
    """
    line = progress.event_line(
        "3f9c2a1e",
        Status.FAILED,
        counts(2, failed=1),
        ErrorRecord(category=Category.UI, detail="dialog\nin  the way " + "x" * 80),
    )

    detail = line.split("  ")[-1]
    assert detail.startswith("ui: dialog in the way ")
    assert detail.endswith("…")
    assert len(detail) == len("ui: ") + progress.DETAIL_MAX


# --------------------------------------------------------------------------- #
# Down a pipe
# --------------------------------------------------------------------------- #


def test_a_pipe_gets_the_header_the_events_and_one_block() -> None:
    stream = StringIO()
    reporter = progress.Reporter(stream=stream)
    reporter.start(counts(2))
    reporter.conversation("aa000001", Status.COMPLETED, counts(2, completed=1))
    reporter.waiting(120.0, "retry 2/3, generation")
    reporter.conversation(
        "bb000002",
        Status.FAILED,
        counts(2, completed=1, failed=1),
        ErrorRecord(category=Category.GENERATION, detail="response never completed"),
    )
    reporter.finish(counts(2, completed=1, failed=1))

    assert stream.getvalue() == (
        "Claude migration\n"
        "\n"
        "2 conversations found\n"
        "\n"
        "aa000001  completed  (1/2)\n"
        "waiting 120s (retry 2/3, generation)\n"
        "bb000002  failed     (2/2)  generation: response never completed\n"
        "[████████████████████] 2/2\n"
        "\n"
        "Completed:  1\n"
        "Partial:    0\n"
        "Failed:     1\n"
        "Pending:    0\n"
    )


def test_quiet_keeps_the_block_and_nothing_else() -> None:
    """`-q` suppresses progress.

    The stop line and the final block are not progress — one is what became of the run
    and the other is what it amounts to.
    """
    stream = StringIO()
    reporter = progress.Reporter(stream=stream, quiet=True)
    reporter.start(counts(3))
    reporter.conversation("aa000001", Status.FAILED, counts(3, failed=1))
    reporter.waiting(30.0, "retry 2/3, network")
    reporter.stopping(3, Category.NETWORK)
    reporter.finish(counts(3, failed=1))

    assert stream.getvalue() == (
        "stopping: 3 consecutive failures (network) — see report\n"
        "[██████░░░░░░░░░░░░░░] 1/3\n"
        "\n"
        "Completed:  0\n"
        "Partial:    0\n"
        "Failed:     1\n"
        "Pending:    2\n"
    )


def test_quiet_emits_no_escape_sequence_on_a_terminal() -> None:
    """The second half of `18`'s rule about ANSI: a terminal is not enough."""
    with terminal() as (stream, read):
        reporter = progress.Reporter(stream=stream, quiet=True)
        reporter.start(counts(2))
        reporter.conversation("aa000001", Status.COMPLETED, counts(2, completed=1))
        reporter.finish(counts(2, completed=2))
        printed = read()

    assert not ESCAPE.search(printed)
    assert progress.TITLE not in printed


# --------------------------------------------------------------------------- #
# The transient line, and what else writes to the screen
# --------------------------------------------------------------------------- #


def test_a_wait_is_a_seventh_line_that_is_rubbed_out() -> None:
    r"""It carries no newline.

    The redraw above it counts on the cursor being one line under the block, and
    `\x1b[2K` is what gives that back.
    """
    with terminal() as (stream, read):
        reporter = progress.Reporter(stream=stream)
        reporter.start(counts(2))
        reporter.waiting(120.0, "retry 2/3, generation")
        waiting = read()
        reporter.conversation("aa000001", Status.COMPLETED, counts(2, completed=1))
        printed = read()

    assert waiting.endswith("waiting 120s (retry 2/3, generation)")
    after = printed[len(waiting) :]
    assert after.startswith(f"{progress.CLEAR_LINE}{progress.CURSOR_UP}")


def test_an_ask_takes_the_screen_and_the_block_comes_back_under_it() -> None:
    """`14` prints where the redraw would land, so the next block is a fresh one.

    The numbers are the ones already on screen: the conversation that paused is
    still running, and nothing has changed while a person was being waited for.
    """
    with terminal() as (stream, read):
        reporter = progress.Reporter(stream=stream)
        reporter.start(counts(2))
        before = read()
        reporter.interrupted()
        stream.write(intervening.block(intervening.Request(short_id="aa000001")))
        reporter.resumed()
        printed = read()

    after = printed[len(before) :]
    assert progress.CURSOR_UP not in after
    assert after.endswith("".join(f"{line}\n" for line in progress.block_lines(counts(2))))


def test_the_stop_line_goes_under_the_block_and_the_last_one_under_it() -> None:
    """`13`'s line is printed, not drawn over.

    What is above it is the state the run stopped in, and the block under it is the same
    numbers, standing still.
    """
    with terminal() as (stream, read):
        reporter = progress.Reporter(stream=stream)
        reporter.start(counts(3))
        reporter.stopping(3, Category.NETWORK)
        reporter.finish(counts(3, failed=3))
        printed = read()

    stop = "stopping: 3 consecutive failures (network) — see report\n"
    assert stop in printed
    after = printed[printed.index(stop) + len(stop) :]
    assert progress.CURSOR_UP not in after


def test_a_stream_that_cannot_answer_is_treated_as_a_pipe() -> None:
    """A detached or closed stdout: print lines, emit nothing that needs a cursor."""

    class Detached(StringIO):
        def isatty(self) -> bool:
            raise ValueError("I/O operation on closed file")

    stream = Detached()
    progress.Reporter(stream=stream).start(counts(1))

    assert stream.getvalue() == "Claude migration\n\n1 conversation found\n\n"


def test_the_default_stream_is_stdout_as_it_is_at_the_time(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Resolved per write, so a reporter built before a redirection follows it."""
    progress.Reporter().finish(counts(1, completed=1))

    assert capsys.readouterr().out.startswith("[████████████████████] 1/1\n")


# --------------------------------------------------------------------------- #
# Through the loop
# --------------------------------------------------------------------------- #


def test_a_failed_conversation_names_its_category_on_the_line(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """The detail column, from `state.json`'s own record rather than from the attempt.

    What the line says is what `19` will report.
    """
    world.retries(max_attempts=1)
    world.answers(result(outcome="failed", error={"category": "ui", "detail": "x"}))

    world.run(only=[FIRST])
    printed = capsys.readouterr().out

    assert f"{FIRST[:8]}  failed     (2/6)  ui: x\n" in printed
    assert world.entry(FIRST).status is Status.FAILED


def test_the_unsupported_conversation_is_counted_before_anything_runs(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """The header is printed from the entries `12` writes first.

    The block a run opens with already knows about §14's refusals.
    """
    world.run(only=[LONG])
    printed = capsys.readouterr().out

    assert printed.startswith("Claude migration\n\n6 conversations found\n\n")
    assert printed.endswith(
        "[██████░░░░░░░░░░░░░░] 2/6\n\nCompleted:  1\nPartial:    0\nFailed:     1\nPending:    4\n"
    )
