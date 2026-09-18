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
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from dataporter.export.source import ExportView


LOOKS_LIKE = "the archive looks like a {looks} export, not a {asked} one: {display}"
"""What an operator reads when an archive is another source's (§64): spelled
once, here, and raised by the reader that noticed and by the fetch that asked."""


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

    origin: str
    """Where the site is: scheme, host and port together — `https://claude.ai`,
    or `http://127.0.0.1:8443` under `--mock` (`65`).

    The one stored value, because every other spelling of *where* follows from
    it: `host` is this without the scheme or the port, `login_url` is this and a
    path, and every wall is built on it. A mock source is this field replaced and
    nothing else, which is the whole of what ADR 0010 claims."""

    auth_origins: tuple[str, ...]
    """Origins the sign-in passes through beside the site's own, admitted whole by
    the sign-in's wall because their real paths are unknown (§61, §65)."""

    login_path: str
    """What `login` opens, on `origin`: `/new` for a site that drops a signed-in
    person into its app, `/` for one that leaves them at its root."""

    sign_in_paths: tuple[str, ...]
    """Regex fragments on `host` a sign-in passes through, without the leading slash."""

    app_paths: tuple[str, ...]
    """Where the site leaves a signed-in person, which the sign-in's wall admits
    beside `sign_in_paths` and the extraction's does not."""

    export_page_path: str
    """Where the vendor lets a user ask for their data. Spelled once, here.

    An address rather than strictly a path: a vendor may serve the page at a
    fragment of its app rather than at a path of its own, as claude.ai does
    (§77). Compared against a URL's path *and* fragment together, because on
    such a site the fragment is the only thing telling the export page apart
    from the app page it opens over."""

    selectors: Mapping[str, str]
    """The source's own page controls, by name: the export page's three, and
    whatever its sign-in needs beyond the credential fields (which are
    `login_form`'s to spell)."""

    fetch_needs_session: bool
    """Whether the archive is served only to the signed-in session (§63)."""

    signed_out_at_root: bool
    """Whether a signed-out request lands on the site's root without a composer,
    rather than on a sign-in path — what `export_page.signed_out` reads."""

    unattended_signin: Literal["agent", "walk", "none"]
    """How `--non-interactive` reaches the form: `24`'s agent, `44`'s walk, or
    not at all (`52`, brief 07 §76) — a source whose sign-in is a person's step
    stops an unattended run with `login` as the remedy, and asks for no
    credential at any door, because none could be a key."""

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

    sign_in_by_link: bool = False
    """Whether the vendor signs an account in with an emailed link (brief 07).

    A source that does has no password step and no unattended sign-in: `login`
    opens the window, waits for the link to be sent, and keeps the window until
    `login --link` has spent it (§73). A source that does not keeps `07`'s
    sign-in — a window, a person, a signed-in probe — unchanged.
    """

    link_serves_manifest: bool = False
    """Whether the emailed link serves an index of the real files, not the archive.

    Claude's does: a JSON naming one single-use URL per category and part, so its
    export arrives as a manifest and several zips rather than as one file. A
    source whose link serves the archive itself leaves this alone, which is every
    other source today.
    """

    organizations_path: str = ""
    """Where the site lists the organisations a signed-in account belongs to, on
    `origin` — the address a skills extraction reads first, since every other
    skills address is under one organisation (`66`). Empty for a source with no
    skills to extract, which is every source but Claude today."""

    skills_list_path: str = ""
    """The address that lists an account's skills, with `{org}` where the
    organisation's uuid goes. Read *in the page*, on the site's own origin, and
    never navigated to (`66`, brief `09` §92)."""

    skills_download_path: str = ""
    """The address one skill is served from, with `{org}` and `{skill}`. The tab
    is pointed at it and the browser's download caught, as a link's is (`45`),
    which is why it is a door in the extraction wall and the list is not."""

    def __post_init__(self) -> None:
        # Read-only from the moment it is built, as `Site` does it: a frozen
        # dataclass protects the binding and not the mapping.
        object.__setattr__(self, "selectors", MappingProxyType(dict(self.selectors)))

    @property
    def host(self) -> str:
        """The site's own host, bare: the trace header's, and what a tab is matched by.

        Without the scheme and **without the port**, because `cdp.Target.host` is
        `urlparse(url).hostname` and a port there would match no tab at all. That
        asymmetry is the reason `origin` is the field and this is derived, rather
        than the other way round (`65`).
        """
        return urlsplit(self.origin).hostname or ""

    @property
    def auth_hosts(self) -> tuple[str, ...]:
        """The auth origins as bare hosts, for the same reason `host` is bare."""
        return tuple(urlsplit(origin).hostname or "" for origin in self.auth_origins)

    @property
    def hosts(self) -> tuple[str, ...]:
        """Every host the source session touches, the site's own first."""
        return (self.host, *self.auth_hosts)

    @property
    def origins(self) -> tuple[str, ...]:
        """Every origin the source session touches, the site's own first."""
        return (self.origin, *self.auth_origins)

    @property
    def has_skills(self) -> bool:
        """Whether this source has skills a person wrote, and all three addresses to read them by.

        All three, not the two `66` first checked: the organisations read comes
        first and its address is as required as the list's and the download's,
        so a source missing it would pass the command's capability check and
        then read the origin root. (Raised by Copilot in review on #64.)
        """
        return bool(self.organizations_path and self.skills_list_path and self.skills_download_path)

    @property
    def login_url(self) -> str:
        """What `login` opens and the signed-in probe asks."""
        return f"{self.origin}{self.login_path}"
