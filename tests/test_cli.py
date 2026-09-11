"""The command surface, and the exit codes it promises."""

import inspect
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from dataporter import cli
from dataporter.errors import ExportError
from dataporter.exit_codes import ExitCode

# Every command in `specs/impl/01-foundation.md`, written out rather than derived
# from the app, so that a command silently disappearing fails this test.
COMMANDS: list[list[str]] = [
    ["verify"],
    ["report"],
]

EXCLUDED_FROM_69: list[list[str]] = [
    ["import"],
    ["resume"],
    ["seeds"],
    ["inspect"],
    ["status"],
    ["login"],
    ["session", "status"],
    ["session", "logout"],
    ["browser", "probe"],
    ["browser", "paste"],
    ["browser", "attach"],
    ["browser", "await-response"],
    ["browser", "close-extra-tabs"],
    ["setup"],
    ["doctor"],
]
"""Commands `--help` must still list that the 69 test cannot cover as written.

`import` runs the migration from `12` and needs a browser and a Hermes, so it is
exercised in `test_importer.py` where the fakes for both live; the one thing it
still refuses is `--pilot`, which has a test of its own below. `seeds` (`04`),
`inspect` (`05`), `status` (`06`), `login` and `session …` (`07`) are implemented
and no longer exit 69 at all, and `08` implemented every `browser …` command;
those two groups are exercised in `test_browser_session.py` and
`test_browser_helpers.py`, where the fake browser they need lives. `09` implemented
`setup` and `doctor`, which exit `6` rather than `69` on a machine with no Hermes;
they are exercised in `test_hermes_setup.py` and `test_hermes_doctor.py`, where the
fake `hermes` they need lives. `14` implemented `resume`, which exits `4` with
`nothing to resume` on a workspace nothing has paused in; it is exercised in
`test_intervention.py`, where the fakes for a whole paused run live."""

GLOBAL_OPTIONS = ["--workspace", "--verbose", "-v", "--quiet", "-q", "--version"]


def test_version_is_the_golden_string(runner: CliRunner) -> None:
    result = runner.invoke(cli.app, ["--version"], catch_exceptions=False)
    assert result.exit_code == ExitCode.OK
    assert result.stdout == "hermes-claude-migrate 0.1.0\n"


def test_missing_export_exits_usage_with_no_traceback(
    runner: CliRunner, workspace: Path
) -> None:
    result = runner.invoke(
        cli.app, ["import", "./nowhere", "--dry-run"], catch_exceptions=False
    )
    assert result.exit_code == ExitCode.USAGE
    # The path is echoed exactly as typed: str(Path("./nowhere")) would be "nowhere".
    assert result.stderr == "error: export not found: ./nowhere\n"
    assert result.stdout == ""
    assert "Traceback" not in result.output


@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: " ".join(c))
def test_unimplemented_commands_exit_69(
    runner: CliRunner, workspace: Path, command: list[str]
) -> None:
    result = runner.invoke(cli.app, command, catch_exceptions=False)
    # The message names the command as typed, not the Python function.
    name = " ".join(
        part for part in command if not part.startswith("-") and part != "."
    )
    assert result.exit_code == ExitCode.NOT_IMPLEMENTED
    assert result.stderr == f"not implemented in this build: {name}\n"
    assert result.stdout == ""


def test_import_pilot_is_not_implemented(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    """`20` owns the pilot selection, and a selection flag cannot be inert: it
    is refused rather than accepted and quietly replaced by the ordinary one."""
    result = runner.invoke(
        cli.app, ["import", str(export_dir), "--pilot"], catch_exceptions=False
    )
    assert result.exit_code == ExitCode.NOT_IMPLEMENTED
    assert result.stderr == "not implemented in this build: import --pilot\n"
    assert result.stdout == ""


def test_help_lists_every_command(runner: CliRunner) -> None:
    result = runner.invoke(cli.app, ["--help"], catch_exceptions=False)
    assert result.exit_code == ExitCode.OK
    for command in COMMANDS + EXCLUDED_FROM_69:
        assert command[0] in result.stdout
    for option in GLOBAL_OPTIONS:
        assert option in result.stdout
    # Plain formatting: no rich boxes, and no completion options in the surface.
    assert "─" not in result.stdout
    assert "--install-completion" not in result.stdout


def test_import_help_carries_every_flag(runner: CliRunner) -> None:
    result = runner.invoke(cli.app, ["import", "--help"], catch_exceptions=False)
    for flag in (
        "--dry-run",
        "--limit",
        "--only",
        "--retry-failed",
        "--retry-partial",
        "--force",
        "--skip-attachments",
        "--attachments-dir",
        "--force-unlock",
        "--pilot",
    ):
        assert flag in result.stdout


def test_limit_has_no_literal_default(runner: CliRunner, workspace: Path) -> None:
    """`15` must be able to tell an explicit `--limit 10` from an unset flag."""
    signature = inspect.signature(cli.import_cmd)
    assert signature.parameters["limit"].default is None


def test_usage_error_exits_2(runner: CliRunner, workspace: Path) -> None:
    result = runner.invoke(cli.app, ["import"], catch_exceptions=False)
    assert result.exit_code == ExitCode.USAGE


def test_verbose_and_quiet_compose(runner: CliRunner, workspace: Path) -> None:
    """They act on different streams, so together they are meaningful, not an error."""
    result = runner.invoke(cli.app, ["-v", "-q", "status"], catch_exceptions=False)
    assert result.exit_code == ExitCode.OK


def test_unhandled_exception_becomes_exit_70(
    runner: CliRunner, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(ctx: typer.Context) -> None:
        raise ZeroDivisionError("boom")

    monkeypatch.setattr(cli, "not_implemented", explode)
    result = runner.invoke(cli.app, ["verify"], catch_exceptions=False)
    assert result.exit_code == ExitCode.INTERNAL
    assert result.stderr == "internal error: ZeroDivisionError\n"
    # The detail goes to the log, never to the operator's terminal.
    assert "boom" not in result.output
    assert "Traceback" not in result.output


def test_invoked_name_skips_the_program_name(
    runner: CliRunner, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`08` implemented every nested command, so the case is exercised by
    pointing one of them back at `not_implemented`."""
    monkeypatch.setattr(
        cli, "emit_helper", lambda ctx, name, work: cli.not_implemented(ctx)
    )
    result = runner.invoke(cli.app, ["browser", "probe"], catch_exceptions=False)
    assert result.stderr == "not implemented in this build: browser probe\n"


def test_a_malformed_export_is_exit_2_not_an_internal_error(
    runner: CliRunner, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`02` raises `ExportError`; without a clause of its own it would reach the
    operator as `internal error: ExportError` and exit `70`."""

    def explode(export: str) -> Path:
        raise ExportError(detail="conversations.json is not a JSON array: ./export.zip")

    monkeypatch.setattr(cli, "require_export", explode)
    result = runner.invoke(cli.app, ["inspect", "."], catch_exceptions=False)
    assert result.exit_code == ExitCode.USAGE
    assert result.stderr == (
        "error: conversations.json is not a JSON array: ./export.zip\n"
    )
    assert "Traceback" not in result.output
