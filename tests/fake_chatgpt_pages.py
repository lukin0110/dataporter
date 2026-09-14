"""chatgpt.com and auth.openai.com as `44`'s expressions see them, without running any.

`fake_export_page.FakeExportPage` is one page with three stages; this is a site
with several, on two hosts, because a ChatGPT sign-in crosses from one to the
other and back:

```text
landing ──click Log in──> email ──Enter──> password ──Enter──> home
   │                                  └──Enter──> code (a step the tool cannot take)
   └── (already signed in) home ──navigate──> export: settings → confirm → requested
```

Every click is recorded with its selector, every typed value with its field, and
every expression the site was asked, so a test can prove the walk is one click
and two fields, that a credential travels only as a CDP parameter, and that an
ask is two clicks after it. The URL is kept in both places a tab's URL lives —
the page's own `location.href` and the fake Chrome's target list — because the
tool reads both and a real browser keeps them together.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from dataporter.browser import chatgpt_login, export_page, login_form, probe, session, sites
from dataporter.browser import sketch as sketching
from dataporter.sources.chatgpt import CHATGPT
from fake_chrome import Call, FakeChrome, FakeTarget
from fake_composer import js_const

ROOT = CHATGPT.login_url
AUTH_URL = "https://auth.openai.com/log-in?state=s3cret-state"
"""With a query value, as a real auth host's URL may carry: the tests prove it reaches no line (§70)."""
EXPORT_URL = sites.export_page_url(CHATGPT)
LINK_PREFIX = "https://chatgpt.com/__mock/exports/"
"""Where the mock chatgpt.com mints its links (`40`): on the site's host, where the cookie is."""


def frame_navigated(url: str) -> dict[str, Any]:
    return {"method": "Page.frameNavigated", "params": {"frame": {"id": "F1", "url": url}, "type": "Navigation"}}


def response_received(url: str, status: int, mime: str) -> dict[str, Any]:
    return {
        "method": "Network.responseReceived",
        "params": {
            "requestId": "d1",
            "timestamp": 1.0,
            "type": "Document",
            "response": {"url": url, "status": status, "mimeType": mime, "headers": {}},
        },
    }


LOGIN_BUTTON = CHATGPT.selectors["LOGIN_BUTTON_SELECTOR"]
EXPORT_BUTTON = CHATGPT.selectors["EXPORT_BUTTON_SELECTOR"]
CONFIRM_BUTTON = CHATGPT.selectors["CONFIRM_BUTTON_SELECTOR"]


class Step(StrEnum):
    """Where the tab is, and what the page there shows."""

    LANDING = "landing"
    EMAIL = "email"
    PASSWORD = "password"
    CODE = "code"
    HOME = "home"
    EXPORT = "export"


class Stage(StrEnum):
    """The export page's own three stages, once the tab is on it."""

    SETTINGS = "settings"
    CONFIRM = "confirm"
    REQUESTED = "requested"


@dataclass
class FakeChatgptPages:
    """The whole site, as the tool's expressions read it."""

    step: Step = Step.LANDING
    stage: Stage = Stage.SETTINGS

    login_button: bool = True
    """Whether the landing page has a **Log in** at all. `False` is the map's
    `signed out` row being wrong — or a redesign — made into a fixture."""

    after_email: Step = Step.PASSWORD
    """What the email step leads to: the password step, or a code prompt."""

    password_ok: bool = True
    """Whether the password is taken. `False` is the site refusing it back to the email step."""

    never_requested: bool = False
    """Whether the export page ever admits the request went through."""

    signs_in_after: int | None = None
    """How many state reads before a person finishes signing in, for the interactive wait."""

    link_answers: str = "download"
    """What the site does when the tab is pointed at a link: `download` the
    archive, `refused` (a 403, the signed-out answer), `page` (a 200 document
    with no download, the redirect-to-landing answer), `huge` (a download that
    grows past the cap), or `stall` (nothing at all)."""

    archive: bytes = b""
    """The bytes a download delivers."""

    download_dir: Path | None = None
    """Where `Browser.setDownloadBehavior` said downloads go."""

    links: list[str] = field(default_factory=list)
    """Every link the tab was pointed at."""

    state_reads: int = 0
    clicks: list[str] = field(default_factory=list)
    typed: dict[str, str] = field(default_factory=dict)
    focused: str | None = None
    expressions: list[str] = field(default_factory=list)
    enters: int = 0
    navigations: list[str] = field(default_factory=list)
    chrome: FakeChrome | None = None

    # -- where the tab is --------------------------------------------------- #

    @property
    def url(self) -> str:
        if self.step in {Step.EMAIL, Step.PASSWORD, Step.CODE}:
            return AUTH_URL
        if self.step is Step.EXPORT:
            return EXPORT_URL
        return ROOT

    @property
    def signed_in(self) -> bool:
        return self.step in {Step.HOME, Step.EXPORT}

    def go(self, step: Step) -> None:
        self.step = step
        if self.chrome is not None:
            self.chrome.targets[0].url = self.url

    # -- what the page shows ------------------------------------------------- #

    def state(self) -> dict[str, Any]:
        self.state_reads += 1
        if self.signs_in_after is not None and self.step is Step.LANDING and self.state_reads >= self.signs_in_after:
            self.go(Step.HOME)
        return {
            "url": self.url,
            "composer_present": self.step is Step.HOME,
            "composer_chars": 0,
            "generating": False,
            "send_enabled": False,
            "dom_dialogs": 1 if self.step is Step.EXPORT and self.stage is Stage.CONFIRM else 0,
        }

    def landing(self) -> dict[str, Any]:
        return {"login_button": self.step is Step.LANDING and self.login_button, "composer": self.step is Step.HOME}

    def fields(self) -> dict[str, Any]:
        return {"email": self.step is Step.EMAIL, "password": self.step is Step.PASSWORD}

    def focus(self, selector: str) -> bool:
        self.focused = "email" if selector == login_form.EMAIL_SELECTOR else "password"
        return self.fields()[self.focused]

    def view(self) -> dict[str, Any]:
        on_page = self.step is Step.EXPORT
        return {
            "button": on_page and self.stage is Stage.SETTINGS,
            "dialog": on_page and self.stage is Stage.CONFIRM,
            "confirm": on_page and self.stage is Stage.CONFIRM,
            "requested": on_page and self.stage is Stage.REQUESTED,
        }

    def click(self, selector: str) -> bool:
        self.clicks.append(selector)
        if selector == LOGIN_BUTTON and self.step is Step.LANDING and self.login_button:
            self.go(Step.EMAIL)
            return True
        if selector == EXPORT_BUTTON and self.step is Step.EXPORT and self.stage is Stage.SETTINGS:
            if not self.never_requested:
                self.stage = Stage.CONFIRM
            return True
        if selector == CONFIRM_BUTTON and self.step is Step.EXPORT and self.stage is Stage.CONFIRM:
            self.stage = Stage.REQUESTED
            return True
        raise AssertionError(f"unexpected click: {selector} at {self.step}")

    def enter(self) -> None:
        self.enters += 1
        if self.step is Step.EMAIL:
            self.go(self.after_email)
        elif self.step is Step.PASSWORD:
            self.go(Step.HOME if self.password_ok else Step.EMAIL)

    def navigate(self, url: str) -> None:
        self.navigations.append(url)
        if url.startswith(LINK_PREFIX):
            self.links.append(url)
            self.answer_link(url)
            return
        if url == EXPORT_URL:
            # A signed-out request for a settings page lands on the landing page.
            self.go(Step.EXPORT if self.signed_in else Step.LANDING)
        elif url == ROOT:
            self.go(Step.HOME if self.signed_in else Step.LANDING)
        else:
            raise AssertionError(f"unexpected navigation: {url}")

    def answer_link(self, url: str) -> None:
        """Push what a browser sends for a download link, in the order Chrome sends it."""
        assert self.chrome is not None
        push = self.chrome.push
        push(frame_navigated(url))
        if self.link_answers == "stall":
            return
        if not self.signed_in or self.link_answers == "refused":
            push(response_received(url, 403, "text/plain"))
            return
        if self.link_answers == "page":
            push(response_received(url, 200, "text/html"))
            push({"method": "Page.loadEventFired", "params": {"timestamp": 1.0}})
            return
        push(response_received(url, 200, "application/zip"))
        guid = "0f5e0d7a-1234-4c9e-8a1b-2f3e4d5c6b7a"
        push({
            "method": "Browser.downloadWillBegin",
            "params": {"frameId": "F1", "guid": guid, "url": url, "suggestedFilename": "chatgpt-export.zip"},
        })
        if self.link_answers == "huge":
            push({
                "method": "Browser.downloadProgress",
                "params": {"guid": guid, "totalBytes": 0, "receivedBytes": 10**12, "state": "inProgress"},
            })
            return
        assert self.download_dir is not None
        (self.download_dir / guid).write_bytes(self.archive)
        push({
            "method": "Browser.downloadProgress",
            "params": {
                "guid": guid,
                "totalBytes": len(self.archive),
                "receivedBytes": len(self.archive),
                "state": "completed",
            },
        })

    # -- answering CDP ------------------------------------------------------- #

    def evaluate(self, expression: str) -> Any:
        self.expressions.append(expression)
        if expression == "location.href":
            return self.url
        if expression == session.READY_JS:
            return self.url
        if expression == login_form.SETTLED_JS:
            return True
        answers: list[tuple[str, Callable[[], Any]]] = [
            (chatgpt_login.LANDING_TAG, self.landing),
            (login_form.LOGIN_FIELDS_TAG, self.fields),
            (login_form.FOCUS_FIELD_TAG, lambda: self.focus(js_const(expression, "selector"))),
            (export_page.EXPORT_PAGE_TAG, self.view),
            (export_page.CLICK_TAG, lambda: self.click(js_const(expression, "selector"))),
            (probe.PAGE_STATE_TAG, self.state),
            (sketching.SELECTORS_TAG, lambda: dict.fromkeys(js_const(expression, "table"), 0)),
        ]
        for tag, answer in answers:
            if tag in expression:
                return answer()
        raise AssertionError(f"unexpected expression: {expression[:80]}")

    def respond(self, call: Call) -> dict[str, Any] | None:
        if call.method == "Browser.setDownloadBehavior":
            self.download_dir = Path(str(call.params["downloadPath"]))
            return {"result": {}}
        if call.method == "Runtime.evaluate":
            return {"result": {"result": {"value": self.evaluate(str(call.params["expression"]))}}}
        if call.method == "Page.navigate":
            self.navigate(str(call.params.get("url", "")))
            return {"result": {}}
        if call.method == "Input.insertText":
            if self.focused is not None:
                self.typed[self.focused] = str(call.params.get("text", ""))
            return {"result": {}}
        if call.method == "Input.dispatchKeyEvent":
            if call.params.get("type") == "keyDown":
                self.enter()
            return {"result": {}}
        return None


def responder(site: FakeChatgptPages) -> Callable[[Any, Call], Any]:
    """Return a `FakeChrome` responder that answers for the one tab and keeps its URL in step."""

    def answer(fake: FakeChrome, call: Call) -> dict[str, Any] | None:
        site.chrome = fake
        return site.respond(call)

    return answer


def browser(site: FakeChatgptPages, port: int = 0) -> FakeChrome:
    """Return a fake Chrome with this site on its one tab."""
    return FakeChrome(targets=[FakeTarget(id="page-1", url=site.url)], responder=responder(site), port=port)
