"""A page that answers `08`'s expressions without running them.

`tests/test_browser_helpers.py` proves the helpers against a real Chrome
rendering the checked-in fixtures, but only where a browser is installed. This
is the other half: a model of a claude.ai page — a composer, a transcript, an
upload input — that `FakeChrome` can answer CDP with, so every line of
`browser.helpers` is covered on a machine with no browser at all.

It never executes JavaScript. Each expression `probe` and `helpers` build opens
with a tag comment (`probe.expression`), and each one that needs an argument
writes it as a `const` on a line of its own; between them that is enough to tell
what was asked and what to answer, which is the whole reason the tags are there.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from dataporter.browser import helpers, probe
from fake_chrome import Call


def js_const(expression: str, name: str) -> Any:
    """The value of `const <name> = …;` in one of our expressions."""
    prefix = f"  const {name} = "
    for line in expression.splitlines():
        if line.startswith(prefix):
            return json.loads(line[len(prefix) :].rstrip(";"))
    raise AssertionError(f"no const {name} in expression")


@dataclass
class FakePage:
    """What one tab holds, and how it answers being asked about it."""

    url: str = "https://claude.ai/new"
    composer: str | None = ""
    """The composer's text. `None` means there is no composer at all."""
    last_role: str | None = None
    last_text: str = ""
    generating: bool = False
    send_enabled: bool = False
    dom_dialogs: int = 0

    file_input: bool = True
    accept_files: bool = True
    chip_polls: int = 0
    """How many times `attach` must ask before the chip appears."""

    focusable: bool = True
    insert: Callable[[str], str] | None = None
    """What the composer makes of inserted text. `None` inserts it verbatim;
    a function stands in for an editor that rewrites what it is given."""
    vanish_text_at: int | None = None
    """Read the composer's text this many times, then report it is gone."""

    on_view: Callable[["FakePage", int], None] | None = None
    """Called before each state read, with the number of reads so far. How a
    fixture changes under a poll loop."""

    uploaded: list[str] = field(default_factory=list)
    views: int = 0
    text_reads: int = 0
    chip_asks: int = 0

    # -- what a read of the page returns ------------------------------------ #

    def state(self) -> dict[str, Any]:
        self.views += 1
        if self.on_view is not None:
            self.on_view(self, self.views)
        return {
            "url": self.url,
            "composer_present": self.composer is not None,
            "composer_chars": len(self.composer or ""),
            "generating": self.generating,
            "send_enabled": self.send_enabled,
            "dom_dialogs": self.dom_dialogs,
        }

    def last_message(self, expect: list[str]) -> dict[str, Any]:
        return {
            "role": self.last_role,
            "chars": len(self.last_text),
            "contains": [item for item in expect if item in self.last_text],
        }

    def composer_text(self) -> str | None:
        self.text_reads += 1
        if self.vanish_text_at is not None and self.text_reads >= self.vanish_text_at:
            self.composer = None
        return self.composer

    def insert_text(self, text: str) -> None:
        if self.composer is None:
            return
        self.composer += text if self.insert is None else self.insert(text)

    # -- answering CDP ------------------------------------------------------- #

    def evaluate(self, expression: str) -> Any:
        if expression == "location.href":
            return self.url
        if probe.PAGE_VIEW_TAG in expression:
            return {
                **self.state(),
                "last_message": self.last_message(js_const(expression, "expect")),
            }
        if probe.PAGE_STATE_TAG in expression:
            return self.state()
        if helpers.COMPOSER_TEXT_TAG in expression:
            return self.composer_text()
        if helpers.FOCUS_TAG in expression:
            return self.composer is not None and self.focusable
        if helpers.EXEC_COMMAND_TAG in expression:
            if self.composer is None or not self.focusable:
                return False
            self.insert_text(js_const(expression, "text"))
            return True
        if helpers.FILE_INPUT_TAG in expression:
            return self.file_input
        if helpers.CHIP_TAG in expression:
            self.chip_asks += 1
            name = js_const(expression, "name")
            return name in self.uploaded and self.chip_asks > self.chip_polls
        raise AssertionError(f"unexpected expression: {expression[:80]}")

    def respond(self, call: Call) -> dict[str, Any] | None:
        """One CDP reply, or `None` to let `FakeChrome` answer as usual."""
        if call.method == "Runtime.evaluate":
            value = self.evaluate(str(call.params.get("expression", "")))
            return {"result": {"result": {"value": value}}}
        if call.method == "Input.insertText":
            self.insert_text(str(call.params.get("text", "")))
            return {"result": {}}
        if call.method == "DOM.setFileInputFiles":
            if not self.accept_files:
                return {"error": {"code": -32000, "message": "File not found"}}
            for item in call.params.get("files", []):
                self.uploaded.append(str(item).rsplit("/", 1)[-1])
            return {"result": {}}
        return None


def responder(pages: dict[str, FakePage]) -> Callable[[Any, Call], Any]:
    """A `FakeChrome` responder that routes each call to its target's page."""

    def answer(fake: Any, call: Call) -> dict[str, Any] | None:
        page = pages.get(call.path.rsplit("/", 1)[-1])
        return None if page is None else page.respond(call)

    return answer
