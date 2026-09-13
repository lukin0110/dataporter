"""The exports a site was asked for: a link minted instead of an email.

`32` for the mock claude.ai and §54 for the mock chatgpt.com: confirming on the
export page mints a token, the site keeps it, and the archive is what the token
is fetched as. A mock has no inbox, so the token's link is printed where an
email would arrive and listed at a witness path for any other terminal.

Site-wide rather than per session: a mock has one account, and the tool
distinguishes nothing finer. A second ask adds a second link rather than
replacing the first, so that two extractions yield two snapshots (§39, 6). A
link lives until the process does and may be fetched any number of times: no
mock has a clock a link could expire on, and an operator whose first fetch
failed for a reason on their side should not have to ask again.
"""

import secrets
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass
class Export:
    """One export the site was asked for: its token, when, and how often it was fetched.

    The token is the whole of the link's secret, as a vendor's would be.
    """

    token: str
    requested_at: float
    fetched: int = 0


class Exports:
    """Every export asked for, in the order asked."""

    def __init__(self, *, wall: Callable[[], float]) -> None:
        self._wall = wall
        self._exports: dict[str, Export] = {}
        self._lock = threading.Lock()

    def request(self) -> Export:
        """Mint a token. The site counts the ask: an export requested is the site's verb."""
        export = Export(token=secrets.token_hex(16), requested_at=float(self._wall()))
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

    def all(self) -> Sequence[Export]:
        with self._lock:
            return tuple(self._exports.values())
