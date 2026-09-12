"""`24`'s deterministic half: the credentials go into the form, and nowhere else."""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import SecretStr

from dataporter.browser import launcher, login_form
from dataporter.browser.cdp import CdpClient
from dataporter.config import Credentials
from fake_composer import Browser, FakePage
from fake_login import LoginForm
from fake_pages import PageServer
from live_browser import live_browser, requires_a_browser, visit

pytestmark = pytest.mark.slow

CREDENTIALS = Credentials(email="someone@example.test", password=SecretStr("hunter2"))


@pytest.fixture
def form() -> Iterator[LoginForm]:
    page = LoginForm()
    with Browser(page):
        yield page


def session_for(
    page: FakePage, browser: Browser, tmp_path: Path
) -> launcher.BrowserSession:
    return launcher.BrowserSession(
        client=CdpClient(port=browser.chrome.port, timeout=2.0),
        profile=tmp_path / "profile",
        adopted=True,
    )


def fill(page: LoginForm, tmp_path: Path, **kwargs: object) -> login_form.FillResult:
    browser = Browser(page)
    with browser:
        session = session_for(page, browser, tmp_path)
        return login_form.fill_and_submit(
            session, CREDENTIALS, timeout_s=0.3, poll_s=0.01, **kwargs
        )


# -- the wall ------------------------------------------------------------------ #


@pytest.mark.parametrize(
    "url",
    [
        "https://claude.ai/login",
        "https://claude.ai/login/password",
        "https://claude.ai/login?returnTo=%2Fnew",
        "https://claude.ai/new",
        "https://claude.ai/chat/11111111-2222-4333-8444-555555555555",
    ],
)
def test_the_login_surface_admits_the_sign_in_pages(url: str) -> None:
    assert login_form.LOGIN_SURFACE.permits(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://claude.ai/settings/profile",
        "https://claude.ai/",
        "https://example.test/login",
    ],
)
def test_the_login_surface_admits_nothing_else(url: str) -> None:
    assert not login_form.LOGIN_SURFACE.permits(url)


def test_the_migration_surface_still_refuses_the_login_page() -> None:
    """The door is this module's alone: every helper the agent runs stays walled."""
    from dataporter.browser import helpers

    assert not helpers.CLAUDE.permits("https://claude.ai/login")


# -- the fill ------------------------------------------------------------------ #


def test_email_then_password_signs_in(tmp_path: Path) -> None:
    page = LoginForm()
    result = fill(page, tmp_path)

    assert result == login_form.FillResult(True, ("email", "password"), 2)
    assert page.typed == {"email": "someone@example.test", "password": "hunter2"}
    assert page.enters == 2
    assert page.stage == "done"


def test_the_values_never_enter_an_expression(tmp_path: Path) -> None:
    """The one rule that makes this the module allowed to hold a credential."""
    page = LoginForm()
    fill(page, tmp_path)

    assert page.expressions
    assert not any("hunter2" in item for item in page.expressions)
    assert not any("someone@example.test" in item for item in page.expressions)


def test_the_field_is_selected_before_the_insert_replaces_what_it_held() -> None:
    script = login_form.focus_field_js(login_form.PASSWORD_SELECTOR)
    assert "field.select();" in script
    assert login_form.FOCUS_FIELD_TAG in script


def test_an_emailed_code_is_reported_not_guessed(tmp_path: Path) -> None:
    page = LoginForm(after_email="code")
    result = fill(page, tmp_path)

    assert result.signed_in is False
    assert result.blocked == login_form.CODE_OR_CHALLENGE
    assert result.filled == ("email",)
    assert "password" not in page.typed


def test_a_page_with_no_form_is_reported(tmp_path: Path) -> None:
    page = LoginForm(stage="code")
    result = fill(page, tmp_path)

    assert result.blocked == login_form.NO_FORM
    assert result.filled == ()


def test_an_already_signed_in_page_is_a_sign_in(tmp_path: Path) -> None:
    page = LoginForm(stage="done")
    result = fill(page, tmp_path)

    assert result.signed_in is True
    assert result.filled == ()


def test_a_form_that_shows_the_email_field_again_is_not_fed_twice(
    tmp_path: Path,
) -> None:
    page = LoginForm(after_email="email")
    result = fill(page, tmp_path)

    assert result.blocked == login_form.NO_PROGRESS
    assert page.enters == 1


def test_a_field_that_will_not_take_focus_is_not_typed_into(tmp_path: Path) -> None:
    page = LoginForm(focusable_fields=False)
    result = fill(page, tmp_path)

    assert result.blocked == login_form.FIELD_NOT_FOCUSED
    assert page.typed == {}


def test_no_claude_tab_is_reported(tmp_path: Path) -> None:
    page = FakePage(url="https://example.test/")
    browser = Browser(page)
    with browser:
        result = login_form.fill_and_submit(
            session_for(page, browser, tmp_path), CREDENTIALS, timeout_s=0.1
        )
    assert result.blocked == login_form.NO_TAB


def test_a_form_that_never_moves_on_runs_out_of_time(tmp_path: Path) -> None:
    """A password step that neither signs in nor changes: the deadline ends it."""
    page = LoginForm(stage="password", after_password="password")
    browser = Browser(page)
    with browser:
        result = login_form.fill_and_submit(
            session_for(page, browser, tmp_path),
            CREDENTIALS,
            timeout_s=0.05,
            poll_s=0.01,
        )
    assert result.signed_in is False
    assert result.blocked == login_form.NO_PROGRESS


def test_a_page_mid_navigation_is_asked_again(tmp_path: Path) -> None:
    """A read that fails while the form is being replaced is "not yet", as it
    is for `session.wait_for_login`; the next poll sees the new page."""
    page = LoginForm(fail_after_enter=2)
    result = fill(page, tmp_path)

    assert result.signed_in is True
    assert result.filled == ("email", "password")


def test_an_answer_that_is_not_a_form_reading_is_no_fields() -> None:
    class Mute:
        def evaluate(self, expression: str) -> object:
            return None

    assert login_form._fields(Mute()) == login_form.Fields()  # type: ignore[arg-type]


def test_filled_names_are_names() -> None:
    result = login_form.FillResult(True, ("email", "password"), 2)
    assert list(login_form.filled_names(result)) == ["email", "password"]


# -- against a real browser ---------------------------------------------------- #


@pytest.fixture(scope="module")
def live() -> Iterator[tuple[launcher.BrowserSession, PageServer]]:
    with live_browser() as pair:
        yield pair


@requires_a_browser
def test_a_real_form_is_filled_and_lands_on_new(
    live: tuple[launcher.BrowserSession, PageServer],
) -> None:
    session, server = live
    visit(session, server.url("/login/form"))
    surface = login_form.Surface(
        host="127.0.0.1",
        allowed=re.compile(r"^http://127\.0\.0\.1:\d+/(login(/.*)?|new)$"),
    )
    result = login_form.fill_and_submit(
        session, CREDENTIALS, timeout_s=10.0, surface=surface
    )
    assert result.signed_in is True
    assert result.filled == ("email", "password")
