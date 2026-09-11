"""Migrate a Claude data export into another Claude account, via Hermes."""

__all__ = ["PROGRAM_NAME", "__version__"]

__version__ = "0.1.0"

PROGRAM_NAME = "hermes-claude-migrate"
"""The command, exactly as §8-§10 of the brief write it.

Here rather than in `cli` because `09` builds the command line Hermes is told to
run through its terminal tool, and a module that `cli` imports cannot import
`cli` back. `cli` re-exports it, so `--version` stays a golden string produced in
one place.
"""
