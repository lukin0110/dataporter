"""Where an operation's lines go, so that the library never prints.

`23` moved every command's body out of `cli` and into the module that owns it —
`login` into `browser.session`, `verify` into `verify`, the run into `importer` —
and the one thing those bodies did that a library must not is `print`. This is
the seam that replaced it: an operation is handed a `Sink` and writes its lines
to that, and the caller decides what a line becomes. The CLI hands it a
`Terminal`; a test, or a Python caller who wants the words, hands it a
`Collected`; everything else gets `DISCARD`, because a library that prints is a
library nobody can call quietly.

Three channels rather than one, because the commands use three: a line on
stdout, a block on stdout that already ends in a newline (§9's, §10's and §16's
golden blocks are printed with `end=""` today and must stay byte-identical), and
a note on stderr. A sink over a generator, because `doctor`, `verify`, `seeds`,
`followup` and `judge` each interleave lines with side effects and end in an exit
code, and a generator that also returns is awkward for the caller this exists
for.

Nothing here decides *what* is printed under `--quiet`: that rule belongs to
each operation, which is where it was when the `print` calls lived in `cli`.
"""

import sys
from dataclasses import dataclass, field
from typing import Protocol

from dataporter.exit_codes import ExitCode

__all__ = ["DISCARD", "Collected", "HasExitCode", "Sink", "Terminal"]


class Sink(Protocol):
    """An operation's three channels."""

    def line(self, text: str) -> None:
        """One line on stdout. A newline is appended."""
        ...

    def block(self, text: str) -> None:
        """Write a block on stdout, verbatim: it already ends in a newline."""
        ...

    def note(self, text: str) -> None:
        """One line on stderr. A newline is appended."""
        ...


class HasExitCode(Protocol):
    """What the CLI reads off an operation's outcome, and all it reads."""

    @property
    def exit_code(self) -> ExitCode: ...


@dataclass(frozen=True)
class Terminal:
    """The process's own streams, resolved at write time.

    At write time rather than at construction: `typer.testing.CliRunner` swaps
    `sys.stdout` and `sys.stderr` for the duration of one invocation, and a
    stream captured when the module was imported would write past it — which is
    also why `print` is used rather than a stored handle.
    """

    def line(self, text: str) -> None:
        print(text)

    def block(self, text: str) -> None:
        print(text, end="")

    def note(self, text: str) -> None:
        print(text, file=sys.stderr)


@dataclass
class Collected:
    """Every line kept, in order, for a caller who wants the words.

    `stdout` and `stderr` are what a terminal would have shown, byte for byte, so
    a test can compare an operation's output to the CLI's and prove the CLI adds
    nothing.
    """

    out: list[str] = field(default_factory=list)
    err: list[str] = field(default_factory=list)

    def line(self, text: str) -> None:
        self.out.append(f"{text}\n")

    def block(self, text: str) -> None:
        self.out.append(text)

    def note(self, text: str) -> None:
        self.err.append(f"{text}\n")

    @property
    def stdout(self) -> str:
        return "".join(self.out)

    @property
    def stderr(self) -> str:
        return "".join(self.err)


@dataclass(frozen=True)
class _Discard:
    """The library default: nothing is printed."""

    def line(self, text: str) -> None:
        pass

    def block(self, text: str) -> None:
        pass

    def note(self, text: str) -> None:
        pass


DISCARD: Sink = _Discard()
