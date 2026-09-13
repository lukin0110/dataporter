"""Typing the credentials into the sign-in form, in this process (`24`).

The unattended sign-in has two halves. The agent's half (`signin`) is adaptive:
get the page to `https://claude.ai/login`, past whatever banner is in the way,
to the point where an email or password field is showing, and stop. This is the
deterministic half: read which field is there, put the credential in it, press
Enter, and look again — up to three times, because the form is a sequence
(email, then password) and only the page knows what comes next.

Two rules make this the only module that may hold a credential's value:

- **It never enters an expression.** The fields are found and focused by tagged
  JavaScript that names a selector; the value goes in through `Input.insertText`,
  a CDP parameter, exactly as a seed does (`08`). Nothing the page could read back
  and nothing a CDP trace of `Runtime.evaluate` would show carries it.
- **It never leaves this process.** The agent is stopped before this runs, the
  helper commands it may call know nothing of `auth`, and the Hermes environment
  is built without it (`hermes.client`). A credential that never enters the
  agent's process tree is one the agent cannot read, quote or log.

What it cannot do is finish a sign-in that asks for something other than a
password — an emailed code, a CAPTCHA, a challenge. It reports that it stopped
and why, and `signin` turns the answer into §12's pause.
"""

import json
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass

from dataporter import log
from dataporter.browser import helpers, probe
from dataporter.browser.cdp import Page, Target
from dataporter.browser.helpers import Surface
from dataporter.browser.launcher import BrowserSession
from dataporter.browser.probe import CLAUDE_HOST
from dataporter.config import Credentials
from dataporter.errors import BrowserError

_logger = log.get_logger(__name__)

LOGIN_URL = "https://claude.ai/login"

LOGIN_SURFACE = Surface(
    host=CLAUDE_HOST,
    allowed=re.compile(r"^https://claude\.ai/(login(/.*)?|new|chat/[0-9a-f-]{36})(\?.*)?$"),
)
"""§17's wall with one more door: the sign-in page and its sub-pages.

Passed to `helpers.driving` by this module and nothing else. `MIGRATION_SURFACE`
is untouched, so every helper the agent can run still refuses `/login`; what
admits it is the code that types into it, which the agent cannot invoke.
"""

EMAIL_SELECTOR = 'input[type="email"], input[autocomplete="username"]'
PASSWORD_SELECTOR = 'input[type="password"], input[autocomplete="current-password"]'  # ruff: ignore[hardcoded-password-string] - a CSS selector, not a credential
"""Semantic selectors, as §5 prefers. Guesses until `docs/claude-ui-map.md`'s
`sign-in form` row is observed, like every other selector in this package."""

LOGIN_FIELDS_TAG = "dataporter:login_fields"
FOCUS_FIELD_TAG = "dataporter:focus_field"

LOGIN_FIELDS_JS = probe.expression(
    LOGIN_FIELDS_TAG,
    f"  const EMAIL = {json.dumps(EMAIL_SELECTOR)};\n"
    f"  const PASSWORD = {json.dumps(PASSWORD_SELECTOR)};\n"
    "  return {\n"
    "    email: all(EMAIL).filter(visible).length > 0,\n"
    "    password: all(PASSWORD).filter(visible).length > 0,\n"
    "  };",
)
"""Which of the two fields the page is showing. Facts about the form, never its
contents."""


def focus_field_js(selector: str) -> str:
    """Focus the first visible field matching `selector`, selecting what it holds.

    The selection is what makes the insert replace a browser-remembered value rather
    than append to it. The selector is a `const` on a line of its own for the test
    suite's fake browser to read back.
    """
    return probe.expression(
        FOCUS_FIELD_TAG,
        f"  const selector = {json.dumps(selector)};\n"
        "  const field = all(selector).filter(visible)[0] || null;\n"
        "  if (field === null) return false;\n"
        "  field.focus();\n"
        "  field.select();\n"
        "  return document.activeElement === field;",
    )


SETTLED_JS = "document.readyState === 'complete'"
"""Whether the page has finished loading.

A form step that submits by navigating — which is what a plain `<form>` does —
leaves a moment in which the document is blank and neither field is visible.
Reading the fields in that moment says "this page is asking for something I do
not have", which is the one answer that stops an unattended run for a person.
So a page that has not settled is "not yet", not an answer. (Found by `29`'s
first rehearsal, against a mock whose sign-in steps are two POSTs.)
"""

MAX_ROUNDS = 3
"""Email, then password, then one more look: a form that still wants something
after that wants something this module does not have."""

POLL_S = 0.5

NO_TAB = "no_tab"
NO_FORM = "no_form"
FIELD_NOT_FOCUSED = "field_not_focused"
NO_PROGRESS = "no_progress"
CODE_OR_CHALLENGE = "code_or_challenge"
"""Why the fill stopped. `code_or_challenge` is the one an account without a
password login produces: the email went in and what came back was neither a
password field nor a signed-in page."""


@dataclass(frozen=True)
class Fields:
    """What `LOGIN_FIELDS_JS` answered."""

    email: bool = False
    password: bool = False

    @property
    def any(self) -> bool:
        return self.email or self.password


@dataclass(frozen=True)
class FillResult:
    """What the fill amounted to.

    `blocked` names the reason when `signed_in` is false; `filled` lists the fields the
    credentials went into, in order.
    """

    signed_in: bool
    filled: tuple[str, ...] = ()
    rounds: int = 0
    blocked: str | None = None


def _fields(page: Page) -> Fields:
    answer = page.evaluate(LOGIN_FIELDS_JS)
    if not isinstance(answer, dict):
        return Fields()
    return Fields(email=bool(answer.get("email")), password=bool(answer.get("password")))


def _login_tab(session: BrowserSession, surface: Surface) -> Target | None:
    tabs = helpers.surface_tabs(session.client, surface)
    return tabs[0] if tabs else None


def _type(page: Page, selector: str, value: str) -> bool:
    """Focus the field and put the value in. The value is a CDP parameter."""
    if page.evaluate(focus_field_js(selector)) is not True:
        return False
    page.insert_text(value)
    page.press_enter()
    return True


def _await_change(
    session: BrowserSession,
    before: Fields,
    *,
    surface: Surface,
    deadline: float,
    poll_s: float,
) -> tuple[bool, Fields]:
    """Wait for the page to move on: signed in, or a different form.

    A probe that fails is "not yet" unless the browser has stopped answering, as
    `session.wait_for_login` treats it: the page is being navigated.
    """
    while True:
        target = _login_tab(session, surface)
        if target is not None:
            settled = True
            try:
                with helpers.driving(session.client, target, surface) as page:
                    if probe.probe(page).logged_in:
                        return True, Fields()
                    settled = page.evaluate(SETTLED_JS) is True
                    now = _fields(page)
            except BrowserError:
                if not session.client.responding():
                    raise
                now = before
            if settled and now != before:
                return False, now
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False, before
        time.sleep(min(poll_s, remaining))


def fill_and_submit(  # ruff: ignore[too-many-return-statements] - one return per state the form can be in
    session: BrowserSession,
    credentials: Credentials,
    *,
    timeout_s: float,
    poll_s: float = POLL_S,
    max_rounds: int = MAX_ROUNDS,
    surface: Surface = LOGIN_SURFACE,
) -> FillResult:
    """Put the credentials into whatever the sign-in form asks for, in turn.

    Each round: read which field is showing, type the credential it wants, press
    Enter, and wait for the page to become either signed in or a different form.
    The email goes in only once; a form that shows the email field again after
    it was submitted is one that refused it, and is reported rather than fed
    again.
    """
    filled: list[str] = []
    deadline = time.monotonic() + timeout_s
    fields = Fields()
    for rounds in range(1, max_rounds + 1):
        target = _login_tab(session, surface)
        if target is None:
            return FillResult(signed_in=False, filled=tuple(filled), rounds=rounds, blocked=NO_TAB)
        with helpers.driving(session.client, target, surface) as page:
            if probe.probe(page).logged_in:
                return FillResult(signed_in=True, filled=tuple(filled), rounds=rounds)
            fields = _fields(page)
            if fields.password:
                which, selector, value = (
                    "password",
                    PASSWORD_SELECTOR,
                    credentials.password.get_secret_value(),
                )
            elif fields.email and "email" not in filled:
                which, selector, value = "email", EMAIL_SELECTOR, credentials.email
            elif fields.email:
                return FillResult(signed_in=False, filled=tuple(filled), rounds=rounds, blocked=NO_PROGRESS)
            else:
                blocked = CODE_OR_CHALLENGE if filled else NO_FORM
                return FillResult(signed_in=False, filled=tuple(filled), rounds=rounds, blocked=blocked)
            if not _type(page, selector, value):
                return FillResult(signed_in=False, filled=tuple(filled), rounds=rounds, blocked=FIELD_NOT_FOCUSED)
        filled.append(which)
        _logger.info("sign-in field submitted", extra={"field": which})
        signed_in, fields = _await_change(session, fields, surface=surface, deadline=deadline, poll_s=poll_s)
        if signed_in:
            return FillResult(signed_in=True, filled=tuple(filled), rounds=rounds)
        if not fields.any:
            blocked = CODE_OR_CHALLENGE if time.monotonic() < deadline else NO_PROGRESS
            return FillResult(signed_in=False, filled=tuple(filled), rounds=rounds, blocked=blocked)
    return FillResult(signed_in=False, filled=tuple(filled), rounds=max_rounds, blocked=NO_PROGRESS)


def filled_names(result: FillResult) -> Sequence[str]:
    """Return the fields the credentials went into — names, never values."""
    return result.filled
