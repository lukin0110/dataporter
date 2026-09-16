"""The page in outline (`34`): the roles, the collapse, the hash, and what never leaks.

Most of it is `outline` on hand-built trees, which needs no browser. `take`
runs against the fake Chrome, and the one live test points a real Chromium at
`leaky.html` — a page seeded with everything a sketch must never carry — and
reads the whole trace file a probe leaves behind.
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from dataporter import trace as tracing
from dataporter.browser import helpers, launcher, probe
from dataporter.browser import sketch as sketching
from dataporter.browser.site import Site
from dataporter.config import BrowserSettings, Settings, TimeoutSettings
from fake_chrome import Call, FakeChrome, FakeTarget
from fake_composer import Browser, FakePage, js_const
from fake_pages import PageServer
from live_browser import live_browser, requires_a_browser, visit

NEW_URL = "https://claude.ai/new"
HEX12 = re.compile(r"^[0-9a-f]{12}$")


def node(
    role: str, name: str = "", *, ignored: bool = False, disabled: bool = False, value: str | None = None
) -> dict[str, Any]:
    """One node as `Accessibility.getFullAXTree` reports it."""
    made: dict[str, Any] = {
        "nodeId": "n",
        "ignored": ignored,
        "role": {"type": "role", "value": role},
        "name": {"type": "computedString", "value": name},
    }
    if disabled:
        made["properties"] = [{"name": "disabled", "value": {"type": "boolean", "value": True}}]
    if value is not None:
        made["value"] = {"type": "string", "value": value}
    return made


LINKS = [f"Conversation {index}" for index in range(12)]
TREE: list[dict[str, Any]] = [
    node("RootWebArea", "New chat"),
    node("generic"),
    node("textbox", "Write your prompt to Claude", value=""),
    node("StaticText", "some text that is not a control"),
    node("button", "Send message", disabled=True),
    *[node("link", title) for title in LINKS],
]
CONTROLS: list[dict[str, Any]] = [
    {"role": "textbox", "label": "Write your prompt to Claude", "chars": 0},
    {"role": "button", "label": "Send message", "disabled": True},
    {"role": "link", "count": 12, "chars": sum(len(title) for title in LINKS)},
]
"""Brief `04` §42's sketch line, from the tree above."""


def settings_for(tmp_path: Path) -> Settings:
    return Settings(workspace=tmp_path / "migration")


def sketch_of(**overrides: Any) -> sketching.Sketch:
    fields: dict[str, Any] = {
        "path": "/new",
        "query": (),
        "title_chars": 8,
        "controls": tuple(CONTROLS),
        "selectors": {"COMPOSER_SELECTOR": 1, "MESSAGE_SELECTOR": 0, "TITLE_SELECTOR": 0, "FILE_INPUT_SELECTOR": 1},
        "dialogs": (),
    }
    fields.update(overrides)
    return sketching.Sketch(**fields)


def lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --------------------------------------------------------------------------- #
# The outline
# --------------------------------------------------------------------------- #


def test_the_outline_is_the_briefs_controls() -> None:
    controls, title_chars = sketching.outline(TREE)
    assert controls == CONTROLS
    assert title_chars == len("New chat")
    for title in LINKS:
        assert title not in json.dumps(controls)


@pytest.mark.parametrize("role", ["link", "heading", "listitem", "image", "navigation"])
def test_a_shaped_node_keeps_its_role_and_shape_and_never_its_name(role: str) -> None:
    controls, _ = sketching.outline([node(role, "Salary negotiation notes")])
    assert controls == [
        {
            "role": role,
            "chars": len("Salary negotiation notes"),
            "hash": sketching.name_hash("Salary negotiation notes"),
        }
    ]
    assert HEX12.match(controls[0]["hash"])
    assert "Salary" not in json.dumps(controls)


def test_a_run_of_one_role_collapses_and_a_break_ends_it() -> None:
    controls, _ = sketching.outline([
        node("link", "aa"),
        node("link", "bbb"),
        node("heading", "cccc"),
        node("link", "d"),
    ])
    assert controls == [
        {"role": "link", "count": 2, "chars": 5},
        {"role": "heading", "chars": 4, "hash": sketching.name_hash("cccc")},
        {"role": "link", "chars": 1, "hash": sketching.name_hash("d")},
    ]


def test_a_labelled_control_between_two_links_breaks_the_run() -> None:
    controls, _ = sketching.outline([node("link", "a"), node("button", "Rename"), node("link", "b")])
    assert [control["role"] for control in controls] == ["link", "button", "link"]
    assert all("count" not in control for control in controls)


def test_a_textbox_reports_its_chars_and_never_its_value() -> None:
    controls, _ = sketching.outline([node("textbox", "Write your prompt", value="MIGRATION-SEED part 1")])
    assert controls == [{"role": "textbox", "label": "Write your prompt", "chars": len("MIGRATION-SEED part 1")}]
    assert "MIGRATION" not in json.dumps(controls)


def test_a_disabled_control_says_so_and_an_enabled_one_says_nothing() -> None:
    controls, _ = sketching.outline([node("button", "Send message", disabled=True), node("button", "Stop response")])
    assert controls == [
        {"role": "button", "label": "Send message", "disabled": True},
        {"role": "button", "label": "Stop response"},
    ]


def test_a_label_is_bounded_and_cannot_forge_a_line() -> None:
    controls, _ = sketching.outline([node("button", "x" * 200 + "\ny"), node("button", "")])
    assert len(controls[0]["label"]) == sketching.LABEL_LIMIT
    assert "\n" not in controls[0]["label"]
    assert controls[1] == {"role": "button", "label": ""}


def test_ignored_and_unknown_nodes_are_skipped() -> None:
    controls, title_chars = sketching.outline([
        node("RootWebArea", "T", ignored=True),
        node("button", "hidden", ignored=True),
        node("paragraph", "a paragraph"),
        node("generic"),
        node("button", "Accept all"),
    ])
    assert controls == [{"role": "button", "label": "Accept all"}]
    assert title_chars == 0


def test_a_tree_that_is_not_a_list_is_an_empty_outline() -> None:
    assert sketching.outline([]) == ([], 0)


# --------------------------------------------------------------------------- #
# The hash and the line
# --------------------------------------------------------------------------- #


def test_the_hash_is_stable_and_changes_with_a_label() -> None:
    assert sketch_of().hash == sketch_of().hash
    assert HEX12.match(sketch_of().hash)
    changed = sketch_of(controls=(*CONTROLS[:-1], {"role": "link", "count": 13, "chars": 1}))
    assert changed.hash != sketch_of().hash


def test_the_line_is_the_briefs(tmp_path: Path) -> None:
    trace = tracing.Trace.open(
        settings_for(tmp_path),
        command="import",
        flags=(),
        site=probe.MIGRATION_SITE,
        chrome=None,
        agent=None,
    )
    digest = trace.sketch(sketch_of())
    trace.close()
    _, line = lines(trace.path)
    assert list(line) == [
        "kind",
        "ts",
        "t_ms",
        "hash",
        "path",
        "query",
        "title_chars",
        "controls",
        "selectors",
        "dialogs",
    ]
    assert line["kind"] == "sketch"
    assert line["hash"] == digest == sketch_of().hash
    assert line["path"] == "/new"
    assert line["query"] == []
    assert line["title_chars"] == 8
    assert line["controls"] == CONTROLS
    assert line["selectors"] == {
        "COMPOSER_SELECTOR": 1,
        "MESSAGE_SELECTOR": 0,
        "TITLE_SELECTOR": 0,
        "FILE_INPUT_SELECTOR": 1,
    }
    assert line["dialogs"] == []


def test_a_second_sketch_of_the_same_page_writes_nothing(tmp_path: Path) -> None:
    trace = tracing.Trace.open(
        settings_for(tmp_path), command="import", flags=(), site=probe.MIGRATION_SITE, chrome=None, agent=None
    )
    first = trace.sketch(sketch_of())
    second = trace.sketch(sketch_of())
    third = trace.sketch(sketch_of(path="/chat/1"))
    trace.close()
    assert first == second != third
    assert [line["hash"] for line in lines(trace.path)[1:]] == [first, third]


def test_an_attached_trace_knows_the_files_sketches(tmp_path: Path) -> None:
    trace = tracing.Trace.open(
        settings_for(tmp_path), command="import", flags=(), site=probe.MIGRATION_SITE, chrome=None, agent=None
    )
    known = trace.sketch(sketch_of())
    trace.close()
    attached = tracing.Trace.attached(trace.path)
    assert attached is not None
    assert attached.sketch(sketch_of()) == known
    attached.close()
    assert len(lines(trace.path)) == 2


# --------------------------------------------------------------------------- #
# Taking one
# --------------------------------------------------------------------------- #


def test_selectors_js_carries_the_table_by_name() -> None:
    site = Site("claude", "claude.ai", {"A": "div", "B": 'input[type="file"]'})
    expression = sketching.selectors_js(site)
    assert sketching.SELECTORS_TAG in expression
    assert js_const(expression, "table") == {"A": "div", "B": 'input[type="file"]'}


@pytest.fixture
def browser() -> Iterator[Browser]:
    with Browser(FakePage(url=NEW_URL)) as made:
        made.chrome.targets[0].ax_tree = TREE
        yield made


@pytest.mark.slow
def test_take_reads_the_tree_the_counts_and_the_url(browser: Browser) -> None:
    page = browser.client.attach("page-1")
    try:
        sketch = sketching.take(page, probe.MIGRATION_SITE)
    finally:
        page.close()
    assert list(sketch.controls) == CONTROLS
    assert sketch.title_chars == 8
    assert sketch.path == "/new"
    assert sketch.query == ()
    assert sketch.selectors == {
        "COMPOSER_SELECTOR": 1,
        "HUMAN_MESSAGE_SELECTOR": 0,
        "MESSAGE_SELECTOR": 0,
        "TITLE_SELECTOR": 0,
        "FILE_INPUT_SELECTOR": 1,
    }
    assert sketch.dialogs == ()
    assert {"Accessibility.enable", "Accessibility.getFullAXTree"} <= set(browser.chrome.methods())


@pytest.mark.slow
def test_a_count_that_is_not_a_number_is_zero() -> None:
    def answer(call: Call) -> Any:
        if sketching.SELECTORS_TAG in str(call.params.get("expression", "")):
            return {"A": "many", "B": True, "C": 3}
        return {"nodes": []}

    with FakeChrome(targets=[FakeTarget(id="page-1", url=NEW_URL, evaluate=answer)]) as chrome:
        page = launcher.BrowserSession(client=chrome_client(chrome), profile=Path()).client.attach("page-1")
        try:
            sketch = sketching.take(page, Site("claude", "claude.ai", {"A": "a", "B": "b", "C": "c", "D": "d"}))
        finally:
            page.close()
    assert sketch.selectors == {"A": 0, "B": 0, "C": 3, "D": 0}
    # `location.href` answered with a dict falls back to the target's URL.
    assert sketch.path == "/new"


def chrome_client(chrome: FakeChrome) -> Any:
    from dataporter.browser.cdp import CdpClient  # ruff: ignore[import-outside-top-level] - one test's helper

    return CdpClient(port=chrome.port, timeout=2.0)


# --------------------------------------------------------------------------- #
# Live: the leaky page
# --------------------------------------------------------------------------- #

SEEDED = (
    "Planning the Lisbon trip",
    "Salary negotiation",
    "Therapy journal",
    "Passwords I keep forgetting",
    "maria.oliveira@example.com",
    "Alfama",
    "five-day itinerary",
    "MIGRATION-SEED",
    "abc123",
)
"""Every string `leaky.html` carries that a sketch must not."""


def _fixture_surface(server: PageServer) -> helpers.Surface:
    return helpers.Surface(
        origin=f"http://127.0.0.1:{server.port}",
        allowed=re.compile(rf"^http://127\.0\.0\.1:{server.port}/leaky(\?.*)?$"),
        site=Site("claude", "127.0.0.1", probe.SELECTORS),
    )


@requires_a_browser
def test_live_a_sketch_of_a_leaky_page_keeps_no_content(tmp_path: Path) -> None:
    with live_browser() as (session, server):
        visit(session, server.url("/leaky?token=abc123"))
        settings = Settings(
            workspace=tmp_path / "migration",
            browser=BrowserSettings(cdp_port=session.client.port),
            timeouts=TimeoutSettings(cdp_call_s=30.0),
        )
        trace = tracing.Trace.open(
            settings, command="import", flags=(), site=probe.MIGRATION_SITE, chrome=None, agent=None
        )
        tracing.set_current(trace)
        try:
            surface = _fixture_surface(server)
            emission = helpers.run(settings, "probe", lambda client, s: helpers.probe_page(client, s, surface=surface))
        finally:
            tracing.finish(trace, 0)
    assert json.loads(emission.text)["ok"] is True

    written = trace.path.read_text(encoding="utf-8")
    for seeded in SEEDED:
        assert seeded not in written, seeded
    sketches = [line for line in lines(trace.path) if line["kind"] == "sketch"]
    assert len(sketches) == 1
    sketch = sketches[0]
    labels = [control.get("label") for control in sketch["controls"]]
    assert "Send message" in labels
    assert "Write your prompt to Claude" in labels
    assert "Accept all" in labels
    assert sketch["query"] == ["token"]
    assert sketch["title_chars"] == len("Planning the Lisbon trip")
    assert {
        "role": "link",
        "count": 12,
        "chars": sum(
            len(title)
            for title in (
                "Planning the Lisbon trip",
                "Salary negotiation notes",
                "Therapy journal",
                "Mortgage numbers",
                "Divorce timeline",
                "Medical results",
                "Passwords I keep forgetting",
                "Letter to my sister",
                "Startup pitch draft",
                "Tax questions",
                "Apartment hunting",
                "Wedding speech",
            )
        ),
    } in sketch["controls"]
    assert sketch["selectors"] == {
        "COMPOSER_SELECTOR": 1,
        "HUMAN_MESSAGE_SELECTOR": 1,
        "MESSAGE_SELECTOR": 2,
        "TITLE_SELECTOR": 1,
        "FILE_INPUT_SELECTOR": 1,
    }
    move = next(line for line in lines(trace.path) if line["kind"] == "move")
    assert move["before"] == move["after"] == sketch["hash"]


# --------------------------------------------------------------------------- #
# When a sketch cannot be taken, and what an attached trace reads back
# --------------------------------------------------------------------------- #


@pytest.mark.slow
def test_a_sketch_that_cannot_be_taken_is_none_and_the_move_still_lands(tmp_path: Path) -> None:
    """The trace is evidence, the helper is the product: a refused tree is a warning."""

    def refuse(chrome: FakeChrome, call: Call) -> dict[str, Any] | None:
        if call.method == "Accessibility.enable":
            return {"error": {"code": -32000, "message": "no accessibility here"}}
        return None

    with Browser(FakePage(url=NEW_URL)) as browser:
        browser.chrome.responder = _both(browser.chrome.responder, refuse)
        settings = browser.settings(tmp_path)
        trace = tracing.Trace.open(
            settings, command="import", flags=(), site=probe.MIGRATION_SITE, chrome=None, agent=None
        )
        tracing.set_current(trace)
        try:
            emission = helpers.run(settings, "probe", helpers.probe_page)
        finally:
            tracing.finish(trace, 0)
    assert json.loads(emission.text)["ok"] is True
    written = lines(trace.path)
    assert [line["kind"] for line in written] == ["header", "move", "observation"]
    assert written[1]["before"] is None
    assert written[1]["after"] is None


def _both(first: Any, second: Any) -> Any:
    def answer(chrome: FakeChrome, call: Call) -> dict[str, Any] | None:
        found = second(chrome, call)
        return found if found is not None else first(chrome, call)

    return answer


def test_an_attached_trace_skips_lines_it_cannot_read_as_sketches(tmp_path: Path) -> None:
    trace = tracing.Trace.open(
        settings_for(tmp_path), command="import", flags=(), site=probe.MIGRATION_SITE, chrome=None, agent=None
    )
    known = trace.sketch(sketch_of())
    trace.close()
    with trace.path.open("a", encoding="utf-8") as handle:
        handle.write('{"kind":"sketch", not json\n')
        handle.write('{"kind":"sketch","hash":12}\n')
        handle.write('{"kind":"observation","what":"end","exit":0,"note":"\\"kind\\":\\"sketch\\""}\n')
    attached = tracing.Trace.attached(trace.path)
    assert attached is not None
    assert attached.sketch(sketch_of()) == known
    assert attached.sketch(sketch_of(path="/chat/1")) != known
    attached.close()
    written = trace.path.read_text(encoding="utf-8").splitlines()
    assert len(written) == 6
    assert json.loads(written[-1])["path"] == "/chat/1"


def test_current_attaches_once_per_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trace = tracing.Trace.open(
        settings_for(tmp_path), command="import", flags=(), site=probe.MIGRATION_SITE, chrome=None, agent=None
    )
    trace.close()
    monkeypatch.setenv(tracing.TRACE_ENV_VAR, str(trace.path))
    first = tracing.current()
    assert first is not None
    assert tracing.current() is first
    first.close()
    again = tracing.current()
    assert again is not None
    assert again is not first
    tracing.reset()


@requires_a_browser
def test_live_the_selector_counts_are_what_the_markup_holds() -> None:
    """`34`'s second live criterion: `new.html`, counted by the map's own selectors."""
    with live_browser() as (session, server):
        visit(session, server.url("/new"))
        page = session.client.attach(session.client.pages()[0].id)
        try:
            sketch = sketching.take(page, Site("claude", "127.0.0.1", probe.SELECTORS))
        finally:
            page.close()
    assert sketch.selectors == {
        "COMPOSER_SELECTOR": 1,
        "HUMAN_MESSAGE_SELECTOR": 0,
        "MESSAGE_SELECTOR": 0,
        "TITLE_SELECTOR": 0,
        "FILE_INPUT_SELECTOR": 1,
    }
    assert sketch.path == "/new"
    assert sketch.title_chars == len("New chat")
    labels = [control.get("label") for control in sketch.controls]
    assert "Send message" in labels
    assert {"role": "button", "label": "Send message", "disabled": True} in sketch.controls
