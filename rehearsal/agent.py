"""The scripted agent's hands: the moves the skill leaves to an agent.

The tool's own suite already has the agent's *head* — `tests/fake_agent.py`
reads a rendered task prompt and performs `11`'s procedure with `13`'s recovery,
against a page a test supplies. What it has never had is a real page. This
module is what it drives instead: one Chrome, over CDP, showing the mock.

Three moves, and no more, because the skill leaves exactly three things to the
agent and gives everything else to a helper:

- **navigate** — go to a URL and wait until the page is there;
- **submit** — put the caret in the composer and press Enter;
- **rename** — open the chat's own menu, type a name into it, and check it took.

Everything else a rehearsal does goes through the real `dataporter
browser …` commands, invoked as a subprocess exactly as Hermes's terminal tool
would invoke them. A seed is never typed here and never passes through this
module at all.

What this cannot be is *adaptive*. A real agent decides what it is looking at; a
script is told. Where the skill says "find the chat's own menu by looking", this
knows the mock's markup, and the UI map row it stands on says so. That is the
line §23 draws: a rehearsal measures the deterministic half, and whether a model
can follow the skill is the pilot's question.
"""

import json
import shlex
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from dataporter.browser import helpers, login_form, probe
from dataporter.browser.cdp import CdpClient, Page, Target
from dataporter.hermes.runner import last_result_object

SETTLE_S = 0.1
"""How long a wait loop sleeps between looks. A tenth of a second: these wait for
a local page to render, not for a model to think."""

READY_S = 20.0
RENAME_S = 20.0
DISMISS_S = 10.0
"""How long the sign-in task waits for the form after it has cleared a banner."""

BLANK = ("", "about:blank", "chrome://newtab/", "about:newtab")


class AgentError(RuntimeError):
    """The page could not be driven at all.

    Never a migration failure — the procedure reports those itself, in the result
    object.
    """


# --------------------------------------------------------------------------- #
# The tab
# --------------------------------------------------------------------------- #


def chosen_tab(client: CdpClient) -> Target:
    """Return the tab this rehearsal is driving.

    The claude.ai one if there is one, and otherwise whatever blank tab Chrome
    started with — which is the state the very first navigation begins from.
    """
    pages = [item for item in client.pages() if not item.url.startswith("devtools://")]
    if not pages:
        raise AgentError("the browser has no page to drive")
    on_claude = [item for item in pages if item.host == probe.CLAUDE_HOST]
    return on_claude[0] if on_claude else pages[0]


@dataclass
class Driver:
    """One Chrome, and a connection opened per move.

    Per move rather than held open, for the reason the helpers do it: a
    rehearsal runs a helper subprocess between every two of these, and two
    long-lived connections to the same target is a way to observe a half-changed
    page.
    """

    client: CdpClient
    ready_s: float = READY_S

    def page(self) -> Page:
        return self.client.attach(chosen_tab(self.client).id)

    def look(self, expression: str) -> Any:
        page = self.page()
        try:
            return page.evaluate(expression)
        finally:
            page.close()

    def url(self) -> str:
        return str(self.look("location.href"))

    def wait_until(self, expression: str, *, timeout_s: float | None = None) -> bool:
        """Poll one expression until it is true. `False` on the deadline."""
        deadline = time.monotonic() + (self.ready_s if timeout_s is None else timeout_s)
        while True:
            if self.look(expression) is True:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(SETTLE_S)


READY_JS = "document.readyState === 'complete'"


# --------------------------------------------------------------------------- #
# The three moves (`11`'s procedure)
# --------------------------------------------------------------------------- #


@dataclass
class CdpBrowser:
    """`fake_agent.Browser`, against a real page."""

    driver: Driver
    visited: list[str] = field(default_factory=list)

    def navigate(self, url: str) -> None:
        self.visited.append(url)
        page = self.driver.page()
        try:
            page.navigate(url)
        finally:
            page.close()
        # Loaded, and not still showing the page it was on. A redirect — to the
        # sign-in page, say — satisfies this too, which is deliberate: the
        # procedure's next step is to probe, and what it finds there is what
        # `13`'s login-expiry row is written against.
        self.driver.wait_until(READY_JS)

    def submit(self, expected_ack: str) -> None:
        """Press Enter in the composer. The ack line is the *page's* business.

        `expected_ack` is what the chat will answer with; nothing here needs it,
        and taking it and dropping it is what keeps this signature the one the
        procedure calls (a stub page needs it, a real site does not).
        """
        page = self.driver.page()
        try:
            if page.evaluate(helpers.FOCUS_JS) is not True:
                # Not an error to raise on: the procedure reads the composer
                # afterwards and has a recovery for a submit that did not land.
                return
            page.press_enter()
        finally:
            page.close()

    def rename(self, title: str) -> None:
        """`17`'s one typed action, through the chat's own menu.

        Opening the menu is a click a real agent makes after looking; here it is
        two ids, which is the whole of what a script can do instead. The name
        goes in through `Input.insertText` and Enter, as every other value this
        rehearsal types does.
        """
        page = self.driver.page()
        try:
            if page.evaluate(OPEN_RENAME_JS) is not True:
                return
            page.insert_text(title)
            page.press_enter()
        finally:
            page.close()
        # Verify it took before answering, because the procedure probes for the
        # new title immediately afterwards and the page writes it through a
        # request of its own.
        self.driver.wait_until(renamed_js(title), timeout_s=RENAME_S)

    def last_assistant_message(self) -> str:
        """`20`'s snapshot, reduced to the message the probe may quote."""
        found = self.driver.look(LAST_ASSISTANT_JS)
        return str(found) if isinstance(found, str) else ""


LAST_ASSISTANT_JS = probe.expression(
    "rehearsal:last_assistant",
    f"  const ASSISTANT = {json.dumps(probe.ASSISTANT_MESSAGE_SELECTOR)};\n"
    "  const turns = all(ASSISTANT).filter(visible);\n"
    "  const last = turns.length === 0 ? null : turns[turns.length - 1];\n"
    "  return last === null ? '' : (last.innerText || '');",
)
"""The one message a rehearsal reads: `20`'s probe reply.

The only place in this package that takes text off a page, and it exists because
the probe prompt asks for the reply verbatim — the single exception `20` makes to
the rule that no message reaches an agent's output tokens. Everything else this
module asks the page is a yes or a no.
"""

OPEN_RENAME_JS = probe.expression(
    "rehearsal:open_rename",
    "  const trigger = document.querySelector('[data-testid=\"chat-menu-trigger\"]');\n"
    "  if (trigger === null) return false;\n"
    "  trigger.click();\n"
    "  const rename = document.querySelector('[data-testid=\"rename-chat\"]');\n"
    "  if (rename === null) return false;\n"
    "  rename.click();\n"
    "  const field = document.querySelector('[data-testid=\"chat-title-input\"]');\n"
    "  if (field === null) return false;\n"
    "  field.focus();\n"
    "  return document.activeElement === field;",
)
"""The rename affordance, as the UI map's row describes the mock's.

The tool's own code looks for none of this — `17` asks an agent to find "the
chat's own menu" by looking, and what the tool checks is only whether the title
changed. This is the scripted stand-in for the looking.
"""


def renamed_js(title: str) -> str:
    """Whether the chat's own menu now carries this name."""
    return probe.expression(
        "rehearsal:renamed",
        f"  const expected = {json.dumps(' '.join(title.split()))};\n"
        "  const el = all(TITLE_SELECTOR).filter(visible)[0] || null;\n"
        "  if (el === null) return false;\n"
        "  return (el.innerText || el.textContent || '')"
        ".replace(/\\s+/g, ' ').trim() === expected;",
    )


# --------------------------------------------------------------------------- #
# The sign-in task (`24`)
# --------------------------------------------------------------------------- #

CODE_SELECTOR = 'input[autocomplete="one-time-code"], input[name*="code"]'
CAPTCHA_SELECTOR = 'iframe[src*="captcha"], [class*="captcha"]'
"""What the tool has no selector for at all: a page asking for something this
rehearsal cannot type. An agent that sees one of these reports `needs_human`,
which is the answer §24 designed for an account that does not sign in with a
password."""

FIELDS_JS = probe.expression(
    "rehearsal:signin_fields",
    f"  const EMAIL = {json.dumps(login_form.EMAIL_SELECTOR)};\n"
    f"  const PASSWORD = {json.dumps(login_form.PASSWORD_SELECTOR)};\n"
    f"  const CODE = {json.dumps(CODE_SELECTOR)};\n"
    f"  const CAPTCHA = {json.dumps(CAPTCHA_SELECTOR)};\n"
    "  const seen = [];\n"
    "  const show = (name, selector) => {\n"
    "    if (all(selector).filter(visible).length > 0) seen.push(name);\n"
    "  };\n"
    "  show('email', EMAIL);\n"
    "  show('password', PASSWORD);\n"
    "  show('code', CODE);\n"
    "  show('captcha', CAPTCHA);\n"
    "  return seen;",
)
"""What the sign-in page is showing, in the agent's own words.

The first two selectors are `login_form`'s, because the UI map's `sign-in form`
row names exactly those and a second spelling of them would be a second thing to
correct when somebody finally looks at claude.ai. The other two are this
module's: they are what an agent reports as `needs_human`, and the tool has no
selector for them at all.
"""

DISMISS_JS = probe.expression(
    "rehearsal:dismiss_banner",
    '  const banners = all(\'[id*="banner"], [id*="cookie"], '
    '[role="region"], [role="dialog"]\').filter(visible);\n'
    "  for (const banner of banners) {\n"
    "    const button = Array.prototype.slice.call(banner.querySelectorAll('button'))\n"
    "      .filter(visible)[0] || null;\n"
    "    if (button !== null) { button.click(); return true; }\n"
    "  }\n"
    "  return false;",
)
"""Getting past whatever is in front of the form — one banner, once.

This is the one place a rehearsal's agent does something that looks like
judgement, and it is not: it clicks the first button in the first banner-shaped
element. A real agent reads the page. What both have in common is that the form
is not visible until it is done, which is what makes the step worth taking.
"""


@dataclass
class CdpSignInBrowser:
    """`fake_agent.SignInBrowser`, against a real page."""

    driver: Driver

    def navigate(self, url: str) -> None:
        CdpBrowser(self.driver).navigate(url)

    def visible_fields(self) -> Sequence[str]:
        """Return what the page is showing, once whatever was in front of it is gone.

        One banner, once: if nothing is showing and there is something
        banner-shaped with a button in it, click it and look again until the
        form appears or the deadline does.
        """
        found = self._fields()
        if found or self.driver.look(DISMISS_JS) is not True:
            return found
        deadline = time.monotonic() + DISMISS_S
        while True:
            found = self._fields()
            if found or time.monotonic() >= deadline:
                return found
            time.sleep(SETTLE_S)

    def _fields(self) -> list[str]:
        answer = self.driver.look(FIELDS_JS)
        return [str(item) for item in answer] if isinstance(answer, list) else []


# --------------------------------------------------------------------------- #
# The helper commands
# --------------------------------------------------------------------------- #


@dataclass
class HelperRunner:
    """`dataporter browser …`, as a subprocess.

    Exactly how Hermes runs them — its terminal tool, our CLI, one JSON object
    on stdout — so that a helper whose output shape changed breaks a rehearsal
    the way it would break a migration.
    """

    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str]) -> tuple[int, dict[str, Any]]:
        command = [str(item) for item in argv]
        self.calls.append(command)
        finished = subprocess.run(command, capture_output=True, text=True, check=False)
        printed = last_json_object(finished.stdout)
        if printed is None:
            return finished.returncode, {
                "ok": False,
                "error": "no json from helper",
                "detail": finished.stderr.strip()[-200:],
            }
        return finished.returncode, printed


def last_json_object(text: str) -> dict[str, Any] | None:
    """Return the last JSON object a helper printed.

    A helper prints exactly one, so the last is the only; reading it with the
    tool's own scanner rather than `json.loads` keeps a stray line of Chrome's
    stderr from turning a good answer into a failure.
    """
    found = last_result_object(text)
    if found is not None:
        return found
    try:
        loaded = json.loads(text.strip())
    except ValueError:
        return None
    return loaded if isinstance(loaded, dict) else None


def helper_argv(prefix: Sequence[str], *args: str) -> list[str]:
    return [*prefix, *args]


def split_helper(line: str) -> list[str]:
    """Return the `helper:` line of a prompt, as argv, with the prompt's `…` dropped."""
    return [item for item in shlex.split(line) if item != "…"]
