"""The sources the tool has (brief `03` §34, brief `06` §60).

One object per vendor, registered here by name. Extraction from a source that
is not registered is refused, not attempted: `store.SOURCES` is this registry's
keys, and `config.with_account` checks a `--source` against it before anything
joins the name to a path.
"""

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING

from dataporter.sources.base import Reading, Source
from dataporter.sources.claude import CLAUDE

if TYPE_CHECKING:
    from dataporter.config import Settings

__all__ = ["CLAUDE", "REGISTRY", "Reading", "Source", "of", "recognised"]

REGISTRY: Mapping[str, Source] = MappingProxyType({CLAUDE.name: CLAUDE})
"""Every source this build has, by the name `--source` takes."""


def of(settings: "Settings") -> Source:
    """Return the source this invocation is about.

    `settings.source` has been through `config.with_account` on every path that
    names an account, so the lookup cannot miss; a destination command, which
    names no account, reads the default and gets Claude.
    """
    return REGISTRY[settings.source]


def recognised(names: Sequence[str]) -> Source | None:
    """Return the source whose archive these member names look like, if any does."""
    for source in REGISTRY.values():
        if source.recognise(names):
            return source
    return None
