"""The ChatGPT source session and the ask (`44`).

Every branch against `fake_chatgpt_pages.FakeChatgptPages` and a fake Chrome: the
walk-in sign-in, the interactive wait, the ask's two clicks, and the trace and the
action log a ChatGPT run leaves — which brief `06` §67 says must be what a Claude
run leaves.
"""

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from dataporter import cli, extract, signin
from dataporter.browser import chatgpt_login, helpers, launcher, login_form
from dataporter.browser.cdp import CdpClient
from dataporter.browser.launcher import BrowserSession
from dataporter.config import (
    AccountsSettings,
    AuthSettings,
    BrowserSettings,
    HermesSettings,
    Settings,
    StoreSettings,
    TimeoutSettings,
    with_account,
)
from dataporter.console import Collected
from dataporter.errors import AuthError, UsageError
from dataporter.exit_codes import ExitCode
from fake_chatgpt_pages import CONFIRM_BUTTON, EXPORT_BUTTON, EXPORT_URL, LOGIN_BUTTON, FakeChatgptPages, Step, browser
from fake_chrome import FakeChrome

pytestmark = pytest.mark.slow
"""A fake Chrome per test, binding two ports."""

ACCOUNT = "work"
EMAIL = "someone@example.test"
SECRET = "hunter2"


@pytest.fixture
def site() -> FakeChatgptPages:
    return FakeChatgptPages()


@pytest.fixture
def chrome(site: FakeChatgptPages) -> Iterator[FakeChrome]:
    with browser(site) as fake:
        yield fake


@pytest.fixture
def launches(monkeypatch: pytest.MonkeyPatch, chrome: FakeChrome) -> list[str]:
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


def make_settings(
    chrome: FakeChrome, tmp_path: Path, *, non_interactive: bool = True, credentials: bool = True
) -> Settings:
    return with_account(
        Settings(
            workspace=tmp_path / "migration",
            non_interactive=non_interactive,
            auth=AuthSettings(email=EMAIL, password=SecretStr(SECRET)) if credentials else AuthSettings(),
            accounts=AccountsSettings(dir=tmp_path / "accounts"),
            store=StoreSettings(dir=tmp_path / "store"),
            browser=BrowserSettings(cdp_port=chrome.port),
            hermes=HermesSettings(executable=tmp_path / "no-hermes-here", home=tmp_path / "hermes-home"),
            timeouts=TimeoutSettings(cdp_call_s=2.0, ask_s=0.3, login_s=0.5, signin_s=1.0),
        ),
        "chatgpt",
        ACCOUNT,
    )


@pytest.fixture
def settings(chrome: FakeChrome, tmp_path: Path) -> Settings:
    return make_settings(chrome, tmp_path)


def session_of(chrome: FakeChrome, settings: Settings) -> BrowserSession:
    return BrowserSession(
        client=CdpClient(port=chrome.port, timeout=2.0), profile=settings.browser_profile_dir, adopted=True
    )


def expected_block(asked_at: str) -> str:
    """§60's block, written out rather than built from the constants."""
    return (
        f"ChatGPT extraction — {ACCOUNT}\n"
        "\n"
        f"Export requested {asked_at}.\n"
        "ChatGPT will email or text a download link to the account's address.\n"
        "It can take up to 7 days. When it arrives:\n"
        "\n"
        f"  dataporter extract --source chatgpt --account {ACCOUNT} --link <url>\n"
    )


def trace_lines(settings: Settings) -> list[dict[str, Any]]:
    files = sorted((Path(settings.logs_dir) / "logs").glob("trace-*.jsonl"))
    assert len(files) == 1, files
    return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


def actions(settings: Settings) -> list[str]:
    path = helpers.actions_path(settings.logs_dir)
    return [json.loads(line)["helper"] for line in path.read_text(encoding="utf-8").splitlines()]


# --------------------------------------------------------------------------- #
# The walk
# --------------------------------------------------------------------------- #


def test_the_walk_is_one_click_and_two_fields_and_no_agent(
    site: FakeChatgptPages, chrome: FakeChrome, settings: Settings
) -> None:
    outcome = signin.SignIn(settings).perform(session_of(chrome, settings))

    assert outcome == signin.SignInOutcome(signed_in=True, filled=("email", "password"))
    assert site.clicks == [LOGIN_BUTTON]
    assert site.typed == {"email": EMAIL, "password": SECRET}
    assert site.step is Step.HOME
    assert not (settings.hermes.home).exists()


def test_no_expression_ever_carries_a_credential(
    site: FakeChatgptPages, chrome: FakeChrome, settings: Settings
) -> None:
    signin.SignIn(settings).perform(session_of(chrome, settings))

    assert not any(SECRET in item or EMAIL in item for item in site.expressions)
    inserted = [str(item.params.get("text")) for item in chrome.calls if item.method == "Input.insertText"]
    assert inserted == [EMAIL, SECRET]


def test_a_signed_in_landing_is_already_done(site: FakeChatgptPages, chrome: FakeChrome, settings: Settings) -> None:
    site.go(Step.HOME)
    outcome = signin.SignIn(settings).perform(session_of(chrome, settings))

    assert outcome.signed_in
    assert site.clicks == []
    assert site.typed == {}


@pytest.mark.parametrize(
    ("arrange", "blocked"),
    [
        (lambda site: setattr(site, "login_button", False), chatgpt_login.NO_LOGIN_BUTTON),
        (lambda site: setattr(site, "after_email", Step.CODE), login_form.CODE_OR_CHALLENGE),
        (lambda site: setattr(site, "password_ok", False), login_form.NO_PROGRESS),
    ],
)
def test_a_page_that_is_not_the_shape_expected_needs_a_person(
    site: FakeChatgptPages,
    chrome: FakeChrome,
    settings: Settings,
    arrange: Callable[[FakeChatgptPages], object],
    blocked: str,
) -> None:
    """§61: a landing page with no **Log in**, a code prompt, a refused password — each stops the walk."""
    arrange(site)
    outcome = signin.SignIn(settings).perform(session_of(chrome, settings))

    assert not outcome.signed_in
    assert outcome.detail == blocked
    assert outcome.reason == "authentication required"
    assert SECRET not in "".join(site.expressions)


def test_ensure_signed_in_walks_then_says_the_login_line_when_it_cannot(
    site: FakeChatgptPages, chrome: FakeChrome, settings: Settings
) -> None:
    site.login_button = False
    with pytest.raises(AuthError) as raised:
        signin.ensure_signed_in(settings, session_of(chrome, settings))

    assert raised.value.detail == "automatic sign-in stopped: authentication required — run: dataporter login"


# --------------------------------------------------------------------------- #
# The ask
# --------------------------------------------------------------------------- #


def test_the_chatgpt_ask_walks_in_presses_twice_and_prints_the_block(
    site: FakeChatgptPages, settings: Settings, launches: list[str]
) -> None:
    sink = Collected()
    outcome = extract.ask(settings, sink=sink)

    assert outcome.exit_code == ExitCode.OK
    assert launches == [EXPORT_URL]
    written = extract.read_ask(settings)
    assert written is not None
    assert written.source == "chatgpt"
    assert sink.stdout == expected_block(written.asked_at.strftime(extract.ASKED_AT_FORMAT))
    assert site.clicks == [LOGIN_BUTTON, EXPORT_BUTTON, CONFIRM_BUTTON]
    assert site.typed == {"email": EMAIL, "password": SECRET}


def test_a_signed_in_profile_asks_without_typing(
    site: FakeChatgptPages, settings: Settings, launches: list[str]
) -> None:
    site.go(Step.HOME)
    outcome = extract.ask(settings, sink=Collected())

    assert outcome.exit_code == ExitCode.OK
    assert site.clicks == [EXPORT_BUTTON, CONFIRM_BUTTON]
    assert site.typed == {}


def test_interactively_the_ask_waits_for_the_person(
    site: FakeChatgptPages, chrome: FakeChrome, tmp_path: Path, launches: list[str]
) -> None:
    site.signs_in_after = 3
    settings = make_settings(chrome, tmp_path, non_interactive=False, credentials=False)
    sink = Collected()
    outcome = extract.ask(settings, sink=sink)

    assert outcome.exit_code == ExitCode.OK
    assert sink.stdout.splitlines()[0] == "Log in to ChatGPT in the browser window that just opened."
    assert site.typed == {}
    assert site.clicks == [EXPORT_BUTTON, CONFIRM_BUTTON]


def test_unattended_without_credentials_is_refused_at_the_sign_in(
    chrome: FakeChrome, tmp_path: Path, launches: list[str]
) -> None:
    """`61`: signed out, the refusal is the same one, reached through the probe.

    The site starts signed out, so the sign-in is really attempted and
    `require_credentials` answers from inside it.
    """
    settings = make_settings(chrome, tmp_path, credentials=False)
    with pytest.raises(UsageError, match="DATAPORTER_AUTH__EMAIL"):
        extract.ask(settings, sink=Collected())
    assert launches == [EXPORT_URL]


def test_a_page_that_never_says_requested_exits_1_and_writes_nothing(
    site: FakeChatgptPages, settings: Settings, launches: list[str]
) -> None:
    site.never_requested = True
    sink = Collected()
    outcome = extract.ask(settings, sink=sink)

    assert outcome.exit_code == ExitCode.FAILED
    assert sink.stderr == "no confirmation that the export was requested\n"
    assert extract.read_ask(settings) is None


# --------------------------------------------------------------------------- #
# What the run leaves (§67)
# --------------------------------------------------------------------------- #


def test_the_trace_and_the_action_log_are_what_a_claude_run_leaves(
    site: FakeChatgptPages, settings: Settings, launches: list[str]
) -> None:
    extract.ask(settings, sink=Collected())
    lines = trace_lines(settings)

    header = lines[0]
    assert header["command"] == "extract"
    assert header["source"] == "chatgpt"
    assert header["host"] == "chatgpt.com"
    moves = [line for line in lines if line["kind"] == "move"]
    assert [move["helper"] for move in moves] == [
        "login-button",
        "email-step",
        "password-step",
        "export-button",
        "export-confirm",
    ]
    assert moves[0]["result"] == {"selector": LOGIN_BUTTON, "path": "/", "query": []}
    assert moves[1]["result"] == {"selector": login_form.EMAIL_SELECTOR, "path": "/log-in", "query": ["state"]}
    assert moves[3]["result"] == {"selector": EXPORT_BUTTON, "path": "/settings/data-controls", "query": []}
    assert actions(settings) == ["login-button", "email-step", "password-step", "export-button", "export-confirm"]
    logged = [
        json.loads(line) for line in helpers.actions_path(settings.logs_dir).read_text(encoding="utf-8").splitlines()
    ]
    assert logged[1]["url"] == "https://auth.openai.com/log-in"
    left = "\n".join(path.read_text(encoding="utf-8") for path in (Path(settings.logs_dir) / "logs").glob("*.jsonl"))
    assert "s3cret-state" not in left
    text = "\n".join(json.dumps(line) for line in lines)
    assert SECRET not in text
    assert EMAIL not in text
    sketches = {line["hash"] for line in lines if line["kind"] == "sketch"}
    assert {move["before"] for move in moves} <= sketches
    assert lines[-1]["what"] == "end"
    assert lines[-1]["exit"] == 0
    assert not (settings.workspace / "logs").exists()


# --------------------------------------------------------------------------- #
# `login`, through the command
# --------------------------------------------------------------------------- #


def test_login_with_source_chatgpt_opens_the_root_and_keeps_its_own_profile(
    site: FakeChatgptPages, chrome: FakeChrome, tmp_path: Path, launches: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    site.signs_in_after = 2
    monkeypatch.setenv("DATAPORTER_ACCOUNTS__DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", str(chrome.port))
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__CDP_CALL_S", "2")
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__LOGIN_S", "1")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli.app, ["login", "--source", "chatgpt", "--account", ACCOUNT], catch_exceptions=False)

    assert result.exit_code == ExitCode.OK, result.output
    assert launches == ["https://chatgpt.com/"]
    profile = tmp_path / "accounts" / "chatgpt" / ACCOUNT / "browser-profile"
    assert result.stdout == (
        f"Log in to ChatGPT in the browser window that just opened.\nLogged in. Session stored in {profile}/.\n"
    )
    assert not (tmp_path / "migration").exists()
