"""What a source knows, as one object per vendor (brief `06` §60, `42`).

Brief `03` §34 says what a source knows: how to sign in, where the vendor lets a
user ask for their data, what the archive that comes back looks like, and what
the account holds that the archive does not. Until `42` that knowledge was
Claude's, spelled across `browser/export_page.py`, `browser/session.py`,
`browser/login_form.py`, `signin.py`, `extract.py` and `store.py`, and a second
source would have been a branch at each of them. It is one object here instead,
and the modules that were Claude's read it.

Data and one reader hook, and nothing of the browser: `store` reads this
package to know which sources exist, `config` reads `store`, and the browser
package reads `config`, so a `Source` that held a `Site` or a `Surface` would
make the store import the browser to list two names. `browser/sites.py`
derives the site and the walls from a source instead, on the browser's side.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from dataporter.export.source import ExportView


@dataclass(frozen=True)
class Reading:
    """What one parse of an archive found: the numbers a manifest keeps (§38).

    `files` is `None` for a source that does not count them — Claude's export
    carries no bytes to count — so that its manifest does not grow a key for a
    number it never had. `missing_files` is the one gap kind either source has
    today: files the account holds that the archive does not carry (§31).
    """

    conversations: int
    fingerprint: str
    projects: int = 0
    memories: int = 0
    files: int | None = None
    missing_files: int = 0


@dataclass(frozen=True, eq=False)
class Source:
    """One vendor, as the tool knows it (§34, §60).

    `eq=False`, so a source is hashed and compared by identity: there is one
    object per vendor, `browser/sites.py` caches what it derives from each, and
    a mapping of selectors is not hashable anyway.
    """

    name: str
    """The store's spelling — `claude`, `chatgpt` — and `--source`'s."""

    display_name: str
    """How a block an operator reads spells the vendor: `Claude`, `ChatGPT`."""

    host: str
    """The site's own host: the trace header's, and the one every wall is built on."""

    auth_hosts: tuple[str, ...]
    """Hosts the sign-in passes through beside the site's own, admitted whole by
    the sign-in's wall because their real paths are unknown (§61, §65)."""

    login_url: str
    """What `login` opens and the signed-in probe asks."""

    sign_in_paths: tuple[str, ...]
    """Regex fragments on `host` a sign-in passes through, without the leading slash."""

    app_paths: tuple[str, ...]
    """Where the site leaves a signed-in person, which the sign-in's wall admits
    beside `sign_in_paths` and the extraction's does not."""

    export_page_path: str
    """Where the vendor lets a user ask for their data. Spelled once, here."""

    selectors: Mapping[str, str]
    """The source's own page controls, by name: the export page's three, and
    whatever its sign-in needs beyond the credential fields (which are
    `login_form`'s to spell)."""

    fetch_needs_session: bool
    """Whether the archive is served only to the signed-in session (§63)."""

    signed_out_at_root: bool
    """Whether a signed-out request lands on the site's root without a composer,
    rather than on a sign-in path — what `export_page.signed_out` reads."""

    unattended_signin: Literal["agent", "walk"]
    """How `--non-interactive` reaches the form: `24`'s agent, or `44`'s walk."""

    ask_lines: tuple[str, ...]
    """The vendor's own sentences in the ask block, between `Export requested …`
    and the command (§60)."""

    counts_line: str
    """The block's count line, a format string over the manifest's counts."""

    login_prompt: str
    """What `login` tells the person at the keyboard."""

    recognise: Callable[[Sequence[str]], bool]
    """Whether an archive with these member names is this source's."""

    read: Callable[["ExportView"], Reading]
    """Parse the archive and say what it holds, or raise `ExportError`."""

    def __post_init__(self) -> None:
        # Read-only from the moment it is built, as `Site` does it: a frozen
        # dataclass protects the binding and not the mapping.
        object.__setattr__(self, "selectors", MappingProxyType(dict(self.selectors)))

    @property
    def hosts(self) -> tuple[str, ...]:
        """Every host the source session touches, the site's own first."""
        return (self.host, *self.auth_hosts)
