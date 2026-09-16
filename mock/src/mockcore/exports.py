"""The exports a site was asked for: a link minted instead of an email.

`32` for the mock claude.ai and §54 for the mock chatgpt.com: confirming on the
export page mints a token, the site keeps it, and the archive is what the token
is fetched as. A mock has no inbox, so the token's link is printed where an
email would arrive and listed at a witness path for any other terminal.

Site-wide rather than per session: a mock has one account, and the tool
distinguishes nothing finer. A second ask adds a second link rather than
replacing the first, so that two extractions yield two snapshots (§39, 6).

## One link, or a link and its parts

A site whose link serves the archive itself asks for no categories and gets an
export with no parts — the mock chatgpt.com. A site whose link serves an *index*
asks for one category per file the index will name, and gets a `Part` for each,
with a token of its own. That is Claude, whose link serves a manifest naming a
zip per category and part.

## What may be fetched twice, and what may not

The link a site mints **may be fetched any number of times**: no mock has a clock
a link could expire on, and an operator whose first fetch failed for a reason on
their side should not have to ask again.

A **part may be fetched once**. The vendor says so in the manifest it serves —
"Each export URL can only be used once" — and a mock that let a part be taken
twice would hide the one failure a re-run actually meets. `spend` is where that
lives: a part token is good once, and the second call is `None`, which the site
turns into the `404` a spent link really answers.
"""

import secrets
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

ARCHIVE_SUFFIX = ".zip"


def part_filename(category: str, part: int) -> str:
    """Return what the vendor calls a part: `conversations-000.zip`."""
    return f"{category}-{part:03d}{ARCHIVE_SUFFIX}"


@dataclass(frozen=True)
class Part:
    """One file an index names: what it holds, which piece of it, and the token that fetches it.

    `category` is the vendor's word for what is in it — `conversations`,
    `light_metadata` — and `part` its index within that category. A mock renders
    one part per category, so `part` is always `0`; it is carried because the
    manifest's shape carries it and a reader of the snapshot should see the same
    field the vendor writes.
    """

    category: str
    part: int
    token: str

    @property
    def filename(self) -> str:
        return part_filename(self.category, self.part)


@dataclass
class Export:
    """One export the site was asked for: its token, when, how often, and its parts.

    The token is the whole of the link's secret, as a vendor's would be. `fetched`
    counts fetches of that link — the archive, or the index naming the parts.
    """

    token: str
    requested_at: float
    fetched: int = 0
    parts: tuple[Part, ...] = ()
    spent: set[str] = field(default_factory=set)


class Exports:
    """Every export asked for, in the order asked."""

    def __init__(self, *, wall: Callable[[], float]) -> None:
        self._wall = wall
        self._exports: dict[str, Export] = {}
        self._lock = threading.Lock()

    def request(self, categories: Sequence[str] = ()) -> Export:
        """Mint a token, and one part token per category. The site counts the ask.

        No categories is a link that serves the archive itself; one or more is a
        link that serves an index naming them.
        """
        export = Export(
            token=secrets.token_hex(16),
            requested_at=float(self._wall()),
            parts=tuple(Part(category=category, part=0, token=secrets.token_hex(16)) for category in categories),
        )
        with self._lock:
            self._exports[export.token] = export
        return export

    def fetch(self, token: str) -> Export | None:
        """Return the export a token names and count the fetch; `None` for one nobody minted.

        Named for what it does to the record, not for the lookup: every call is a
        download, and `Export.fetched` is how many there have been.
        """
        with self._lock:
            export = self._exports.get(token)
            if export is not None:
                export.fetched += 1
            return export

    def spend(self, part_token: str) -> Part | None:
        """Return the part a token names, once. `None` for an unknown part or a spent one.

        The whole of the single-use rule. It is here rather than in `fetch`
        because the two answers differ: an index may be read again, and the file
        it names may not.

        By the part's own token and not by the index's, because a part's address
        does not carry the index's — the tool files the manifest, and what is in a
        URL there is on disk. A part token is the whole of its own secret, as a
        vendor's is.
        """
        with self._lock:
            for export in self._exports.values():
                if part_token in export.spent:
                    return None
                for part in export.parts:
                    if part.token == part_token:
                        export.spent.add(part_token)
                        return part
            return None

    def all(self) -> Sequence[Export]:
        with self._lock:
            return tuple(self._exports.values())
