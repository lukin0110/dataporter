"""Where a source lets a user ask for their data, and the one click that does.

`probe` is the one place that knows what a *chat* looks like; this is the one
place that knows what an *export page* looks like, and it is deliberately a
separate file. Nothing a migration does may reach this page, and nothing the ask
does may reach a chat:

- **A second wall.** A source's extraction surface (`sites.extraction_surface`)
  is the sign-in page and the export page and nothing else — not `/new`, not
  `/chat/<uuid>` — beside `08`'s `MIGRATION_SURFACE`, which does not admit the
  export page. §36 asks for exactly that: the destination session never extracts
  and the source session never imports, and the two lists are how a reader
  checks it in one place each.
- **Its own selectors.** The source's are injected into this module's
  expressions the way `probe` injects its own, and never appended to
  `probe.PRELUDE_JS`: every migration expression, run once per part per
  conversation, would otherwise carry three selectors that only the ask has any
  use for.
- **Two synthesized inputs, both clicks.** `Input.insertText` is never sent from
  this path — there is nothing here to type — and a JavaScript dialog is never
  answered. The ask stops instead, because what such a dialog says is unknown
  (§36: anything else on that page stops).

Since `42` every function here takes the source it acts for, and what a page is
called — its path, its three controls — is the source's to spell
(`sources/claude.py`, later `sources/chatgpt.py`). The module-level constants
are Claude's, kept under the names `31` gave them for the callers and the tests
that spell them.
"""

import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlsplit

from orval import utcnow

from dataporter import log
from dataporter.browser import helpers, sites
from dataporter.browser import probe as probing
from dataporter.browser.cdp import Page
from dataporter.browser.launcher import BrowserSession
from dataporter.browser.probe import PageState
from dataporter.config import Settings
from dataporter.errors import BrowserError, SafetyError
from dataporter.sources.claude import CLAUDE

if TYPE_CHECKING:
    from collections.abc import Callable

    from dataporter.sources.base import Source

_logger = log.get_logger(__name__)

# --------------------------------------------------------------------------- #
# Claude's, by the names `31` gave them
# --------------------------------------------------------------------------- #

EXPORT_PAGE_PATH = CLAUDE.export_page_path
EXPORT_PAGE_URL = sites.export_page_url(CLAUDE)
EXPORT_BUTTON_SELECTOR = CLAUDE.selectors["EXPORT_BUTTON_SELECTOR"]
CONFIRM_BUTTON_SELECTOR = CLAUDE.selectors["CONFIRM_BUTTON_SELECTOR"]
REQUESTED_SELECTOR = CLAUDE.selectors["REQUESTED_SELECTOR"]
EXTRACTION_SITE = sites.extraction_site(CLAUDE)
EXTRACTION_SURFACE = sites.extraction_surface(CLAUDE)
NOT_THE_EXPORT_PAGE = sites.not_the_export_page(CLAUDE)
"""Claude's spellings, read off its source: the path, the URL, the three
controls, the site a trace describes and §36's wall. Each is one object with
what `sites` derives, so a test that asks `is` gets the same answer as a
caller that asks `sites` directly."""

EXPORT_PAGE_TAG = "dataporter:export_page"
CLICK_TAG = "dataporter:click"


def expression(source: "Source", tag: str, body: str) -> str:
    """Return one expression: `probe`'s prelude, this source's selectors, then `body`.

    Public since `44`, which reads the landing page with the same consts.
    """
    consts = "".join(f"  const {name} = {json.dumps(value)};\n" for name, value in source.selectors.items())
    return probing.expression(tag, consts + body)


def export_page_js(source: "Source") -> str:
    """Return the expression that reads the whole page: one round trip, four booleans.

    One evaluate for the reason `probe` makes one: a poll that asked four
    questions would be describing four moments of a page that is changing under
    it, and "the dialog is open" and "its confirm button is there" have to be
    true together for the second click to be the click this thinks it is.
    """
    return expression(
        source,
        EXPORT_PAGE_TAG,
        "  const shown = (selector) => all(selector).filter(visible).length > 0;\n"
        "  return {\n"
        "    button: shown(EXPORT_BUTTON_SELECTOR),\n"
        "    dialog: all('[role=\"dialog\"]').filter(visible).length > 0,\n"
        "    confirm: shown(CONFIRM_BUTTON_SELECTOR),\n"
        "    requested: shown(REQUESTED_SELECTOR),\n"
        "  };",
    )


EXPORT_PAGE_JS = export_page_js(CLAUDE)


def click_js(selector: str, *, source: "Source" = CLAUDE) -> str:
    """Click the first visible element matching `selector`.

    `element.click()` through `Runtime.evaluate`, beside `login_form`'s
    `focus_field_js` and for the same reasons: the selector is ours, it is a
    `const` on a line of its own so the test suite's fake browser can read it
    back, and what crosses the wire is the selector and never what the element
    says. `false` when nothing visible matches, so a click is reported by
    whether it happened rather than by the call returning.
    """
    return expression(
        source,
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
    """`export_page_js`'s four booleans, and the dialogs beside them.

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
    def read(cls, page: Page, source: "Source" = CLAUDE) -> "ExportPageView":
        raw = page.evaluate(export_page_js(source))
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

OFF_SURFACE = "the browser left the extraction surface for {where}"
"""The wall refused the page the tab is on. Named with where it went, because
the whole difficulty of a page that moves under a click is knowing where to."""


def where_of(url: str) -> str:
    """Return a URL's path and fragment, which is what may be said about it.

    Never the query: §66 keeps one out of everything this tool records, and a
    refusal an operator reads is no different. The fragment is kept because on a
    site that routes in one it is the only thing that says which screen.
    """
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        # `about:blank` parses to the path `blank`, which names nothing an
        # operator would recognise. Anything not a web page is said whole.
        return url
    return f"{parsed.path}#{parsed.fragment}" if parsed.fragment else (parsed.path or "/")


NO_TAB = "no tab on {host} for the ask"
"""The tab the ask came for is not there. Named for the source's host and never
for the program (ADR 0004): `helpers.NO_CLAUDE_TAB` is the migration helpers'
wire token, and a ChatGPT ask has no business reporting it."""

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


def signed_out(state: PageState, source: "Source" = CLAUDE) -> bool:
    """Whether the export page sent us somewhere signed out instead.

    Not `state.logged_in`, which is `07`'s question about a *chat*: it reads a
    composer, and a settings page has none, so a signed-in export page would
    answer "signed out" and an ask on a perfectly good session would go looking
    for credentials. What a signed-out request for this page produces is a
    redirect — to `/login` on claude.ai, which is the `signed out` row of
    `docs/claude-ui-map.md` asked of a different URL; to the site's root with no
    composer on it for a source whose landing page is that (§65), which is the
    `signed out` row of its own map.
    """
    if state.kind is probing.PageKind.LOGIN:
        return True
    return source.signed_out_at_root and state.kind is probing.PageKind.NEW_CHAT and not state.composer_present


def request_export(
    settings: Settings,
    session: BrowserSession,
    *,
    source: "Source" = CLAUDE,
    poll_s: float = ASK_POLL_S,
) -> AskResult:
    """Press the vendor's button, confirm if it asks, and watch for the answer.

    The whole of what this tool does inside a source account (§36). Everything
    before it — the browser, the sign-in — is `extract.ask`'s, and everything
    after it is a record in the account home.
    """
    surface = sites.extraction_surface(source)
    deadline = time.monotonic() + settings.timeouts.ask_s
    _bring_to_export_page(session, source, deadline=deadline, poll_s=poll_s)
    tab = helpers.chosen_tab(session.client, surface=surface)
    if isinstance(tab, helpers.Failure):
        raise BrowserError(detail=str(tab.error))

    with helpers.driving(session.client, tab, surface) as page:
        view = ExportPageView.read(page, source)
        if view.dialogs:
            return _stopped(JS_DIALOG)
        if not view.button:
            helpers.record_step(settings, BUTTON_ACTION, ok=False, url=page.url)
            return _stopped(BUTTON_NOT_FOUND)

        pressed_at = _click(settings, page, source, source.selectors["EXPORT_BUTTON_SELECTOR"], BUTTON_ACTION)
        clicks = [BUTTON_ACTION]
        while True:
            view = ExportPageView.read(page, source)
            if view.dialogs:
                # Never answered: what it asks is unknown, and `Page.
                # handleJavaScriptDialog` would be answering it blind.
                return _stopped(JS_DIALOG, pressed_at, clicks)
            if view.requested:
                _logger.info(
                    "export requested",
                    extra={"source": settings.source, "clicks": len(clicks)},
                )
                return AskResult(requested=True, pressed_at=pressed_at, clicks=tuple(clicks))
            if view.dialog and view.confirm and CONFIRM_ACTION not in clicks:
                _click(settings, page, source, source.selectors["CONFIRM_BUTTON_SELECTOR"], CONFIRM_ACTION)
                clicks.append(CONFIRM_ACTION)
                # Straight round again rather than through the sleep: the page
                # has just been acted on, and the answer may already be there.
                continue
            if time.monotonic() >= deadline:
                return _stopped(NOT_REQUESTED, pressed_at, clicks)
            time.sleep(poll_s)


def _stopped(reason: str, pressed_at: datetime | None = None, clicks: list[str] | None = None) -> AskResult:
    """Return an ask that did not get its confirmation, and why."""
    _logger.info("export not requested", extra={"reason": reason})
    return AskResult(blocked=reason, pressed_at=pressed_at, clicks=tuple(clicks or ()))


def _click(settings: Settings, page: Page, source: "Source", selector: str, action: str) -> datetime:
    """Click, record it, and answer with the moment it happened.

    The live URL is checked immediately before the click and not only when the
    tab was attached to, and it is checked against the *page* and not only
    against the wall. The wall admits the sign-in — it has to, because that is
    where a signed-out request for the export page lands — so "inside the
    extraction surface" is not the same statement as "this is the page the
    button is on". A session that expired between the look and the click would
    otherwise have this pressing whatever a sign-in page happens to have where
    the confirm button was, and a confirm selector is generic enough to find
    one. (Raised by Copilot in review on #44.)
    """
    surface = sites.extraction_surface(source)
    url = page.url
    try:
        helpers.guard(url, surface)
    except SafetyError as exc:
        # The rail still fires and nothing after it runs; what changes is that an
        # operator is told where the tab went. A bare `SafetyError` out of here
        # reaches the CLI as `internal error: SafetyError`, which is the least
        # useful thing a wall can say about a page that moved under it.
        raise BrowserError(detail=OFF_SURFACE.format(where=where_of(url))) from exc
    if not on_export_page(url, source):
        raise BrowserError(detail=sites.not_the_export_page(source))
    before = helpers.sketch_of(page, surface)
    started = time.monotonic()
    clicked = page.evaluate(click_js(selector, source=source)) is True
    elapsed_ms = round((time.monotonic() - started) * 1000)
    helpers.record_step(
        settings,
        action,
        ok=clicked,
        url=url,
        selector=selector,
        elapsed_ms=elapsed_ms,
        before=before,
        after=helpers.sketch_of(page, surface),
    )
    if not clicked:  # pragma: no cover - the view said it was there a moment ago
        raise BrowserError(detail=f"{action} could not be clicked")
    # To the second: the stamp the snapshot is filed under is to the second, and
    # a moment with microseconds in it would be a precision nothing else keeps.
    return utcnow().replace(microsecond=0)


def _bring_to_export_page(session: BrowserSession, source: "Source", *, deadline: float, poll_s: float) -> None:
    """Point the tab at the export page, and wait until it is showing it.

    The one CDP call the ask makes on a page outside the extraction surface, and
    it is the navigation *into* it: after an interactive sign-in the tab is
    wherever the site left the person — `/new`, on claude.ai — and
    `helpers.driving` refuses to attach to that, which is the point. So this
    attaches, navigates and lets go, and every read and every click after it
    happens under the wall.

    Then it waits twice, because a navigation lands in two places at two
    moments: the page's own `location.href`, which is what the tab is really
    showing, and the target list, which is the stale copy `chosen_tab` and
    `driving` read next. `Page.navigate` returns before either. Waiting only for
    the second would leave the ask reading a page the list merely believes in.
    """
    surface = sites.extraction_surface(source)
    tabs = helpers.surface_tabs(session.client, surface)
    if not tabs:
        raise BrowserError(detail=NO_TAB.format(host=source.host))
    page = session.client.attach(tabs[0].id)
    try:
        if not on_export_page(page.url, source):
            page.navigate(sites.export_page_url(source))
        _wait_until(lambda: on_export_page(page.url, source), deadline, poll_s, source)
    finally:
        page.close()
    _wait_until(_listed(session, source), deadline, poll_s, source)


def _listed(session: BrowserSession, source: "Source") -> "Callable[[], bool]":
    """Whether the *target list* has the tab on the export page yet."""

    def looked() -> bool:
        tabs = helpers.surface_tabs(session.client, sites.extraction_surface(source))
        return bool(tabs) and on_export_page(tabs[0].url, source)

    return looked


def _wait_until(answered: "Callable[[], bool]", deadline: float, poll_s: float, source: "Source") -> None:
    """Poll until it is true, or give up on the ask's own deadline."""
    while True:
        if answered():
            return
        if time.monotonic() >= deadline:
            raise BrowserError(detail=sites.not_the_export_page(source))
        time.sleep(poll_s)


def on_export_page(url: str, source: "Source" = CLAUDE) -> bool:
    """Whether this URL *is* the export page, rather than merely allowed on the surface.

    The sign-in page is inside the surface too, and so is wherever the site
    leaves a person once they are through it, so "the wall admits this" is not
    the question the navigation asks.

    Path *and* fragment, since `51`: claude.ai serves the export page at a
    fragment of its app (§77), so `/new` and `/new#settings/data-privacy-controls`
    are the app page and the export page, and a check that looked only at the
    path could not tell a person who has just signed in — and been left on
    `/new` — from one already looking at the panel.

    The address *or a screen under it*: claude.ai's export is two screens, the
    panel and `…/export-data`, and the second click happens on the second one. A
    check that accepted only the address refused to press the button that asks.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    path = parsed.path or "/"
    address = f"{path}#{parsed.fragment}" if parsed.fragment else path
    target = source.export_page_path
    return address == target or address.startswith(f"{target}/")
