"""The sources the tool has (brief `03` §34, brief `06` §60).

One object per vendor, registered here by name. Extraction from a source that
is not registered is refused, not attempted: `store.SOURCES` is this registry's
keys, and `config.with_account` checks a `--source` against it before anything
joins the name to a path.
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from types import MappingProxyType
from typing import TYPE_CHECKING

from dataporter.sources import chatgpt as chatgpt_source
from dataporter.sources import claude as claude_source
from dataporter.sources.base import LOOKS_LIKE, Reading, Source
from dataporter.sources.chatgpt import CHATGPT
from dataporter.sources.claude import CLAUDE

if TYPE_CHECKING:
    from dataporter.config import Settings

__all__ = [
    "CHATGPT",
    "CLAUDE",
    "LOOKS_LIKE",
    "MOCK_REGISTRY",
    "REGISTRY",
    "Reading",
    "Source",
    "of",
    "recognised",
]

REGISTRY: Mapping[str, Source] = MappingProxyType({CLAUDE.name: CLAUDE, CHATGPT.name: CHATGPT})
"""Every source this build has, by the name `--source` takes."""

MOCK_REGISTRY: Mapping[str, Source] = MappingProxyType({
    CLAUDE.name: replace(CLAUDE, origin=claude_source.MOCK_ORIGIN),
    CHATGPT.name: replace(
        CHATGPT,
        origin=chatgpt_source.MOCK_ORIGIN,
        auth_origins=(chatgpt_source.MOCK_AUTH_ORIGIN,),
    ),
})
"""The same sources, pointed at the mocks (`65`).

**One field replaced, and one more for a site with a second origin.** That is the
whole of what `--mock` does to the tool, and `tests/test_sources.py` asserts it
field by field — the claim ADR 0010 rests on is a test and not a sentence.

Separate objects rather than mutated ones, because `browser/sites.py` caches what
it derives on a source's *identity* (`Source` is `eq=False`): a mock source gets
its own wall, its own surface and its own `Site`, and neither can be served from
the other's cache entry.
"""


def of(settings: "Settings") -> Source:
    """Return the source this invocation is about.

    `settings.source` has been through `config.with_account` on every path that
    names an account, so the lookup cannot miss; a destination command, which
    names no account, reads the default and gets Claude.

    Under `--mock` it is the same source at a local origin. This is the one place
    the swap happens, so nothing downstream needs to know a mock exists.
    """
    registry = MOCK_REGISTRY if settings.mock else REGISTRY
    return registry[settings.source]


def recognised(names: Sequence[str]) -> Source | None:
    """Return the source whose archive these member names look like, if any does."""
    for source in REGISTRY.values():
        if source.recognise(names):
            return source
    return None
