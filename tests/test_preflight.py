"""`69`: a command that needs a session and has none opens no browser.

Every test here proves the same two things about one command — the refusal is
`SIGNED_OUT_LINE` byte for byte, and `launcher.launch` was never reached — so the
`no_browser` fixture is the assertion and the body is only the call.

What is *not* here is a browser, a fake Chrome or a served page, which is the
point: the whole of this slice is answerable from the filesystem. The commands
that do open one, and what they do when the session has lapsed rather than never
existed, are `70`'s.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dataporter import extract as extracting
from dataporter import extract_skills as skills
from dataporter import followup as following
from dataporter import state
from dataporter import verify as verifying
from dataporter.browser import launcher
from dataporter.browser import session as browser_session
from dataporter.config import Settings, load_settings, with_account, with_store_dir
from dataporter.errors import AuthError
from dataporter.exit_codes import ExitCode
from dataporter.hermes import doctor as hermes_doctor
from dataporter.importer import ImportRequest, import_command, resume_command
from dataporter.state import ConversationState, PauseRecord, Status

ACCOUNT = "work"
SOURCE_SIGNED_OUT = f"not logged in — run: dataporter login --source claude --account {ACCOUNT}"
"""What the four account-scoped commands refuse with: `52`'s remedy, carrying the flags."""

DESTINATION_SIGNED_OUT = "not logged in — run: dataporter login"
"""What the three workspace-scoped ones refuse with: §86 left the destination no account to name."""

LINK = "https://claude.ai/export/abc"
CONVERSATION = "aa000001-1111-4111-8111-111111111111"
CHAT = "11111111-2222-4333-8444-555555555555"


@pytest.fixture
def no_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make launching Chrome the failure, so each test's claim is structural.

    `launch` alone and not `adopt`: `adopt` is what `launch` itself calls to find
    a browser already on the port, and nothing under test reaches it by another
    road.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a browser was launched; `69` says the command should have refused first")

    monkeypatch.setattr(launcher, "launch", refuse)


@pytest.fixture
def account(tmp_path: Path, workspace: Path) -> Settings:
    """Return a source account whose home has never existed."""
    loaded = with_store_dir(load_settings(), tmp_path / "store")
    return with_account(
        loaded.model_copy(update={"accounts": loaded.accounts.model_copy(update={"dir": tmp_path / "accounts"})}),
        "claude",
        ACCOUNT,
    )


@pytest.fixture
def destination(tmp_path: Path) -> Settings:
    """Return a workspace whose destination profile has never existed."""
    return Settings(workspace=tmp_path / "migration")


def refused(call: Any) -> str:
    """Run `call`, require an `AuthError`, and return its detail."""
    with pytest.raises(AuthError) as raised:
        call()
    return raised.value.detail


# --------------------------------------------------------------------------- #
# The four account-scoped commands
# --------------------------------------------------------------------------- #


def test_the_ask_refuses_before_a_browser(account: Settings, no_browser: None) -> None:
    assert refused(lambda: extracting.ask(account)) == SOURCE_SIGNED_OUT


def test_the_ask_leaves_the_account_home_untouched(account: Settings, no_browser: None) -> None:
    """Before `enable_run_log`, for `logout`'s reason: a refusal leaves no log behind.

    A mistyped label is the case this is really about — it should not create a
    tree of directories for an account nobody has.
    """
    refused(lambda: extracting.ask(account))
    assert account.account_home is not None
    assert not account.account_home.exists()


def test_a_session_fetch_refuses_before_a_browser(account: Settings, no_browser: None) -> None:
    """Claude's link serves a manifest, so the fetch goes through the session."""
    assert refused(lambda: extracting.fetch(account, LINK)) == SOURCE_SIGNED_OUT


def test_a_session_fetch_leaves_the_account_home_untouched(account: Settings, no_browser: None) -> None:
    refused(lambda: extracting.fetch(account, LINK))
    assert account.account_home is not None
    assert not account.account_home.exists()


def test_extract_skills_refuses_before_a_browser(account: Settings, no_browser: None) -> None:
    request = skills.SkillsRequest()
    assert refused(lambda: skills.extract_skills_command(account, request)) == SOURCE_SIGNED_OUT


# --------------------------------------------------------------------------- #
# The three workspace-scoped ones
# --------------------------------------------------------------------------- #


def test_import_refuses_before_a_browser(destination: Settings, export_zip: Path, no_browser: None) -> None:
    request = ImportRequest(export=str(export_zip))
    assert refused(lambda: import_command(destination, request)) == DESTINATION_SIGNED_OUT


def test_a_dry_run_needs_no_session(destination: Settings, export_zip: Path, no_browser: None) -> None:
    """A dry run opens no browser, so it has nothing to require one for."""
    outcome = import_command(destination, ImportRequest(export=str(export_zip), dry_run=True))
    assert outcome.exit_code == ExitCode.OK


def paused_workspace(settings: Settings, export_zip: Path) -> None:
    """Leave the workspace with a pause `resume` would continue.

    No `state.json` entry for the paused conversation: an entry that is
    `completed` is one somebody finished another way, which `_pause_to_resume`
    clears rather than resumes.
    """
    store = state.StateStore(settings.workspace)
    store.bind_export(_fingerprint(export_zip), export_zip)
    store.set_paused(PauseRecord(conversation_uuid=CONVERSATION, reason="needs_human", since=datetime.now(UTC)))


def test_resume_refuses_before_a_browser(destination: Settings, export_zip: Path, no_browser: None) -> None:
    paused_workspace(destination, export_zip)
    assert refused(lambda: resume_command(destination)) == DESTINATION_SIGNED_OUT


def test_nothing_to_resume_is_still_exit_4(destination: Settings, no_browser: None) -> None:
    """The check sits after the pause is looked for, not before it.

    A workspace with nothing to continue is exit `4` whether or not anybody is
    signed in: sending somebody to `login` for work that does not exist is a
    worse answer than the truth.
    """
    outcome = resume_command(destination)
    assert outcome.exit_code == ExitCode.NOTHING_TO_DO


def test_verify_refuses_before_a_browser(destination: Settings, no_browser: None) -> None:
    store = state.StateStore(destination.workspace)
    store.update(CONVERSATION, **_entry().model_dump())
    assert refused(lambda: verifying.verify_all(destination)) == DESTINATION_SIGNED_OUT


def test_nothing_to_verify_is_exit_4(destination: Settings, no_browser: None) -> None:
    assert verifying.verify_all(destination).exit_code == ExitCode.NOTHING_TO_DO


def test_followup_refuses_before_a_browser(
    destination: Settings, no_browser: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After the Hermes check, which is the order `Importer._preflight` already uses."""
    monkeypatch.setattr(hermes_doctor, "local_failure", lambda settings: None)
    store = state.StateStore(destination.workspace)
    store.update(CONVERSATION, **_entry().model_dump())
    assert refused(lambda: following.ask_all(destination)) == DESTINATION_SIGNED_OUT


def test_nothing_to_probe_is_exit_4(destination: Settings, no_browser: None) -> None:
    assert following.ask_all(destination).exit_code == ExitCode.NOTHING_TO_DO


# --------------------------------------------------------------------------- #
# The commands that must not have one
# --------------------------------------------------------------------------- #


def test_logout_needs_no_session_to_remove_one(account: Settings) -> None:
    """`logout` is how a profile stops existing; a preflight on it refuses its own job."""
    outcome = browser_session.logout(account)
    assert outcome.removed is False


def test_status_reads_the_same_test_by_name(account: Settings) -> None:
    """`status` shares `never_signed_in` and keeps its own shape: a line, not an error."""
    assert browser_session.never_signed_in(account) is True


def test_a_profile_that_exists_passes(account: Settings) -> None:
    """The directory is the whole test — its contents are the vendor's business (`70`)."""
    account.browser_profile_dir.mkdir(parents=True)
    assert browser_session.never_signed_in(account) is False
    browser_session.require_session(account)


def _entry(**fields: object) -> ConversationState:
    return ConversationState.model_validate({
        "title": "A conversation",
        "status": Status.COMPLETED,
        "destination": {"conversation_id": CHAT},
        "chunks_total": 2,
        **fields,
    })


def _fingerprint(export_zip: Path) -> str:
    from dataporter.export import load_export  # ruff: ignore[import-outside-top-level] - one test's own concern

    return load_export(export_zip).fingerprint
