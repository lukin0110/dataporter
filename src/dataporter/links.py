"""What every link a person hands the tool has in common (§66, §74).

Two commands take one — `extract --link`, the export link, and `login --link`,
the sign-in link — and both check the same thing before anything is driven to
it: the scheme. A link that is not `https` is not a link this tool follows,
and finding that out from the server would mean having spoken to it. Spelled
once, here, because the two commands live in modules that do not import each
other.
"""

import urllib.parse
from collections.abc import Sequence

LINK_SCHEME = "https"
LINK_NOT_HTTPS = "the link must be an https URL"
LINK_NOT_ON_ORIGIN = "the link must be on {origin}"


def is_https(link: str) -> bool:
    """Whether the link's scheme is the one the tool follows."""
    return urllib.parse.urlsplit(link).scheme == LINK_SCHEME


def is_followable(link: str, origins: Sequence[str] = ()) -> bool:
    """Whether the tool will drive to this link: `https`, or exactly one of `origins`.

    The second half is `--mock`'s (`65`), and it is deliberately narrow. A mock
    is on `http://127.0.0.1:844x`, so the scheme check alone would refuse every
    link it ever prints — but *relaxing the scheme* would be a door: `http` on
    any host would then be followable, on a real run, for anybody who could get
    a link in front of an operator. So this admits a plain-HTTP link only when it
    is on an origin the source itself names, which under `--mock` is the mock and
    under a real run is an `https` origin no `http` link can match.
    """
    if is_https(link):
        return True
    return any(link == origin or link.startswith(f"{origin}/") for origin in origins)


def not_followable(origins: Sequence[str] = ()) -> str:
    """Why a link was refused, in the words the mode makes true."""
    plain = [origin for origin in origins if not origin.startswith(f"{LINK_SCHEME}:")]
    return LINK_NOT_ON_ORIGIN.format(origin=plain[0]) if plain else LINK_NOT_HTTPS
