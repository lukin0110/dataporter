"""A page that answers `31`'s expressions without running them.

`fake_composer.FakePage` is the same idea for a chat: a model of a page that
`FakeChrome` can answer CDP with, so every branch of the ask is covered on a
machine with no browser at all. This one models the other page — the one where
the vendor lets a user ask for their data — and it is a separate file for the
reason `export_page.py` is: the ask never touches a composer and a migration
never touches this.

The page has three stages, in the order a person would walk them:

```text
settings ──click the export button──> confirm ──click confirm──> requested
```

and two variants of it that do not get there: one with no button at all, and one
that opens a JavaScript dialog instead of a confirmation. Every click is
recorded, with the selector read back out of the expression, so a test can prove
the acceptance criterion that matters most — an ask is two clicks and nothing
else went into the page.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from dataporter.browser import export_page, login_form, probe, session
from fake_chrome import Call, FakeChrome, FakeTarget, dialog_event
from fake_composer import js_const

SIGNED_OUT_URL = "https://claude.ai/login"
"""Where claude.ai sends a request for a settings page it will not serve."""


class Stage(StrEnum):
    """What the page is showing. `settings` is where an ask starts."""

    SETTINGS = "settings"
    CONFIRM = "confirm"
    REQUESTED = "requested"


@dataclass
class FakeExportPage:
    """The export page, as `export_page`'s four booleans see it."""

    url: str = export_page.EXPORT_PAGE_URL
    stage: Stage = Stage.SETTINGS

    button: bool = True
    """Whether the export control is there at all. `False` is `10`'s risk made
    into a fixture: a page whose row in the UI map is wrong."""

    dialog_on_click: bool = False
    """Whether pressing the button opens a JavaScript dialog rather than a
    confirmation. The one thing the ask never answers."""

    confirms: bool = True
    """Whether the button opens a confirmation at all. `False` goes straight from
    `settings` to `requested`, which is the one-click shape of the same page."""

    never_requested: bool = False
    """Whether the page ever admits the request went through. `True` is the wait
    running out — a rate limit on asking, as far as anyone here can tell."""

    dialog_already_open: bool = False
    """Whether a JavaScript dialog was open before the ask ever attached.

    Reported on the connection's first reply, which is what a dialog opened by
    an earlier page looks like to a client that has just connected.
    """

    follows_navigation: bool = True
    """Whether `Page.navigate` moves this page. `False` is a browser that never
    arrives — a redirect back, a page that will not load."""

    loading_for: int = 0
    """How many looks the page spends still loading (`07`'s `settled`)."""

    signs_in_after: int | None = None
    """How many state reads before the person finishes signing in.

    `None` is a page that never does, which is the interactive wait running out.
    A number is what claude.ai really does: the tab leaves `/login` and lands in
    the application, with a composer on it, and the ask then has to bring it back
    to the export page itself.
    """

    state_reads: int = 0

    clicks: list[str] = field(default_factory=list)
    """The selectors that were clicked, in order."""

    inserts: list[str] = field(default_factory=list)
    """Anything `Input.insertText` sent. Always empty from the ask's path, and
    asserted to be."""

    dialogs: list[dict[str, Any]] = field(default_factory=list)
    """JavaScript dialog events to push before the next reply."""

    def state(self) -> dict[str, Any]:
        """What `07`'s probe makes of this page.

        No composer, whatever the stage: a settings page has none, which is the
        whole reason `export_page.signed_out` reads the URL instead. The one page
        here that does have one is where a finished sign-in lands.
        """
        self.state_reads += 1
        if self.signs_in_after is not None and self.state_reads >= self.signs_in_after:
            self.url = probe.NEW_CHAT_URL
        return {
            "url": self.url,
            "composer_present": self.url == probe.NEW_CHAT_URL,
            "composer_chars": 0,
            "generating": False,
            "send_enabled": False,
            "dom_dialogs": 1 if self.stage is Stage.CONFIRM else 0,
        }

    def view(self) -> dict[str, Any]:
        """What `EXPORT_PAGE_JS` answers for this stage."""
        return {
            "button": self.button and self.stage is Stage.SETTINGS,
            "dialog": self.stage is Stage.CONFIRM,
            "confirm": self.stage is Stage.CONFIRM,
            "requested": self.stage is Stage.REQUESTED,
        }

    def click(self, selector: str) -> bool:
        """Press whatever this selector names, and move the page on."""
        self.clicks.append(selector)
        if selector == export_page.EXPORT_BUTTON_SELECTOR:
            if self.dialog_on_click:
                self.dialogs.append(dialog_event("confirm"))
                return True
            if self.never_requested:
                return True
            self.stage = Stage.CONFIRM if self.confirms else Stage.REQUESTED
            return True
        if selector == export_page.CONFIRM_BUTTON_SELECTOR:
            self.stage = Stage.REQUESTED
            return True
        raise AssertionError(f"unexpected click: {selector}")

    # -- answering CDP ------------------------------------------------------- #

    def evaluate(self, expression: str) -> Any:
        if expression == "location.href":
            return self.url
        if expression in (session.READY_JS, login_form.SETTLED_JS):
            if self.loading_for > 0:
                self.loading_for -= 1
                return False
            return self.url if expression == session.READY_JS else True
        if export_page.EXPORT_PAGE_TAG in expression:
            return self.view()
        if export_page.CLICK_TAG in expression:
            return self.click(js_const(expression, "selector"))
        if probe.PAGE_STATE_TAG in expression:
            return self.state()
        raise AssertionError(f"unexpected expression: {expression[:80]}")

    def respond(self, call: Call) -> dict[str, Any] | None:
        if call.method == "Runtime.evaluate":
            return {
                "result": {
                    "result": {"value": self.evaluate(str(call.params["expression"]))}
                }
            }
        if call.method == "Page.enable":
            if self.dialog_already_open:
                self.dialogs.append(dialog_event())
            return None
        if call.method == "Page.navigate":
            if not self.follows_navigation:
                # Answered here rather than by `FakeChrome`, which would move the
                # target list to a page this one never went to.
                return {"result": {}}
            self.url = str(call.params.get("url", self.url))
            return None
        if call.method == "Input.insertText":
            self.inserts.append(str(call.params.get("text", "")))
            return {"result": {}}
        return None


def responder(page: FakeExportPage) -> Callable[[Any, Call], Any]:
    """A `FakeChrome` responder that answers for one tab and pushes its dialogs.

    The dialog is pushed as an event rather than returned, because that is how
    Chrome reports one and how `probe.pending_dialogs` finds it: the ask learns
    about it on its next read, which is exactly the moment it has to stop.
    """

    def answer(fake: FakeChrome, call: Call) -> dict[str, Any] | None:
        pending, page.dialogs = page.dialogs, []
        for event in pending:
            fake.events.append(event)
        return page.respond(call)

    return answer


def visit(chrome: FakeChrome, page: FakeExportPage, url: str) -> None:
    """Move the tab, in both places a tab's URL is known.

    `FakeChrome` answers `/json/list` from its own targets and the page answers
    `location.href` from itself; a browser that was somewhere else all along has
    to say so in both, exactly as a real one does.
    """
    page.url = url
    chrome.targets[0].url = url


def browser(page: FakeExportPage, port: int = 0) -> FakeChrome:
    """A fake Chrome with this page on its one tab.

    `port` is for the test that asks twice: an ask closes the browser on its way
    out, as `login` does and for the same reason — Chrome flushes its cookie jar
    on exit — so a second ask is a second browser, and it comes up on the port
    the settings already name.
    """
    return FakeChrome(
        targets=[FakeTarget(id="page-1", url=page.url)],
        responder=responder(page),
        port=port,
    )
