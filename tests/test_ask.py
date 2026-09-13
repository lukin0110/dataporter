"""The ask: one press in a source account, and the record it leaves (`31`).

Every branch is covered against `fake_export_page.FakeExportPage` and a fake
Chrome, so the coverage gate never rests on a browser being installed — the same
arrangement `08` and `24` use, pointed at the other page. The live tier's one
test of this page is in `test_browser_helpers.py`, where a real Chrome renders
the checked-in fixture.

What is asserted here, over and over, is the shape of the promise §36 makes: two
clicks, nothing typed, nothing written down when the page did not say the export
was requested, and no browser at all when an ask is already open.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from dataporter import cli, extract, signin, store
from dataporter.browser import export_page, helpers, launcher
from dataporter.browser.cdp import CdpClient
from dataporter.browser.launcher import BrowserSession
from dataporter.config import (
    AccountsSettings,
    BrowserSettings,
    Settings,
    StoreSettings,
    TimeoutSettings,
    with_account,
)
from dataporter.console import Collected
from dataporter.errors import AuthError, BrowserError, StoreError, UsageError
from dataporter.exit_codes import ExitCode
from fake_chrome import FakeChrome, FakeTarget
from fake_export_page import SIGNED_OUT_URL, FakeExportPage, Stage, browser, visit

pytestmark = pytest.mark.slow
"""Slow all the way through: a fake Chrome per test, binding two ports."""

ACCOUNT = "old-personal"


@pytest.fixture
def page() -> FakeExportPage:
    """Return the export page as an ask meets it: a button, and a dialog behind it."""
    return FakeExportPage()


@pytest.fixture
def chrome(page: FakeExportPage) -> Iterator[FakeChrome]:
    with browser(page) as fake:
        yield fake


@pytest.fixture
def launches(monkeypatch: pytest.MonkeyPatch, chrome: FakeChrome) -> list[str]:
    """Every URL `launch` was asked for, and a session on the fake instead.

    `07`'s adoption without a Chrome, as `world.py` does it: the browser belongs
    to the fixture, so the session is `adopted` and nothing tries to close it.
    """
    urls: list[str] = []

    def fake_launch(settings: Settings, url: str) -> BrowserSession:
        urls.append(url)
        return BrowserSession(
            client=CdpClient(port=chrome.port, timeout=2.0),
            profile=settings.browser_profile_dir,
            adopted=True,
        )

    monkeypatch.setattr(launcher, "launch", fake_launch)
    return urls


@pytest.fixture
def settings(chrome: FakeChrome, tmp_path: Path) -> Settings:
    """One invocation, about one source account, pointed at the fake browser."""
    return with_account(
        Settings(
            workspace=tmp_path / "migration",
            accounts=AccountsSettings(dir=tmp_path / "accounts"),
            store=StoreSettings(dir=tmp_path / "store"),
            browser=BrowserSettings(cdp_port=chrome.port),
            timeouts=TimeoutSettings(cdp_call_s=2.0, ask_s=0.3, login_s=0.1),
        ),
        "claude",
        ACCOUNT,
    )


def expected_block(asked_at: str) -> str:
    """§31's block, written out rather than built from the constants.

    A golden string: the brief prints these words, and a test that assembled
    them from the same constants the code assembles them from would pass however
    they were reworded.
    """
    return (
        f"Claude extraction — {ACCOUNT}\n"
        "\n"
        f"Export requested {asked_at}.\n"
        "Claude will email a download link to the account's address.\n"
        "When it arrives:\n"
        "\n"
        f"  dataporter extract --source claude --account {ACCOUNT} --link <url>\n"
    )


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #


def test_the_ask_presses_the_button_confirms_and_writes_the_record(
    settings: Settings, page: FakeExportPage, launches: list[str]
) -> None:
    sink = Collected()
    outcome = extract.ask(settings, sink=sink)

    assert outcome.exit_code == ExitCode.OK
    assert launches == [export_page.EXPORT_PAGE_URL]
    written = extract.read_ask(settings)
    assert written is not None
    assert written.source == "claude"
    assert written.account == ACCOUNT
    # To the second, because the stamp the snapshot is filed under is.
    assert written.asked_at.microsecond == 0
    assert sink.stdout == expected_block(written.asked_at.strftime(extract.ASKED_AT_FORMAT))
    assert not sink.stderr


def test_the_ask_is_two_clicks_and_nothing_is_typed(
    settings: Settings, page: FakeExportPage, launches: list[str]
) -> None:
    """§36: the only synthesized inputs are the two clicks."""
    extract.ask(settings)

    assert page.clicks == [
        export_page.EXPORT_BUTTON_SELECTOR,
        export_page.CONFIRM_BUTTON_SELECTOR,
    ]
    assert page.inserts == []
    assert page.stage is Stage.REQUESTED


def test_a_page_that_needs_no_confirmation_is_one_click(
    settings: Settings, page: FakeExportPage, launches: list[str]
) -> None:
    """Whether a dialog follows the button is `*unknown*` in the UI map.

    The ask works either way, and presses nothing it was not shown.
    """
    page.confirms = False
    outcome = extract.ask(settings)

    assert outcome.exit_code == ExitCode.OK
    assert page.clicks == [export_page.EXPORT_BUTTON_SELECTOR]


def test_both_clicks_are_recorded_with_the_page_and_the_selector(
    settings: Settings, page: FakeExportPage, launches: list[str], tmp_path: Path
) -> None:
    """In the account home's log, never the workspace's.

    This is an action in an account, and §38 keeps what is written *about* one to labels
    and our own strings.
    """
    extract.ask(settings)

    records = [
        json.loads(line) for line in helpers.actions_path(settings.logs_dir).read_text(encoding="utf-8").splitlines()
    ]
    assert [item["helper"] for item in records] == [
        export_page.BUTTON_ACTION,
        export_page.CONFIRM_ACTION,
    ]
    assert all(item["url"] == export_page.EXPORT_PAGE_URL for item in records)
    assert records[0]["selector"] == export_page.EXPORT_BUTTON_SELECTOR
    assert all(item["ok"] for item in records)
    assert not (settings.workspace / "logs").exists()


def test_the_ask_goes_through_the_cli_and_prints_the_block(
    settings: Settings,
    page: FakeExportPage,
    launches: list[str],
    runner: CliRunner,
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli_env(settings, monkeypatch)
    result = runner.invoke(cli.app, ["extract", "--account", ACCOUNT], catch_exceptions=False)

    assert result.exit_code == ExitCode.OK
    written = extract.read_ask(settings)
    assert written is not None
    assert result.stdout == expected_block(written.asked_at.strftime(extract.ASKED_AT_FORMAT))


# --------------------------------------------------------------------------- #
# An ask that is already open
# --------------------------------------------------------------------------- #


def test_a_second_ask_is_refused_before_a_browser_starts(
    settings: Settings, page: FakeExportPage, launches: list[str]
) -> None:
    extract.ask(settings)
    launches.clear()
    page.clicks.clear()

    with pytest.raises(StoreError) as raised:
        extract.ask(settings)

    assert "an ask is already open for claude/old-personal, made " in str(raised.value)
    assert "--abandon" in str(raised.value)
    assert launches == []
    assert page.clicks == []


def test_abandoning_the_ask_lets_the_next_one_through(
    settings: Settings, page: FakeExportPage, launches: list[str], chrome: FakeChrome
) -> None:
    """A second browser, because an ask closes the one it opened.

    Chrome writes its cookie jar out on exit, and `login` has always closed for that
    reason.
    """
    extract.ask(settings)
    extract.abandon(settings)
    page.stage = Stage.SETTINGS

    with browser(page, port=chrome.port):
        assert extract.ask(settings).exit_code == ExitCode.OK
    assert len(launches) == 2


# --------------------------------------------------------------------------- #
# Signing in to the source account
# --------------------------------------------------------------------------- #


def test_an_interactive_ask_waits_for_the_person_and_comes_back_to_the_page(
    settings: Settings, page: FakeExportPage, launches: list[str], chrome: FakeChrome
) -> None:
    """Signed out, claude.ai answers the export page with `/login`.

    The person signs in, lands where the application puts them, and the ask navigates
    back to the page it came for — `/new` is never driven, only left.
    """
    visit(chrome, page, SIGNED_OUT_URL)
    page.signs_in_after = 2
    sink = Collected()

    outcome = extract.ask(settings, sink=sink)

    assert outcome.exit_code == ExitCode.OK
    assert sink.out[0] == "Log in to Claude in the browser window that just opened.\n"
    assert page.url == export_page.EXPORT_PAGE_URL
    assert page.clicks == [
        export_page.EXPORT_BUTTON_SELECTOR,
        export_page.CONFIRM_BUTTON_SELECTOR,
    ]


def test_a_sign_in_nobody_completes_is_exit_3_and_no_record(
    settings: Settings, page: FakeExportPage, launches: list[str], chrome: FakeChrome
) -> None:
    visit(chrome, page, SIGNED_OUT_URL)

    with pytest.raises(AuthError) as raised:
        extract.ask(settings)

    assert "timed out after 0.1s waiting for login" in (raised.value.detail or "")
    assert extract.read_ask(settings) is None
    assert page.clicks == []


def test_the_mode_without_credentials_starts_no_browser(
    settings: Settings, page: FakeExportPage, launches: list[str]
) -> None:
    """`login`'s rule, and `login`'s reason.

    A run that would stop at the first sign-in form is a run that should not have opened
    a window.
    """
    unattended = settings.model_copy(update={"non_interactive": True})

    with pytest.raises(UsageError) as raised:
        extract.ask(unattended)

    assert str(raised.value) == signin.MISSING_CREDENTIALS
    assert launches == []


def test_the_mode_on_a_signed_in_profile_attempts_no_sign_in(
    settings: Settings,
    page: FakeExportPage,
    launches: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unattended ask on a signed-out profile needs Hermes.

    On a signed-in one it needs nothing, and a cron job without a model still backs up.
    """

    def never(*args: object, **kwargs: object) -> bool:
        raise AssertionError("no sign-in should be attempted")

    monkeypatch.setattr(signin, "ensure_signed_in", never)
    outcome = extract.ask(with_credentials(settings))

    assert outcome.exit_code == ExitCode.OK


def test_the_mode_on_a_signed_out_profile_signs_in_first(
    settings: Settings,
    page: FakeExportPage,
    launches: list[str],
    chrome: FakeChrome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    visit(chrome, page, SIGNED_OUT_URL)
    signed_in: list[str] = []

    def sign_in(settings: Settings, session: BrowserSession, **kwargs: object) -> bool:
        signed_in.append(settings.account or "")
        visit(chrome, page, export_page.EXPORT_PAGE_URL)
        return True

    monkeypatch.setattr(signin, "ensure_signed_in", sign_in)
    outcome = extract.ask(with_credentials(settings))

    assert outcome.exit_code == ExitCode.OK
    assert signed_in == [ACCOUNT]


# --------------------------------------------------------------------------- #
# Pages that do not say the export was requested
# --------------------------------------------------------------------------- #


def test_no_export_button_is_exit_1_and_no_record(
    settings: Settings, page: FakeExportPage, launches: list[str]
) -> None:
    """`31`'s first risk.

    Every row of this page is a guess until somebody looks, and the honest answer to a
    page we do not recognise is to say so.
    """
    page.button = False
    sink = Collected()

    outcome = extract.ask(settings, sink=sink)

    assert outcome.exit_code == ExitCode.FAILED
    assert sink.stderr == (f"export button not found on {export_page.EXPORT_PAGE_PATH}\n")
    assert not sink.stdout
    assert extract.read_ask(settings) is None


def test_a_javascript_dialog_stops_the_ask_and_is_never_answered(
    settings: Settings, page: FakeExportPage, launches: list[str]
) -> None:
    """§36: anything else on that page stops.

    What the dialog asks is unknown, and answering it would be the second action in an
    account that allows one.
    """
    page.dialog_on_click = True
    sink = Collected()

    outcome = extract.ask(settings, sink=sink)

    assert outcome.exit_code == ExitCode.FAILED
    assert "javascript dialog" in sink.stderr
    assert extract.read_ask(settings) is None
    assert page.clicks == [export_page.EXPORT_BUTTON_SELECTOR]


def test_a_dialog_that_was_already_open_stops_the_ask_before_any_click(
    settings: Settings, page: FakeExportPage, launches: list[str]
) -> None:
    """A modal that was in the way before the ask ever attached.

    Nothing is pressed on a page a dialog is sitting on top of.
    """
    page.dialog_already_open = True
    sink = Collected()

    outcome = extract.ask(settings, sink=sink)

    assert outcome.exit_code == ExitCode.FAILED
    assert "javascript dialog" in sink.stderr
    assert page.clicks == []


def test_a_browser_that_never_arrives_at_the_page_is_exit_6(
    settings: Settings, page: FakeExportPage, launches: list[str], chrome: FakeChrome
) -> None:
    """The navigation into the extraction surface is waited for, not assumed.

    Reading a page the target list merely believes in is how a wall gets walked through.
    """
    visit(chrome, page, SIGNED_OUT_URL)
    page.signs_in_after = 1
    page.follows_navigation = False

    with pytest.raises(BrowserError) as raised:
        extract.ask(settings)

    assert raised.value.detail == export_page.NOT_THE_EXPORT_PAGE
    assert extract.read_ask(settings) is None


def test_a_session_that_expires_before_the_click_is_never_clicked_on(
    settings: Settings, page: FakeExportPage, launches: list[str]
) -> None:
    """The wall admits `/login`.

    The wall alone does not say the tab is on the page the button is on. A session that
    expired between the look and the click would otherwise have the ask pressing a sign-
    in form's submit button, which `CONFIRM_BUTTON_SELECTOR` is generic enough to find.
    (Raised by Copilot in review on #44.)
    """
    page.leaves_after_view = 1

    with pytest.raises(BrowserError) as raised:
        extract.ask(settings)

    assert raised.value.detail == export_page.NOT_THE_EXPORT_PAGE
    assert page.clicks == []
    assert extract.read_ask(settings) is None


def test_two_claude_tabs_are_not_driven_blind(
    settings: Settings, page: FakeExportPage, launches: list[str], chrome: FakeChrome
) -> None:
    """`08`'s `ambiguous_tab`, on the other surface.

    Which of two tabs the ask would press a button in is not a question this tool
    guesses at.
    """
    chrome.targets.append(FakeTarget(id="page-2", url=export_page.EXPORT_PAGE_URL, evaluate={}))

    with pytest.raises(BrowserError) as raised:
        extract.ask(settings)

    assert raised.value.detail == helpers.AMBIGUOUS_TAB
    assert page.clicks == []


def test_a_browser_with_no_tab_at_all_is_a_browser_error(settings: Settings, page: FakeExportPage) -> None:
    """Straight at `request_export`, because a launched browser always has a tab.

    This is the state a closed one leaves behind.
    """
    with FakeChrome(targets=[]) as empty:
        session = BrowserSession(
            client=CdpClient(port=empty.port, timeout=2.0),
            profile=settings.browser_profile_dir,
            adopted=True,
        )
        with pytest.raises(BrowserError) as raised:
            export_page.request_export(settings, session)

    assert raised.value.detail == helpers.NO_CLAUDE_TAB


def test_a_confirmation_that_never_arrives_is_exit_1(
    settings: Settings, page: FakeExportPage, launches: list[str]
) -> None:
    """A rate limit on asking would look exactly like this, which is why no record is written.

    The export may have been requested, and a stamp that claims it was is worse than a
    person reading the page.
    """
    page.never_requested = True
    sink = Collected()

    outcome = extract.ask(settings, sink=sink)

    assert outcome.exit_code == ExitCode.FAILED
    assert sink.stderr == f"{extract.NOT_CONFIRMED}\n"
    assert extract.read_ask(settings) is None


def test_a_failed_ask_exits_1_through_the_cli(
    settings: Settings,
    page: FakeExportPage,
    launches: list[str],
    runner: CliRunner,
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page.button = False
    cli_env(settings, monkeypatch)
    result = runner.invoke(cli.app, ["extract", "--account", ACCOUNT], catch_exceptions=False)

    assert result.exit_code == ExitCode.FAILED
    assert result.stderr.startswith("export button not found on ")


# --------------------------------------------------------------------------- #
# What is never written down
# --------------------------------------------------------------------------- #


def test_nothing_written_about_the_ask_names_the_account_itself(
    settings: Settings, page: FakeExportPage, launches: list[str]
) -> None:
    """§38: logs name the account by its label, never by its email."""
    extract.ask(settings)
    written = [path.read_text(encoding="utf-8") for path in sorted(settings.logs_dir.rglob("*")) if path.is_file()]

    assert written
    assert all("@" not in text for text in written)


def with_credentials(settings: Settings) -> Settings:
    """Return the same invocation, unattended, with one run's credentials in memory."""
    return settings.model_copy(
        update={
            "non_interactive": True,
            "auth": settings.auth.model_copy(
                update={
                    "email": "someone@example.com",
                    "password": SecretStr("not-a-real-password"),
                }
            ),
        }
    )


def cli_env(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the fixture's settings into the environment the CLI loads them from."""
    monkeypatch.setenv("DATAPORTER_WORKSPACE", str(settings.workspace))
    monkeypatch.setenv("DATAPORTER_ACCOUNTS__DIR", str(settings.accounts_dir))
    monkeypatch.setenv("DATAPORTER_STORE__DIR", str(settings.store_dir))
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", str(settings.browser.cdp_port))
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__CDP_CALL_S", "2")
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__ASK_S", "0.3")
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__LOGIN_S", "0.1")


def test_the_store_is_untouched_by_an_ask(settings: Settings, page: FakeExportPage, launches: list[str]) -> None:
    """The ask writes one file, and it is not in the store (§33).

    A snapshot is what the fetch files, and an open ask is abandonable operational
    state.
    """
    extract.ask(settings)

    assert extract.ask_path(settings).exists()
    assert store.Store(settings.store_dir).rows() == []
