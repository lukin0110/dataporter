"""A source, as the browser sees it: its site and its walls (`42`).

`sources` knows what a vendor is; this module knows what that means to the
code that drives a tab. Three things are derived from a `Source` and nothing
else is: the `Site` a trace, a sketch and a watch are told about (brief `04`
§50); the extraction surface — §36's wall for the ask, the sign-in and the
export page and nothing else; and the sign-in's own wall, which admits where
the site leaves a signed-in person as well.

Each wall is one regular expression built the way `24` and `31` wrote Claude's
by hand, so that Claude's are byte-identical to what they were, and a second
source's are the same shape with its own paths and hosts. A host the sign-in
passes through beside the site's own is admitted whole: its real paths are
unknown, and the wall's work on that host is done by `login_form` finding a
field or stopping.

Derived once per source and cached: `session.site_of` and `export_page` hand
out the same `Site` object, which is what a test that asks `is` expects.
"""

import re
from functools import cache
from typing import TYPE_CHECKING

from dataporter.browser import probe as probing
from dataporter.browser.helpers import Surface
from dataporter.browser.site import Site

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dataporter.sources.base import Source

NOT_THE_EXPORT_PAGE = "the browser did not arrive at {path}"
"""The tab is not on the page the ask came for — it never got there, or it left
between the look and the click."""


def export_page_url(source: "Source") -> str:
    """Where the source's export page is, built from the path spelled once."""
    return f"{source.origin}{source.export_page_path}"


def not_the_export_page(source: "Source") -> str:
    """Return the line for a tab that is not on the source's export page."""
    return NOT_THE_EXPORT_PAGE.format(path=source.export_page_path)


def _wall(source: "Source", paths: "Sequence[str]") -> re.Pattern[str]:
    """One pattern: the site's origin with these paths, and every auth origin whole.

    The **origin** and not the host, so the scheme and the port are inside the
    wall rather than assumed by it. That is what makes the two modes disjoint
    (`65`): a wall built on `https://claude.ai` admits no localhost, and one
    built on `http://127.0.0.1:8443` admits no claude.ai, so a run that forgot
    `--mock` — or was given it by mistake — stops at the wall with the URL in
    hand instead of quietly driving the wrong site.
    """
    own = rf"^{re.escape(source.origin)}/({'|'.join(paths)})(\?.*)?$"
    others = "".join(rf"|^{re.escape(origin)}/.*$" for origin in source.auth_origins)
    return re.compile(own + others)


def extraction_pattern(source: "Source") -> re.Pattern[str]:
    """§36's wall for the ask: the sign-in's paths and the export page. Two doors.

    The export page's *whole address* and not its path, fragment included, which
    is what keeps this wall as narrow as it was when the page had a path of its
    own: a wall matches the URL as a string, so admitting
    `/new#settings/data-privacy-controls` admits neither `/new` nor any chat on
    it. `on_export_page` compares the same two halves of a *parsed* URL.

    The halves are escaped either side of a query, because that is where a query
    goes: `/new?from=nav#settings/…` is the same page as `/new#settings/…`, and a
    door that expected the two halves to be adjacent would refuse it. Raised by
    Copilot in review on #52.

    A fragment route admits what is under it as well. claude.ai's export is two
    screens — the panel, and `…/export-data` where the button that asks lives —
    and a door that admitted only the first refused the second the moment it was
    clicked through to. So *the export page* is the subtree rather than the
    address, which is still the sign-in and the export page and nothing else:
    `/new` is not admitted, and neither is another settings route beside it. A
    source whose export page is a plain path keeps exactly the door it had.
    """
    path, _, fragment = source.export_page_path.lstrip("/").partition("#")
    door = re.escape(path) + (rf"(\?[^#]*)?\#{re.escape(fragment)}(/.*)?" if fragment else "")
    return _wall(source, (*source.sign_in_paths, door))


def login_pattern(source: "Source") -> re.Pattern[str]:
    """Return the sign-in's wall: its own paths, and where the site leaves a signed-in person."""
    return _wall(source, (*source.sign_in_paths, *source.app_paths))


@cache
def extraction_site(source: "Source") -> Site:
    """Return the source as an extraction's trace describes it (brief `04` §50).

    The same host, and every selector the ask and a source sign-in drive it
    with, by name, in the order `31` merged them: `probe`'s, the source's own,
    then the credential fields. `login_form` imports this module for its own
    wall, so its table is read here when the site is first asked for and not
    when the module loads.
    """
    from dataporter.browser import login_form  # ruff: ignore[import-outside-top-level] - see the docstring

    return Site(
        source.name,
        source.host,
        {**probing.SELECTORS, **source.selectors, **login_form.SELECTORS},
        hosts=source.hosts,
    )


@cache
def extraction_surface(source: "Source") -> Surface:
    """§36's wall for the ask, with the site a sketch on it counts."""
    return Surface(
        origin=source.origin, site=extraction_site(source), allowed=extraction_pattern(source), origins=source.origins
    )


@cache
def login_surface(source: "Source") -> Surface:
    """Return the sign-in's wall: `MIGRATION_SURFACE`'s doors and the sign-in's own."""
    from dataporter.browser import login_form  # ruff: ignore[import-outside-top-level] - see `extraction_site`

    site = Site(source.name, source.host, {**probing.SELECTORS, **login_form.SELECTORS}, hosts=source.hosts)
    return Surface(origin=source.origin, site=site, allowed=login_pattern(source), origins=source.origins)
