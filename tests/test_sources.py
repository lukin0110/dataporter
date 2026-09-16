"""The source seam (`42`): one object per vendor, and Claude on it unchanged.

Most of what this slice promises is that nothing moved: the selector table, the
two walls and the block strings `31` and `24` spelled are spelled here again
and compared byte for byte with what the seam now derives from `CLAUDE`.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from dataporter import sources, store
from dataporter.browser import export_page, helpers, login_form, probe, sites
from dataporter.browser import session as browser_session
from dataporter.browser.cdp import CdpClient
from dataporter.browser.site import Site
from dataporter.config import Settings, with_session_account
from dataporter.sources.chatgpt import CHATGPT
from dataporter.sources.claude import CLAUDE
from fake_chrome import FakeChrome, FakeTarget

# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #


def test_the_registry_holds_the_two_sources_the_tool_has() -> None:
    assert list(sources.REGISTRY) == ["claude", "chatgpt"]
    assert sources.REGISTRY["claude"] is CLAUDE
    assert sources.REGISTRY["chatgpt"] is CHATGPT
    assert store.SOURCES == ("claude", "chatgpt")
    assert store.SOURCE_NAMES == {"claude": "Claude", "chatgpt": "ChatGPT"}


def test_a_source_s_hosts_are_its_own_and_the_ones_its_sign_in_passes_through() -> None:
    assert CLAUDE.hosts == ("claude.ai",)
    assert CLAUDE.auth_hosts == ()


def test_the_invocation_s_source_is_looked_up_by_name(tmp_path: Path) -> None:
    settings = Settings(workspace=tmp_path)
    assert sources.of(settings) is CLAUDE
    assert sources.of(with_session_account(settings, "claude", "old")) is CLAUDE


def test_an_archive_is_recognised_by_its_member_names() -> None:
    assert sources.recognised(["conversations.json", "users.json"]) is CLAUDE
    assert sources.recognised(["conversations.json"]) is CLAUDE
    assert sources.recognised(["conversations.json", "user.json"]) is CHATGPT
    assert sources.recognised(["conversations-001.json", "conversations-002.json"]) is CHATGPT
    assert sources.recognised(["chat.html"]) is None


# --------------------------------------------------------------------------- #
# Spelled once
# --------------------------------------------------------------------------- #


def test_the_host_and_the_export_page_are_spelled_once() -> None:
    assert probe.CLAUDE_HOST == CLAUDE.host == "claude.ai"
    assert CLAUDE.login_url == probe.NEW_CHAT_URL
    assert export_page.EXPORT_PAGE_PATH == CLAUDE.export_page_path == "/new#settings/data-privacy-controls"
    assert export_page.EXPORT_PAGE_URL == "https://claude.ai/new#settings/data-privacy-controls"
    assert sites.not_the_export_page(CLAUDE) == export_page.NOT_THE_EXPORT_PAGE
    assert export_page.NOT_THE_EXPORT_PAGE == "the browser did not arrive at /new#settings/data-privacy-controls"
    # The fragment is the only thing telling the export page apart from the app
    # page it opens over, so the check reads path and fragment together (§77).
    assert export_page.on_export_page("https://claude.ai/new#settings/data-privacy-controls")
    # The export is two screens, and the button that asks is on the second.
    assert export_page.on_export_page("https://claude.ai/new#settings/data-privacy-controls/export-data")
    assert not export_page.on_export_page("https://claude.ai/new")
    assert not export_page.on_export_page("https://claude.ai/login")
    assert not export_page.on_export_page("https://claude.ai/new#settings/account")


def test_the_extraction_site_s_selectors_are_the_ones_the_ask_had() -> None:
    """`31`'s table, in `31`'s order: `probe`'s, the page's own, the credential fields."""
    expected = {
        "COMPOSER_SELECTOR": 'div[contenteditable="true"]',
        "HUMAN_MESSAGE_SELECTOR": '[data-testid="user-message"]',
        "MESSAGE_SELECTOR": '[data-testid="user-message"], [data-testid="assistant-message"]',
        "TITLE_SELECTOR": '[data-testid="chat-menu-trigger"], [data-testid="conversation-title"], header h1, header h2',
        "FILE_INPUT_SELECTOR": 'input[type="file"]',
        "EXPORT_BUTTON_SELECTOR": (
            '[data-perf-screen="data-privacy-controls"] [data-settings-row] button[data-cds="Button"]'
        ),
        "CONFIRM_BUTTON_SELECTOR": '[data-testid="export-confirm-button"]',
        "REQUESTED_SELECTOR": '[data-cds="Toast"] [role="dialog"] h2',
        "REQUESTED_TEXT": "Export started",
        "EMAIL_SELECTOR": 'input[type="email"], input[autocomplete="username"]',
        "PASSWORD_SELECTOR": 'input[type="password"], input[autocomplete="current-password"]',
        "CODE_SELECTOR": 'input[data-testid="code"], input[autocomplete="one-time-code"]',
    }
    assert list(export_page.EXTRACTION_SITE.selectors.items()) == list(expected.items())
    assert export_page.EXTRACTION_SITE.source == "claude"
    assert export_page.EXTRACTION_SITE.host == "claude.ai"
    assert export_page.EXTRACTION_SITE.hosts == ("claude.ai",)


def test_the_walls_are_the_ones_24_and_31_wrote() -> None:
    """Two regular expressions, byte for byte, because a wall is easier to trust when it is one line long."""
    assert export_page.EXTRACTION_SURFACE.allowed.pattern == (
        r"^https://claude\.ai/(login(/.*)?|magic-link(/.*)?"
        r"|new(\?[^#]*)?\#settings/data\-privacy\-controls(/.*)?)(\?.*)?$"
    )
    assert login_form.LOGIN_SURFACE.allowed.pattern == (
        r"^https://claude\.ai/(login(/.*)?|magic-link(/.*)?|new|chat/[0-9a-f-]{36})(\?.*)?$"
    )
    # Where a sign-in link lands (`53`): a door in both walls, and nothing under `/new` with it.
    assert login_form.LOGIN_SURFACE.permits("https://claude.ai/magic-link")
    assert export_page.EXTRACTION_SURFACE.permits("https://claude.ai/magic-link")
    # The export page is a fragment of the app (§77), and the wall stays as
    # narrow as it was: the address is admitted, the app page under it is not.
    assert export_page.EXTRACTION_SURFACE.permits("https://claude.ai/new#settings/data-privacy-controls")
    assert not export_page.EXTRACTION_SURFACE.permits("https://claude.ai/new")
    # A query goes before the fragment, so the door is escaped either side of one.
    assert export_page.EXTRACTION_SURFACE.permits("https://claude.ai/new?from=nav#settings/data-privacy-controls")
    assert not export_page.EXTRACTION_SURFACE.permits("https://claude.ai/new?from=nav")
    assert not export_page.EXTRACTION_SURFACE.permits("https://claude.ai/new#settings/other")
    # The export is a subtree: the panel, and the screen the button that asks is on.
    assert export_page.EXTRACTION_SURFACE.permits("https://claude.ai/new#settings/data-privacy-controls/export-data")
    assert export_page.EXTRACTION_SURFACE.hosts == ("claude.ai",)
    assert login_form.LOGIN_SURFACE.hosts == ("claude.ai",)


def test_the_ask_block_s_words_are_the_source_s() -> None:
    assert CLAUDE.ask_lines == ("Claude will email a download link to the account's address.", "When it arrives:")
    assert CLAUDE.counts_line == "Conversations: {conversations}     Projects: {projects}     Memories: {memories}"
    assert CLAUDE.login_prompt == browser_session.LOGIN_PROMPT


def test_a_source_is_the_same_object_wherever_it_is_asked_for() -> None:
    assert sites.extraction_site(CLAUDE) is export_page.EXTRACTION_SITE
    assert sites.extraction_surface(CLAUDE) is export_page.EXTRACTION_SURFACE
    assert sites.login_surface(CLAUDE) is login_form.LOGIN_SURFACE
    assert export_page.export_page_js(CLAUDE) == export_page.EXPORT_PAGE_JS


def test_whose_session_a_command_means(tmp_path: Path) -> None:
    settings = Settings(workspace=tmp_path)
    assert browser_session.whose(settings) == browser_session.Whose(
        url=probe.NEW_CHAT_URL,
        prompt=browser_session.LOGIN_PROMPT,
        origins=("https://claude.ai",),
        vendor="Claude",
        by_link=True,
    )
    assert browser_session.whose(with_session_account(settings, "claude", "old")) == browser_session.Whose(
        url=CLAUDE.login_url, prompt=CLAUDE.login_prompt, origins=CLAUDE.origins, vendor="Claude", by_link=True
    )
    # The destination is a Claude account (§75): it signs in the way Claude does.
    assert browser_session.whose(settings).by_link is CLAUDE.sign_in_by_link


# --------------------------------------------------------------------------- #
# A site with several hosts
# --------------------------------------------------------------------------- #


def test_a_one_host_site_is_written_as_it_was() -> None:
    assert Site("x", "a.example", {}).hosts == ("a.example",)
    assert Site("x", "a.example", {}, hosts=("a.example", "b.example")).hosts == ("a.example", "b.example")
    surface = helpers.Surface(origin="https://a.example", allowed=re.compile(r".*"))
    assert surface.hosts == ("a.example",)
    assert surface.origins == ("https://a.example",)


def test_a_wall_admits_every_auth_host_whole() -> None:
    """What `44` will write as data: the site's paths, and a second host with any path."""
    source = sources.Source(
        name="x",
        display_name="X",
        origin="https://x.example",
        auth_origins=("https://auth.x.example",),
        login_path="/",
        sign_in_paths=("", "auth/callback"),
        app_paths=(),
        export_page_path="/settings/data",
        selectors={},
        fetch_needs_session=True,
        signed_out_at_root=True,
        unattended_signin="walk",
        ask_lines=(),
        counts_line="",
        login_prompt="",
        recognise=lambda names: False,
        read=CLAUDE.read,
    )
    assert sites.extraction_pattern(source).pattern == (
        r"^https://x\.example/(|auth/callback|settings/data)(\?.*)?$|^https://auth\.x\.example/.*$"
    )
    assert source.host == "x.example"
    assert source.auth_hosts == ("auth.x.example",)
    assert source.login_url == "https://x.example/"
    wall = sites.extraction_surface(source)
    assert wall.hosts == ("x.example", "auth.x.example")
    assert wall.permits("https://x.example/")
    assert wall.permits("https://x.example/settings/data?tab=1")
    assert wall.permits("https://auth.x.example/log-in/password")
    assert not wall.permits("https://x.example/c/abc")
    assert not wall.permits("https://x.example/settings")
    assert not wall.permits("https://other.example/")
    assert not sites.login_surface(source).permits("https://x.example/settings/data")


@pytest.mark.slow
def test_a_tab_on_any_of_the_surface_s_hosts_is_found() -> None:
    surface = helpers.Surface(
        origin="https://a.example", allowed=re.compile(r".*"), origins=("https://a.example", "https://b.example")
    )
    with FakeChrome(
        targets=[
            FakeTarget(id="page-1", url="https://c.example/"),
            FakeTarget(id="page-2", url="https://b.example/log-in"),
        ]
    ) as chrome:
        client = CdpClient(port=chrome.port, timeout=2.0)
        assert [item.id for item in helpers.surface_tabs(client, surface)] == ["page-2"]
        assert [item.id for item in browser_session.tabs_on(client, ("https://b.example",))] == ["page-2"]
        assert browser_session.tabs_on(client, ("https://a.example",)) == []
        # A bare host matches nothing now, and asserting on one would pass for the
        # wrong reason (raised by Copilot in review on #63).
        assert browser_session.tabs_on(client, ("b.example",)) == []


@pytest.mark.slow
def test_importing_the_sources_imports_nothing_of_the_browser() -> None:
    """`store` reads the registry, and the store must not pull a browser in to list two names."""
    code = (
        "import sys, dataporter.sources, dataporter.store\n"
        "loaded = sorted(m for m in sys.modules if m.startswith('dataporter.browser'))\n"
        "assert not loaded, loaded\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=60)
