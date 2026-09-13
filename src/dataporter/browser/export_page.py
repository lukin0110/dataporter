"""Where claude.ai lets a user ask for their data, and the one click that does.

`probe` is the one place that knows what a *chat* looks like; this is the one
place that knows what the *export page* looks like, and it is deliberately a
separate file. Nothing a migration does may reach this page, and nothing the ask
does may reach a chat:

- **A second wall.** `EXTRACTION_SURFACE` is the sign-in page and the export page
  and nothing else — not `/new`, not `/chat/<uuid>` — beside `08`'s
  `MIGRATION_SURFACE`, which does not admit the export page. §36 asks for exactly
  that: the destination session never extracts and the source session never
  imports, and the two lists are how a reader checks it in one place each.
- **Its own selectors.** They are injected into this module's expressions the way
  `probe` injects its own, and never appended to `probe.PRELUDE_JS`: every
  migration expression, run once per part per conversation, would otherwise carry
  three selectors that only the ask has any use for.
- **Two synthesized inputs, both clicks.** `Input.insertText` is never sent from
  this path — there is nothing here to type — and a JavaScript dialog is never
  answered. The ask stops instead, because what such a dialog says is unknown
  (§36: anything else on that page stops).

Every row this module depends on is `*unknown*` in `docs/claude-ui-map.md`: the
page's path, the button, whether a confirmation follows, and what the page shows
when the request was accepted. The first real ask is what corrects them, and the
four constants below are what it corrects — one line each.
"""

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from orval import utcnow

from dataporter import log
from dataporter.browser import helpers
from dataporter.browser import probe as probing
from dataporter.browser.cdp import Page
from dataporter.browser.helpers import Surface
from dataporter.browser.launcher import BrowserSession
from dataporter.browser.probe import CLAUDE_HOST, PageState
from dataporter.config import Settings
from dataporter.errors import BrowserError

_logger = log.get_logger(__name__)

EXPORT_PAGE_PATH = "/settings/data-privacy-controls"
"""Where claude.ai lets a user ask for their data.

A placeholder, spelled once, here: nobody has looked, and `docs/claude-ui-map.md`
carries the row as `*unknown*`. Everything else in this module — the URL, the
surface that admits it, the message that names it — is built from this string, so
the observation that corrects it is one edit.
"""

EXPORT_PAGE_URL = f"https://{CLAUDE_HOST}{EXPORT_PAGE_PATH}"

EXTRACTION_SURFACE = Surface(
    host=CLAUDE_HOST,
    allowed=re.compile(
        rf"^https://claude\.ai/(login(/.*)?|{re.escape(EXPORT_PAGE_PATH.lstrip('/'))})"
        r"(\?.*)?$"
    ),
)
"""§36's wall for the ask: the sign-in page, and the page the export is asked for.

Two doors and no more. `/new` is not one of them — an extraction that could open
a new chat is an extraction that could send a message — and neither is
`/chat/<uuid>`. Passed to `helpers.driving` by this module and nothing else, so
every helper Hermes can run still refuses this page under `MIGRATION_SURFACE`.
"""

# --------------------------------------------------------------------------- #
# What an element of the export page is called
# --------------------------------------------------------------------------- #

EXPORT_BUTTON_SELECTOR = '[data-testid="export-data"], button[aria-label="Export data"]'
"""The control that asks the vendor for the account's data."""

CONFIRM_BUTTON_SELECTOR = (
    '[role="dialog"] [data-testid="confirm-export"], '
    '[role="dialog"] button[type="submit"]'
)
"""The confirmation inside whatever dialog the button opens, if it opens one."""

REQUESTED_SELECTOR = '[data-testid="export-requested"], [role="status"]'
"""What the page shows once the request has been accepted.

Read as an element that is there, never as the sentence it holds: this module
obeys `probe`'s rule that nothing off the page crosses the wire, and "the request
was accepted" is a fact about the page rather than a message from it.
"""

_SELECTORS: tuple[tuple[str, str], ...] = (
    ("EXPORT_BUTTON_SELECTOR", EXPORT_BUTTON_SELECTOR),
    ("CONFIRM_BUTTON_SELECTOR", CONFIRM_BUTTON_SELECTOR),
    ("REQUESTED_SELECTOR", REQUESTED_SELECTOR),
)
"""The three, as JavaScript consts, injected into this module's expressions —
`probe`'s own discipline, applied to the page `probe` knows nothing about."""

EXPORT_PAGE_TAG = "dataporter:export_page"
CLICK_TAG = "dataporter:click"


def _expression(tag: str, body: str) -> str:
    """One expression: `probe`'s prelude, this page's selectors, then `body`."""
    consts = "".join(
        f"  const {name} = {json.dumps(value)};\n" for name, value in _SELECTORS
    )
    return probing.expression(tag, consts + body)


EXPORT_PAGE_JS = _expression(
    EXPORT_PAGE_TAG,
    "  const shown = (selector) => all(selector).filter(visible).length > 0;\n"
    "  return {\n"
    "    button: shown(EXPORT_BUTTON_SELECTOR),\n"
    "    dialog: all('[role=\"dialog\"]').filter(visible).length > 0,\n"
    "    confirm: shown(CONFIRM_BUTTON_SELECTOR),\n"
    "    requested: shown(REQUESTED_SELECTOR),\n"
    "  };",
)
"""The whole of the page, in one round trip and four booleans.

One evaluate for the reason `probe` makes one: a poll that asked four questions
would be describing four moments of a page that is changing under it, and
"the dialog is open" and "its confirm button is there" have to be true together
for the second click to be the click this thinks it is.
"""


def click_js(selector: str) -> str:
    """Click the first visible element matching `selector`.

    `element.click()` through `Runtime.evaluate`, beside `login_form`'s
    `focus_field_js` and for the same reasons: the selector is ours, it is a
    `const` on a line of its own so the test suite's fake browser can read it
    back, and what crosses the wire is the selector and never what the element
    says. `false` when nothing visible matches, so a click is reported by
    whether it happened rather than by the call returning.
    """
    return _expression(
        CLICK_TAG,
        f"  const selector = {json.dumps(selector)};\n"
        "  const el = all(selector).filter(visible)[0] || null;\n"
        "  if (el === null) return false;\n"
        "  el.click();\n"
        "  return true;",
    )


# --------------------------------------------------------------------------- #
# What one look at the export page saw
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ExportPageView:
    """`EXPORT_PAGE_JS`'s four booleans, and the dialogs beside them.

    Tolerant of a page that answers with something else — an error page, a
    document that has not rendered — for the reason `probe.LastMessage.from_raw`
    is: "no button" is what an unrendered page should read as, and an exception
    out of a poll is not.
    """

    button: bool = False
    dialog: bool = False
    confirm: bool = False
    requested: bool = False
    dialogs: tuple[str, ...] = ()

    @classmethod
    def read(cls, page: Page) -> "ExportPageView":
        raw = page.evaluate(EXPORT_PAGE_JS)
        if not isinstance(raw, dict):  # pragma: no cover - defensive
            raw = {}
        return cls(
            button=bool(raw.get("button")),
            dialog=bool(raw.get("dialog")),
            confirm=bool(raw.get("confirm")),
            requested=bool(raw.get("requested")),
            dialogs=tuple(probing.pending_dialogs(page)),
        )


JS_DIALOG = "js_dialog"
BUTTON_NOT_FOUND = "button_not_found"
NOT_REQUESTED = "not_requested"
"""Why an ask stopped. Stable strings: `extract` turns each into the line an
operator reads, and a log record carries this rather than the prose."""

BUTTON_ACTION = "export-button"
CONFIRM_ACTION = "export-confirm"
"""What `logs/actions.jsonl` calls the two clicks. Named like `08`'s helpers
because `19` counts the same file, and an ask is two browser actions."""

ASK_POLL_S = 0.5
"""How often the page is asked whether the request went through. Half a second:
the answer is a re-render rather than a generation, and the whole wait is
`timeouts.ask_s`."""


@dataclass(frozen=True)
class AskResult:
    """What the ask amounted to: the moment of the press, or why there was none.

    `pressed_at` is the moment the *export* button was clicked, to the second,
    because that is the moment the account was as the export will describe it —
    §33's stamp, and what `ask.json` keeps. `clicks` is what was clicked, in
    order, so a test can prove that an ask is two clicks and nothing else.
    """

    requested: bool = False
    blocked: str | None = None
    pressed_at: datetime | None = None
    clicks: tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# The ask
# --------------------------------------------------------------------------- #


def signed_out(state: PageState) -> bool:
    """Whether the export page sent us to the sign-in page instead.

    Not `state.logged_in`, which is `07`'s question about a *chat*: it reads a
    composer, and a settings page has none, so a signed-in export page would
    answer "signed out" and an ask on a perfectly good session would go looking
    for credentials. What a signed-out request for this page produces is a
    redirect to `/login`, and that is what this reads — the same signal the
    `signed out` row of `docs/claude-ui-map.md` already describes, asked of a
    different URL.
    """
    return state.kind is probing.PageKind.LOGIN


def request_export(
    settings: Settings, session: BrowserSession, *, poll_s: float = ASK_POLL_S
) -> AskResult:
    """Press the vendor's button, confirm if it asks, and watch for the answer.

    The whole of what this tool does inside a source account (§36). Everything
    before it — the browser, the sign-in — is `extract.ask`'s, and everything
    after it is a record in the account home.
    """
    deadline = time.monotonic() + settings.timeouts.ask_s
    _bring_to_export_page(session, deadline=deadline, poll_s=poll_s)
    tab = helpers.chosen_tab(session.client, surface=EXTRACTION_SURFACE)
    if isinstance(tab, helpers.Failure):
        raise BrowserError(detail=str(tab.error))

    with helpers.driving(session.client, tab, EXTRACTION_SURFACE) as page:
        view = ExportPageView.read(page)
        if view.dialogs:
            return _stopped(JS_DIALOG)
        if not view.button:
            _record(settings, BUTTON_ACTION, ok=False, url=page.url)
            return _stopped(BUTTON_NOT_FOUND)

        pressed_at = _click(settings, page, EXPORT_BUTTON_SELECTOR, BUTTON_ACTION)
        clicks = [BUTTON_ACTION]
        while True:
            view = ExportPageView.read(page)
            if view.dialogs:
                # Never answered: what it asks is unknown, and `Page.
                # handleJavaScriptDialog` would be answering it blind.
                return _stopped(JS_DIALOG, pressed_at, clicks)
            if view.requested:
                _logger.info(
                    "export requested",
                    extra={"source": settings.source, "clicks": len(clicks)},
                )
                return AskResult(
                    requested=True, pressed_at=pressed_at, clicks=tuple(clicks)
                )
            if view.dialog and view.confirm and CONFIRM_ACTION not in clicks:
                _click(settings, page, CONFIRM_BUTTON_SELECTOR, CONFIRM_ACTION)
                clicks.append(CONFIRM_ACTION)
                # Straight round again rather than through the sleep: the page
                # has just been acted on, and the answer may already be there.
                continue
            if time.monotonic() >= deadline:
                return _stopped(NOT_REQUESTED, pressed_at, clicks)
            time.sleep(poll_s)


def _stopped(
    reason: str, pressed_at: datetime | None = None, clicks: list[str] | None = None
) -> AskResult:
    """An ask that did not get its confirmation, and why."""
    _logger.info("export not requested", extra={"reason": reason})
    return AskResult(blocked=reason, pressed_at=pressed_at, clicks=tuple(clicks or ()))


def _click(settings: Settings, page: Page, selector: str, action: str) -> datetime:
    """Click, record it, and answer with the moment it happened.

    The live URL is checked immediately before the click and not only when the
    tab was attached to: a session that expired between the two would have this
    synthesizing an input on a sign-in page — which the surface admits, and which
    has nothing on it anybody asked us to press.
    """
    url = page.url
    helpers.guard(url, EXTRACTION_SURFACE)
    started = time.monotonic()
    clicked = page.evaluate(click_js(selector)) is True
    _record(
        settings,
        action,
        ok=clicked,
        url=url,
        selector=selector,
        elapsed_ms=round((time.monotonic() - started) * 1000),
    )
    if not clicked:  # pragma: no cover - the view said it was there a moment ago
        raise BrowserError(detail=f"{action} could not be clicked")
    # To the second: the stamp the snapshot is filed under is to the second, and
    # a moment with microseconds in it would be a precision nothing else keeps.
    return utcnow().replace(microsecond=0)


def _record(
    settings: Settings,
    action: str,
    *,
    ok: bool,
    url: str,
    selector: str | None = None,
    elapsed_ms: int = 0,
) -> None:
    """One line in the account home's `logs/actions.jsonl`.

    The page's URL and the selector, never the element's text: §38 keeps
    everything the tool writes *about* an account to numbers, labels and our own
    strings.
    """
    helpers.record_action(
        Path(settings.logs_dir),
        action,
        ok=ok,
        elapsed_ms=elapsed_ms,
        url=url,
        selector=selector,
    )


NOT_THE_EXPORT_PAGE = f"the browser did not arrive at {EXPORT_PAGE_PATH}"


def _bring_to_export_page(
    session: BrowserSession, *, deadline: float, poll_s: float
) -> None:
    """Point the tab at the export page, and wait until it is showing it.

    The one CDP call the ask makes on a page outside the extraction surface, and
    it is the navigation *into* it: after an interactive sign-in the tab is
    wherever claude.ai left the person — `/new`, as it happens — and
    `helpers.driving` refuses to attach to that, which is the point. So this
    attaches, navigates and lets go, and every read and every click after it
    happens under the wall.

    Then it waits twice, because a navigation lands in two places at two
    moments: the page's own `location.href`, which is what the tab is really
    showing, and the target list, which is the stale copy `chosen_tab` and
    `driving` read next. `Page.navigate` returns before either. Waiting only for
    the second would leave the ask reading a page the list merely believes in.
    """
    tabs = helpers.surface_tabs(session.client, EXTRACTION_SURFACE)
    if not tabs:
        raise BrowserError(detail=helpers.NO_CLAUDE_TAB)
    page = session.client.attach(tabs[0].id)
    try:
        if not on_export_page(page.url):
            page.navigate(EXPORT_PAGE_URL)
        _wait_until(lambda: on_export_page(page.url), deadline, poll_s)
    finally:
        page.close()
    _wait_until(_listed(session), deadline, poll_s)


def _listed(session: BrowserSession) -> "Callable[[], bool]":
    """Whether the *target list* has the tab on the export page yet."""

    def looked() -> bool:
        tabs = helpers.surface_tabs(session.client, EXTRACTION_SURFACE)
        return bool(tabs) and on_export_page(tabs[0].url)

    return looked


def _wait_until(answered: "Callable[[], bool]", deadline: float, poll_s: float) -> None:
    """Poll until it is true, or give up on the ask's own deadline."""
    while True:
        if answered():
            return
        if time.monotonic() >= deadline:
            raise BrowserError(detail=NOT_THE_EXPORT_PAGE)
        time.sleep(poll_s)


def on_export_page(url: str) -> bool:
    """Whether this URL *is* the export page, rather than merely allowed on the
    surface.

    The sign-in page is inside the surface too, and so is wherever claude.ai
    leaves a person once they are through it, so "the wall admits this" is not
    the question the navigation asks.
    """
    return probing.path_of(url) == EXPORT_PAGE_PATH
