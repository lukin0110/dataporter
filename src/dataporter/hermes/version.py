"""The minimum Hermes this build is willing to drive.

Hermes releases fast, and the three things we depend on — the `-z` one-shot
flag, the `browser.*` config keys `profile` sets and the `browser_*` tools the
skill calls — are all things a release can rename. A pinned floor turns that
into a `doctor` line printed before a migration starts rather than a run that
dies halfway through a conversation.

The *mechanism* is the deliverable here; the *number* is provisional. Nobody has
run this against a real Hermes yet, so pinning a version observed on somebody's
laptop would be a fabricated fact. `10` installs Hermes for the first time,
records the version it saw in `docs/hermes-attach.md`, and raises
`MINIMUM_VERSION` to it — from then on the check has teeth.

Comparison is numeric and nothing else. `hermes --version` may print
`hermes 0.4.1`, `0.4.1` or `hermes-agent 0.4.1 (python 3.12.3)`; the first
dotted run of digits is the version and the rest is decoration. A pre-release
suffix (`0.4.1-rc2`) compares equal to its release, because refusing to run on
a release candidate of a version we accept would be a stricter promise than the
floor is making.
"""

import re

MINIMUM_VERSION: tuple[int, ...] = (0, 1, 0)
"""The least Hermes `doctor` accepts. `10` raises this to what it observed."""

_NUMBERS = re.compile(r"\d+(?:\.\d+)*")


def parse_version(text: str) -> tuple[int, ...] | None:
    """Return the first dotted run of digits in `text`, or `None` if there is none."""
    found = _NUMBERS.search(text)
    if found is None:
        return None
    return tuple(int(part) for part in found.group().split("."))


def format_version(parts: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in parts)


def at_least(found: tuple[int, ...], minimum: tuple[int, ...] = MINIMUM_VERSION) -> bool:
    """Whether `found` is `minimum` or newer.

    Both sides are padded to the same length so that `0.4` and `0.4.0` compare
    equal rather than by the accident that a shorter tuple sorts first.
    """
    width = max(len(found), len(minimum))
    padded = found + (0,) * (width - len(found))
    floor = minimum + (0,) * (width - len(minimum))
    return padded >= floor
