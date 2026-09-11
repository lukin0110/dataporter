"""Reading the page: the URL rules, the DOM signals, and the dialogs.

Two halves. The URL rules and the shape of `PageState` are pure functions and are
tested as such. The DOM signals are tested twice: once against a fake browser
that answers whatever the test says, and once — the half that actually proves the
selectors — against a real Chrome rendering the checked-in page fixtures.
"""

import time
from collections.abc import Iterator

import pytest

from dataporter.browser import launcher
from dataporter.browser import session as browser_session
from dataporter.browser.cdp import CdpClient, Page
from dataporter.browser.probe import (
    COMPOSER_SELECTOR,
    PAGE_STATE_JS,
    LastMessage,
    PageKind,
    PageState,
    conversation_id_of,
    kind_of,
    page_view,
    path_of,
    probe,
)
from fake_chrome import (
    FakeChrome,
    FakeTarget,
    dialog_closed_event,
    dialog_event,
    page_state,
)
from fake_pages import CHAT_ID, GENERATING_CHAT_ID, PageServer
from live_browser import live_browser, requires_a_browser

CHAT_URL = f"https://claude.ai/chat/{CHAT_ID}"


# --------------------------------------------------------------------------- #
# The URL rules
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://claude.ai/login", PageKind.LOGIN),
        ("https://claude.ai/login/callback?next=/new", PageKind.LOGIN),
        ("https://claude.ai/new", PageKind.NEW_CHAT),
        ("https://claude.ai/", PageKind.NEW_CHAT),
        ("https://claude.ai/new?q=1", PageKind.NEW_CHAT),
        (CHAT_URL, PageKind.CHAT),
        (f"{CHAT_URL}?first=1#top", PageKind.CHAT),
        (f"https://claude.ai/chat/{CHAT_ID.upper()}", PageKind.CHAT),
        ("https://claude.ai/settings/profile", PageKind.OTHER),
        ("https://claude.ai/chat/not-a-uuid", PageKind.OTHER),
        ("https://claude.ai/project/abc", PageKind.OTHER),
        ("about:blank", PageKind.OTHER),
        ("http://127.0.0.1:8000/new", PageKind.NEW_CHAT),
    ],
)
def test_kind_of(url: str, expected: PageKind) -> None:
    assert kind_of(url) is expected


def test_path_of_handles_a_url_with_no_path() -> None:
    assert path_of("https://claude.ai") == "/"
    assert path_of("https://claude.ai/new#anchor") == "/new"


def test_conversation_id_comes_from_the_url_only() -> None:
    assert conversation_id_of(CHAT_URL) == CHAT_ID
    assert conversation_id_of("https://claude.ai/new") is None


# --------------------------------------------------------------------------- #
# The DOM signals, against a browser that answers to order
# --------------------------------------------------------------------------- #


@pytest.fixture
def fake() -> Iterator[FakeChrome]:
    with FakeChrome(
        targets=[FakeTarget(id="page-1", url="https://claude.ai/new")]
    ) as chrome:
        yield chrome


def probe_with(
    chrome: FakeChrome, state: dict[str, object], **kwargs: int
) -> PageState:
    chrome.targets[0].evaluate = state
    client = CdpClient(port=chrome.port, timeout=5.0)
    with client.attach("page-1") as page:
        return probe(page, **kwargs)


def test_a_login_page_is_not_logged_in(fake: FakeChrome) -> None:
    state = probe_with(
        fake,
        page_state(url="https://claude.ai/login", composer_present=False),
    )
    assert state.kind is PageKind.LOGIN
    assert not state.logged_in
    assert state.conversation_id is None


def test_a_composer_on_a_login_page_is_still_not_logged_in(fake: FakeChrome) -> None:
    """The two conditions are `and`ed: a login form's own text box must not read
    as a signed-in session."""
    state = probe_with(fake, page_state(url="https://claude.ai/login"))
    assert not state.logged_in


def test_a_composer_off_the_login_page_is_logged_in(fake: FakeChrome) -> None:
    state = probe_with(fake, page_state(composer_chars=12, send_enabled=True))
    assert state.logged_in
    assert state.composer_chars == 12
    assert state.send_enabled
    assert state.kind is PageKind.NEW_CHAT


def test_generation_and_the_conversation_id(fake: FakeChrome) -> None:
    state = probe_with(fake, page_state(url=CHAT_URL, generating=True), tab_count=3)
    assert state.generating
    assert state.conversation_id == CHAT_ID
    assert state.tab_count == 3


def test_a_dom_dialog_is_reported(fake: FakeChrome) -> None:
    state = probe_with(fake, page_state(dom_dialogs=2))
    assert state.dialogs == ("dom", "dom")


def test_a_javascript_dialog_is_reported_by_kind_never_by_message(
    fake: FakeChrome,
) -> None:
    """§10: the message is page text. The kind is not."""
    fake.targets[0].evaluate = page_state()
    fake.events = [dialog_event("confirm")]
    client = CdpClient(port=fake.port, timeout=5.0)
    with client.attach("page-1") as page:
        state = probe(page)
    assert state.dialogs == ("javascript:confirm",)
    assert "are you sure" not in state.model_dump_json()


def test_a_dialog_that_has_been_closed_is_not_pending(fake: FakeChrome) -> None:
    fake.targets[0].evaluate = page_state()
    fake.events = [dialog_event(), dialog_closed_event()]
    client = CdpClient(port=fake.port, timeout=5.0)
    with client.attach("page-1") as page:
        assert probe(page).dialogs == ()


def test_the_url_the_page_reports_wins_over_the_target_list(fake: FakeChrome) -> None:
    """The target list said `/new`; the page has since redirected to `/login`."""
    state = probe_with(fake, page_state(url="https://claude.ai/login"))
    assert state.url == "https://claude.ai/login"
    assert state.kind is PageKind.LOGIN


def test_a_page_that_answers_with_nothing_is_read_as_empty(fake: FakeChrome) -> None:
    state = probe_with(fake, {})
    assert state.url == "https://claude.ai/new"  # the target's, as a fallback
    assert not state.composer_present
    assert state.composer_chars == 0


# --------------------------------------------------------------------------- #
# The last message
# --------------------------------------------------------------------------- #


def test_page_view_is_one_evaluate_for_both_answers(fake: FakeChrome) -> None:
    fake.targets[0].evaluate = page_state(
        url=CHAT_URL,
        last_message={"role": "assistant", "chars": 12, "contains": ["ACK part 1"]},
    )
    client = CdpClient(port=fake.port, timeout=5.0)
    with client.attach("page-1") as page:
        view = page_view(page, expect=["ACK part 1"])
    assert view.state.conversation_id == CHAT_ID
    assert view.last_message == LastMessage(
        role="assistant", chars=12, contains=("ACK part 1",)
    )
    assert fake.methods().count("Runtime.evaluate") == 1


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "not an object",
        {},
        {"role": "system", "chars": None, "contains": "ACK"},
    ],
)
def test_a_page_that_answers_with_nonsense_reads_as_no_message(raw: object) -> None:
    """Same tolerance `probe` has: an error page, or a document that has not
    rendered, is "no message" and not an exception."""
    assert LastMessage.from_raw(raw) == LastMessage(role=None, chars=0, contains=())


def test_the_selectors_are_named_once() -> None:
    """Every expression is built from the same constants, which is what makes
    `08`'s paste and `07`'s count refer to the same element."""
    assert f'const COMPOSER_SELECTOR = "{COMPOSER_SELECTOR}"' in PAGE_STATE_JS.replace(
        '\\"', '"'
    )
    assert "/* hcm:page_state */" in PAGE_STATE_JS


def test_page_state_carries_no_content_fields() -> None:
    """The model is the contract `08` prints to stdout. Nothing that could hold a
    message, a title or a snapshot has a place in it."""
    assert set(PageState.model_fields) == {
        "url",
        "kind",
        "logged_in",
        "composer_present",
        "composer_chars",
        "generating",
        "send_enabled",
        "dialogs",
        "conversation_id",
        "tab_count",
    }


# --------------------------------------------------------------------------- #
# The same signals, against a real browser
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def live() -> Iterator[tuple[launcher.BrowserSession, PageServer]]:
    """One real browser and one fixture server for the whole module."""
    with live_browser() as pair:
        yield pair


def visit(session: launcher.BrowserSession, url: str) -> PageState:
    """Navigate the tab and probe it once the document has settled."""
    page: Page = browser_session.open_claude_tab(session, url)
    try:
        page.navigate(url)
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if page.evaluate("document.readyState") == "complete":
                state = probe(
                    page, tab_count=len(browser_session.claude_tabs(session.client))
                )
                if state.url == url:
                    return state
            time.sleep(0.1)
        raise AssertionError(f"{url} never finished loading")  # pragma: no cover
    finally:
        page.close()


@requires_a_browser
def test_live_login_page(live: tuple[launcher.BrowserSession, PageServer]) -> None:
    session, server = live
    state = visit(session, server.url("/login"))
    assert state.kind is PageKind.LOGIN
    assert not state.logged_in
    assert not state.composer_present
    assert state.composer_chars == 0
    assert not state.generating
    assert not state.send_enabled
    assert state.dialogs == ()
    assert state.conversation_id is None


@requires_a_browser
def test_live_new_chat_page(live: tuple[launcher.BrowserSession, PageServer]) -> None:
    session, server = live
    state = visit(session, server.url("/new"))
    assert state.kind is PageKind.NEW_CHAT
    assert state.logged_in
    assert state.composer_present
    assert state.composer_chars == 0
    # The Send button is there but disabled while the composer is empty.
    assert not state.send_enabled
    assert not state.generating
    assert state.conversation_id is None


@requires_a_browser
def test_live_chat_page(live: tuple[launcher.BrowserSession, PageServer]) -> None:
    session, server = live
    state = visit(session, server.url(f"/chat/{CHAT_ID}"))
    assert state.kind is PageKind.CHAT
    assert state.conversation_id == CHAT_ID
    assert state.logged_in
    assert state.composer_chars == len("ACK part 1")
    assert state.send_enabled
    assert not state.generating


@requires_a_browser
def test_live_generating_page(live: tuple[launcher.BrowserSession, PageServer]) -> None:
    session, server = live
    state = visit(session, server.url(f"/chat/{GENERATING_CHAT_ID}"))
    assert state.generating
    assert not state.send_enabled
    assert state.conversation_id == GENERATING_CHAT_ID


@requires_a_browser
def test_live_dialog_page(live: tuple[launcher.BrowserSession, PageServer]) -> None:
    session, server = live
    state = visit(session, server.url("/settings/profile"))
    assert state.dialogs == ("dom",)
    assert state.kind is PageKind.OTHER
