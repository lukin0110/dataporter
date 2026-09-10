"""Exit codes, used by every command.

The codes are outcome-shaped, not error-shaped: `1` means "a conversation did not
make it", `4` means "there was nothing to do". There is deliberately no generic
mapping from `errors.Category` to an exit code, because for most categories the
right code depends on what the command was trying to do, not on what went wrong.

Sub-convention for the `browser` helper commands (see `08`): those print exactly
one JSON object on stdout and reuse `OK` / `FAILED` / `USAGE` as
"ok: true" / "ok: false" / "bad arguments". That is a narrowing of the meanings
below, not a contradiction of them.
"""

from enum import IntEnum


class ExitCode(IntEnum):
    """The exit-code convention from `specs/impl/01-foundation.md`."""

    OK = 0
    """Success."""

    FAILED = 1
    """Migration finished with at least one failed or partial conversation."""

    USAGE = 2
    """Usage or configuration error."""

    NOT_AUTHENTICATED = 3
    """Destination session not authenticated — run `login`."""

    NOTHING_TO_DO = 4
    """Nothing to do (already migrated, or selection empty)."""

    PAUSED = 5
    """Paused for human intervention (non-TTY); run `resume`."""

    ENVIRONMENT = 6
    """Environment not ready (Hermes or Chrome missing) — run `doctor`."""

    NOT_IMPLEMENTED = 69
    """Command not implemented in this build."""

    INTERNAL = 70
    """Unexpected internal error."""
