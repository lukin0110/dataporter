"""`23`'s seam: where an operation's lines go.

Three sinks, one contract. `Collected` is what the parity tests in
`test_operations.py` compare against the CLI's output, so its bytes are checked
here against exactly what `Terminal` would have printed.
"""

import sys
from io import StringIO

import pytest

from dataporter import console


def test_collected_keeps_the_bytes_a_terminal_would_show() -> None:
    sink = console.Collected()
    sink.line("one")
    sink.block("two\nthree\n")
    sink.note("careful")
    sink.line("")

    assert sink.stdout == "one\ntwo\nthree\n\n"
    assert sink.stderr == "careful\n"


def test_terminal_resolves_the_streams_at_write_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`CliRunner` swaps `sys.stdout` per invocation.

    A handle taken earlier would write past it.
    """
    sink = console.Terminal()
    out, err = StringIO(), StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    sink.line("one")
    sink.block("two\n")
    sink.note("careful")

    assert out.getvalue() == "one\ntwo\n"
    assert err.getvalue() == "careful\n"


def test_discard_prints_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    console.DISCARD.line("one")
    console.DISCARD.block("two\n")
    console.DISCARD.note("three")
    captured = capsys.readouterr()
    assert not captured.out
    assert not captured.err
