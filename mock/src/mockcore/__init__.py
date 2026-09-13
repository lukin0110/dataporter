"""What every mock shares, and no site owns.

Brief `05` §53 (ADR 0007): the mocks are one project. The mock claude.ai and the
mock chatgpt.com are each a package of their own — their pages, their paths,
their selectors, their archive, their citations of their UI map — and this
package is the half they share: a certificate minted for a site's host names and
a key Chrome is told to trust, a session that survives the browser closing, the
witness routes the tool never drives, the ledger and its block, the reachability
block that tells the operator how to reach a mock, the obedient reply that finds
the one line a seed asks for and answers with exactly it in steps, and a link
minted instead of an email.

The core knows no site. Everything in it that has to name one is handed an
`Identity` by the site that owns it, and a helper wanted by one site alone
stays in that site. A helper wanted by a site and the tool is still duplicated,
never imported across (ADR 0003): this project imports nothing from
`dataporter`, and `dataporter` imports nothing from it.
"""

from dataclasses import dataclass
from importlib import metadata

DISTRIBUTION = "mocks"
"""The one distribution every mock ships in. `claude-mock` until `38` renamed it."""

try:
    __version__ = metadata.version(DISTRIBUTION)
except metadata.PackageNotFoundError:  # pragma: no cover - a checkout nobody installed
    __version__ = "0+uninstalled"


@dataclass(frozen=True)
class Identity:
    """Who a mock is, as the core needs to know it: a command, a site and its hosts.

    `program` is the command and names the certificate directory
    (`~/.cache/<program>/`); `site` is how the site is named in prose (`Mock
    claude.ai`); `hosts` are every host name the mock answers as — the resolver
    rule sends each of them to the mock and the certificate names each of them;
    `port` is the mock's own, beside the other mocks' (§54, *Reachability*).
    """

    program: str
    site: str
    hosts: tuple[str, ...]
    port: int

    @property
    def title(self) -> str:
        """`Mock claude.ai` — how the blocks and the headings name the mock."""
        return f"Mock {self.site}"

    @property
    def heading(self) -> str:
        """The ledger block's first line, which names the site (§54, *The ledger*)."""
        return f"{self.title} — ledger"

    @property
    def spelled_hosts(self) -> str:
        """The hosts in prose: `claude.ai`, or `chatgpt.com and auth.openai.com`."""
        if len(self.hosts) == 1:
            return self.hosts[0]
        return ", ".join(self.hosts[:-1]) + f" and {self.hosts[-1]}"
