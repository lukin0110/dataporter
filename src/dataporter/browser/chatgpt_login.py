"""Signing in to ChatGPT without a person, and without a model (`44`, brief `06` §61).

`24`'s unattended sign-in has two halves: an agent brings the tab to the form,
then `login_form` types into it. This is the same second half with a different
first: the shape of chatgpt.com's sign-in is documented — a landing page with a
**Log in** control, then an email step and a password step on
`auth.openai.com`, each with a **Continue** — so the tool walks it itself,
deterministically, and a backup that runs from cron needs no agent and no API
key on this path.

Three rules hold, as they do for `login_form`:

- **One click, two fields, nothing else.** The **Log in** control is clicked
  through `export_page.click_js` — a selector on the wire, never a value — and
  the credentials go in through `login_form.fill_and_submit`, the one module
  that may hold a value. Nothing here reads what a field holds.
- **A page that is not the shape expected stops the walk.** A landing page
  with no **Log in**, an email step that never appears, a code prompt, a
  refused password: each is a `FillResult` with its reason, and `signin` turns
  it into §12's "authentication required", exit `3`, the `login` instruction.
  The auth host's real screens are *unknown* (`docs/chatgpt-ui-map.md`), so
  the first real run is expected to stop here, with a sketch of what it saw.
- **Every step is a move.** The click and the two submits are recorded in the
  account home's `actions.jsonl` and in the trace, selector and URL only, so a
  ChatGPT sign-in leaves what a Claude ask leaves (§67).
"""

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dataporter import log
from dataporter.browser import export_page, helpers, login_form, sites
from dataporter.browser.cdp import Page
from dataporter.browser.launcher import BrowserSession
from dataporter.browser.login_form import FillResult
from dataporter.config import Credentials, Settings
from dataporter.errors import BrowserError

if TYPE_CHECKING:
    from dataporter.browser.helpers import Surface
    from dataporter.sources.base import Source

_logger = log.get_logger(__name__)

LANDING_TAG = "dataporter:chatgpt_landing"
LOGIN_ACTION = "login-button"
"""What `actions.jsonl` and the trace call the one click."""

NO_LOGIN_BUTTON = "no_login_button"
NO_EMAIL_STEP = "no_email_step"
"""Why the walk stopped before a field was typed into: the landing page had no
**Log in**, or the click led to no email step in time. Both are §12's
`auth_required` — the page wants something this tool cannot give."""

POLL_S = 0.5


def landing_js(source: "Source") -> str:
    """Return the expression that reads the landing page: a **Log in** control, or a composer."""
    return export_page.expression(
        source,
        LANDING_TAG,
        "  return {\n"
        "    login_button: all(LOGIN_BUTTON_SELECTOR).filter(visible).length > 0,\n"
        "    composer: composer !== null,\n"
        "  };",
    )


@dataclass(frozen=True)
class Landing:
    """What the site's root is showing: the way in, or the way already in."""

    login_button: bool = False
    composer: bool = False

    @classmethod
    def read(cls, page: Page, source: "Source") -> "Landing":
        raw = page.evaluate(landing_js(source))
        if not isinstance(raw, dict):  # pragma: no cover - defensive
            raw = {}
        return cls(login_button=bool(raw.get("login_button")), composer=bool(raw.get("composer")))


def walk(
    settings: Settings,
    session: BrowserSession,
    source: "Source",
    credentials: Credentials,
    *,
    poll_s: float = POLL_S,
) -> FillResult:
    """Sign the session in the way the site documents, or say where it stopped.

    The tab is wherever `launch` or the probe left it — the root, for a
    signed-out account — and the wall is the sign-in's (`sites.login_surface`),
    which admits the root, the sign-in's own paths and the whole of the auth
    host, and nothing else on the site.
    """
    surface = sites.login_surface(source)
    deadline = time.monotonic() + settings.timeouts.signin_s
    target = login_form.login_tab(session, surface)
    if target is None:
        return FillResult(signed_in=False, blocked=login_form.NO_TAB)
    with helpers.driving(session.client, target, surface) as page:
        landing = Landing.read(page, source)
        if landing.composer:
            return FillResult(signed_in=True)
        if not landing.login_button:
            _logger.info("sign-in walk stopped", extra={"reason": NO_LOGIN_BUTTON})
            return FillResult(signed_in=False, blocked=NO_LOGIN_BUTTON)
        _click(settings, page, source, surface)
    if not _await_form(session, surface, deadline=deadline, poll_s=poll_s):
        _logger.info("sign-in walk stopped", extra={"reason": NO_EMAIL_STEP})
        return FillResult(signed_in=False, blocked=NO_EMAIL_STEP)
    return login_form.fill_and_submit(
        session,
        credentials,
        timeout_s=max(deadline - time.monotonic(), poll_s),
        poll_s=poll_s,
        surface=surface,
        settings=settings,
    )


def _click(settings: Settings, page: Page, source: "Source", surface: "Surface") -> None:
    """Press **Log in**, and record it as a move."""
    selector = source.selectors["LOGIN_BUTTON_SELECTOR"]
    url = page.url
    helpers.guard(url, surface)
    before = helpers.sketch_of(page, surface)
    started = time.monotonic()
    clicked = page.evaluate(export_page.click_js(selector, source=source)) is True
    helpers.record_step(
        settings,
        LOGIN_ACTION,
        ok=clicked,
        url=url,
        selector=selector,
        elapsed_ms=round((time.monotonic() - started) * 1000),
        before=before,
        after=helpers.sketch_of(page, surface),
    )
    if not clicked:  # pragma: no cover - the landing said it was there a moment ago
        raise BrowserError(detail=f"{LOGIN_ACTION} could not be clicked")


def _await_form(session: BrowserSession, surface: "Surface", *, deadline: float, poll_s: float) -> bool:
    """Wait for the click to land on a page with a field on it, on any of the surface's hosts.

    A probe that fails is "not yet", as `login_form._await_change` treats it:
    the tab is being redirected from one host to the other.
    """
    while True:
        target = login_form.login_tab(session, surface)
        if target is not None:
            try:
                with helpers.driving(session.client, target, surface) as page:
                    if login_form.fields_of(page).any:
                        return True
            except BrowserError:
                if not session.client.responding():
                    raise
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_s)
