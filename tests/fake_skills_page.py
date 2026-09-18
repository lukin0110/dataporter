"""A tab that answers `66`'s two reads and serves its downloads, without a browser.

`fake_export_page.FakeExportPage` models the page the ask stands on; this one
models the same tab under a skills extraction. The two reads are answered by
tag, as every fake page answers an expression, and the download address is
answered the way `fake_chatgpt_pages` answers a link: by pushing what Chrome
sends, in Chrome's order, and writing the bytes where
`Browser.setDownloadBehavior` said downloads go.

What it records is what the acceptance criteria ask about — which addresses
the tab was pointed at, in order, and which reads were made — so a test can
prove that the skills the account did not write were never fetched and that
nothing was clicked.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from dataporter.browser import export_page, login_form, probe, session
from dataporter.browser import sketch as sketching
from dataporter.browser import skills as reading
from fake_chatgpt_pages import frame_navigated, response_received
from fake_chrome import Call, FakeChrome, FakeTarget
from fake_composer import js_const

ORG = "ccbfbca0-c0b7-4421-835e-1dbaeacc6b29"
"""The organisation's uuid, as the committed login trace spells one."""

SIGNED_OUT_URL = "https://claude.ai/login"
"""Where claude.ai sends a request for the export page it will not serve."""

DOWNLOAD_MARKER = "download-dot-skill-file"
"""What tells a download navigation from any other, without importing the path."""


def entry(
    skill_id: str,
    name: str,
    creator_type: str = reading.OURS,
    *,
    enabled: bool = True,
    plugin: str | None = None,
) -> dict[str, Any]:
    """Return one listing entry as claude.ai spells it, fields the tool ignores included.

    The description and the display name are here so that a test can prove
    they never leave the page: the fake maps an entry to the five fields the
    expression keeps, and everything else stays in this dict.
    """
    return {
        "id": skill_id,
        "name": name,
        "display_name": name.replace("-", " ").title(),
        "description": "A description the tool never reads.",
        "creator_type": creator_type,
        "enabled": enabled,
        "backing_plugin_id": plugin,
        "source": "plugin" if plugin else "user",
    }


@dataclass
class FakeSkillsPage:
    """The export page, as a skills extraction sees it, and the site behind it."""

    url: str = export_page.EXPORT_PAGE_URL
    entries: list[dict[str, Any]] = field(default_factory=list)
    """What `list-skills` answers, in the vendor's shape."""

    bodies: dict[str, bytes] = field(default_factory=dict)
    """The bytes each skill's address serves, by id. A listed id with no body
    is refused with a `500`, which is one skill that will not come back (§93)."""

    stalls: set[str] = field(default_factory=set)
    """Ids whose download begins and then says nothing more."""

    org: str | None = ORG
    org_status: int = 200
    list_status: int = 200
    """What the two reads answer. A status other than `200` is a read that failed."""

    list_answers: dict[str, Any] | None = None
    """What the list read answers verbatim, when a test wants a body the
    expression would not recognise — a `200` that is not a list of skills."""

    signed_out: bool = False
    """Whether the site sends the export page's request to `/login` instead."""

    download_dir: Path | None = None
    fetched: list[str] = field(default_factory=list)
    """Every download address the tab was pointed at, in order."""

    reads: list[str] = field(default_factory=list)
    """The tags of every expression answered, in order."""

    chrome: FakeChrome | None = None

    # -- what the page answers --------------------------------------------- #

    def state(self) -> dict[str, Any]:
        """Return what `07`'s probe makes of this page: no composer, as the export page has none."""
        return {
            "url": SIGNED_OUT_URL if self.signed_out else self.url,
            "composer_present": False,
            "composer_chars": 0,
            "generating": False,
            "send_enabled": False,
            "dom_dialogs": 0,
        }

    def organisations(self) -> dict[str, Any]:
        if self.org_status != 200:
            return {"status": self.org_status}
        return {"status": 200, "org": self.org}

    def listing(self) -> dict[str, Any]:
        """Return what `list_js` returns: five fields per entry, and nothing else of them."""
        if self.list_status != 200:
            return {"status": self.list_status}
        if self.list_answers is not None:
            return dict(self.list_answers)
        return {
            "status": 200,
            "skills": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "creator_type": item["creator_type"],
                    "enabled": item["enabled"] is True,
                    "plugin": bool(item.get("backing_plugin_id")),
                }
                for item in self.entries
            ],
        }

    def answer_download(self, url: str) -> None:
        """Push what a browser sends for a skill's address, in the order Chrome sends it."""
        assert self.chrome is not None
        self.fetched.append(url)
        skill_id = parse_qs(urlsplit(url).query).get("skill_id", [""])[0]
        push = self.chrome.push
        push(frame_navigated(url))
        if skill_id in self.stalls:
            # Chrome had begun writing: a `.crdownload` that then stops growing.
            assert self.download_dir is not None
            (self.download_dir / f"guid-{len(self.fetched)}.crdownload").write_bytes(b"PK\x03\x04 half")
            return
        body = self.bodies.get(skill_id)
        if body is None:
            push(response_received(url, 500, "application/json"))
            return
        push(response_received(url, 200, "application/zip"))
        guid = f"guid-{len(self.fetched)}"
        name = next(item["name"] for item in self.entries if item["id"] == skill_id)
        push({
            "method": "Browser.downloadWillBegin",
            "params": {"frameId": "F1", "guid": guid, "url": url, "suggestedFilename": f"{name}.skill"},
        })
        assert self.download_dir is not None
        (self.download_dir / guid).write_bytes(body)
        push({
            "method": "Browser.downloadProgress",
            "params": {"guid": guid, "totalBytes": len(body), "receivedBytes": len(body), "state": "completed"},
        })

    # -- answering CDP ------------------------------------------------------- #

    def evaluate(self, expression: str) -> Any:
        if expression == "location.href":
            return self.url
        if expression == session.READY_JS:
            return self.url
        if expression == login_form.SETTLED_JS:
            return True
        answers = (
            (reading.ORG_TAG, self.organisations),
            (reading.LIST_TAG, self.listing),
            (probe.PAGE_STATE_TAG, self.state),
            (sketching.SELECTORS_TAG, lambda: dict.fromkeys(js_const(expression, "table"), 0)),
        )
        for tag, answer in answers:
            if tag in expression:
                self.reads.append(tag)
                return answer()
        raise AssertionError(f"unexpected expression: {expression[:80]}")

    def respond(self, call: Call) -> dict[str, Any] | None:
        if call.method == "Runtime.evaluate":
            return {"result": {"result": {"value": self.evaluate(str(call.params["expression"]))}}}
        if call.method == "Browser.setDownloadBehavior":
            self.download_dir = Path(str(call.params["downloadPath"]))
            return {"result": {}}
        if call.method == "Page.navigate":
            url = str(call.params.get("url", ""))
            if DOWNLOAD_MARKER in url:
                # A navigation that became a download commits no document: the
                # tab stays where it was, in the target list and in the page.
                self.answer_download(url)
                return {"result": {}}
            self.url = url
            return None
        return None


def browser(page: FakeSkillsPage, port: int = 0) -> FakeChrome:
    """Return a fake Chrome with this page on its one tab, and the page wired to push through it."""
    fake = FakeChrome(
        targets=[FakeTarget(id="page-1", url=page.url)],
        responder=lambda _chrome, call: page.respond(call),
        port=port,
    )
    page.chrome = fake
    return fake
