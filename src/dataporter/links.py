"""What every link a person hands the tool has in common (§66, §74).

Two commands take one — `extract --link`, the export link, and `login --link`,
the sign-in link — and both check the same thing before anything is driven to
it: the scheme. A link that is not `https` is not a link this tool follows,
and finding that out from the server would mean having spoken to it. Spelled
once, here, because the two commands live in modules that do not import each
other.
"""

import urllib.parse

LINK_SCHEME = "https"
LINK_NOT_HTTPS = "the link must be an https URL"


def is_https(link: str) -> bool:
    """Whether the link's scheme is the one the tool follows."""
    return urllib.parse.urlsplit(link).scheme == LINK_SCHEME
