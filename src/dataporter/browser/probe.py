"""The one place that knows what claude.ai looks like.

Everything else in this package is about *a* browser. This module is about *the*
page: which of the four states it is in, whether a composer is there, whether
Claude is generating, whether something is in the way. `08`'s helpers, `11`'s
step protocol and `17`'s verification all decide by reading a `PageState`, so
when the UI changes, this file is the one that changes.

Two rules shape it:

- **Nothing here reads content.** `composer_chars` is a length; `dialogs` names a
  kind, never a message; nothing returns a title or a message body. §10 forbids
  content on stdout and in logs, and `08` prints this object to stdout verbatim.
- **One round trip.** The whole DOM question is a single `Runtime.evaluate`, so a
  probe cannot observe a half-changed page across several calls, and polling
  every two seconds for ten minutes costs 300 CDP calls rather than 1,800.

`10` is the slice that checks these signals against the real application and
owns the selectors from then on. Until it does, they are informed guesses and
are written here in one place so that correcting them is a small edit.
"""

import re
from enum import StrEnum
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from dataporter import log
from dataporter.browser.cdp import Page

_logger = log.get_logger(__name__)

CLAUDE_HOST = "claude.ai"
NEW_CHAT_URL = f"https://{CLAUDE_HOST}/new"

_CHAT_PATH = re.compile(
    r"^/chat/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?$",
    re.IGNORECASE,
)
_NEW_CHAT_PATHS = frozenset({"/", "/new"})

DIALOG_OPENING = "Page.javascriptDialogOpening"
DIALOG_CLOSED = "Page.javascriptDialogClosed"

PAGE_STATE_JS = """
(() => {
  const visible = (el) =>
    !!el &&
    (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0);
  const all = (selector) =>
    Array.prototype.slice.call(document.querySelectorAll(selector));
  const composer = all('div[contenteditable="true"]').filter(visible)[0] || null;
  const buttons = all('button').filter(visible);
  const label = (b) => (b.getAttribute('aria-label') || '') + '';
  const labelled = (needle) =>
    buttons.filter((b) => label(b).indexOf(needle) !== -1);
  const disabled = (b) =>
    b.disabled === true || b.getAttribute('aria-disabled') === 'true';
  return {
    url: location.href,
    composer_present: composer !== null,
    composer_chars: composer === null ? 0 : (composer.innerText || '').length,
    generating: labelled('Stop').length > 0,
    send_enabled: labelled('Send').some((b) => !disabled(b)),
    dom_dialogs: all('[role="dialog"]').filter(visible).length,
  };
})()
"""
"""One expression, one object, no content.

`innerText` and not `textContent`: the composer is a ProseMirror-style
`contenteditable` whose line breaks are elements, and `08` compares a pasted seed
against what the user would see.
"""


class PageKind(StrEnum):
    """Where the browser is, as far as this tool is concerned."""

    LOGIN = "login"
    NEW_CHAT = "new_chat"
    CHAT = "chat"
    OTHER = "other"


class PageState(BaseModel):
    """What one probe saw. `08` prints this as its JSON object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    kind: PageKind
    logged_in: bool
    composer_present: bool
    composer_chars: int
    generating: bool
    send_enabled: bool
    dialogs: tuple[str, ...]
    conversation_id: str | None
    tab_count: int


def path_of(url: str) -> str:
    """The path of an http(s) URL, without the query.

    `""` for everything else — `about:blank`, `chrome://newtab/`, a `file:` URL —
    so that a browser sitting on a blank tab is `other` and never `new_chat`.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return ""
    return parsed.path or "/"


def kind_of(url: str) -> PageKind:
    """Which of the four states a URL names.

    Path only, and never the host: the fixtures the probe is tested against are
    served from `127.0.0.1`, and the rule that keeps the tool on claude.ai is
    `08`'s safety gate, which is a separate thing from reading where we are.
    """
    path = path_of(url)
    if path.startswith("/login"):
        return PageKind.LOGIN
    if path in _NEW_CHAT_PATHS:
        return PageKind.NEW_CHAT
    if _CHAT_PATH.match(path):
        return PageKind.CHAT
    return PageKind.OTHER


def conversation_id_of(url: str) -> str | None:
    """The uuid in `/chat/<uuid>`, or `None`."""
    match = _CHAT_PATH.match(path_of(url))
    return match.group(1) if match else None


def pending_dialogs(page: Page) -> list[str]:
    """The JavaScript dialogs that have opened and not yet closed.

    Kinds only — `alert`, `confirm`, `prompt`, `beforeunload` — never the
    message, which is page text and therefore content. Openings and closings are
    matched by order because CDP gives no dialog identity; a dialog reported as
    open when it is not costs one `07` poll, and the opposite would let a run
    walk into a modal.
    """
    page.drain()
    opened = page.events(DIALOG_OPENING)
    closed = page.events(DIALOG_CLOSED)
    return [
        "javascript:"
        + log.safe_token(str(item.get("params", {}).get("type", "dialog")))
        for item in opened[len(closed) :]
    ]


def probe(page: Page, *, tab_count: int = 1) -> PageState:
    """Read the page. One CDP evaluate, plus whatever events are already queued.

    `tab_count` is the caller's: a page cannot see its siblings, and the count
    that matters — claude.ai tabs — is a question for the target list.
    """
    raw = page.evaluate(PAGE_STATE_JS)
    if not isinstance(raw, dict):  # pragma: no cover - defensive
        raw = {}
    url = str(raw.get("url") or page.target.url)
    kind = kind_of(url)
    composer_present = bool(raw.get("composer_present"))
    dialogs = pending_dialogs(page) + ["dom"] * int(raw.get("dom_dialogs") or 0)
    state = PageState(
        url=url,
        kind=kind,
        # Not "who is logged in": §8 asks for the signed-in *state*, and reading
        # the account would mean reading the page's text.
        logged_in=kind is not PageKind.LOGIN and composer_present,
        composer_present=composer_present,
        composer_chars=int(raw.get("composer_chars") or 0),
        generating=bool(raw.get("generating")),
        send_enabled=bool(raw.get("send_enabled")),
        dialogs=tuple(dialogs),
        conversation_id=conversation_id_of(url),
        tab_count=tab_count,
    )
    # The URL is not logged: a claude.ai chat URL carries only a uuid, but this
    # probe also runs against fixtures and, one day, against a mistyped address.
    _logger.debug(
        "probe",
        extra={
            "kind": str(state.kind),
            "logged_in": state.logged_in,
            "generating": state.generating,
            "dialogs": len(state.dialogs),
        },
    )
    return state
