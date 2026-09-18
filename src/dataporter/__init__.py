"""Migrate a Claude data export into another Claude account, via Hermes.

An installable package (`25`), not only a checkout: a host project that has the
`hermes` binary on its `PATH` installs this one, imports it, and calls the same
operations the command line calls. `py.typed` ships beside this file, so those
calls carry their real types into the caller's type checker rather than arriving
as `Any`.

There are two doors, and they are the same operations either way.

**`Dataporter`** (`68`) is the short one, and the only name this module exports:

    from dataporter import Dataporter

    dp = Dataporter()
    dp.extract_skills("work")

It covers `login`, `logout`, the four modes of `extract`, `extract-skills` and
`doctor` — what a host project reaches for — and it owns nothing but the
settings plumbing those calls would otherwise repeat. See `dataporter.api`.

**The operations table** in `specs/impl/23-library-operations.md` is the full
one: one function per command, in the module that owns the domain, each taking
`Settings` and returning a frozen outcome with an `exit_code`. They are reached
at the module that holds them — `importer.import_command`, `browser.session.login`,
`verify.verify_all` — and are deliberately not re-exported here, because a
re-export is a second spelling of where a thing lives. `import`, `resume`,
`seeds`, `inspect`, `verify` and the rest have no facade method and are reached
this way.

`Dataporter` is the one exception to that rule, and it is not a re-export: it is
a class of its own, holding configuration the operations do not hold, and it is
named here rather than only in `dataporter.api` because `68` was asked for the
shortest import a caller could have. It is fetched lazily, so importing any
other module of this package still costs nothing of Chrome's or Hermes's.

Give an operation a `console.Collected` to read back exactly what the CLI would
have printed, or leave the default `console.DISCARD` and read the outcome alone.

Nothing in the package reads a file from this repository at runtime. The one
thing it ships besides code is the `claude-migrate` skill under `skills/`, which
`hermes.skill.packaged_dir` resolves through `importlib.resources` out of the
install.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dataporter.api import Dataporter

__all__ = ["PROGRAM_NAME", "Dataporter", "__version__"]

__version__ = "0.1.0"

PROGRAM_NAME = "dataporter"
"""The command. The brief wrote it as `hermes-claude-migrate` in §8-§10; ADR
0004 renamed it to the package's own name, because the program is meant to port
more than Claude and the brief's spelling is a record, not edited in passing.

Here rather than in `cli` because `09` builds the command line Hermes is told to
run through its terminal tool, and a module that `cli` imports cannot import
`cli` back. `cli` re-exports it, so `--version` stays a golden string produced in
one place.
"""


def __getattr__(name: str) -> Any:
    """Fetch `Dataporter` on first use, and nothing else (`68`).

    Lazy because `api` imports the extraction, browser and Hermes modules, and
    importing them eagerly here would make every `from dataporter.config import …`
    anywhere in the tool pay for Chrome. `AttributeError` for every other name is
    not politeness: `from dataporter import console` asks for this attribute
    first and falls back to importing the submodule only when it is refused.
    """
    if name == "Dataporter":
        from dataporter.api import Dataporter  # ruff: ignore[import-outside-top-level] - lazy on purpose, see above

        return Dataporter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
