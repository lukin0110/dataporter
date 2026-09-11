"""§16's block, the records under it, and `report.json`.

`19`'s acceptance criteria are the first sections; the rest cover rules the spec
states that the brief's example does not force — the `Pending` line, the folding
of `04`'s counted slugs, an entry with no error of its own, and what `report`
does in a workspace nothing has run in.

Two things are measured rather than described. The block is compared against the
brief itself, so a change to the rule that no longer reproduces §16 fails here
and not in a pilot; and the failure and limitation blocks are compared against
the spec, which is where their columns are written down.
"""

import json
from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataporter import cli, render, report, state
from dataporter import verify as verifying
from dataporter.errors import Category
from dataporter.exit_codes import ExitCode
from dataporter.plan import PLAN_FILENAME, SKIPPED_BY_FLAG, MigrationPlan, PlanTotals
from dataporter.state import (
    AttachmentCounts,
    AttachmentDetail,
    ConversationState,
    Destination,
    ErrorRecord,
    Status,
)
from dataporter.steps import Step
from world import CONTENT, FIRST, World, cli_env

BRIEF = Path(__file__).resolve().parents[1] / "specs" / "01-initial-brief.md"
SPEC = Path(__file__).resolve().parents[1] / "specs" / "impl" / "19-report.md"
LIMITATIONS = Path(__file__).resolve().parents[1] / "docs" / "LIMITATIONS.md"

FINGERPRINT = "sha256:0123456789abcdef"

BRIEF_TOTALS = report.ReportTotals(
    source_conversations=127,
    created=124,
    partial=2,
    failed=1,
    pending=0,
    messages_represented=4_821,
    attachments_migrated=31,
    browser_actions=1_842,
    retries=17,
    human_interventions=2,
)
"""The brief's §16 example numbers."""

BRIEF_BLOCK = (
    "Claude migration complete\n"
    "\n"
    "Source conversations:        127\n"
    "Created:                     124\n"
    "Partial:                       2\n"
    "Failed:                        1\n"
    "\n"
    "Messages represented:      4,821\n"
    "Attachments migrated:         31\n"
    "\n"
    "Browser actions:           1,842\n"
    "Retries:                      17\n"
    "Human interventions:           2\n"
)
"""§16 under the one rule that reproduces its four well-formed lines.

The other five of the brief's hand-aligned example are one space narrower than
any single rule can make them; `19`'s design notes settle it, as `05`'s do for §9.
"""

WELL_FORMED = [
    "Messages represented:      4,821",
    "Attachments migrated:         31",
    "Browser actions:           1,842",
    "Retries:                      17",
]
"""The lines of §16 that are 32 columns wide in the brief itself."""

HAND_ALIGNED = [
    "Source conversations:       127",
    "Created:                    124",
    "Partial:                      2",
    "Failed:                       1",
    "Human interventions:          2",
]
"""And the five that are 31, in the brief's own narrower form."""

FAILED_GENERATION = "3f9c2a1e-0000-4000-8000-000000000001"
PARTIAL_VERIFY = "8a02c7d1-0000-4000-8000-000000000002"
FAILED_UNSUPPORTED = "c41d90aa-0000-4000-8000-000000000003"
COMPLETED = "11112222-0000-4000-8000-000000000004"
"""The spec's three failure ids, and one conversation that made it."""

FAILURES_BLOCK = (
    "Failures and partial migrations:\n"
    "  3f9c2a1e  failed    step=submit    "
    "generation: response never completed    retry=yes\n"
    "  8a02c7d1  partial   step=await     "
    "verification: ack 2/2 missing           retry=yes\n"
    "  c41d90aa  failed    step=-         "
    "unsupported: empty_conversation         retry=no\n"
)

LIMITATIONS_BLOCK = (
    "Limitations:\n"
    "  timestamps_not_preserved    124\n"
    "  thinking_omitted             41\n"
    "  branches_dropped              3\n"
    "  title_not_set                 2\n"
)


# --------------------------------------------------------------------------- #
# Building a workspace by hand
# --------------------------------------------------------------------------- #


def entry(**fields: object) -> ConversationState:
    """One `state.json` entry, defaulted to a conversation that completed."""
    return ConversationState.model_validate(
        {
            "title": "Naming the tool",
            "status": Status.COMPLETED,
            "destination": Destination(conversation_id="chat-1"),
            "messages_represented": 3,
            **fields,
        }
    )


FIXTURE_ENTRIES: dict[str, ConversationState] = {
    FAILED_GENERATION: entry(
        status=Status.FAILED,
        destination=Destination(),
        last_step=Step.SUBMIT,
        messages_represented=0,
        error=ErrorRecord(
            category=Category.GENERATION,
            detail="response never completed",
            retry_recommended=True,
        ),
    ),
    PARTIAL_VERIFY: entry(
        status=Status.PARTIAL,
        last_step=Step.AWAIT,
        messages_represented=2,
        error=ErrorRecord(
            category=Category.VERIFICATION,
            detail="ack 2/2 missing",
            retry_recommended=True,
        ),
        limitations=["timestamps_not_preserved", "title_not_set"],
    ),
    FAILED_UNSUPPORTED: entry(
        status=Status.FAILED,
        destination=Destination(),
        messages_represented=0,
        error=ErrorRecord(
            category=Category.UNSUPPORTED,
            detail="empty_conversation",
            retry_recommended=False,
        ),
    ),
    COMPLETED: entry(
        attachments=AttachmentCounts(uploaded=1, inline=1),
        limitations=["thinking_omitted:3", "timestamps_not_preserved"],
        verified_at=state.now(),
    ),
}
"""Two failures, one partial and one conversation that made it — the workspace
`19`'s second criterion describes."""


def write_plan(root: Path, *, conversations: int, attachments: int) -> None:
    """A `plan.json` with the two totals `19` reads and no conversations.

    The report takes "source conversations" and "attachments found" off
    `totals`; a per-conversation list would be fixture that nothing here reads,
    and `test_plan.py` is where the planner's own output is checked.
    """
    plan = MigrationPlan(
        export_fingerprint=FINGERPRINT,
        totals=PlanTotals(
            conversations=conversations,
            messages=12,
            attachments=attachments,
            migratable=conversations,
            unsupported=0,
        ),
    )
    state.write_atomically(root / PLAN_FILENAME, plan.model_dump_json(indent=2))


def workspace_of(
    root: Path,
    entries: Mapping[str, ConversationState] = FIXTURE_ENTRIES,
    *,
    conversations: int | None = None,
    attachments: int = 2,
    counters: Mapping[str, int] | None = None,
) -> Path:
    """The three files `report` reads, written the way a run writes them."""
    store = state.StateStore(root)
    for uuid, item in entries.items():
        store.update(uuid, **item.model_dump())
    store.bind_export(FINGERPRINT)
    for name, by in (counters or {}).items():
        store.bump_counter(name, by)
    write_plan(
        root,
        conversations=len(entries) if conversations is None else conversations,
        attachments=attachments,
    )
    return root


def actions(root: Path, records: int) -> None:
    """`records` lines in `logs/actions.jsonl`, as `08`'s helpers write them."""
    path = root / "logs" / "actions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps({"helper": "paste", "ok": True, "elapsed_ms": 1}) + "\n"
            for _ in range(records)
        ),
        encoding="utf-8",
    )


def run_cli(runner: CliRunner, *arguments: str) -> tuple[int, str, str]:
    result = runner.invoke(cli.app, list(arguments), catch_exceptions=False)
    return result.exit_code, result.stdout, result.stderr


# --------------------------------------------------------------------------- #
# Acceptance: the golden block
# --------------------------------------------------------------------------- #


def test_the_brief_s_numbers_render_to_the_golden_block() -> None:
    """`19`'s first criterion: 124 / 2 / 1 of 127, byte for byte."""
    assert report.block(BRIEF_TOTALS) == BRIEF_BLOCK


def test_the_rule_reproduces_the_well_formed_lines_of_the_brief() -> None:
    """§16 is a golden string, so the rule is measured against the brief itself.

    Four lines come back byte-for-byte. The other five are hand-aligned one
    column narrower than any single rule can make them, and `19`'s design notes
    treat them as typos — this test is where that is visible rather than buried
    in prose.
    """
    brief = BRIEF.read_text(encoding="utf-8").splitlines()
    rendered = report.block(BRIEF_TOTALS).splitlines()
    assert [line for line in rendered if line and line in brief] == [
        "Claude migration complete",
        *WELL_FORMED,
    ]
    for typo in HAND_ALIGNED:
        assert typo in brief


def test_every_line_of_the_block_is_the_same_width() -> None:
    lines = [line for line in report.block(BRIEF_TOTALS).splitlines() if line]
    assert {len(line) for line in lines[1:]} == {report.MIN_WIDTH}


def test_a_six_figure_count_widens_the_block_past_its_floor() -> None:
    """`MIN_WIDTH` is a floor, not a field: a bigger export widens every line
    rather than losing a separator."""
    totals = BRIEF_TOTALS.model_copy(update={"browser_actions": 123_456_789})
    lines = [line for line in report.block(totals).splitlines() if line][1:]
    assert {len(line) for line in lines} == {33}
    assert "Browser actions:      123,456,789" in lines


# --------------------------------------------------------------------------- #
# Acceptance: the failures section
# --------------------------------------------------------------------------- #


def test_the_fixture_renders_the_failures_section_exactly(tmp_path: Path) -> None:
    """`19`'s second criterion: two failures and one partial, as the spec writes
    them — and the spec is checked against the same bytes, because that block is
    where these columns are written down."""
    built = report.build(workspace_of(tmp_path))

    rendered = "".join(f"{line}\n" for line in report.failure_lines(built.failures))
    assert rendered == FAILURES_BLOCK
    spec = SPEC.read_text(encoding="utf-8")
    for line in FAILURES_BLOCK.splitlines()[1:]:
        assert f"  {line}" in spec


def test_the_failure_list_is_partial_and_failed_in_state_order(
    tmp_path: Path,
) -> None:
    built = report.build(workspace_of(tmp_path))
    assert [record.short_id for record in built.failures] == [
        "3f9c2a1e",
        "8a02c7d1",
        "c41d90aa",
    ]
    assert [record.status for record in built.failures] == [
        Status.FAILED,
        Status.PARTIAL,
        Status.FAILED,
    ]


def test_a_failure_carries_the_chat_it_left_behind(tmp_path: Path) -> None:
    """§16 asks for the source conversation; `16`'s partial also has a
    destination one, and an operator's next move is to go and look at it."""
    built = report.build(workspace_of(tmp_path))
    records = {record.short_id: record for record in built.failures}
    assert records["8a02c7d1"].destination_conversation_id == "chat-1"
    assert records["3f9c2a1e"].destination_conversation_id is None
    assert records["8a02c7d1"].uuid == PARTIAL_VERIFY


def test_an_entry_with_no_error_of_its_own_renders_a_dash(tmp_path: Path) -> None:
    """The `partial` crash recovery leaves behind: a chat exists, nothing said
    why. A dash says the file holds no reason rather than inventing one, and
    `retry=unknown` says nobody decided."""
    entries = {PARTIAL_VERIFY: entry(status=Status.PARTIAL, error=None)}
    built = report.build(workspace_of(tmp_path, entries))

    line = report.failure_lines(built.failures)[1]
    assert line.endswith("step=-         -    retry=unknown")
    assert built.failures[0].category is None


def test_the_step_column_says_dash_when_no_step_was_reached(tmp_path: Path) -> None:
    built = report.build(workspace_of(tmp_path))
    assert "step=-" in report.failure_lines(built.failures)[3]


def test_a_report_with_no_failures_has_no_failures_section(tmp_path: Path) -> None:
    """An empty list under a header is a question an operator has to answer."""
    built = report.build(workspace_of(tmp_path, {COMPLETED: entry()}))
    assert built.failures == []
    assert report.FAILURES_HEADER not in report.render(built)


# --------------------------------------------------------------------------- #
# Acceptance: the same bytes twice, and through JSON
# --------------------------------------------------------------------------- #


def test_two_invocations_print_the_same_bytes(tmp_path: Path) -> None:
    """`generated_at` differs between them and is not in the block, which is
    what lets a report be diffed against the one taken yesterday."""
    root = workspace_of(tmp_path)
    first, second = report.build(root), report.build(root)
    assert report.render(first) == report.render(second)
    assert first.generated_at <= second.generated_at


def test_the_text_survives_a_json_round_trip(tmp_path: Path) -> None:
    """`19`'s third criterion, and the reason the text is derived from a model:
    `report --json` and `report` are two renderings of one object."""
    built = report.build(workspace_of(tmp_path))
    again = report.Report.model_validate_json(built.model_dump_json())
    assert again == built
    assert report.render(again) == report.render(built)


def test_the_command_prints_the_same_bytes_as_the_model(
    runner: CliRunner, tmp_path: Path
) -> None:
    root = workspace_of(tmp_path)
    code, out, _ = run_cli(runner, "--workspace", str(root), "report")
    assert code == ExitCode.OK
    assert out == report.render(report.build(root))


def test_report_json_prints_the_model(runner: CliRunner, tmp_path: Path) -> None:
    root = workspace_of(tmp_path)
    code, out, _ = run_cli(runner, "--workspace", str(root), "report", "--json")
    assert code == ExitCode.OK
    assert report.render(report.Report.model_validate_json(out)) == report.render(
        report.build(root)
    )


def test_the_command_writes_nothing(runner: CliRunner, tmp_path: Path) -> None:
    """`report` answers a question about a workspace; `import` is what writes
    `report.json`, under the lock."""
    root = workspace_of(tmp_path)
    before = sorted(path.name for path in root.iterdir())
    run_cli(runner, "--workspace", str(root), "report")
    assert sorted(path.name for path in root.iterdir()) == before
    assert report.REPORT_FILENAME not in before


# --------------------------------------------------------------------------- #
# Acceptance: the identities
# --------------------------------------------------------------------------- #


def test_the_four_statuses_account_for_every_source_conversation(
    tmp_path: Path,
) -> None:
    """`19`'s fourth criterion, on the fixture. `Pending` is the remainder, so a
    conversation `--limit` never reached is counted without an entry."""
    totals = report.build(workspace_of(tmp_path, conversations=7)).totals
    assert totals.source_conversations == 7
    assert (
        totals.created + totals.partial + totals.failed + totals.pending
        == totals.source_conversations
    )
    assert totals.pending == 3


def test_the_attachment_counts_reconcile_with_the_plan(tmp_path: Path) -> None:
    """`16`'s identity: every file the plan found is in exactly one outcome."""
    entries = {
        COMPLETED: entry(
            attachments=AttachmentCounts(
                uploaded=1,
                inline=1,
                unsupported=1,
                failed=1,
                detail=[
                    AttachmentDetail(
                        file_name="q3-chart.png",
                        klass="unsupported",
                        reason=SKIPPED_BY_FLAG,
                    ),
                    AttachmentDetail(file_name="notes.pdf", klass="failed", reason="x"),
                ],
            )
        )
    }
    attachments = report.build(
        workspace_of(tmp_path, entries, attachments=4)
    ).attachments
    assert (
        attachments.inline
        + attachments.uploaded
        + attachments.unsupported
        + attachments.failed
        == attachments.found
    )
    # `skipped` reads the detail rather than the flag: it is the subset of
    # `unsupported` an operator asked for, not a fifth outcome.
    assert attachments.skipped == 1


def test_attachments_migrated_is_what_is_in_the_new_chat(tmp_path: Path) -> None:
    """Uploads and inlined text both reached the destination; the other two did
    not, and the block says "migrated"."""
    totals = report.build(workspace_of(tmp_path)).totals
    assert totals.attachments_migrated == 2


def test_messages_represented_counts_the_conversations_that_landed(
    tmp_path: Path,
) -> None:
    """Completed and partial: a failed conversation represents nothing, however
    many messages the export had for it."""
    totals = report.build(workspace_of(tmp_path)).totals
    assert totals.messages_represented == 5


# --------------------------------------------------------------------------- #
# The `Pending` line
# --------------------------------------------------------------------------- #


def test_pending_is_printed_after_failed_when_there_is_any(tmp_path: Path) -> None:
    lines = report.block(report.build(workspace_of(tmp_path, conversations=7)).totals)
    failed = next(line for line in lines.splitlines() if line.startswith("Failed:"))
    assert f"{failed}\nPending:" in lines
    assert lines.splitlines()[-1].startswith("Human interventions:")


def test_pending_is_left_out_when_it_is_zero(tmp_path: Path) -> None:
    """A finished migration that printed `Pending: 0` would invite the question
    the line exists to answer."""
    built = report.build(workspace_of(tmp_path))
    assert built.totals.pending == 0
    assert report.PENDING_LABEL not in report.render(built)


# --------------------------------------------------------------------------- #
# Limitations
# --------------------------------------------------------------------------- #


def test_the_limitation_block_is_the_spec_s_own(tmp_path: Path) -> None:
    counts = {
        "timestamps_not_preserved": 124,
        "thinking_omitted": 41,
        "branches_dropped": 3,
        "title_not_set": 2,
    }
    rendered = "".join(f"{line}\n" for line in report.limitation_lines(counts))
    assert rendered == LIMITATIONS_BLOCK
    spec = SPEC.read_text(encoding="utf-8")
    for line in LIMITATIONS_BLOCK.splitlines()[1:]:
        assert f"  {line}" in spec


def test_a_counted_slug_is_folded_to_its_name(tmp_path: Path) -> None:
    """`04` writes `thinking_omitted:3` against one conversation. The column
    counts conversations, so the number stays in `state.json`."""
    built = report.build(workspace_of(tmp_path))
    assert built.limitations == {
        "timestamps_not_preserved": 2,
        "thinking_omitted": 1,
        "title_not_set": 1,
    }


def test_one_conversation_counts_once_per_limitation(tmp_path: Path) -> None:
    """Two spellings of one limitation on one conversation are one conversation.

    `17` merges its own slugs into `04`'s and would not write both, but a
    workspace an older build wrote can hold both, and a count that read 2 for one
    chat would be a column meaning two things.
    """
    entries = {
        COMPLETED: entry(limitations=["thinking_omitted:3", "thinking_omitted:1"])
    }
    assert report.build(workspace_of(tmp_path, entries)).limitations == {
        "thinking_omitted": 1
    }


def test_limitations_sort_by_count_then_name(tmp_path: Path) -> None:
    """Ties break on the name, so two reports of one workspace are one file."""
    entries = {
        COMPLETED: entry(limitations=["zebra", "alpha", "common"]),
        FIRST: entry(limitations=["common"]),
    }
    built = report.build(workspace_of(tmp_path, entries))
    assert list(built.limitations) == ["common", "alpha", "zebra"]


def test_a_report_with_no_limitations_has_no_limitations_section(
    tmp_path: Path,
) -> None:
    built = report.build(workspace_of(tmp_path, {COMPLETED: entry()}))
    assert report.LIMITATIONS_HEADER not in report.render(built)


def test_every_limitation_name_is_written_down(tmp_path: Path) -> None:
    """The spec's rule: each name the code can produce has an entry in
    `docs/LIMITATIONS.md`, so a slug in a report is a slug an operator can look
    up."""
    names = [field.name for field in fields(render.Limitations)] + [
        verifying.TIMESTAMPS_NOT_PRESERVED,
        verifying.TITLE_NOT_SET,
    ]
    written = LIMITATIONS.read_text(encoding="utf-8")
    for name in names:
        assert f"**`{name}`**" in written, name


# --------------------------------------------------------------------------- #
# Browser actions, retries, interventions
# --------------------------------------------------------------------------- #


def test_browser_actions_counts_the_records_our_helpers_wrote(
    tmp_path: Path,
) -> None:
    root = workspace_of(tmp_path, counters={"browser_actions": 4})
    actions(root, 9)
    assert report.build(root).totals.browser_actions == 9


def test_a_truncated_actions_log_falls_back_to_the_counter(tmp_path: Path) -> None:
    """`run.json` counted the same lines as they were written, so a log that was
    rotated cannot make a run look idler than it was."""
    root = workspace_of(tmp_path, counters={"browser_actions": 1_842})
    actions(root, 2)
    assert report.build(root).totals.browser_actions == 1_842


def test_a_workspace_with_no_actions_log_reports_none(tmp_path: Path) -> None:
    assert report.build(workspace_of(tmp_path)).totals.browser_actions == 0


def test_the_run_counters_are_read_from_run_json(tmp_path: Path) -> None:
    root = workspace_of(tmp_path, counters={"retries": 17, "human_interventions": 2})
    totals = report.build(root).totals
    assert (totals.retries, totals.human_interventions) == (17, 2)


def test_the_runs_are_carried_into_the_json(tmp_path: Path) -> None:
    """`20` reads them: how many invocations it took, and what each one asked
    for."""
    root = workspace_of(tmp_path)
    store = state.StateStore(root)
    index = store.start_run(state.Selection(limit=2, uuids=[COMPLETED]))
    store.finish_run(index, int(ExitCode.OK))

    built = report.build(root)
    assert [record.exit_code for record in built.runs] == [int(ExitCode.OK)]
    assert built.runs[0].selection.limit == 2
    assert built.export_fingerprint == FINGERPRINT


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #


def test_verification_counts_over_the_chats_that_exist(tmp_path: Path) -> None:
    """The population is the conversations with a destination id: one that never
    landed has nothing to read back. `not_run` is the remainder, so the three
    sum to it."""
    built = report.build(workspace_of(tmp_path))
    assert built.verification == {"verified": 1, "failed": 1, "not_run": 0}
    assert sum(built.verification.values()) == 2


def test_a_chat_nothing_checked_is_not_a_failed_check(tmp_path: Path) -> None:
    """A `completed` entry from a build that did not verify, and the `partial` a
    crash left: neither is a verification that failed."""
    entries = {
        COMPLETED: entry(),
        PARTIAL_VERIFY: entry(status=Status.PARTIAL, error=None),
    }
    built = report.build(workspace_of(tmp_path, entries))
    assert built.verification == {"verified": 0, "failed": 0, "not_run": 2}


def test_a_failure_of_its_own_is_counted_under_its_own_category(
    tmp_path: Path,
) -> None:
    """`17` writes a `verification` error only where the run left no reason, so
    a chat that failed a step and then its check is reported under the step."""
    entries = {
        PARTIAL_VERIFY: entry(
            status=Status.PARTIAL,
            error=ErrorRecord(category=Category.SAFETY, detail="off the surface"),
        )
    }
    built = report.build(workspace_of(tmp_path, entries))
    assert built.verification["failed"] == 0
    assert built.failures[0].category is Category.SAFETY


# --------------------------------------------------------------------------- #
# A workspace nothing has run in
# --------------------------------------------------------------------------- #


def test_report_without_a_plan_exits_2(runner: CliRunner, tmp_path: Path) -> None:
    """A report is about a run, and a workspace with no plan has not had one."""
    code, out, err = run_cli(runner, "--workspace", str(tmp_path), "report")
    assert code == ExitCode.USAGE
    assert err == f"error: no plan.json in {tmp_path} — run `import` first\n"
    assert out == ""


def test_an_unreadable_plan_is_reported_as_one(tmp_path: Path) -> None:
    workspace_of(tmp_path)
    (tmp_path / PLAN_FILENAME).write_text('{"totals": {}}', encoding="utf-8")
    with pytest.raises(state.StateError) as raised:
        report.build(tmp_path)
    assert str(raised.value).startswith(f"invalid {PLAN_FILENAME}")


def test_a_workspace_from_another_schema_stops_the_command(
    runner: CliRunner, tmp_path: Path
) -> None:
    """`run.json` is read before anything is printed, like `status`: a workspace
    a different build wrote is a version mismatch, not half a report."""
    workspace_of(tmp_path)
    (tmp_path / state.RUN_FILENAME).write_text(
        json.dumps({"schema_version": 99}), encoding="utf-8"
    )
    code, out, err = run_cli(runner, "--workspace", str(tmp_path), "report")
    assert code == ExitCode.USAGE
    assert "state schema" in err
    assert out == ""


# --------------------------------------------------------------------------- #
# On a real run
# --------------------------------------------------------------------------- #


def test_import_writes_the_report_and_prints_it_last(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The block `18` prints is the run's progress; this is its account."""
    cli_env(world, monkeypatch)

    code, out, _ = run_cli(runner, "import", str(world.export), "--limit", "1")

    assert code == ExitCode.OK
    written = world.settings.workspace / report.REPORT_FILENAME
    built = report.Report.model_validate_json(written.read_text(encoding="utf-8"))
    assert out.endswith(report.render(built))
    assert report.render(built) == report.render(report.build(world.settings.workspace))


def test_quiet_keeps_the_report(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`-q` suppresses progress, and this is what the run amounts to."""
    cli_env(world, monkeypatch)

    _, out, _ = run_cli(runner, "-q", "import", str(world.export), "--limit", "1")

    assert report.TITLE in out


def test_the_identities_hold_on_a_real_run(world: World) -> None:
    """`19`'s fourth criterion again, on a run of the fixture export rather than
    on a workspace a test wrote.

    The whole export, because that is what the attachment identity needs: `16`'s
    four counts sum to what the plan found *for a conversation that has been
    attempted*, so a run that stopped short leaves the files of everything still
    pending on the other side of it — see the test below.
    """
    world.run()

    built = report.build(world.settings.workspace)
    totals, attachments = built.totals, built.attachments
    assert totals.source_conversations == 6
    assert totals.pending == 0
    assert (
        totals.created + totals.partial + totals.failed + totals.pending
        == totals.source_conversations
    )
    assert (
        attachments.inline
        + attachments.uploaded
        + attachments.unsupported
        + attachments.failed
        == attachments.found
    )
    assert totals.browser_actions > 0


def test_a_run_that_stopped_short_has_not_accounted_for_every_file(
    world: World,
) -> None:
    """The other half of the identity, so that it is a rule rather than a
    coincidence of the fixture: a conversation nothing has attempted has all
    four of its counts at zero, and the difference is exactly its planned
    files."""
    world.run(limit=2)

    attachments = report.build(world.settings.workspace).attachments
    assert attachments.found == 2
    assert (
        attachments.inline
        + attachments.uploaded
        + attachments.unsupported
        + attachments.failed
        == 0
    )


def test_no_content_reaches_the_report(world: World) -> None:
    """`19`'s fifth criterion. `state.json` holds the titles — §7 puts them
    there — and neither the text nor the JSON carries one."""
    world.run(limit=2)

    built = report.build(world.settings.workspace)
    written = (world.settings.workspace / "state.json").read_text(encoding="utf-8")
    for phrase in CONTENT:
        assert phrase not in report.render(built)
        assert phrase not in built.model_dump_json()
    # The fixture really does put a title in the workspace: the report is not
    # clean because nothing was there to leak.
    assert any(phrase in written for phrase in CONTENT)


def test_a_failed_conversation_is_reported_with_its_reason(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fixture's unmigratable conversation, through the whole loop: `12`
    records it as `failed` with `03`'s reason, and §16's record is that line."""
    cli_env(world, monkeypatch)

    _, out, _ = run_cli(runner, "import", str(world.export), "--limit", "6")

    built = report.build(world.settings.workspace)
    unsupported = [
        record for record in built.failures if record.category is Category.UNSUPPORTED
    ]
    assert unsupported and unsupported[0].retry_recommended is False
    assert report.FAILURES_HEADER in out
