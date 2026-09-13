"""The watch (`35`): every event the brief names, as the line it becomes.

The fake Chrome pushes events to every open connection unprompted, the way a
browser does, so each row of `35`'s table is one pushed event and one line
read back. The live cases point a real Chromium at the fixture pages for the
two things a fake cannot show: a redirect the page makes itself, and a
`history.replaceState`.
"""

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from dataporter import trace as tracing
from dataporter.browser import launcher, probe
from dataporter.browser import watch as watching
from dataporter.browser.cdp import CdpClient
from dataporter.browser.site import Site
from dataporter.config import BrowserSettings, Settings, TimeoutSettings
from fake_chrome import FakeChrome, FakeTarget, entered
from fake_composer import Browser, FakePage
from live_browser import live_browser, requires_a_browser, visit

pytestmark = pytest.mark.slow
"""Every test here opens a WebSocket to a fake Chrome."""

NEW_URL = "https://claude.ai/new"
CHAT_URL = "https://claude.ai/chat/2b1f7c3e-4d5a-4f6b-8c7d-9e0f1a2b3c4d"
WAIT_S = 3.0


def lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def observations(path: Path) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in line.items() if key not in {"ts", "t_ms"}}
        for line in lines(path)
        if line["kind"] == "observation"
    ]


def wait_for(path: Path, count: int) -> None:
    """Wait until the trace holds `count` lines after its header."""
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        if len(lines(path)) - 1 >= count:
            return
        time.sleep(0.02)
    raise AssertionError(f"{count} lines never arrived: {lines(path)}")


def event(method: str, **params: Any) -> dict[str, Any]:
    return {"method": method, "params": params}


def navigated(url: str, *, parent: str | None = None) -> dict[str, Any]:
    frame: dict[str, Any] = {"id": "F1", "url": url}
    if parent is not None:
        frame["parentId"] = parent
    return event("Page.frameNavigated", frame=frame, type="Navigation")


def request(
    identifier: str, url: str, *, kind: str = "Fetch", method: str = "POST", stamp: float = 1.0
) -> dict[str, Any]:
    return event(
        "Network.requestWillBeSent",
        requestId=identifier,
        request={"url": url, "method": method, "headers": {"Cookie": "secret=1"}, "postData": "a message"},
        timestamp=stamp,
        type=kind,
    )


def response(
    identifier: str,
    url: str,
    *,
    status: int = 200,
    mime: str = "application/json",
    security: dict[str, Any] | None = None,
    stamp: float = 1.2,
) -> dict[str, Any]:
    body: dict[str, Any] = {"url": url, "status": status, "mimeType": mime, "headers": {"Set-Cookie": "secret=2"}}
    if security is not None:
        body["securityDetails"] = security
    return event("Network.responseReceived", requestId=identifier, timestamp=stamp, type="Fetch", response=body)


def finished(identifier: str, *, size: int = 211, stamp: float = 1.282) -> dict[str, Any]:
    return event("Network.loadingFinished", requestId=identifier, timestamp=stamp, encodedDataLength=size)


@pytest.fixture
def browser() -> Iterator[Browser]:
    with Browser(FakePage(url=NEW_URL)) as made:
        yield made


@pytest.fixture
def traced(browser: Browser, tmp_path: Path) -> Iterator[tracing.Trace]:
    settings = browser.settings(tmp_path)
    trace = tracing.Trace.open(settings, command="import", flags=(), site=probe.MIGRATION_SITE, chrome=None, agent=None)
    yield trace
    if not trace.ended:
        trace.close()


@pytest.fixture
def watch(browser: Browser, traced: tracing.Trace) -> Iterator[watching.Watch]:
    started = watching.Watch.start(traced, browser.client, probe.MIGRATION_SITE)
    assert started.running
    yield started
    started.stop()


# --------------------------------------------------------------------------- #
# The table, one row at a time
# --------------------------------------------------------------------------- #


def test_the_watch_enables_the_four_domains_and_nothing_else(browser: Browser, watch: watching.Watch) -> None:
    watch.stop()
    assert browser.chrome.methods() == [
        "Page.enable",
        "Network.enable",
        "Target.setDiscoverTargets",
        "Accessibility.enable",
    ]


def test_a_navigation_is_a_line_and_its_sketch_waits_for_the_load(
    browser: Browser, traced: tracing.Trace, watch: watching.Watch
) -> None:
    browser.chrome.push(navigated("https://claude.ai/login?code=s3cret#frag"))
    wait_for(traced.path, 1)
    assert [line["kind"] for line in lines(traced.path)[1:]] == ["observation"]
    assert observations(traced.path) == [
        {"kind": "observation", "what": "navigation", "path": "/login", "query": ["code"]}
    ]

    browser.chrome.push(event("Page.loadEventFired", timestamp=2.0))
    wait_for(traced.path, 2)
    sketch = lines(traced.path)[2]
    assert sketch["kind"] == "sketch"
    assert sketch["path"] == "/login"
    assert sketch["query"] == ["code"]
    assert "s3cret" not in traced.path.read_text(encoding="utf-8")


def test_a_child_frame_s_navigation_is_not_the_page_s(
    browser: Browser, traced: tracing.Trace, watch: watching.Watch
) -> None:
    browser.chrome.push(navigated("https://claude.ai/embedded", parent="F0"))
    browser.chrome.push(event("Page.loadEventFired", timestamp=2.0))
    browser.chrome.push(event("Page.navigatedWithinDocument", frameId="F1", url=CHAT_URL))
    wait_for(traced.path, 2)
    assert observations(traced.path) == [
        {
            "kind": "observation",
            "what": "url_changed",
            "path": "/chat/2b1f7c3e-4d5a-4f6b-8c7d-9e0f1a2b3c4d",
            "query": [],
        }
    ]


def test_a_url_change_within_the_document_is_sketched_at_once(
    browser: Browser, traced: tracing.Trace, watch: watching.Watch
) -> None:
    browser.chrome.push(event("Page.navigatedWithinDocument", frameId="F1", url=CHAT_URL))
    wait_for(traced.path, 2)
    written = lines(traced.path)[1:]
    assert [line["kind"] for line in written] == ["observation", "sketch"]
    assert written[0]["what"] == "url_changed"
    assert written[1]["path"] == "/chat/2b1f7c3e-4d5a-4f6b-8c7d-9e0f1a2b3c4d"
    # The sketch's one evaluate is the selector count; the URL came from the event.
    evaluated = [call for call in browser.chrome.calls if call.method == "Runtime.evaluate"]
    assert len(evaluated) == 1
    assert "dataporter:selectors" in str(evaluated[0].params["expression"])


def test_a_dialog_is_its_type_and_never_its_message(
    browser: Browser, traced: tracing.Trace, watch: watching.Watch
) -> None:
    browser.chrome.push(
        event(
            "Page.javascriptDialogOpening",
            url=NEW_URL,
            message="Leave? Your draft: hello",
            type="beforeunload",
            hasBrowserHandler=False,
        )
    )
    browser.chrome.push(event("Page.javascriptDialogClosed", result=True, userInput=""))
    wait_for(traced.path, 2)
    assert observations(traced.path) == [
        {"kind": "observation", "what": "dialog_opened", "type": "beforeunload"},
        {"kind": "observation", "what": "dialog_closed", "accepted": True},
    ]
    assert "draft" not in traced.path.read_text(encoding="utf-8")


def test_a_request_and_its_response_are_two_lines_with_their_own_id(
    browser: Browser, traced: tracing.Trace, watch: watching.Watch
) -> None:
    browser.chrome.push(request("1000.7", "https://claude.ai/api/chats?since=1"))
    browser.chrome.push(response("1000.7", "https://claude.ai/api/chats?since=1"))
    wait_for(traced.path, 1)
    assert observations(traced.path) == [
        {
            "kind": "observation",
            "what": "request",
            "id": "r1",
            "method": "POST",
            "path": "/api/chats",
            "query": ["since"],
            "type": "fetch",
        }
    ]
    browser.chrome.push(finished("1000.7"))
    wait_for(traced.path, 2)
    assert observations(traced.path)[1] == {
        "kind": "observation",
        "what": "response",
        "id": "r1",
        "status": 200,
        "content_type": "application/json",
        "bytes": 211,
        "elapsed_ms": 282,
    }
    written = traced.path.read_text(encoding="utf-8")
    assert "secret" not in written
    assert "a message" not in written
    assert "1000.7" not in written


def test_other_hosts_and_static_assets_are_not_recorded(
    browser: Browser, traced: tracing.Trace, watch: watching.Watch
) -> None:
    browser.chrome.push(request("1", "https://analytics.example.com/collect"))
    browser.chrome.push(request("2", "https://claude.ai/static/app.css", kind="Stylesheet"))
    browser.chrome.push(request("3", "https://claude.ai/static/app.js", kind="Script"))
    browser.chrome.push(finished("1"))
    browser.chrome.push(finished("2"))
    browser.chrome.push(request("4", "https://claude.ai/api/chats/1", kind="XHR", method="GET"))
    wait_for(traced.path, 1)
    time.sleep(0.3)
    assert observations(traced.path) == [
        {
            "kind": "observation",
            "what": "request",
            "id": "r1",
            "method": "GET",
            "path": "/api/chats/1",
            "query": [],
            "type": "xhr",
        }
    ]


def test_a_failed_load_is_a_response_of_nothing(browser: Browser, traced: tracing.Trace, watch: watching.Watch) -> None:
    browser.chrome.push(request("9", "https://claude.ai/api/chats", stamp=5.0))
    browser.chrome.push(event("Network.loadingFailed", requestId="9", timestamp=5.5, errorText="net::ERR_FAILED"))
    wait_for(traced.path, 2)
    assert observations(traced.path)[1] == {
        "kind": "observation",
        "what": "response",
        "id": "r1",
        "status": 0,
        "content_type": "",
        "bytes": 0,
        "elapsed_ms": 500,
    }


def test_the_certificate_is_written_once_from_the_first_response_that_carries_one(
    browser: Browser, traced: tracing.Trace, watch: watching.Watch
) -> None:
    security = {
        "protocol": "TLS 1.3",
        "issuer": "claude-mock",
        "subjectName": "claude.ai",
        "validFrom": 1,
        "validTo": 2,
    }
    browser.chrome.push(response("a", "https://claude.ai/", security=security))
    browser.chrome.push(response("b", "https://claude.ai/api/chats", security=security))
    browser.chrome.push(response("c", "https://cdn.example.com/x", security={"issuer": "Other", "subjectName": "cdn"}))
    wait_for(traced.path, 1)
    time.sleep(0.3)
    assert observations(traced.path) == [
        {
            "kind": "observation",
            "what": "certificate",
            "host": "claude.ai",
            "issuer": "claude-mock",
            "subject": "claude.ai",
        }
    ]


def test_tabs_appearing_and_closing_are_lines_and_the_existing_ones_are_not(
    browser: Browser, traced: tracing.Trace, watch: watching.Watch
) -> None:
    # Discovery announces what already exists first; only the new tab counts.
    browser.chrome.push(
        event("Target.targetCreated", targetInfo={"targetId": "page-1", "type": "page", "url": NEW_URL})
    )
    browser.chrome.push(event("Target.targetCreated", targetInfo={"targetId": "browser", "type": "browser", "url": ""}))
    browser.chrome.push(
        event(
            "Target.targetCreated",
            targetInfo={"targetId": "page-2", "type": "page", "url": "https://claude.ai/chat/abc?x=1"},
        )
    )
    browser.chrome.push(event("Target.targetDestroyed", targetId="page-2"))
    browser.chrome.push(event("Target.targetDestroyed", targetId="page-1"))
    wait_for(traced.path, 2)
    time.sleep(0.2)
    assert observations(traced.path) == [
        {"kind": "observation", "what": "target_created", "path": "/chat/abc", "query": ["x"]},
        {"kind": "observation", "what": "target_closed"},
    ]


# --------------------------------------------------------------------------- #
# Losing it, and stopping
# --------------------------------------------------------------------------- #


def test_a_broken_frame_is_watch_lost_and_the_trace_goes_on(
    browser: Browser, traced: tracing.Trace, watch: watching.Watch
) -> None:
    browser.chrome.push_raw("not json")
    wait_for(traced.path, 1)
    deadline = time.monotonic() + WAIT_S
    while watch.running and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not watch.running
    assert observations(traced.path) == [
        {"kind": "observation", "what": "watch_lost", "reason": "browser sent a frame that is not JSON"}
    ]
    assert traced.observation("navigation", path="/new", query=[]) is True
    traced.end(0)
    assert lines(traced.path)[-1]["what"] == "end"


def test_stop_closes_the_session_and_writes_nothing(
    browser: Browser, traced: tracing.Trace, watch: watching.Watch
) -> None:
    before = browser.chrome.open_connections
    started = time.monotonic()
    watch.stop()
    assert time.monotonic() - started < watching.STOP_S
    assert not watch.running
    deadline = time.monotonic() + WAIT_S
    while browser.chrome.open_connections >= before and time.monotonic() < deadline:
        time.sleep(0.02)
    assert browser.chrome.open_connections < before
    assert lines(traced.path)[1:] == []
    watch.stop()


def test_without_a_trace_there_is_no_watch(browser: Browser) -> None:
    watch = watching.Watch.start(None, browser.client, probe.MIGRATION_SITE)
    assert not watch.running
    watch.stop()
    assert browser.chrome.methods() == []


def test_a_tab_that_cannot_be_watched_is_watch_lost(tmp_path: Path) -> None:
    with FakeChrome(targets=[FakeTarget(id="page-1", url="https://example.com/")]) as chrome:
        settings = Settings(workspace=tmp_path / "migration", browser=BrowserSettings(cdp_port=chrome.port))
        trace = tracing.Trace.open(
            settings, command="import", flags=(), site=probe.MIGRATION_SITE, chrome=None, agent=None
        )
        watch = watching.Watch.start(trace, CdpClient(port=chrome.port, timeout=2.0), probe.MIGRATION_SITE)
        assert not watch.running
        watch.stop()
        trace.close()
    assert observations(trace.path) == [
        {"kind": "observation", "what": "watch_lost", "reason": "no tab on claude.ai to watch"}
    ]


def test_a_refused_enable_is_watch_lost_and_the_page_is_let_go(browser: Browser, traced: tracing.Trace) -> None:
    def refuse(chrome: FakeChrome, call: Any) -> dict[str, Any] | None:
        if call.method == "Network.enable":
            return {"error": {"code": -32601, "message": "no network domain"}}
        return None

    original = browser.chrome.responder
    browser.chrome.responder = lambda chrome, call: (
        refuse(chrome, call) or (original(chrome, call) if original else None)
    )
    watch = watching.Watch.start(traced, browser.client, probe.MIGRATION_SITE)
    assert not watch.running
    traced.close()
    assert observations(traced.path)[0]["what"] == "watch_lost"
    assert "no network domain" in observations(traced.path)[0]["reason"]


def test_a_trace_that_ended_stops_the_watch_quietly(
    browser: Browser, traced: tracing.Trace, watch: watching.Watch
) -> None:
    traced.end(0)
    browser.chrome.push(event("Page.navigatedWithinDocument", frameId="F1", url=CHAT_URL))
    deadline = time.monotonic() + WAIT_S
    while watch.running and time.monotonic() < deadline:
        time.sleep(0.02)
    assert lines(traced.path)[-1]["what"] == "end"


def test_watched_starts_after_the_header_and_stops_before_the_end(browser: Browser, tmp_path: Path) -> None:
    settings = browser.settings(tmp_path)
    session = launcher.BrowserSession(client=browser.client, profile=settings.browser_profile_dir, adopted=True)
    with watching.watched(settings, command="verify", flags=(), site=probe.MIGRATION_SITE, browser=session) as traced:
        assert traced.trace is not None
        browser.chrome.push(event("Page.navigatedWithinDocument", frameId="F1", url=CHAT_URL))
        wait_for(traced.trace.path, 2)
        traced.exit_code = 0
    written = lines(traced.trace.path)
    assert [line["kind"] for line in written] == ["header", "observation", "sketch", "observation"]
    assert written[-1]["what"] == "end"


# --------------------------------------------------------------------------- #
# Live: what a fake cannot show
# --------------------------------------------------------------------------- #


def _live_settings(session: launcher.BrowserSession, tmp_path: Path) -> Settings:
    return Settings(
        workspace=tmp_path / "migration",
        browser=BrowserSettings(cdp_port=session.client.port),
        timeouts=TimeoutSettings(cdp_call_s=30.0),
    )


@requires_a_browser
def test_live_a_redirect_the_page_makes_is_a_navigation_with_a_sketch(tmp_path: Path) -> None:
    with live_browser() as (session, server):
        visit(session, server.url("/new"))
        settings = _live_settings(session, tmp_path)
        site = Site("claude", "127.0.0.1", probe.SELECTORS)
        trace = tracing.Trace.open(settings, command="login", flags=(), site=site, chrome=None, agent=None)
        watch = watching.Watch.start(trace, session.client, site)
        assert watch.running
        page = session.client.attach(session.client.pages()[0].id)
        try:
            page.navigate(server.url("/redirect"))
            # Until the sketch of `/new` has landed, not only its navigation:
            # stopping the watch mid-sketch would cut the line off.
            _wait_until(trace.path, lambda line: line["kind"] == "sketch" and line.get("path") == "/new")
        finally:
            page.close()
            watch.stop()
            trace.close()
    written = lines(trace.path)
    paths = [line["path"] for line in written if line.get("what") == "navigation"]
    assert "/redirect" in paths
    assert "/new" in paths
    sketches = [line for line in written if line["kind"] == "sketch"]
    assert any(line["path"] == "/new" and line["selectors"]["COMPOSER_SELECTOR"] == 1 for line in sketches)
    # The page's own two document loads are same-host requests of a watched
    # type; a static fixture makes no other.
    requests = [(line["type"], line["path"]) for line in written if line.get("what") == "request"]
    assert requests == [("document", "/redirect"), ("document", "/new")]


def _wait_until(path: Path, wanted: Any, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if any(wanted(line) for line in lines(path)):
            return
        time.sleep(0.1)
    raise AssertionError(f"never arrived: {lines(path)}")


@requires_a_browser
def test_live_a_replace_state_is_a_url_change(tmp_path: Path) -> None:
    with live_browser() as (session, server):
        visit(session, server.url("/replace-state"))
        settings = _live_settings(session, tmp_path)
        site = Site("claude", "127.0.0.1", probe.SELECTORS)
        trace = tracing.Trace.open(settings, command="import", flags=(), site=site, chrome=None, agent=None)
        watch = watching.Watch.start(trace, session.client, site)
        page = session.client.attach(session.client.pages()[0].id)
        try:
            page.evaluate("document.getElementById('submit').click()")
            # Until the sketch has landed, for the reason the redirect case waits.
            _wait_until(trace.path, lambda line: line["kind"] == "sketch" and line.get("path", "").startswith("/chat/"))
        finally:
            page.close()
            watch.stop()
            trace.close()
    written = lines(trace.path)
    changed = [line for line in written if line.get("what") == "url_changed"]
    assert changed
    assert changed[0]["path"] == "/chat/2b1f7c3e-4d5a-4f6b-8c7d-9e0f1a2b3c4d"
    assert any(line["kind"] == "sketch" and line["path"].startswith("/chat/") for line in written)


def test_a_sketch_the_browser_refuses_is_a_warning_and_the_line_still_lands(
    browser: Browser, traced: tracing.Trace
) -> None:
    def refuse(chrome: FakeChrome, call: Any) -> dict[str, Any] | None:
        if call.method == "Accessibility.getFullAXTree":
            return {"error": {"code": -32000, "message": "no tree"}}
        return None

    original = browser.chrome.responder
    browser.chrome.responder = lambda chrome, call: (
        refuse(chrome, call) or (original(chrome, call) if original else None)
    )
    watch = watching.Watch.start(traced, browser.client, probe.MIGRATION_SITE)
    try:
        browser.chrome.push(event("Page.navigatedWithinDocument", frameId="F1", url=CHAT_URL))
        wait_for(traced.path, 1)
        time.sleep(0.3)
    finally:
        watch.stop()
    assert [line["kind"] for line in lines(traced.path)[1:]] == ["observation"]
    assert observations(traced.path)[0]["what"] == "url_changed"


def test_a_browser_that_goes_away_is_watch_lost(tmp_path: Path) -> None:
    chrome = entered(FakeChrome(targets=[FakeTarget(id="page-1", url=NEW_URL)]))
    settings = Settings(workspace=tmp_path / "migration", browser=BrowserSettings(cdp_port=chrome.port))
    trace = tracing.Trace.open(settings, command="import", flags=(), site=probe.MIGRATION_SITE, chrome=None, agent=None)
    watch = watching.Watch.start(trace, CdpClient(port=chrome.port, timeout=2.0), probe.MIGRATION_SITE)
    assert watch.running
    chrome.stop()
    deadline = time.monotonic() + WAIT_S
    while watch.running and time.monotonic() < deadline:
        time.sleep(0.02)
    watch.stop()
    trace.close()
    assert not watch.running
    lost = observations(trace.path)
    assert len(lost) == 1
    assert lost[0]["what"] == "watch_lost"
    assert lost[0]["reason"].startswith("browser connection lost")
