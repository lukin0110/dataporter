"""`24`'s two halves, in order: the agent reaches the form, this process fills it.

The credential's whole journey is asserted here: it is in `Settings`, it goes
into the page through `Input.insertText`, and it is in no prompt, no Hermes
environment, no expression and no log record on the way.
"""

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import SecretStr

from dataporter import signin
from dataporter.browser import launcher, login_form
from dataporter.browser import session as browser_session
from dataporter.browser.cdp import CdpClient
from dataporter.config import (
    AuthSettings,
    BrowserSettings,
    HermesSettings,
    Settings,
    TimeoutSettings,
)
from dataporter.errors import AuthError, UsageError
from fake_agent import ScriptedSignIn
from fake_composer import Browser
from fake_hermes import FakeHermes
from fake_login import LoginForm

pytestmark = pytest.mark.slow

EMAIL = "someone@example.test"
SECRET = "hunter2"


def settings_for(
    tmp_path: Path,
    fake: FakeHermes | None,
    browser: Browser,
    *,
    non_interactive: bool = True,
    credentials: bool = True,
) -> Settings:
    return Settings(
        workspace=tmp_path / "migration",
        non_interactive=non_interactive,
        auth=AuthSettings(email=EMAIL, password=SecretStr(SECRET)) if credentials else AuthSettings(),
        browser=BrowserSettings(cdp_port=browser.chrome.port),
        hermes=HermesSettings(
            executable=fake.executable if fake is not None else tmp_path / "none",
            home=tmp_path / "hermes-home",
        ),
        timeouts=TimeoutSettings(cdp_call_s=2.0, hermes_cli_s=30.0, hermes_check_s=30.0, signin_s=0.5),
    )


def session_of(browser: Browser, settings: Settings) -> launcher.BrowserSession:
    return launcher.BrowserSession(
        client=CdpClient(port=browser.chrome.port, timeout=2.0),
        profile=settings.browser_profile_dir,
        adopted=True,
    )


def hermes(tmp_path: Path, **result: object) -> FakeHermes:
    return FakeHermes(root=tmp_path / "bin").write(answer=json.dumps(result))


def form_ready(tmp_path: Path, *fields: str) -> FakeHermes:
    return hermes(tmp_path, outcome="form_ready", fields=list(fields), url=login_form.LOGIN_URL)


# -- the prompt ---------------------------------------------------------------- #


def test_the_prompt_names_the_url_and_the_helper_and_nothing_secret(
    tmp_path: Path,
) -> None:
    text = signin.prompt(workspace=tmp_path / "ws")
    assert f"login url: {login_form.LOGIN_URL}" in text
    assert "helper: dataporter --workspace" in text
    assert "You hold no credentials" in text
    assert "form_ready" in text


def test_credentials_are_required_before_anything_starts(tmp_path: Path) -> None:
    with Browser(LoginForm()) as browser:
        settings = settings_for(tmp_path, None, browser, credentials=False)
        with pytest.raises(UsageError, match="DATAPORTER_AUTH__EMAIL"):
            signin.require_credentials(settings)
        assert signin.require_credentials(settings_for(tmp_path, None, browser)).email == EMAIL


# -- the two halves ------------------------------------------------------------ #


def test_the_form_is_reached_then_filled_then_proved(tmp_path: Path) -> None:
    page = LoginForm()
    fake = form_ready(tmp_path, "email")
    with Browser(page) as browser:
        settings = settings_for(tmp_path, fake, browser)
        outcome = signin.SignIn(settings).perform(session_of(browser, settings))

    assert outcome == signin.SignInOutcome(signed_in=True, filled=("email", "password"))
    assert page.typed == {"email": EMAIL, "password": SECRET}
    assert page.stage == "done"
    assert len(fake.one_shots) == 1
    assert fake.one_shots[0].flag("-p") == "dataporter"


def test_the_secret_reaches_the_page_and_nothing_else(tmp_path: Path) -> None:
    page = LoginForm()
    fake = form_ready(tmp_path, "email")
    with Browser(page) as browser:
        settings = settings_for(tmp_path, fake, browser)
        signin.SignIn(settings).perform(session_of(browser, settings))
        calls = browser.chrome.calls

    call = fake.one_shots[0]
    assert SECRET not in call.prompt
    assert EMAIL not in call.prompt
    assert not any(SECRET in value or EMAIL in value for value in call.env.values())
    assert not any(SECRET in item or EMAIL in item for item in call.argv)
    assert not any(SECRET in item for item in page.expressions)
    inserted = [str(item.params.get("text")) for item in calls if item.method == "Input.insertText"]
    assert inserted == [EMAIL, SECRET]


def test_a_code_prompt_is_a_person_s_job(tmp_path: Path) -> None:
    page = LoginForm(after_email="code")
    with Browser(page) as browser:
        settings = settings_for(tmp_path, form_ready(tmp_path, "email"), browser)
        outcome = signin.SignIn(settings).perform(session_of(browser, settings))

    assert outcome.signed_in is False
    assert outcome.reason == "authentication required"
    assert outcome.detail == login_form.CODE_OR_CHALLENGE
    assert "password" not in page.typed


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        ({"outcome": "needs_human", "needs_human_reason": "captcha"}, "CAPTCHA"),
        (
            {"outcome": "needs_human", "needs_human_reason": "security_challenge"},
            "security challenge",
        ),
        ({"outcome": "needs_human"}, "ambiguous UI state"),
        ({"outcome": "failed", "error": "no form"}, "ambiguous UI state"),
    ],
)
def test_what_the_agent_could_not_reach_is_not_typed_into(
    tmp_path: Path, result: dict[str, object], reason: str
) -> None:
    page = LoginForm()
    with Browser(page) as browser:
        settings = settings_for(tmp_path, hermes(tmp_path, **result), browser)
        outcome = signin.SignIn(settings).perform(session_of(browser, settings))

    assert outcome.signed_in is False
    assert outcome.reason == reason
    assert page.typed == {}


@pytest.mark.parametrize("answer", ["", "not json", '{"outcome": "elsewhere"}'])
def test_an_agent_that_did_not_answer_is_hermes_failed(tmp_path: Path, answer: str) -> None:
    page = LoginForm()
    fake = FakeHermes(root=tmp_path / "bin").write(answer=answer)
    with Browser(page) as browser:
        settings = settings_for(tmp_path, fake, browser)
        outcome = signin.SignIn(settings).perform(session_of(browser, settings))

    assert outcome.reason == signin.HERMES_FAILED
    assert page.typed == {}


def test_each_attempt_gets_its_own_run_id(tmp_path: Path) -> None:
    page = LoginForm(after_email="code")
    fake = form_ready(tmp_path, "email")
    with Browser(page) as browser:
        settings = settings_for(tmp_path, fake, browser)
        signer = signin.SignIn(settings)
        session = session_of(browser, settings)
        signer.perform(session)
        signer.perform(session)
    names = sorted(item.name for item in settings.hermes_dir.glob("signin-*.stdout.txt"))
    assert names == ["signin-1.stdout.txt", "signin-2.stdout.txt"]


# -- the guard every run makes ------------------------------------------------- #


def test_a_signed_in_session_needs_nothing(tmp_path: Path) -> None:
    with Browser(LoginForm(stage="done")) as browser:
        settings = settings_for(tmp_path, None, browser, non_interactive=False)
        signin.ensure_signed_in(settings, session_of(browser, settings))


def test_interactively_a_signed_out_session_is_12s_exit_3(tmp_path: Path) -> None:
    with Browser(LoginForm()) as browser:
        settings = settings_for(tmp_path, None, browser, non_interactive=False)
        with pytest.raises(AuthError) as raised:
            signin.ensure_signed_in(settings, session_of(browser, settings))
    assert raised.value.detail == browser_session.SIGNED_OUT


def test_unattended_a_signed_out_session_is_signed_in(tmp_path: Path) -> None:
    page = LoginForm()
    with Browser(page) as browser:
        settings = settings_for(tmp_path, form_ready(tmp_path, "email"), browser)
        signin.ensure_signed_in(settings, session_of(browser, settings))
    assert page.stage == "done"


def test_unattended_a_sign_in_that_stopped_names_the_reason_and_the_remedy(
    tmp_path: Path,
) -> None:
    with Browser(LoginForm(after_email="code")) as browser:
        settings = settings_for(tmp_path, form_ready(tmp_path, "email"), browser)
        with pytest.raises(AuthError) as raised:
            signin.ensure_signed_in(settings, session_of(browser, settings))
    assert raised.value.detail == ("automatic sign-in stopped: authentication required — run: dataporter login")


# -- the skill's section, performed ------------------------------------------ #


class _Page:
    def __init__(self, shows: Sequence[str]) -> None:
        self.shows = list(shows)
        self.visited: list[str] = []

    def navigate(self, url: str) -> None:
        self.visited.append(url)

    def visible_fields(self) -> Sequence[str]:
        return self.shows


def test_the_sign_in_prompt_is_performable(tmp_path: Path) -> None:
    page = _Page(["email"])
    printed = ScriptedSignIn(page).run(signin.prompt(workspace=tmp_path))
    assert page.visited == [login_form.LOGIN_URL]
    assert signin.FormResult.model_validate(printed) == signin.FormResult(
        outcome="form_ready", fields=["email"], url=login_form.LOGIN_URL
    )


@pytest.mark.parametrize(
    ("shows", "reason"),
    [
        (["code"], "auth_required"),
        (["captcha"], "captcha"),
        (["challenge"], "security_challenge"),
    ],
)
def test_what_is_not_a_form_is_reported_as_the_skill_says(tmp_path: Path, shows: list[str], reason: str) -> None:
    printed = ScriptedSignIn(_Page(shows)).run(signin.prompt(workspace=tmp_path))
    found = signin.FormResult.model_validate(printed)
    assert (found.outcome, found.needs_human_reason) == ("needs_human", reason)


def test_a_prompt_missing_a_field_is_not_guessed_at() -> None:
    printed = ScriptedSignIn(_Page(["email"])).run("helper: x\n")
    assert printed["outcome"] == "failed"


def test_a_page_with_nothing_on_it_is_failed(tmp_path: Path) -> None:
    printed = ScriptedSignIn(_Page([])).run(signin.prompt(workspace=tmp_path))
    assert printed["outcome"] == "failed"
