"""The dry run and `inspect`.

`05`'s acceptance criteria are the first sections; the rest cover rules the spec
states that the fixture does not force. The blocks are golden strings: they are
compared byte-for-byte, and a change to one of them is a change to what an
operator reads before deciding to migrate their account.
"""

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataporter import cli, summary
from dataporter.config import AttachmentSettings, Settings
from dataporter.exit_codes import ExitCode
from dataporter.export import load_export
from dataporter.plan import MigrationPlan, PlanTotals, build_plan

BRIEF = Path(__file__).resolve().parents[1] / "specs" / "01-initial-brief.md"
"""§9's example block, which this slice's rule is measured against."""

BRANCH = "ee000005-5555-4555-8555-555555555555"
EMPTY = "ff000006-6666-4666-8666-666666666666"
ATTACHMENT = "dd000004-4444-4444-8444-444444444444"

CHART = "q3-chart.png"
"""The fixture attachment whose bytes are not in the export."""

FIXTURE_CONTENT = (
    "Listing files",
    "Postgres",
    "Shorter loop",
    "Q3 report",
    "Naming the tool",
    "pathlib",
    "revenue",
    "`ferry` — short, and it carries things across.",
)
"""Titles and message text that exist only inside the fixture's conversations.

§10: none of it may reach stdout. Written out rather than harvested from the
export so that a fixture edit cannot quietly empty the list.
"""

BRIEF_TOTALS = PlanTotals(
    conversations=127, messages=4821, attachments=36, migratable=124, unsupported=3
)
"""The brief's §9 example numbers."""

BRIEF_BLOCK = (
    "Conversations found:    127\n"
    "Messages:             4,821\n"
    "Attachments:             36\n"
    "\n"
    "Migratable:             124\n"
    "Unsupported:              3\n"
)
"""§9, as the brief writes it since `05` amended it to the rule's bytes."""


def settings_for(attachments_dir: Path) -> Settings:
    return Settings(
        workspace=attachments_dir.parent,
        attachments=AttachmentSettings(dir=attachments_dir),
    )


def plan_of(export_dir: Path, attachments_dir: Path) -> MigrationPlan:
    return build_plan(load_export(export_dir), settings_for(attachments_dir))


def run(runner: CliRunner, *arguments: str) -> tuple[int, str, str]:
    result = runner.invoke(cli.app, list(arguments), catch_exceptions=False)
    return result.exit_code, result.stdout, result.stderr


# --------------------------------------------------------------------------- #
# Acceptance: the §9 block
# --------------------------------------------------------------------------- #


def test_the_brief_s_numbers_render_to_the_golden_block() -> None:
    assert summary.dry_run_report(BRIEF_TOTALS) == BRIEF_BLOCK


def test_the_block_is_the_brief_s_own() -> None:
    """§9 is a golden string, so the rule is checked against the brief itself.

    Every line comes back byte-for-byte: `05` amended the brief's hand-aligned
    example to the rule's bytes, and this test is what keeps the two from
    drifting apart again in either direction.
    """
    assert BRIEF_BLOCK in BRIEF.read_text(encoding="utf-8")


BRIEF_COUNTS = {"total": 127, "completed": 89, "partial": 1, "failed": 1, "pending": 36}
"""The brief's §10 example numbers. `06` prints these four lines; `18` adds the
bar and the header above them."""


def test_the_counters_are_the_brief_s_own_lines() -> None:
    """§10 is a golden string too, and its block was self-consistent from the
    start: every counter line is 13 columns, so the rule reproduces all four."""
    brief = BRIEF.read_text(encoding="utf-8").splitlines()
    rendered = summary.counters_lines(BRIEF_COUNTS)
    assert rendered == [
        "Completed: 89",
        "Partial:    1",
        "Failed:     1",
        "Pending:   36",
    ]
    assert [line for line in rendered if line in brief] == rendered
    assert {len(line) for line in rendered} == {summary.COUNTERS_MIN_WIDTH}


def test_a_six_figure_total_widens_every_counter_line() -> None:
    counters = summary.counters_lines(
        {
            "total": 200_000,
            "completed": 123_456,
            "partial": 0,
            "failed": 7,
            "pending": 1,
        }
    )
    assert counters == [
        "Completed: 123,456",
        "Partial:         0",
        "Failed:          7",
        "Pending:         1",
    ]


def test_every_line_of_the_golden_block_is_the_same_width() -> None:
    widths = {len(line) for line in BRIEF_BLOCK.splitlines() if line}
    assert widths == {summary.MIN_WIDTH}


def test_a_seven_figure_message_count_widens_every_line() -> None:
    totals = BRIEF_TOTALS.model_copy(update={"messages": 1_234_567})
    block = summary.dry_run_report(totals)
    assert block == (
        "Conversations found:       127\n"
        "Messages:            1,234,567\n"
        "Attachments:                36\n"
        "\n"
        "Migratable:                124\n"
        "Unsupported:                 3\n"
    )
    # `Conversations found:` + one space + `1,234,567`, which is wider than the
    # floor: the widest label and the widest value set it, not any one line.
    assert {len(line) for line in block.splitlines() if line} == {30}


def test_a_narrow_plan_still_gets_the_minimum_width() -> None:
    totals = PlanTotals(
        conversations=0, messages=0, attachments=0, migratable=0, unsupported=0
    )
    assert {
        len(line) for line in summary.dry_run_report(totals).splitlines() if line
    } == {summary.MIN_WIDTH}


# --------------------------------------------------------------------------- #
# Acceptance: `inspect` explains the unsupported count
# --------------------------------------------------------------------------- #


def test_inspect_prints_the_block_the_reasons_and_the_classes(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    code, out, err = run(runner, "inspect", str(export_dir))
    assert code == ExitCode.OK
    assert err == ""
    assert out == (
        "Conversations found:      6\n"
        "Messages:                50\n"
        "Attachments:              2\n"
        "\n"
        "Migratable:               5\n"
        "Unsupported:              1\n"
        "\n"
        "Unsupported reasons:\n"
        "  empty_conversation      1\n"
        "\n"
        "Attachments:\n"
        "  inline           1\n"
        "  upload           0\n"
        "  unsupported      1\n"
    )


def test_the_reasons_sum_to_the_unsupported_count(
    export_dir: Path, attachments_dir: Path
) -> None:
    plan = plan_of(export_dir, attachments_dir)
    reasons = summary.unsupported_reasons(plan)
    assert sum(count for _, count in reasons) == plan.totals.unsupported


def test_reasons_are_sorted_by_count_then_name(
    export_dir: Path, attachments_dir: Path
) -> None:
    """Two runs of the same command print the same lines, in the same order."""
    plan = plan_of(export_dir, attachments_dir)
    unmigratable = [
        item.model_copy(update={"migratable": False, "reasons": [reason]})
        for reason in ("seed_over_hard_cap", "empty_conversation", "empty_conversation")
        for item in [plan.conversations[0]]
    ]
    widened = plan.model_copy(update={"conversations": unmigratable})
    assert summary.unsupported_reasons(widened) == [
        ("empty_conversation", 2),
        ("seed_over_hard_cap", 1),
    ]
    assert (
        "Unsupported reasons:\n"
        "  empty_conversation      2\n"
        "  seed_over_hard_cap      1\n"
    ) in summary.inspect_report(widened)


def test_only_the_blocking_reason_is_counted(
    export_dir: Path, attachments_dir: Path
) -> None:
    """`reasons` continues with limitation slugs, which describe a conversation
    that *is* being migrated and would otherwise be counted as a second cause."""
    plan = plan_of(export_dir, attachments_dir)
    empty = next(item for item in plan.conversations if item.uuid == EMPTY)
    with_limitations = empty.model_copy(
        update={"reasons": ["empty_conversation", "thinking_omitted:3"]}
    )
    widened = plan.model_copy(update={"conversations": [with_limitations]})
    assert summary.unsupported_reasons(widened) == [("empty_conversation", 1)]


def test_every_attachment_class_is_listed_even_at_zero(
    export_dir: Path, attachments_dir: Path
) -> None:
    plan = plan_of(export_dir, attachments_dir)
    assert summary.attachment_classes(plan) == [
        ("inline", 1),
        ("upload", 0),
        ("unsupported", 1),
    ]


def test_the_classes_sum_to_the_attachment_total(
    export_dir: Path, attachments_dir: Path
) -> None:
    plan = plan_of(export_dir, attachments_dir)
    classes = summary.attachment_classes(plan)
    assert sum(count for _, count in classes) == plan.totals.attachments


def test_a_plan_with_nothing_unsupported_prints_no_reasons_section(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    code, out, _ = run(runner, "inspect", str(export_dir), "--json")
    assert code == ExitCode.OK
    plan = MigrationPlan.model_validate_json(out)
    migratable = [item for item in plan.conversations if item.migratable]
    without = plan.model_copy(
        update={
            "conversations": migratable,
            "totals": plan.totals.model_copy(
                update={"conversations": len(migratable), "unsupported": 0}
            ),
        }
    )
    report = summary.inspect_report(without)
    assert summary.UNSUPPORTED_REASONS_HEADER not in report
    # The attachment classes still follow the block, separated by one blank line.
    assert report.endswith(
        "\nAttachments:\n"
        "  inline           1\n"
        "  upload           0\n"
        "  unsupported      1\n"
    )


# --------------------------------------------------------------------------- #
# Acceptance: nothing is written, nothing is contacted, nothing leaks
# --------------------------------------------------------------------------- #


def test_a_dry_run_creates_no_workspace(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    code, out, _ = run(runner, "import", str(export_dir), "--dry-run")
    assert code == ExitCode.OK
    assert out.splitlines()[0] == "Conversations found:      6"
    # Not even `<workspace>/logs/`: a dry run leaves the filesystem as it found it.
    assert not (workspace / "migration").exists()
    assert list(workspace.iterdir()) == []


def test_a_dry_run_touches_nothing_that_could_reach_an_account(
    runner: CliRunner,
    workspace: Path,
    export_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `07`/`09` half of the criterion, standing in for objects that do not
    exist yet: anything that could open a socket or start a process raises."""

    def explode(*arguments: object, **keywords: object) -> None:
        raise AssertionError("a dry run contacted something")

    import socket
    import subprocess

    monkeypatch.setattr(socket.socket, "connect", explode)
    monkeypatch.setattr(subprocess, "Popen", explode)
    monkeypatch.setattr(subprocess, "run", explode)
    code, _, _ = run(runner, "import", str(export_dir), "--dry-run")
    assert code == ExitCode.OK


def test_inspect_is_byte_identical_across_runs(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    first = run(runner, "inspect", str(export_dir))
    second = run(runner, "inspect", str(export_dir))
    assert first == second


def test_neither_command_prints_a_title_or_a_message(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    """§10: no conversation content on stdout at any verbosity."""
    _, inspected, inspect_err = run(runner, "-v", "inspect", str(export_dir))
    _, dry, dry_err = run(runner, "-v", "import", str(export_dir), "--dry-run")
    for forbidden in FIXTURE_CONTENT:
        assert forbidden not in inspected + inspect_err
        assert forbidden not in dry + dry_err


def test_inspect_prints_only_labels_counts_and_slugs(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    """Stronger than the string scan: every line is one this slice owns.

    A file name is not content the way a title is, but it is export data, and the
    §9 block has no column for one — so nothing on stdout comes from the export
    at all except a reason slug and a number.
    """
    _, out, _ = run(runner, "inspect", str(export_dir))
    allowed = re.compile(
        r"^$"
        r"|^(?:Conversations found|Messages|Attachments|Migratable|Unsupported):"
        r"\s+[\d,]+$"
        r"|^(?:Unsupported reasons|Attachments):$"
        r"|^  [a-z_]+(?::\d+)?\s+[\d,]+$"
    )
    assert [line for line in out.splitlines() if not allowed.match(line)] == []


# --------------------------------------------------------------------------- #
# Selection, applied before counting
# --------------------------------------------------------------------------- #


def test_only_narrows_what_the_dry_run_counts(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    code, out, _ = run(runner, "import", str(export_dir), "--dry-run", "--only", BRANCH)
    assert code == ExitCode.OK
    assert out == (
        "Conversations found:      1\n"
        "Messages:                 4\n"
        "Attachments:              0\n"
        "\n"
        "Migratable:               1\n"
        "Unsupported:              0\n"
    )


def test_limit_truncates_in_export_order(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    code, out, _ = run(runner, "import", str(export_dir), "--dry-run", "--limit", "2")
    assert code == ExitCode.OK
    # The first two conversations of the fixture: 2 messages and 40.
    assert out.startswith("Conversations found:      2\nMessages:                42\n")


def test_the_retry_flags_widen_nothing_before_there_is_state(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    """`06` owns selection from state; with no `state.json` every conversation is
    pending, so `--retry-failed` and `--retry-partial` add nothing to add."""
    plain = run(runner, "import", str(export_dir), "--dry-run")
    retried = run(
        runner,
        "import",
        str(export_dir),
        "--dry-run",
        "--retry-failed",
        "--retry-partial",
    )
    assert plain == retried


def test_an_empty_selection_is_exit_4(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    code, out, _ = run(runner, "import", str(export_dir), "--dry-run", "--limit", "0")
    assert code == ExitCode.NOTHING_TO_DO
    assert out == ""


def test_a_negative_limit_is_a_usage_error(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    """`[:-1]` would quietly drop the last conversation instead."""
    code, _, err = run(runner, "import", str(export_dir), "--dry-run", "--limit", "-1")
    assert code == ExitCode.USAGE
    assert err == "error: --limit must not be negative\n"


def test_an_unknown_only_uuid_is_a_usage_error(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    code, _, err = run(runner, "import", str(export_dir), "--dry-run", "--only", "nope")
    assert code == ExitCode.USAGE
    assert err == "error: conversation not in export: nope\n"


# --------------------------------------------------------------------------- #
# `--attachments-dir` and `--json`
# --------------------------------------------------------------------------- #


def test_attachments_dir_moves_a_file_from_unsupported_to_upload(
    runner: CliRunner, workspace: Path, export_dir: Path, tmp_path: Path
) -> None:
    """The flag `01` gave only to `import`: without it `inspect` cannot tell
    class 2 from class 3, which is the question it exists to answer."""
    before = run(runner, "inspect", str(export_dir))[1]
    assert "  upload           0\n" in before

    elsewhere = tmp_path / "bytes"
    elsewhere.mkdir()
    (elsewhere / CHART).write_bytes(b"\x89PNG\r\n\x1a\n")
    code, after, _ = run(
        runner, "inspect", str(export_dir), "--attachments-dir", str(elsewhere)
    )
    assert code == ExitCode.OK
    assert "  upload           1\n" in after
    assert "  unsupported      0\n" in after


def test_json_prints_the_plan_and_nothing_else(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    code, out, err = run(runner, "inspect", str(export_dir), "--json")
    assert code == ExitCode.OK
    assert err == ""
    plan = MigrationPlan.model_validate_json(out)
    assert out == plan.model_dump_json(indent=2) + "\n"
    # Indented, so `plan.json` and this stream are diffable by hand.
    assert json.loads(out)["totals"]["conversations"] == 6


def test_the_json_plan_carries_the_export_fingerprint(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    """A selection narrows the conversations, never the identity of the export."""
    whole = MigrationPlan.model_validate_json(
        run(runner, "inspect", str(export_dir), "--json")[1]
    )
    assert whole.export_fingerprint == load_export(export_dir).fingerprint


def test_inspect_does_not_write_a_workspace_either(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    run(runner, "inspect", str(export_dir))
    assert list(workspace.iterdir()) == []


def test_inspect_of_a_missing_export_is_exit_2(
    runner: CliRunner, workspace: Path
) -> None:
    code, out, err = run(runner, "inspect", "./nowhere")
    assert code == ExitCode.USAGE
    assert out == ""
    assert err == "error: export not found: ./nowhere\n"


def test_an_export_with_no_conversations_inspects_to_zeros(
    runner: CliRunner, workspace: Path, tmp_path: Path
) -> None:
    """`inspect` answers a question about a file; "it holds nothing" is an answer."""
    export = tmp_path / "empty-export"
    export.mkdir()
    (export / "conversations.json").write_text("[]", encoding="utf-8")
    code, out, _ = run(runner, "inspect", str(export))
    assert code == ExitCode.OK
    assert out.startswith("Conversations found:      0\n")
    assert summary.UNSUPPORTED_REASONS_HEADER not in out
    assert out.endswith(
        "Attachments:\n"
        "  inline           0\n"
        "  upload           0\n"
        "  unsupported      0\n"
    )
