"""Migrate a Claude data export into another Claude account, via Hermes.

An installable package (`25`), not only a checkout: a host project that has the
`hermes` binary on its `PATH` installs this one, imports it, and calls the same
operations the command line calls. `py.typed` ships beside this file, so those
calls carry their real types into the caller's type checker rather than arriving
as `Any`.

The API is the operations table in `specs/impl/23-library-operations.md`: one
function per command, in the module that owns the domain, each taking `Settings`
and returning a frozen outcome with an `exit_code`. They are reached at the
module that holds them — `importer.import_command`, `browser.session.login`,
`verify.verify_all` — and are deliberately not re-exported here, because a
re-export is a second spelling of where a thing lives. Give an operation a
`console.Collected` to read back exactly what the CLI would have printed, or
leave the default `console.DISCARD` and read the outcome alone.

Nothing in the package reads a file from this repository at runtime. The one
thing it ships besides code is the `claude-migrate` skill under `skills/`, which
`hermes.skill.packaged_dir` resolves through `importlib.resources` out of the
install.
"""

__all__ = ["PROGRAM_NAME", "__version__"]

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
