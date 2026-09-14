"""What the trace, the sketch and the watch are told about a source, and all of it.

Brief `04` §50: nothing that writes a trace may know Claude. A `Site` is the
whole of what it is told instead — the source's name, the host the watch
filters requests on and the header names, and the selectors the source drives
its pages with, by name, so that a sketch can say how many elements each found
without knowing what any of them is for.

`probe.MIGRATION_SITE` is Claude's own; every other site is derived from a
source by `browser/sites.py` (`42`), and nothing here knows which.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class Site:
    """One site, as the trace describes it."""

    source: str
    """The vendor's name, as `store.SOURCES` spells it: `claude`, later `chatgpt`."""

    host: str
    """The host whose pages are driven, named in the trace's header."""

    selectors: Mapping[str, str]
    """The source's selector table, name → CSS selector, in the source's order."""

    hosts: tuple[str, ...] = ()
    """Every host the watch records requests on and a tab is looked for on:
    `host`, and the hosts a sign-in passes through beside it (`42`, §61).
    Empty means `host` alone, so a one-host site is written as it always was."""

    def __post_init__(self) -> None:
        # Read-only from the moment it is built: a frozen dataclass protects the
        # binding and not the mapping, and a site is a constant.
        object.__setattr__(self, "selectors", MappingProxyType(dict(self.selectors)))
        if not self.hosts:
            object.__setattr__(self, "hosts", (self.host,))
