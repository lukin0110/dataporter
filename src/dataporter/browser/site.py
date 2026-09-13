"""What the trace, the sketch and the watch are told about a source, and all of it.

Brief `04` §50: nothing that writes a trace may know Claude. A `Site` is the
whole of what it is told instead — the source's name, the host the watch
filters requests on and the header names, and the selectors the source drives
its pages with, by name, so that a sketch can say how many elements each found
without knowing what any of them is for.

`probe.MIGRATION_SITE` and `export_page.EXTRACTION_SITE` are Claude's two; a
second source adds its own beside them and changes nothing here.
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
    """The host whose pages are driven, and whose requests the watch records."""

    selectors: Mapping[str, str]
    """The source's selector table, name → CSS selector, in the source's order."""

    def __post_init__(self) -> None:
        # Read-only from the moment it is built: a frozen dataclass protects the
        # binding and not the mapping, and a site is a constant.
        object.__setattr__(self, "selectors", MappingProxyType(dict(self.selectors)))
