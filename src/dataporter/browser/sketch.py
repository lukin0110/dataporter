"""The page in outline (brief `04` §45, `34`).

A probe reports a page as booleans, which is the right answer for an agent
deciding its next step and the wrong one for a person deciding why the composer
was not found: "false" says nothing about what *was* there. A sketch does — its
path, its controls by role and label, everything else by role and shape — and
carries no message, title or address by construction.

## Where the labels stop

The accessibility tree is the page as a person meets it: roles and names, no
markup. A **control** — what a person presses, types into or is told by —
keeps its name, through `log.safe_token` and a limit, because a control's name
is the site's chrome and is what the mock has to reproduce. Everything else
that shapes a page — a heading, a link, a list item, an image, a landmark —
keeps its role, the length of its name and a short hash of it, never the name:
a sidebar link is a conversation's title, a heading is one too, a list item is
a message. A run of the same shaped role collapses to a count. Every other
role is skipped, and its children are still walked.

The line is drawn on the role and not on the text, so it cannot be argued with
one label at a time. The one label that can carry content — a button named
after a conversation — is `34`'s first risk, and the first real trace is read
end to end before it is committed (§49).

## Where a sketch may look

Anywhere the tab is. A sketch sends no input and navigates nowhere; the wall
(ADR 0001) is a rule about hands, and `helpers.driving` has already applied it
before the first sketch is taken. What a sketch of an off-surface page shows is
exactly the evidence the UI map's `signed out` row wants.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from orval import deep_get
from pydantic import BaseModel, ConfigDict

from dataporter import log
from dataporter import trace as tracing
from dataporter.browser import probe as probing
from dataporter.browser.cdp import Page
from dataporter.browser.site import Site

LABELLED_ROLES: tuple[str, ...] = (
    "button",
    "textbox",
    "searchbox",
    "combobox",
    "checkbox",
    "radio",
    "switch",
    "menuitem",
    "menuitemcheckbox",
    "menuitemradio",
    "tab",
    "dialog",
    "alertdialog",
    "alert",
    "status",
    "progressbar",
)
"""The controls: these keep their accessible name, as `label`."""

SHAPED_ROLES: tuple[str, ...] = (
    "heading",
    "link",
    "list",
    "listitem",
    "image",
    "table",
    "main",
    "navigation",
    "banner",
    "contentinfo",
    "complementary",
    "region",
    "article",
    "form",
)
"""The shape: these keep their role, the length of their name and a hash of
it. `image`, not `img`: roles are the accessibility tree's own names, as CDP
reports them."""

TEXT_ROLES: tuple[str, ...] = ("textbox", "searchbox")
"""The two controls whose value is content: they report `chars`, never the value."""

LABEL_LIMIT = 80
ROOT_ROLE = "RootWebArea"
"""The document's own node, whose name is its title. Reported as `title_chars`."""

HASH_LENGTH = 12
SELECTORS_TAG = "dataporter:selectors"


class Sketch(BaseModel):
    """One page in outline. Frozen: its hash is its name."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    query: tuple[str, ...]
    title_chars: int
    controls: tuple[dict[str, Any], ...]
    selectors: dict[str, int]
    dialogs: tuple[str, ...]

    @property
    def hash(self) -> str:
        """The first twelve hex digits of the SHA-256 of the canonical fields."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:HASH_LENGTH]

    def fields(self) -> dict[str, Any]:
        """Return the line's fields in the brief's order, `hash` first."""
        return {
            "hash": self.hash,
            "path": self.path,
            "query": list(self.query),
            "title_chars": self.title_chars,
            "controls": [dict(control) for control in self.controls],
            "selectors": dict(self.selectors),
            "dialogs": list(self.dialogs),
        }


# --------------------------------------------------------------------------- #
# The outline, from a tree
# --------------------------------------------------------------------------- #


def name_hash(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:HASH_LENGTH]


def _disabled(node: dict[str, Any]) -> bool:
    for item in node.get("properties") or ():
        if item.get("name") == "disabled" and deep_get(item, "value.value") is True:
            return True
    return False


def _labelled(role: str, name: str, node: dict[str, Any]) -> dict[str, Any]:
    control: dict[str, Any] = {"role": role, "label": log.safe_token(name, LABEL_LIMIT) if name else ""}
    if _disabled(node):
        control["disabled"] = True
    if role in TEXT_ROLES:
        control["chars"] = len(str(deep_get(node, "value.value") or ""))
    return control


def _shaped(controls: list[dict[str, Any]], role: str, name: str) -> None:
    """Append a shaped node, or fold it into the run of its role before it."""
    previous = controls[-1] if controls else None
    if previous is not None and previous.get("role") == role and "label" not in previous:
        if "count" in previous:
            previous["count"] += 1
            previous["chars"] += len(name)
        else:
            controls[-1] = {"role": role, "count": 2, "chars": previous["chars"] + len(name)}
        return
    controls.append({"role": role, "chars": len(name), "hash": name_hash(name)})


def outline(nodes: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Return the controls in document order, and the title's length.

    `nodes` is `Accessibility.getFullAXTree`'s list, which is in tree order;
    an `ignored` node is skipped and its children are not, since they are
    listed on their own.
    """
    title_chars = 0
    controls: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("ignored"):
            continue
        role = str(deep_get(node, "role.value") or "")
        name = str(deep_get(node, "name.value") or "")
        if role == ROOT_ROLE:
            title_chars = len(name)
        elif role in LABELLED_ROLES:
            controls.append(_labelled(role, name, node))
        elif role in SHAPED_ROLES:
            _shaped(controls, role, name)
    return controls, title_chars


# --------------------------------------------------------------------------- #
# Taking one
# --------------------------------------------------------------------------- #


def selectors_js(site: Site) -> str:
    """One expression counting what each of the site's selectors finds.

    A count of what is there, visible or not: the UI map's middle column is a
    list of selectors nobody has tested on the real page, and the honest report
    is how many elements each finds. A selector the page's engine refuses
    counts `-1`.
    """
    table = json.dumps(dict(site.selectors), ensure_ascii=False)
    return (
        f"/* {SELECTORS_TAG} */\n"
        "(() => {\n"
        f"  const table = {table};\n"
        "  const counts = {};\n"
        "  for (const [name, selector] of Object.entries(table)) {\n"
        "    try {\n"
        "      counts[name] = document.querySelectorAll(selector).length;\n"
        "    } catch (error) {\n"
        "      counts[name] = -1;\n"
        "    }\n"
        "  }\n"
        "  return counts;\n"
        "})()"
    )


def take(page: Page, site: Site) -> Sketch:
    """Sketch the page the connection is on.

    Reads and counts, and nothing else: `Accessibility.enable` (idempotent,
    once per call rather than tracked per connection), the full tree, one
    evaluate for the selector counts, the pending dialogs `probe` already
    tracks, and the live URL.
    """
    page.send("Accessibility.enable")
    tree = page.send("Accessibility.getFullAXTree")
    nodes = tree.get("nodes")
    controls, title_chars = outline(nodes if isinstance(nodes, list) else [])
    counted = page.evaluate(selectors_js(site))
    counts = counted if isinstance(counted, Mapping) else {}
    selectors = {
        name: int(counts[name]) if isinstance(counts.get(name), int) and not isinstance(counts.get(name), bool) else 0
        for name in site.selectors
    }
    located = tracing.url_fields(page.url)
    return Sketch(
        path=located["path"],
        query=tuple(located["query"]),
        title_chars=title_chars,
        controls=tuple(controls),
        selectors=selectors,
        dialogs=tuple(probing.pending_dialogs(page)),
    )
