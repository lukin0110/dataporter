"""The command surface, and the exit codes it promises."""

import inspect
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from dataporter import cli
from dataporter.exit_codes import ExitCode

# Every command in `specs/impl/01-foundation.md`, written out rather than derived
# from the app, so that a command silently disappearing fails this test.
COMMANDS: list[list[str]] = [
    ["login"],
    ["inspect", "."],
    ["seeds", "."],
    ["status"],
    ["resume"],
    ["verify"],
    ["report"],
    ["setup"],
    ["doctor"],
    ["session", "status"],
    ["session", "logout"],
    ["browser", "probe"],
    ["browser", "paste"],
    ["browser", "attach"],
    ["browser", "await-response"],
    ["browser", "close-extra-tabs"],
]

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


def test_import_reaches_69_once_the_export_exists(
    runner: CliRunner, workspace: Path
) -> None:
    export = workspace / "export"
    export.mkdir()
    result = runner.invoke(
        cli.app, ["import", str(export), "--dry-run"], catch_exceptions=False
    )
    assert result.exit_code == ExitCode.NOT_IMPLEMENTED
    assert result.stderr == "not implemented in this build: import\n"


def test_help_lists_every_command(runner: CliRunner) -> None:
    result = runner.invoke(cli.app, ["--help"], catch_exceptions=False)
    assert result.exit_code == ExitCode.OK
    for command in COMMANDS + [["import"]]:
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
    assert result.exit_code == ExitCode.NOT_IMPLEMENTED


def test_unhandled_exception_becomes_exit_70(
    runner: CliRunner, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(ctx: typer.Context) -> None:
        raise ZeroDivisionError("boom")

    monkeypatch.setattr(cli, "not_implemented", explode)
    result = runner.invoke(cli.app, ["status"], catch_exceptions=False)
    assert result.exit_code == ExitCode.INTERNAL
    assert result.stderr == "internal error: ZeroDivisionError\n"
    # The detail goes to the log, never to the operator's terminal.
    assert "boom" not in result.output
    assert "Traceback" not in result.output


def test_invoked_name_skips_the_program_name(
    runner: CliRunner, workspace: Path
) -> None:
    result = runner.invoke(cli.app, ["session", "logout"], catch_exceptions=False)
    assert result.stderr == "not implemented in this build: session logout\n"
