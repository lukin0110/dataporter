"""The command surface, and the exit codes it promises."""

import ast
import inspect
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataporter import cli
from dataporter import judge as judging
from dataporter import pilot as piloting
from dataporter import selection as selecting
from dataporter.errors import ExportError, UsageError
from dataporter.exit_codes import ExitCode

# Every command in `specs/impl/01-foundation.md`, written out rather than derived
# from the app, so that a command silently disappearing fails this test.
COMMANDS: list[list[str]] = [
    ["import"],
    ["verify"],
    ["followup"],
    ["judge"],
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
    ["report"],
]
"""The whole surface, and where each command's behaviour is exercised.

`import` runs the migration from `12` and needs a browser and a Hermes, so it is
exercised in `test_importer.py` where the fakes for both live, and its `--pilot`
selection in `test_pilot.py`. `seeds` (`04`),
`inspect` (`05`), `status` (`06`), `login` and `session …` (`07`) are implemented
and no longer exit 69 at all, and `08` implemented every `browser …` command;
those two groups are exercised in `test_browser_session.py` and
`test_browser_helpers.py`, where the fake browser they need lives. `09` implemented
`setup` and `doctor`, which exit `6` rather than `69` on a machine with no Hermes;
they are exercised in `test_hermes_setup.py` and `test_hermes_doctor.py`, where the
fake `hermes` they need lives. `14` implemented `resume`, which exits `4` with
`nothing to resume` on a workspace nothing has paused in; it is exercised in
`test_intervention.py`, where the fakes for a whole paused run live. `17`
implemented `verify`, which exits `4` on a workspace with nothing migrated in it;
it is exercised in `test_verify.py`, where the fake browser it reads through
lives. `19` implemented `report`, the last command that exited `69`; it exits `2`
on a workspace no run has written a plan into, and is exercised in
`test_report.py`. `20` added the last two, `followup` and `judge`, which exit `4`
on a workspace nothing has been migrated or probed in; they are exercised in
`test_followup.py` and `test_judge.py`.

Nothing in the surface answers `69` any more, and nothing refuses a flag either:
`--pilot` was the last refusal and `20` implemented it."""

GLOBAL_OPTIONS = ["--workspace", "--verbose", "-v", "--quiet", "-q", "--version"]


def test_version_is_the_golden_string(runner: CliRunner) -> None:
    result = runner.invoke(cli.app, ["--version"], catch_exceptions=False)
    assert result.exit_code == ExitCode.OK
    assert result.stdout == "dataporter 0.1.0\n"


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


def test_help_lists_every_command(runner: CliRunner) -> None:
    result = runner.invoke(cli.app, ["--help"], catch_exceptions=False)
    assert result.exit_code == ExitCode.OK
    for command in COMMANDS:
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
        "--all",
        "--only",
        "--delay",
        "--max-retries",
        "--timeout",
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
    """`15` tells an explicit `--limit 10` from an unset flag, and so do the
    three pacing flags it added: a literal default here would outrank config."""
    signature = inspect.signature(cli.import_cmd)
    for name in ("limit", "delay", "max_retries", "timeout"):
        assert signature.parameters[name].default is None


def test_usage_error_exits_2(runner: CliRunner, workspace: Path) -> None:
    result = runner.invoke(cli.app, ["import"], catch_exceptions=False)
    assert result.exit_code == ExitCode.USAGE


def test_verbose_and_quiet_compose(runner: CliRunner, workspace: Path) -> None:
    """They act on different streams, so together they are meaningful, not an error."""
    result = runner.invoke(cli.app, ["-v", "-q", "status"], catch_exceptions=False)
    assert result.exit_code == ExitCode.OK


def test_unhandled_exception_becomes_exit_70(
    runner: CliRunner,
    workspace: Path,
    export_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Through `--pilot`, whose selection is the newest thing in the surface:
    what this is about is any command that raises something nobody caught."""

    def explode(*args: object, **kwargs: object) -> None:
        raise ZeroDivisionError("boom")

    monkeypatch.setattr(piloting, "choose", explode)
    result = runner.invoke(
        cli.app,
        ["import", str(export_dir), "--dry-run", "--pilot"],
        catch_exceptions=False,
    )
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

    monkeypatch.setattr(selecting, "export_path", explode)
    result = runner.invoke(cli.app, ["inspect", "."], catch_exceptions=False)
    assert result.exit_code == ExitCode.USAGE
    assert result.stderr == (
        "error: conversations.json is not a JSON array: ./export.zip\n"
    )
    assert "Traceback" not in result.output


# --------------------------------------------------------------------------- #
# `23`: the CLI is an interface
# --------------------------------------------------------------------------- #

COMMAND_APPS = ("app", "session_app", "browser_app")
LOGIC = (ast.For, ast.While, ast.Try, ast.With, ast.If, ast.AsyncFor, ast.AsyncWith)
FORBIDDEN_IMPORTS = ("state", "launcher", "probe", "summary", "load_export")


def command_functions(tree: ast.Module) -> list[ast.FunctionDef]:
    """Every function registered on one of the three Typer apps."""
    found: list[ast.FunctionDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            call = decorator if isinstance(decorator, ast.Call) else None
            target = call.func if call is not None else decorator
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "command"
                and isinstance(target.value, ast.Name)
                and target.value.id in COMMAND_APPS
            ):
                found.append(node)
    return found


def test_every_command_is_an_interface() -> None:
    """`23`'s acceptance criterion, made checkable: a command parses, calls one
    library function, and exits. No loop, no branch, no lock, no browser."""
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    commands = command_functions(tree)
    assert {item.name for item in commands} >= {
        "import_cmd",
        "login",
        "verify",
        "followup",
        "judge",
        "doctor",
        "session_status",
        "browser_probe",
    }
    offenders = [
        f"{function.name}:{node.lineno}"
        for function in commands
        for node in ast.walk(function)
        if isinstance(node, LOGIC)
    ]
    assert offenders == []


def test_the_cli_opens_no_workspace_and_no_browser_itself() -> None:
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.col_offset == 0
        for alias in node.names
    }
    assert not imported & set(FORBIDDEN_IMPORTS)


def test_a_usage_error_from_the_library_is_exit_2(
    runner: CliRunner, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(export: str) -> Path:
        raise UsageError("two flags that cannot both be honoured")

    monkeypatch.setattr(selecting, "export_path", refuse)
    result = runner.invoke(cli.app, ["inspect", "."], catch_exceptions=False)
    assert result.exit_code == ExitCode.USAGE
    assert result.stderr == "error: two flags that cannot both be honoured\n"


def test_a_judge_error_is_exit_6(
    runner: CliRunner, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise judging.JudgeError("the judge extra is not installed")

    monkeypatch.setattr(judging, "judge_all", refuse)
    result = runner.invoke(cli.app, ["judge"], catch_exceptions=False)
    assert result.exit_code == ExitCode.ENVIRONMENT
    assert result.stderr == "error: the judge extra is not installed\n"
