"""The two reads a skills extraction makes, and nothing it clicks (`66`, brief `09` §92).

`export_page` is the one place that knows what the *export page* looks like and
the one click that asks. This is the one place that knows where a source lists
the skills its account wrote and where it serves each one — and it looks at no
page at all. Both reads are a same-origin `fetch` the browser makes on the
vendor's own origin, evaluated in the tab the extraction already holds, so the
cookie never leaves Chrome and the tool constructs no authenticated request of
its own: the rule ADR 0008 set for the sign-in, kept for this.

Three things are deliberately not here:

- **No page.** The page the skills are listed on is never navigated to. Its
  controls are labelled with the skills' names — *View <name>*, *More actions
  for <name>* — and a sketch keeps a control's label (§46), so a watch that saw
  the tab arrive there would write every skill's name into the trace. The reads
  happen wherever the tab already is inside the extraction surface, which is
  the export page, and the fetch's own navigation is to the download address.
- **No words.** The list is a JSON body and the tool keeps five fields of each
  entry — `id`, `name`, `creator_type`, `enabled`, and whether a plugin backs
  it — and returns those. The description and the display name stay in the
  page: nothing needs them, and §38 keeps everything of ours to labels and
  numbers.
- **No door for the list.** The organisations and the list are read and never
  navigated to, so neither address is in the wall. What keeps them on the
  surface is that both are built from the `Source` and from nothing a response
  carried: the organisation's uuid goes into the list's address, and a skill's
  `id` into the download's, and that is the whole of what a response is allowed
  to decide.
"""

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from dataporter import log
from dataporter.browser import sites
from dataporter.browser.cdp import Page
from dataporter.errors import BrowserError

if TYPE_CHECKING:
    from dataporter.sources.base import Source

_logger = log.get_logger(__name__)

HTTP_ERROR = 400
"""The first status that is the site refusing rather than answering."""

ORG_TAG = "dataporter:skills_org"
LIST_TAG = "dataporter:skills_list"
"""What names each expression in a CDP trace, and how the test suite's fake
browser tells one from the other without running it — `probe.expression`'s
convention, kept."""

ORG_ACTION = "skills-org"
LIST_ACTION = "skills-list"
"""What `logs/actions.jsonl` calls the two reads. Named like the ask's two
clicks, because `19` counts the same file."""

OURS = "user"
"""The `creator_type` of a skill the account wrote (brief `09` §90).

Two values were read on 2026-09-18 — `anthropic` and this one — and a value the
tool does not know is **not** ours: a skill shared into the account, or authored
by an organisation, would be somebody else's, and filing it would put another
party's work in this account's snapshot. Missing one of ours is a gap a person
notices and a second run fixes; the other mistake is not."""

NO_ANSWER = "no answer"
NOT_THE_SHAPE = "not the shape the tool reads"
ORG_UNREADABLE = "could not read the account's organisation ({why})"
LIST_UNREADABLE = "could not read the account's skills ({why})"
"""Why a read stopped the extraction. A status when the site refused; the
status and `not the shape the tool reads` when the site answered and the body
was not what the read expects — a list that is not a list, an entry that is
not an object; `no answer` when the page returned nothing at all, which is
what the interstitial an attestation puts in the way answers a same-origin
`fetch` with.

The shape is refused rather than read as empty, because an empty list is an
answer — *no skills of your own* — and a body the tool does not recognise is
not one. A read that turned the second into the first would report success on
the day the vendor renamed a key. (Raised by Copilot in review on #64.)"""


def expression(tag: str, body: str) -> str:
    """One read: an async IIFE, tagged, with no prelude.

    Not `probe.expression`, whose prelude reads the composer and the page's
    selectors: a read that touches no element has no use for either, and an
    `await` needs an async function to sit in. `Page.evaluate` already awaits
    the promise it returns.
    """
    return f"(async () => {{\n  /* {tag} */\n{body}\n}})()"


def org_js(source: "Source") -> str:
    """Return the expression that reads the account's first organisation's uuid.

    The address is a `const` on a line of its own, as `click_js`'s selector is,
    so the fake browser can read it back. `credentials: 'same-origin'` is the
    browser's default for a same-origin request and is said anyway, because the
    whole of ADR 0008's argument rests on it.
    """
    return expression(
        ORG_TAG,
        f"  const url = {json.dumps(sites.organizations_url(source))};\n"
        "  const response = await fetch(url, { credentials: 'same-origin' });\n"
        "  if (!response.ok) return { status: response.status };\n"
        "  const body = await response.json();\n"
        "  const first = Array.isArray(body) ? body[0] : null;\n"
        "  const org = first && typeof first.uuid === 'string' ? first.uuid : null;\n"
        "  return { status: response.status, org };",
    )


def list_js(source: "Source", org: str) -> str:
    """Return the expression that lists one organisation's skills, five fields each."""
    return expression(
        LIST_TAG,
        f"  const url = {json.dumps(sites.skills_list_url(source, org))};\n"
        "  const response = await fetch(url, { credentials: 'same-origin' });\n"
        "  if (!response.ok) return { status: response.status };\n"
        "  const body = await response.json();\n"
        "  const items = body && Array.isArray(body.skills) ? body.skills : null;\n"
        "  const named = (value) => typeof value === 'string' && value !== '';\n"
        "  const entry = (item) => item !== null && typeof item === 'object'\n"
        "    && named(item.id) && named(item.name) && named(item.creator_type);\n"
        "  if (items === null || !items.every(entry)) {\n"
        "    return { status: response.status };\n"
        "  }\n"
        "  const text = (value) => (typeof value === 'string' ? value : '');\n"
        "  return {\n"
        "    status: response.status,\n"
        "    skills: items.map((item) => ({\n"
        "      id: text(item.id),\n"
        "      name: text(item.name),\n"
        "      creator_type: text(item.creator_type),\n"
        "      enabled: item.enabled === true,\n"
        "      plugin: text(item.backing_plugin_id) !== '',\n"
        "    })),\n"
        "  };",
    )


@dataclass(frozen=True)
class Listed:
    """One skill as the list describes it, in the five fields the tool keeps."""

    id: str
    name: str
    creator_type: str
    enabled: bool = True
    plugin: bool = False

    @property
    def ours(self) -> bool:
        """Whether the account wrote this skill (§90)."""
        return self.creator_type == OURS


def read_org(page: Page, source: "Source") -> str:
    """Return the account's organisation, or say why it could not be read."""
    raw = page.evaluate(org_js(source))
    org = raw.get("org") if isinstance(raw, dict) else None
    if not isinstance(org, str) or not org:
        raise BrowserError(detail=ORG_UNREADABLE.format(why=_why(raw)))
    return org


def read_list(page: Page, source: "Source", org: str) -> tuple[Listed, ...]:
    """Return every skill the list names, ours or not; the caller filters (§90).

    Ours or not, so that a log can say how many were listed beside how many
    were kept — the number that tells a person the filter did something.

    An entry is a skill only with an `id`, a `name` and a `creator_type`, each
    a string with something in it: the first is what the download address
    needs, the second what the file is named after, the third what the filter
    reads. The expression refuses the rest; this refuses them again, because a
    fake answers the tag and not the JavaScript. (Raised by Copilot in review
    on #64.)
    """
    raw = page.evaluate(list_js(source, org))
    items = raw.get("skills") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not all(_is_entry(item) for item in items):
        raise BrowserError(detail=LIST_UNREADABLE.format(why=_why(raw)))
    listed = tuple(_listed(item) for item in items)
    _logger.info("skills listed", extra={"listed": len(listed), "ours": sum(item.ours for item in listed)})
    return listed


REQUIRED = ("id", "name", "creator_type")
"""What an entry has to carry to be a skill the tool can act on."""


def _is_entry(item: Any) -> bool:
    """Whether `item` is an object carrying the three required fields, each a non-empty string."""
    return isinstance(item, dict) and all(isinstance(item.get(name), str) and item[name] for name in REQUIRED)


def _listed(item: dict[str, Any]) -> Listed:
    return Listed(
        id=str(item.get("id") or ""),
        name=str(item.get("name") or ""),
        creator_type=str(item.get("creator_type") or ""),
        enabled=item.get("enabled") is True,
        plugin=item.get("plugin") is True,
    )


def _why(raw: Any) -> str:
    """Return why a read failed: a status, the status and the shape, or `no answer`."""
    status = raw.get("status") if isinstance(raw, dict) else None
    if not isinstance(status, int) or not status:
        return NO_ANSWER
    return f"HTTP {status}" if status >= HTTP_ERROR else f"HTTP {status}, {NOT_THE_SHAPE}"
