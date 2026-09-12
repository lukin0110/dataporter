"""`24` end to end: a run that never waits for a person.

The world's page is signed in throughout, so what these prove is the *seams*:
that an `auth_required` the agent reports mid-run is answered by the tool and
counted as its own thing, that a sign-in the tool cannot make becomes §12's
pause and exit `5`, that `resume` in the same mode signs in itself, and that
the block printed on the way names no window and no keypress. What the fill
does against a real form is `test_login_form.py`'s and `test_signin.py`'s.
"""

import io
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from dataporter import cli, signin, state
from dataporter import importer as importing
from dataporter import intervention as intervening
from dataporter.browser import login_form
from dataporter.config import AuthSettings
from dataporter.errors import AuthError, UsageError
from dataporter.exit_codes import ExitCode
from dataporter.state import Status
from fake_login import LoginForm
from world import FIRST, World, cli_env, completed, needs_human

EMAIL = "someone@example.test"
SECRET = "hunter2"

UNATTENDED_BLOCK = (
    "Human intervention required\n"
    "\n"
    "Reason:       authentication required\n"
    "Conversation: aa000001 (1 of 1)\n"
    "Last step:    open\n"
    "Browser:      no window — non-interactive run; clear it, then run: "
    "dataporter resume\n"
    "\n"
    "Paused for a person (non-interactive); run: dataporter resume\n"
)


def form_ready(*fields: str) -> str:
    return json.dumps(
        {"outcome": "form_ready", "fields": list(fields), "url": login_form.LOGIN_URL}
    )


def form_blocked(reason: str) -> str:
    """The sign-in task stopping: the agent's own object, not a migration's."""
    return json.dumps({"outcome": "needs_human", "needs_human_reason": reason})


def unattended(world: World, *, credentials: bool = True) -> None:
    """Switch the world's settings to `24`'s mode."""
    world.settings = world.settings.model_copy(
        update={
            "non_interactive": True,
            "auth": AuthSettings(email=EMAIL, password=SecretStr(SECRET))
            if credentials
            else AuthSettings(),
        }
    )


def unattended_env(
    monkeypatch: pytest.MonkeyPatch, *, credentials: bool = True
) -> None:
    monkeypatch.setenv("DATAPORTER_NON_INTERACTIVE", "1")
    if credentials:
        monkeypatch.setenv("DATAPORTER_AUTH__EMAIL", EMAIL)
        monkeypatch.setenv("DATAPORTER_AUTH__PASSWORD", SECRET)


# --------------------------------------------------------------------------- #
# The block, and who answers it
# --------------------------------------------------------------------------- #


def test_the_unattended_block_names_no_window_and_no_key(
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = intervening.Request(short_id="aa000001", reason="auth_required")
    assert intervening.block(request, unattended=True) == UNATTENDED_BLOCK
    assert intervening.Unattended().ask(request) is False
    assert capsys.readouterr().out == UNATTENDED_BLOCK


def test_the_attended_block_is_unchanged() -> None:
    request = intervening.Request(short_id="aa000001", reason="auth_required")
    assert intervening.block(request) == intervening.block(request, unattended=False)
    assert intervening.PROMPT in intervening.block(request)
    assert intervening.BROWSER_HELP in intervening.block(request)


def test_unattended_never_reads_a_keystroke_that_happens_to_be_there(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    class Untouchable(io.StringIO):
        def readline(self, *args: Any) -> str:
            raise AssertionError("stdin was read")

        def isatty(self) -> bool:
            raise AssertionError("stdin was consulted")

    monkeypatch.setattr("sys.stdin", Untouchable("\n"))
    answered = intervening.Unattended()
    assert answered.ask(intervening.Request("aa000001")) is False
    assert answered.retry("still not logged in") is False
    err = io.StringIO()
    intervening.Unattended(stderr=err).note("paused")
    assert err.getvalue() == "paused\n"
    assert "still not logged in\n" in capsys.readouterr().out


@pytest.mark.slow
def test_a_run_in_the_mode_asks_nobody(world: World) -> None:
    unattended(world)
    assert isinstance(world.importer().intervention, intervening.Unattended)
    assert isinstance(
        importing.Importer(
            world.settings, intervention=intervening.Console()
        ).intervention,
        intervening.Console,
    )


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


def test_a_login_expiry_mid_run_is_cleared_by_the_tool(world: World) -> None:
    """`13`-shaped: the conversation is tried again, nobody was asked, and the
    sign-in is counted as its own thing."""
    unattended(world)
    world.answers(needs_human(), form_ready("email"), completed())

    summary = world.run(limit=1)

    assert summary.exit_code is ExitCode.OK
    assert world.entry(FIRST).status is Status.COMPLETED
    assert world.entry(FIRST).attempts == 2
    run = world.store().run()
    assert run.auto_signins == 1
    assert run.human_interventions == 0
    assert run.paused is None
    # Three Hermes tasks: the migration, the sign-in, the migration again.
    prompts = [call.prompt for call in world.hermes.one_shots]
    assert len(prompts) == 3
    assert "a sign-in and not a migration" in prompts[1]
    assert SECRET not in prompts[1] and EMAIL not in prompts[1]


def test_a_sign_in_the_tool_cannot_make_pauses_the_run(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    unattended(world)
    world.answers(needs_human(), form_blocked("captcha"))

    summary = world.run(limit=1)

    assert summary.exit_code is ExitCode.PAUSED
    run = world.store().run()
    assert run.paused is not None
    assert run.paused.reason == "auth_required"
    assert run.auto_signins == 0
    assert run.human_interventions == 1
    assert UNATTENDED_BLOCK in capsys.readouterr().out


def test_resume_in_the_mode_signs_in_itself(world: World) -> None:
    """Four Hermes tasks across two processes: the migration, the sign-in that
    stopped, then on `resume` the sign-in that worked and the migration again.
    Listed up front because the fake counts its one-shot runs across both."""
    unattended(world)
    world.answers(
        needs_human(), form_blocked("captcha"), form_ready("email"), completed()
    )
    world.run(limit=2)
    assert world.store().run().paused is not None

    resumed = world.importer().resume()

    assert resumed.exit_code is ExitCode.OK
    assert world.entry(FIRST).status is Status.COMPLETED
    run = world.store().run()
    assert run.paused is None
    assert run.auto_signins == 1
    assert run.human_interventions == 1


def test_a_resume_whose_sign_in_fails_again_stays_paused(world: World) -> None:
    unattended(world)
    world.answers(
        needs_human(),
        form_blocked("captcha"),
        form_blocked("security_challenge"),
    )
    world.run(limit=1)
    # The page is still a sign-in form when `resume` looks: the world's own page
    # is always signed in, which would clear the pause on the re-probe alone.
    world.browser.pages["page-1"] = LoginForm()

    resumed = world.importer().resume()

    assert resumed.exit_code is ExitCode.PAUSED
    assert world.store().run().paused is not None
    assert world.store().run().auto_signins == 0


def test_a_signed_out_session_at_the_start_is_signed_in_and_counted(
    world: World,
) -> None:
    """The preflight: the page is a sign-in form, and the run begins anyway."""
    unattended(world)
    form = LoginForm()
    world.browser.pages["page-1"] = form
    world.answers(form_ready("email"), completed())

    summary = world.run(limit=1)

    assert summary.exit_code is ExitCode.OK
    assert form.typed == {"email": EMAIL, "password": SECRET}
    assert world.entry(FIRST).status is Status.COMPLETED
    assert world.store().run().auto_signins == 1


def test_a_signed_out_session_the_tool_cannot_sign_in_is_exit_3(
    world: World,
) -> None:
    unattended(world)
    world.browser.pages["page-1"] = LoginForm(after_email="code")
    world.answers(form_ready("email"))

    with pytest.raises(AuthError) as raised:
        world.run(limit=1)
    assert raised.value.detail == (
        "automatic sign-in stopped: authentication required — run: dataporter login"
    )
    assert world.hermes.one_shots and len(world.hermes.one_shots) == 1


def test_without_credentials_the_mode_stops_before_a_browser(world: World) -> None:
    unattended(world, credentials=False)
    with pytest.raises(UsageError, match="DATAPORTER_AUTH__EMAIL"):
        importing.import_command(
            world.settings, importing.ImportRequest(export=str(world.export))
        )
    with pytest.raises(UsageError):
        importing.resume_command(world.settings)
    assert world.launches == []
    # A dry run touches no account and needs no credentials.
    outcome = importing.import_command(
        world.settings,
        importing.ImportRequest(export=str(world.export), dry_run=True),
    )
    assert outcome.exit_code is ExitCode.OK


def test_interactively_the_mode_is_off_and_nothing_signs_in(world: World) -> None:
    """The other side of the switch: a signed-out page is still `12`'s exit 3."""
    world.browser.pages["page-1"] = LoginForm()
    with pytest.raises(AuthError) as raised:
        world.run(limit=1)
    assert raised.value.detail == signin.browser_session.SIGNED_OUT
    assert world.hermes.one_shots == []


# --------------------------------------------------------------------------- #
# The commands
# --------------------------------------------------------------------------- #


def test_login_without_credentials_is_exit_2(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli_env(world, monkeypatch)
    unattended_env(monkeypatch, credentials=False)
    result = runner.invoke(cli.app, ["login"], catch_exceptions=False)
    assert result.exit_code == ExitCode.USAGE
    assert result.stderr == f"error: {signin.MISSING_CREDENTIALS}\n"
    assert world.launches == []


@pytest.mark.parametrize("command", ["verify", "followup", "resume"])
def test_every_command_that_signs_in_refuses_the_mode_without_credentials(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    cli_env(world, monkeypatch)
    unattended_env(monkeypatch, credentials=False)
    result = runner.invoke(cli.app, [command], catch_exceptions=False)
    assert result.exit_code == ExitCode.USAGE
    assert result.stderr == f"error: {signin.MISSING_CREDENTIALS}\n"
    assert world.launches == []


def test_login_in_the_mode_signs_in_and_closes_the_browser(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli_env(world, monkeypatch)
    unattended_env(monkeypatch)
    form = LoginForm()
    world.browser.pages["page-1"] = form
    world.answers(form_ready("email"))

    result = runner.invoke(cli.app, ["login"], catch_exceptions=False)

    assert result.exit_code == ExitCode.OK
    assert result.stdout == (
        f"Logged in. Session stored in {world.settings.browser_profile_dir}/.\n"
    )
    assert form.stage == "done"
    assert SECRET not in result.output


def test_login_in_the_mode_that_stops_is_exit_3(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli_env(world, monkeypatch)
    unattended_env(monkeypatch)
    world.browser.pages["page-1"] = LoginForm()
    world.answers(form_blocked("captcha"))

    result = runner.invoke(cli.app, ["login"], catch_exceptions=False)

    assert result.exit_code == ExitCode.NOT_AUTHENTICATED
    assert result.stderr == (
        "error: automatic sign-in stopped: CAPTCHA — run: dataporter login\n"
    )


def test_the_flag_and_the_variable_are_the_same_switch(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli_env(world, monkeypatch)
    secret = tmp_path / "secret.txt"
    secret.write_text(f"{SECRET}\n", encoding="utf-8")
    form = LoginForm()
    world.browser.pages["page-1"] = form
    world.answers(form_ready("email"))

    result = runner.invoke(
        cli.app,
        [
            "--non-interactive",
            "--email",
            EMAIL,
            "--password-file",
            str(secret),
            "login",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == ExitCode.OK
    assert form.typed == {"email": EMAIL, "password": SECRET}


def test_import_in_the_mode_prints_the_unattended_block_and_exits_5(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli_env(world, monkeypatch)
    unattended_env(monkeypatch)
    world.answers(needs_human(), form_blocked("captcha"))

    result = runner.invoke(
        cli.app, ["import", str(world.export), "--limit", "1"], catch_exceptions=False
    )

    assert result.exit_code == ExitCode.PAUSED
    assert "Paused for a person (non-interactive); run: " in result.stdout
    assert intervening.PROMPT not in result.stdout
    assert state.StateStore(world.settings.workspace).run().paused is not None


# --------------------------------------------------------------------------- #
# Where the secret is not
# --------------------------------------------------------------------------- #


def test_the_secret_is_in_no_file_the_run_leaves_behind(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """After a run that signed in twice — at the start and after an expiry —
    every file in the workspace, every Hermes transcript, every log record and
    everything printed carries neither the email nor the password."""
    unattended(world)
    form = LoginForm()
    world.browser.pages["page-1"] = form
    world.answers(form_ready("email"), needs_human(), form_ready("email"), completed())

    summary = world.run(limit=1)
    assert summary.exit_code is ExitCode.OK
    assert world.store().run().auto_signins == 2

    leaks: list[str] = []
    for path in sorted(world.settings.workspace.rglob("*")):
        if path.is_file():
            text = path.read_bytes().decode("utf-8", errors="replace")
            if SECRET in text or EMAIL in text:
                leaks.append(str(path.relative_to(world.settings.workspace)))
    assert leaks == []
    printed = capsys.readouterr()
    assert SECRET not in printed.out + printed.err
    assert EMAIL not in printed.out + printed.err
    for call in world.hermes.calls:
        assert SECRET not in json.dumps(call.env) and EMAIL not in json.dumps(call.env)
        assert SECRET not in " ".join(call.argv) and EMAIL not in " ".join(call.argv)
    # The one place it went: the form, through `Input.insertText`, twice.
    assert form.typed == {"email": EMAIL, "password": SECRET}
    assert not any(SECRET in item for item in form.expressions)
