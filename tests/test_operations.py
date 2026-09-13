"""`23`: the library does what the CLI does, and the CLI adds nothing.

Every operation is called twice here — once directly with a `console.Collected`,
once through the CLI with the same settings in the environment — and the two
outputs are compared byte for byte, along with the exit code. That is the whole
claim of the slice: a Python caller gets the same words and the same code without
typer.

The runs that need a workspace, a fake Hermes and a fake browser use `world`,
which marks them `slow`; the ones that read a file or a directory need nothing.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataporter import cli, console
from dataporter import extract as extracting
from dataporter import importer as importing
from dataporter import report as reporting
from dataporter import seed as seeding
from dataporter import selection as selecting
from dataporter import store as storing
from dataporter.browser import launcher
from dataporter.browser import session as browser_session
from dataporter.browser.cdp import CdpClient
from dataporter.config import (
    BrowserSettings,
    Settings,
    TimeoutSettings,
    load_settings,
    with_account,
    with_store_dir,
)
from dataporter.exit_codes import ExitCode
from dataporter.state import Status
from fake_export_page import FakeExportPage, browser
from world import FIRST, World, cli_env


def invoke(runner: CliRunner, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(cli.app, list(args), catch_exceptions=False)
    return result.exit_code, result.stdout, result.stderr


# --------------------------------------------------------------------------- #
# Reading an export
# --------------------------------------------------------------------------- #


def test_inspect_is_the_same_through_the_library(runner: CliRunner, workspace: Path, export_dir: Path) -> None:
    sink = console.Collected()
    outcome = selecting.inspect_export(load_settings(), str(export_dir), sink=sink)
    code, out, err = invoke(runner, "inspect", str(export_dir))

    assert (outcome.exit_code, sink.stdout, sink.stderr) == (code, out, err)
    assert outcome.plan.totals.conversations > 0


def test_inspect_json_is_the_plan_itself(runner: CliRunner, workspace: Path, export_dir: Path) -> None:
    sink = console.Collected()
    outcome = selecting.inspect_export(load_settings(), str(export_dir), json_output=True, sink=sink)
    _, out, _ = invoke(runner, "inspect", str(export_dir), "--json")

    assert sink.stdout == out
    assert json.loads(sink.stdout) == outcome.plan.model_dump(mode="json")


def test_a_dry_run_is_the_same_through_the_library(runner: CliRunner, workspace: Path, export_dir: Path) -> None:
    sink = console.Collected()
    outcome = importing.import_command(
        load_settings(),
        importing.ImportRequest(export=str(export_dir), dry_run=True),
        sink=sink,
    )
    code, out, err = invoke(runner, "import", str(export_dir), "--dry-run")

    assert (outcome.exit_code, sink.stdout, sink.stderr) == (code, out, err)
    assert outcome.plan is not None
    assert outcome.summary is None
    # §9's local promise, kept by the library as it was by the CLI.
    assert not (workspace / "migration").exists()


def test_a_dry_run_of_the_pilot_prints_the_selection_first(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    sink = console.Collected()
    outcome = importing.import_command(
        load_settings(),
        importing.ImportRequest(export=str(export_dir), dry_run=True, pilot=True),
        sink=sink,
    )
    code, out, _ = invoke(runner, "import", str(export_dir), "--dry-run", "--pilot")

    assert (outcome.exit_code, sink.stdout) == (code, out)
    assert outcome.choices
    assert sink.stdout.startswith("Pilot selection:")


def test_seeds_are_the_same_through_the_library(
    runner: CliRunner, workspace: Path, export_dir: Path, tmp_path: Path
) -> None:
    sink = console.Collected()
    outcome = seeding.write_seeds(load_settings(), str(export_dir), out=tmp_path / "one", sink=sink)
    code, out, err = invoke(runner, "seeds", str(export_dir), "--out", str(tmp_path / "two"))

    assert (outcome.exit_code, sink.stdout, sink.stderr) == (code, out, err)
    assert outcome.written == len(sink.out)
    # The fixture's one empty conversation, named on stderr by both.
    assert [reason for _, reason in outcome.skipped] == ["empty_conversation"]


def test_seeds_of_nothing_is_exit_4(workspace: Path, tmp_path: Path) -> None:
    empty = tmp_path / "export-empty"
    empty.mkdir()
    (empty / "conversations.json").write_text("[]", encoding="utf-8")

    outcome = seeding.write_seeds(load_settings(), str(empty))

    assert outcome.exit_code == ExitCode.NOTHING_TO_DO
    assert outcome.written == 0


# --------------------------------------------------------------------------- #
# The store (`30`)
# --------------------------------------------------------------------------- #


def extract_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str = "store") -> tuple[Settings, list[str]]:
    """Return Settings for the library call, and the flags that produce the same ones.

    A store per caller: the two file the same archive moments apart, and §33's
    "the store never overwrites" is exactly what would refuse the second one
    when both land in the same second. `blanked` is what puts the two blocks
    back on the same footing.
    """
    monkeypatch.setenv("DATAPORTER_ACCOUNTS__DIR", str(tmp_path / "accounts"))
    root = tmp_path / name
    settings = with_account(with_store_dir(load_settings(), root), "claude", "a")
    return settings, ["--account", "a", "--store", str(root)]


def test_extract_from_is_the_same_through_the_library(
    runner: CliRunner,
    workspace: Path,
    export_zip: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, _ = extract_env(tmp_path, monkeypatch, "store-library")
    _, flags = extract_env(tmp_path, monkeypatch, "store-cli")
    sink = console.Collected()
    outcome = extracting.file(settings, export_zip, sink=sink)
    code, out, err = invoke(runner, "extract", *flags, "--from", str(export_zip))

    assert (outcome.exit_code, sink.stderr) == (code, err)
    assert blanked(sink.stdout, tmp_path) == blanked(out, tmp_path)
    assert outcome.snapshot is not None


def test_extract_abandon_is_the_same_through_the_library(
    runner: CliRunner,
    workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, flags = extract_env(tmp_path, monkeypatch)
    extracting.write_ask(settings, datetime.now(UTC))
    sink = console.Collected()
    outcome = extracting.abandon(settings, sink=sink)

    extracting.write_ask(settings, datetime.now(UTC))
    code, out, err = invoke(runner, "extract", *flags, "--abandon")

    assert (outcome.exit_code, sink.stdout, sink.stderr) == (code, out, err)


@pytest.mark.slow
def test_extract_the_ask_is_the_same_through_the_library(
    runner: CliRunner,
    workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`31`'s ask, twice: once as a call and once as a command.

    Two browsers, because an ask closes the one it opened, and two accounts,
    because one ask is open per account at a time — which is the same shape
    `extract --from` needs two stores for.
    """
    page = FakeExportPage()
    with browser(page) as chrome:
        monkeypatch.setenv("DATAPORTER_ACCOUNTS__DIR", str(tmp_path / "accounts"))
        settings = ask_settings(tmp_path, chrome.port, "library")
        fake_launch(monkeypatch, chrome.port)
        sink = console.Collected()
        outcome = extracting.ask(settings, sink=sink)

    page = FakeExportPage()
    with browser(page, port=chrome.port) as second:
        fake_launch(monkeypatch, second.port)
        code, out, err = invoke(runner, "extract", "--account", "cli")

    assert (outcome.exit_code, sink.stderr) == (code, err)
    assert without_account(sink.stdout, "library") == without_account(out, "cli")


def ask_settings(tmp_path: Path, port: int, account: str) -> Settings:
    """One invocation about one source account, pointed at the fake browser."""
    loaded = load_settings().model_copy(
        update={
            "browser": BrowserSettings(cdp_port=port),
            "timeouts": TimeoutSettings(cdp_call_s=2.0, ask_s=0.3, login_s=0.1),
        }
    )
    return with_account(loaded, "claude", account)


def fake_launch(monkeypatch: pytest.MonkeyPatch, port: int) -> None:
    """`07`'s adoption, without a Chrome — `world.py`'s seam, one test at a time."""
    monkeypatch.setattr(
        launcher,
        "launch",
        lambda settings, url: launcher.BrowserSession(
            client=CdpClient(port=port, timeout=2.0),
            profile=settings.browser_profile_dir,
            adopted=True,
        ),
    )


def without_account(text: str, account: str) -> str:
    """Return the ask's block with the label and the minute taken out of it.

    Two asks are two accounts and two moments; every other byte has to match.
    """
    moment = re.sub(r"\d{4}-\d\d-\d\d \d\d:\d\d UTC", "<moment>", text)
    return moment.replace(account, "<account>")


def test_snapshots_is_the_same_through_the_library(
    runner: CliRunner,
    workspace: Path,
    export_zip: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, flags = extract_env(tmp_path, monkeypatch)
    extracting.file(settings, export_zip)

    for json_output in (False, True):
        sink = console.Collected()
        outcome = storing.list_command(settings, json_output=json_output, sink=sink)
        code, out, err = invoke(runner, "snapshots", *flags[2:], *(["--json"] if json_output else []))

        assert (outcome.exit_code, sink.stdout, sink.stderr) == (code, out, err)
        assert len(outcome.rows) == 1


def test_snapshots_of_an_empty_store_is_the_same_through_the_library(
    runner: CliRunner, workspace: Path, tmp_path: Path
) -> None:
    settings = with_store_dir(load_settings(), tmp_path / "store")
    sink = console.Collected()
    outcome = storing.list_command(settings, sink=sink)
    code, out, err = invoke(runner, "snapshots", "--store", str(tmp_path / "store"))

    assert (outcome.exit_code, sink.stdout, sink.stderr) == (code, out, err)
    assert outcome.exit_code == ExitCode.OK


def blanked(text: str, tmp_path: Path) -> str:
    """Return a block with the stamp and the store's name taken out of it.

    Two filings of the same archive are two moments into two stores, and every
    other byte of the two blocks has to match.
    """
    without_stamp = re.sub(r"\d{4}-\d\d-\d\dT\d\d-\d\d-\d\dZ", "<stamp>", text)
    return without_stamp.replace(f"{tmp_path}/store-library", "<store>").replace(f"{tmp_path}/store-cli", "<store>")


# --------------------------------------------------------------------------- #
# Reading a workspace
# --------------------------------------------------------------------------- #


def test_status_of_an_empty_workspace_is_the_same_through_the_library(runner: CliRunner, workspace: Path) -> None:
    for json_output in (False, True):
        sink = console.Collected()
        outcome = reporting.status(load_settings(), json_output=json_output, sink=sink)
        flags = ["--json"] if json_output else []
        code, out, _ = invoke(runner, "status", *flags)

        assert (outcome.exit_code, sink.stdout) == (code, out)
        assert dict(outcome.migration.items()) == {}


def test_logout_with_no_profile_is_the_same_through_the_library(runner: CliRunner, workspace: Path) -> None:
    sink = console.Collected()
    outcome = browser_session.logout(load_settings(), sink=sink)
    code, out, _ = invoke(runner, "session", "logout")

    assert (outcome.exit_code, sink.stdout) == (code, out)
    assert not outcome.removed


def test_logout_of_a_source_account_is_the_same_through_the_library(
    runner: CliRunner,
    workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`31`'s label, through both doors.

    The path in the line is the account home's, which is the whole of what naming an
    account changes.
    """
    monkeypatch.setenv("DATAPORTER_ACCOUNTS__DIR", str(tmp_path / "accounts"))
    settings = with_account(load_settings(), "claude", "a")
    sink = console.Collected()
    outcome = browser_session.logout(settings, sink=sink)
    code, out, _ = invoke(runner, "session", "logout", "--account", "a")

    assert (outcome.exit_code, sink.stdout) == (code, out)
    assert str(settings.accounts_dir) in out


def test_resume_with_nothing_to_resume_is_the_same_through_the_library(runner: CliRunner, workspace: Path) -> None:
    sink = console.Collected()
    outcome = importing.resume_command(load_settings(), sink=sink)
    code, out, _ = invoke(runner, "resume")

    assert (outcome.exit_code, sink.stdout) == (code, out)
    assert outcome.exit_code == ExitCode.NOTHING_TO_DO


def test_a_summary_with_no_report_has_no_text() -> None:
    summary = importing.RunSummary(total=0, selected=(), outcomes={}, counts={}, exit_code=ExitCode.OK)
    assert not importing.report_text(summary)


# --------------------------------------------------------------------------- #
# A run
# --------------------------------------------------------------------------- #


def test_a_run_is_the_same_through_the_library(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run's progress goes to the terminal through `Reporter`, however the run was started.

    It is `18`'s. What the sink gets is §16's block, and it is the same block the CLI
    prints last.
    """
    sink = console.Collected()
    outcome = importing.import_command(
        world.settings,
        importing.ImportRequest(export=str(world.export), only=[FIRST]),
        sink=sink,
    )
    assert outcome.exit_code == ExitCode.OK
    assert outcome.summary is not None
    assert outcome.summary.outcomes[FIRST] is Status.COMPLETED
    assert outcome.summary.report is not None
    assert sink.stdout == f"\n{reporting.render(outcome.summary.report)}"

    cli_env(world, monkeypatch)
    code, out, _ = invoke(runner, "import", str(world.export), "--only", FIRST)
    assert code == ExitCode.OK
    assert out.endswith(f"\n{reporting.render(reporting.build(world.settings.workspace))}")


def test_report_after_a_run_is_the_same_through_the_library(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    importing.import_command(world.settings, importing.ImportRequest(export=str(world.export), limit=1))
    cli_env(world, monkeypatch)
    for json_output in (False, True):
        sink = console.Collected()
        outcome = reporting.show(world.settings, json_output=json_output, sink=sink)
        flags = ["--json"] if json_output else []
        code, out, _ = invoke(runner, "report", *flags)

        assert (outcome.exit_code, sink.stdout) == (code, out)
        assert outcome.report.totals.created == 1
