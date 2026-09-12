"""A sign-in form `login_form` can be pointed at without a browser.

A `FakePage` with stages: `email` shows the email field, `password` the password
field, `code` a page asking for something the tool does not have, and `done` a
signed-in `/new`. Enter advances the stage. What was typed is kept, by field,
so a test can prove the value went in through `Input.insertText` and nowhere
else — and `evaluate` records every expression it was asked, so a test can
prove no expression carried it.
"""

from dataclasses import dataclass, field
from typing import Any

from dataporter.browser import login_form
from fake_chrome import Call
from fake_composer import FakePage, js_const

LOGIN_URL = "https://claude.ai/login"
NEW_URL = "https://claude.ai/new"


@dataclass
class LoginForm(FakePage):
    """The form, stage by stage."""

    stage: str = "email"
    after_email: str = "password"
    """What the email step leads to: `password`, or `code` for an account whose
    sign-in is an emailed code."""
    after_password: str = "done"
    focusable_fields: bool = True
    typed: dict[str, str] = field(default_factory=dict)
    focused: str | None = None
    expressions: list[str] = field(default_factory=list)
    enters: int = 0
    fail_after_enter: int = 0
    """How many page reads fail after each Enter — a page mid-navigation, which
    `login_form` treats as "not yet" and asks again."""
    failing: int = 0

    def __post_init__(self) -> None:
        self._apply_stage()

    def _apply_stage(self) -> None:
        if self.stage == "done":
            self.url = NEW_URL
            self.composer = ""
        else:
            self.url = LOGIN_URL
            self.composer = None

    def advance(self) -> None:
        self.failing = self.fail_after_enter
        if self.stage == "email":
            self.stage = self.after_email
        elif self.stage == "password":
            self.stage = self.after_password
        self._apply_stage()

    def evaluate(self, expression: str) -> Any:
        self.expressions.append(expression)
        if login_form.LOGIN_FIELDS_TAG in expression:
            return {
                "email": self.stage == "email",
                "password": self.stage == "password",
            }
        if login_form.FOCUS_FIELD_TAG in expression:
            if not self.focusable_fields:
                return False
            selector = js_const(expression, "selector")
            self.focused = (
                "email" if selector == login_form.EMAIL_SELECTOR else "password"
            )
            return self.focused == self.stage
        return super().evaluate(expression)

    def respond(self, call: Call) -> dict[str, Any] | None:
        if call.method == "Runtime.evaluate" and self.failing > 0:
            self.failing -= 1
            return {"result": {"exceptionDetails": {"text": "navigating"}}}
        if self.stage == "done":
            # Signed in: a `/new` like any other, so a migration can run on it.
            return super().respond(call)
        if call.method == "Input.insertText":
            if self.focused is not None:
                self.typed[self.focused] = str(call.params.get("text", ""))
            return {"result": {}}
        if call.method == "Input.dispatchKeyEvent":
            if call.params.get("type") == "keyDown":
                self.enters += 1
                self.advance()
            return {"result": {}}
        return super().respond(call)
