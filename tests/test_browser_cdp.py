"""The CDP client: what it asks, what it refuses, and what it never carries."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from dataporter.browser import cdp
from dataporter.errors import BrowserError, Category
from fake_chrome import (
    BROKEN_TARGET,
    Call,
    FakeChrome,
    FakeTarget,
    dialog_event,
    free_port,
)


@pytest.fixture
def chrome() -> Iterator[FakeChrome]:
    with FakeChrome(
        targets=[
            FakeTarget(id="page-1", url="https://claude.ai/new", evaluate={"ok": 1}),
            FakeTarget(
                id="worker-1", url="https://claude.ai/sw.js", type="service_worker"
            ),
        ]
    ) as fake:
        yield fake


@pytest.fixture
def client(chrome: FakeChrome) -> cdp.CdpClient:
    return cdp.CdpClient(port=chrome.port, timeout=5.0)


# --------------------------------------------------------------------------- #
# The HTTP half
# --------------------------------------------------------------------------- #


def test_version_and_browser_id(client: cdp.CdpClient, chrome: FakeChrome) -> None:
    assert client.version()["Browser"].startswith("Chrome/")
    assert client.browser_id() == chrome.browser_id


def test_responding_is_false_when_nothing_is_there() -> None:
    assert not cdp.CdpClient(port=free_port(), timeout=1.0).responding()


def test_a_dead_port_is_a_browser_error() -> None:
    with pytest.raises(BrowserError) as caught:
        cdp.CdpClient(port=free_port(), timeout=1.0).version()
    assert caught.value.category is Category.BROWSER


def test_targets_drop_the_title(client: cdp.CdpClient) -> None:
    """A claude.ai tab's title is a conversation title (§10). There is no field
    for it, so no helper and no log line can grow one by accident."""
    targets = client.targets()
    assert [item.id for item in targets] == ["page-1", "worker-1"]
    assert not any(hasattr(item, "title") for item in targets)
    assert [item.id for item in client.pages()] == ["page-1"]


def test_targets_carry_host_and_kind(client: cdp.CdpClient) -> None:
    page = client.pages()[0]
    assert page.host == "claude.ai"
    assert page.is_page
    assert cdp.Target.from_json({}).host == ""


def test_close_target_removes_the_tab(client: cdp.CdpClient) -> None:
    client.close_target("page-1")
    assert [item.id for item in client.targets()] == ["worker-1"]


def test_closing_a_target_that_is_already_gone_is_fine(client: cdp.CdpClient) -> None:
    """Chrome answers `404 No such target id` — the outcome the call wanted.

    `08`'s close-extra-tabs lists targets and then closes them one at a time, so
    a tab that closed itself in between is a race, not a failure.
    """
    client.close_target("page-1")
    client.close_target("page-1")  # again, now that it is gone
    client.close_target("never-existed")


def test_a_close_that_fails_for_another_reason_still_raises(
    client: cdp.CdpClient,
) -> None:
    """Only the 404 is forgiven. A browser answering 500 is a real failure."""
    with pytest.raises(BrowserError, match="answered 500"):
        client.close_target(BROKEN_TARGET)


def test_an_http_status_carries_it(chrome: FakeChrome) -> None:
    client = cdp.CdpClient(port=chrome.port, timeout=5.0)
    with pytest.raises(cdp.HttpStatusError) as caught:
        cdp.http_get(f"{client.base_url}/json/nothing-here", 5.0)
    assert caught.value.status == 404
    assert caught.value.category is Category.BROWSER


def test_attaching_to_an_unknown_target_fails(client: cdp.CdpClient) -> None:
    with pytest.raises(BrowserError, match="no such target"):
        client.attach("page-404")


def test_attaching_to_a_target_without_a_socket_fails(chrome: FakeChrome) -> None:
    chrome.targets = [FakeTarget(id="page-1", url="https://claude.ai/new")]
    client = cdp.CdpClient(port=chrome.port, timeout=5.0)
    original = chrome._list

    def without_socket() -> list[dict[str, object]]:
        return [{**item, "webSocketDebuggerUrl": ""} for item in original()]

    chrome._list = without_socket  # type: ignore[method-assign]
    with pytest.raises(BrowserError, match="cannot be attached to"):
        client.attach("page-1")


def test_a_reply_that_is_not_json_is_a_browser_error(chrome: FakeChrome) -> None:
    client = cdp.CdpClient(port=chrome.port, timeout=5.0)
    with pytest.raises(BrowserError, match="did not answer with JSON"):
        cdp.http_json(f"{client.base_url}/json/close/page-1", 5.0)  # answers text


def test_json_endpoints_that_answer_the_wrong_shape(chrome: FakeChrome) -> None:
    client = cdp.CdpClient(port=chrome.port, timeout=5.0)
    chrome._version = lambda: ["not", "a", "browser"]  # type: ignore[assignment,method-assign]
    chrome._list = lambda: {"not": "a list"}  # type: ignore[assignment,method-assign]
    with pytest.raises(BrowserError, match="is not a browser"):
        client.version()
    with pytest.raises(BrowserError, match="is not a target list"):
        client.targets()


# --------------------------------------------------------------------------- #
# The WebSocket half
# --------------------------------------------------------------------------- #


def test_evaluate_returns_the_value(client: cdp.CdpClient, chrome: FakeChrome) -> None:
    with client.attach("page-1") as page:
        assert page.evaluate("1 + 1") == {"ok": 1}
    # `Page.enable` first, so a dialog that opens later is an event we receive.
    assert chrome.methods()[0] == "Page.enable"


def test_evaluate_surfaces_a_page_exception(chrome: FakeChrome) -> None:
    def responder(fake: FakeChrome, call: Call) -> dict[str, object] | None:
        if call.method != "Runtime.evaluate":
            return None
        return {"result": {"exceptionDetails": {"text": "ReferenceError"}}}

    chrome.responder = responder
    client = cdp.CdpClient(port=chrome.port, timeout=5.0)
    with client.attach("page-1") as page:
        with pytest.raises(BrowserError, match="ReferenceError"):
            page.evaluate("boom")


def test_a_cdp_error_is_a_browser_error(client: cdp.CdpClient) -> None:
    with client.attach("page-1") as page:
        with pytest.raises(BrowserError, match="wasn't found"):
            page.send("Nonsense.method")


def test_navigate_reports_an_error_text(chrome: FakeChrome) -> None:
    def responder(fake: FakeChrome, call: Call) -> dict[str, object] | None:
        if call.method != "Page.navigate":
            return None
        return {"result": {"errorText": "net::ERR_NAME_NOT_RESOLVED"}}

    chrome.responder = responder
    client = cdp.CdpClient(port=chrome.port, timeout=5.0)
    with client.attach("page-1") as page:
        with pytest.raises(BrowserError, match="ERR_NAME_NOT_RESOLVED"):
            page.navigate("https://claude.invalid/")


def test_navigate_moves_the_tab(client: cdp.CdpClient, chrome: FakeChrome) -> None:
    with client.attach("page-1") as page:
        page.navigate("https://claude.ai/chat/x")
    assert chrome.targets[0].url == "https://claude.ai/chat/x"


def test_insert_text_sends_the_whole_string(
    client: cdp.CdpClient, chrome: FakeChrome
) -> None:
    """`08` pastes 40 kB seeds through this and compares hashes; the string must
    arrive as one `Input.insertText` and not as keystrokes."""
    seed = "a" * 40_000
    with client.attach("page-1") as page:
        page.insert_text(seed)
    inserted = [call for call in chrome.calls if call.method == "Input.insertText"]
    assert len(inserted) == 1
    assert inserted[0].params["text"] == seed


def test_set_file_input_files(
    client: cdp.CdpClient, chrome: FakeChrome, tmp_path: Path
) -> None:
    upload = tmp_path / "notes.md"
    upload.write_text("hello", encoding="utf-8")
    with client.attach("page-1") as page:
        page.set_file_input_files('input[type="file"]', [upload])
    call = next(c for c in chrome.calls if c.method == "DOM.setFileInputFiles")
    assert call.params["files"] == [str(upload.resolve())]
    assert call.params["nodeId"] == 2


def test_set_file_input_files_without_a_match(client: cdp.CdpClient) -> None:
    with client.attach("page-1") as page:
        with pytest.raises(BrowserError, match="no element matches"):
            page.set_file_input_files("input.missing", [])


def test_url_is_read_from_the_page(chrome: FakeChrome) -> None:
    """`/json/list` is a snapshot; a redirect to /login between then and now is
    exactly what `probe` exists to notice."""
    chrome.targets = [
        FakeTarget(
            id="page-1", url="https://claude.ai/new", evaluate="https://claude.ai/login"
        )
    ]
    client = cdp.CdpClient(port=chrome.port, timeout=5.0)
    with client.attach("page-1") as page:
        assert page.url == "https://claude.ai/login"


def test_url_falls_back_to_the_target(chrome: FakeChrome) -> None:
    chrome.targets = [
        FakeTarget(id="page-1", url="https://claude.ai/new", evaluate=None)
    ]
    client = cdp.CdpClient(port=chrome.port, timeout=5.0)
    with client.attach("page-1") as page:
        assert page.url == "https://claude.ai/new"


def test_events_are_kept_not_dropped(chrome: FakeChrome) -> None:
    """A dialog opening arrives unsolicited, between a command and its reply."""
    chrome.events = [dialog_event("confirm")]
    client = cdp.CdpClient(port=chrome.port, timeout=5.0)
    with client.attach("page-1") as page:
        page.evaluate("1")
        assert page.events("Page.javascriptDialogOpening")
        assert page.events("Page.loadEventFired") == []


def test_drain_collects_events_that_arrive_unprompted(chrome: FakeChrome) -> None:
    client = cdp.CdpClient(port=chrome.port, timeout=5.0)
    with client.attach("page-1") as page:
        chrome.events = [dialog_event()]
        page.evaluate("1")  # flushes the queued event alongside the reply
        assert len(page.drain(0.05)) == 1


def test_drain_collects_an_event_that_arrives_between_commands(
    chrome: FakeChrome,
) -> None:
    """A dialog can open while nothing is being asked. `12` holds a connection
    open for a whole conversation and finds out this way."""
    client = cdp.CdpClient(port=chrome.port, timeout=5.0)
    with client.attach("page-1") as page:
        chrome.push(dialog_event("beforeunload"))
        events = page.drain(2.0)
    assert [item["params"]["type"] for item in events] == ["beforeunload"]


def test_a_frame_that_is_not_a_cdp_message(chrome: FakeChrome) -> None:
    with pytest.raises(BrowserError, match="not JSON"):
        cdp._decode("<html>")
    with pytest.raises(BrowserError, match="not a CDP message"):
        cdp._decode(b"[1, 2]")


def test_a_call_whose_budget_is_already_spent(chrome: FakeChrome) -> None:
    """The deadline is checked before waiting, not only after."""
    client = cdp.CdpClient(port=chrome.port, timeout=5.0)
    with client.attach("page-1") as page:
        page.timeout = 0.0
        with pytest.raises(BrowserError, match="timed out after 0s"):
            page.send("Page.enable")


def test_a_command_that_is_never_answered_times_out(chrome: FakeChrome) -> None:
    """Every call has a timeout, so a wedged browser cannot hang a run."""

    def responder(fake: FakeChrome, call: Call) -> dict[str, object] | None:
        if call.method == "Runtime.evaluate":
            return {"id": -1, "result": {}}  # a reply to nobody
        return None

    chrome.responder = responder
    client = cdp.CdpClient(port=chrome.port, timeout=0.4)
    with client.attach("page-1") as page:
        with pytest.raises(BrowserError, match="timed out after 0.4s"):
            page.evaluate("1")


def test_a_connection_that_goes_away_mid_command(chrome: FakeChrome) -> None:
    client = cdp.CdpClient(port=chrome.port, timeout=5.0)
    page = client.attach("page-1")
    chrome.stop()
    with pytest.raises(BrowserError):
        page.evaluate("1")


def test_connecting_to_a_dead_socket() -> None:
    with pytest.raises(BrowserError, match="cannot connect"):
        cdp.Connection(f"ws://127.0.0.1:{free_port()}/devtools/browser/x", timeout=1.0)


def test_browser_connection_needs_a_debugger_url(chrome: FakeChrome) -> None:
    client = cdp.CdpClient(port=chrome.port, timeout=5.0)
    chrome._version = lambda: {"Browser": "Chrome/141"}  # type: ignore[method-assign]
    with pytest.raises(BrowserError, match="no debugger URL"):
        with client.browser_connection():
            pass  # pragma: no cover - the context manager raises on entry
