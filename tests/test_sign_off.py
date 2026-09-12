"""`21`'s instruments, held to the rule they exist to enforce.

The gate, the metrics, the drill and the safety audit all answer questions about
a run nobody here has made, so what is testable is the arithmetic and the
refusals — and those are exactly what a sign-off depends on. A gate that scored
`90 %` where the run created nine chats in ten but two of them were the same
chat would wave through a full run nobody could report on.

The workspace is built by hand, as `test_report.py` builds one: `state.json`,
`run.json` and `plan.json`, written the way a run writes them, plus the two
files only this module reads — the run log that remembers which conversation a
person was asked about, and a Chrome `History` database with four URLs in it.

Nothing here spawns a process or opens a browser, so nothing here is `slow`.
"""

import sqlite3
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from dataporter import state
from dataporter.exit_codes import ExitCode
from dataporter.plan import PLAN_FILENAME, MigrationPlan, PlanTotals
from dataporter.state import (
    ConversationState,
    Destination,
    PauseRecord,
    Status,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "spikes"))

import sign_off  # noqa: E402  — after the path insert, as `10`'s scripts are

FINGERPRINT = "0" * 64

FIRST = "11112222-0000-4000-8000-000000000001"
SECOND = "33334444-0000-4000-8000-000000000002"
THIRD = "55556666-0000-4000-8000-000000000003"


# --------------------------------------------------------------------------- #
# A workspace, by hand
# --------------------------------------------------------------------------- #


def entry(**fields: object) -> ConversationState:
    """One entry, defaulted to a conversation that completed unattended."""
    return ConversationState.model_validate(
        {
            "status": Status.COMPLETED,
            "destination": Destination(conversation_id="chat-1"),
            "attempts": 1,
            "chunks_acked": 2,
            "chunks_total": 2,
            "messages_represented": 4,
            **fields,
        }
    )


DEFAULT_ENTRIES: dict[str, ConversationState] = {
    FIRST: entry(),
    SECOND: entry(destination=Destination(conversation_id="chat-2"), attempts=2),
    THIRD: entry(
        status=Status.FAILED,
        destination=Destination(),
        chunks_acked=0,
        chunks_total=2,
        messages_represented=0,
    ),
}


def workspace_of(
    root: Path,
    entries: Mapping[str, ConversationState] = DEFAULT_ENTRIES,
    *,
    conversations: int | None = None,
    attachments: int = 0,
    counters: Mapping[str, int] | None = None,
    runs: int = 1,
    fingerprint: str = FINGERPRINT,
) -> Path:
    """The three files every subcommand reads, plus a finished run record."""
    store = state.StateStore(root)
    for uuid, item in entries.items():
        store.update(uuid, **item.model_dump())
    store.bind_export(fingerprint)
    for name, by in (counters or {}).items():
        store.bump_counter(name, by)
    for _ in range(runs):
        store.finish_run(store.start_run(state.Selection()), int(ExitCode.OK))
    plan = MigrationPlan(
        export_fingerprint=fingerprint,
        totals=PlanTotals(
            conversations=len(entries) if conversations is None else conversations,
            messages=12,
            attachments=attachments,
            migratable=len(entries),
            unsupported=0,
        ),
    )
    state.write_atomically(root / PLAN_FILENAME, plan.model_dump_json(indent=2))
    return root


def opened(root: Path) -> sign_off.Workspace:
    return sign_off.open_workspace(root)


def named(checks: list[sign_off.Check], name: str) -> sign_off.Check:
    """One row of a check block, by name rather than by position.

    By name because `safety`'s rows are a fixed list a reviewer can read off
    `SAFETY_CHECKS`, and a test that indexed them would have to be renumbered
    every time a row is added — which is how a row stops being checked.
    """
    found = [check for check in checks if check.name == name]
    assert len(found) == 1, f"{name}: {len(found)} rows"
    return found[0]


def log_line(root: Path, **fields: object) -> None:
    """One record in a run log, as `log.JsonlFormatter` writes it."""
    path = root / "logs" / "run-20260101T000000Z.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(state.json.dumps({"ts": "2026-01-01T00:00:00Z", **fields}) + "\n")


def seed_part(root: Path, uuid: str, index: int, chars: int) -> None:
    directory = root / "seeds" / uuid
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"part-{index:02d}.txt").write_text("x" * chars, encoding="utf-8")


def verdicts(root: Path, *scores: str) -> None:
    """A `pilot/probes.json` with one judged probe per score."""
    probes = [
        {
            "conversation_uuid": f"{position}",
            "short_id": f"id-{position}",
            "conversation_id": f"chat-{position}",
            "outcome": "answered",
            "reply": "a reply",
            "asked_at": "2026-01-01T00:00:00Z",
            "verdict": {"score": score, "reason": "because", "model": "m"},
        }
        for position, score in enumerate(scores)
    ]
    path = root / "pilot" / "probes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        state.json.dumps({"question": "What did we discuss?", "probes": probes}),
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- #
# Reading the workspace
# --------------------------------------------------------------------------- #


def test_a_workspace_with_no_plan_is_a_usage_error(tmp_path: Path) -> None:
    """`report.read_plan`'s rule, and the only way in: a directory nothing has
    run in has no numbers, and inventing zeros would read like a finished run."""
    assert sign_off.main(["gate", "--workspace", str(tmp_path)]) == ExitCode.USAGE


def test_it_reads_the_four_files(tmp_path: Path) -> None:
    workspace = opened(workspace_of(tmp_path))

    assert workspace.report.totals.source_conversations == 3
    assert workspace.report.totals.created == 2
    assert len(workspace.run.runs) == 1


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #


def test_question_one_counts_chats_against_attempts(tmp_path: Path) -> None:
    """Two of three attempted conversations have a chat: below the threshold,
    and therefore a no-go rather than a number somebody has to interpret."""
    checks = sign_off.gate(opened(workspace_of(tmp_path)), failures_understood=False)

    assert checks[0].number == "66.7%"
    assert checks[0].terms == "2 ÷ 3"
    assert checks[0].verdict == sign_off.NO_GO


def test_question_one_passes_when_every_attempt_landed(tmp_path: Path) -> None:
    entries = {
        FIRST: entry(),
        SECOND: entry(destination=Destination(conversation_id="c")),
    }
    checks = sign_off.gate(
        opened(workspace_of(tmp_path, entries)), failures_understood=False
    )

    assert checks[0].verdict == sign_off.GO
    assert checks[0].number == "100.0%"


def test_a_conversation_never_attempted_is_in_neither_term(tmp_path: Path) -> None:
    """`attempts == 0` is a conversation the run did not reach. Counting it as a
    failure to create a chat would make `--limit` look like a fault."""
    entries = {FIRST: entry(), SECOND: entry(status=Status.PENDING, attempts=0)}
    checks = sign_off.gate(
        opened(workspace_of(tmp_path, entries)), failures_understood=False
    )

    assert checks[0].terms == "1 ÷ 1"


def test_question_two_leaves_out_the_parts_it_does_not_cover(tmp_path: Path) -> None:
    """`21` sets question 2's threshold "for parts under 50 k characters", so a
    conversation with a bigger part is in neither term — and is named, because a
    part nobody has a threshold for is the write-up's business."""
    root = workspace_of(tmp_path)
    seed_part(root, FIRST, 1, 1_000)
    seed_part(root, FIRST, 2, 1_000)
    seed_part(root, SECOND, 1, sign_off.BIG_PART_CHARS + 1)
    seed_part(root, THIRD, 1, 2_000)
    seed_part(root, THIRD, 2, 2_000)
    workspace = opened(root)

    assert sign_off.small_part_acks(workspace) == sign_off.Number(2, 4)
    assert sign_off.big_part_conversations(workspace) == ["33334444"]


def test_part_sizes_fall_back_to_the_plan(tmp_path: Path) -> None:
    """A workspace whose seeds were cleaned up still has `plan.json`'s estimate,
    which is an average — enough to bucket a conversation, and said so."""
    root = tmp_path
    plan = MigrationPlan(
        export_fingerprint=FINGERPRINT,
        totals=PlanTotals(
            conversations=1, messages=1, attachments=0, migratable=1, unsupported=0
        ),
        conversations=[
            {
                "uuid": FIRST,
                "migratable": True,
                "message_count": 4,
                "off_path_count": 0,
                "estimated_seed_chars": 9_000,
                "chunk_count": 3,
            }
        ],
    )
    workspace_of(root, {FIRST: entry()})
    state.write_atomically(root / PLAN_FILENAME, plan.model_dump_json(indent=2))

    assert sign_off.part_sizes(opened(root), FIRST) == [3_000, 3_000, 3_000]


def test_question_three_is_unknown_until_somebody_grades(tmp_path: Path) -> None:
    """The hand grades live in the write-up, and the one in this repo is still
    the unrun template. No grades is not "no failures"."""
    checks = sign_off.gate(opened(workspace_of(tmp_path)), failures_understood=False)

    assert checks[2].verdict == sign_off.UNKNOWN
    assert sign_off.hand_grades() == []


def test_hand_grades_are_read_out_of_the_table(tmp_path: Path) -> None:
    document = tmp_path / "experiment.md"
    document.write_text(
        "## Semantic probe grades\n"
        "\n"
        "| Conversation | Hand grade | Why | Judge | Mark |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| `11112222` | pass | recalls it | pass | *measured on 2026-01-01* |\n"
        "| `33334444` | fail | about nothing | weak | *measured on 2026-01-01* |\n"
        "\n"
        "## Next\n"
        "| — | — | — | — | — |\n",
        encoding="utf-8",
    )

    assert sign_off.hand_grades(document) == [
        ("11112222", "pass"),
        ("33334444", "fail"),
    ]


def test_one_fail_grade_is_a_no_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = tmp_path / "experiment.md"
    document.write_text(
        "## Semantic probe grades\n"
        "| Conversation | Hand grade |\n"
        "| --- | --- |\n"
        "| `11112222` | fail |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sign_off, "EXPERIMENT_01", document)
    checks = sign_off.gate(opened(workspace_of(tmp_path)), failures_understood=False)

    assert checks[2].verdict == sign_off.NO_GO


def test_the_failure_row_needs_a_person_to_say_the_reasons_are_understood(
    tmp_path: Path,
) -> None:
    """ "Every `Failures` line understood" is a judgement, so the gate refuses to
    make it: it stays `unknown` until the operator passes the flag that says a
    reason has been written down."""
    workspace = opened(workspace_of(tmp_path))

    assert sign_off.gate(workspace, failures_understood=False)[3].verdict == (
        sign_off.UNKNOWN
    )
    assert sign_off.gate(workspace, failures_understood=True)[3].verdict == sign_off.GO


def test_a_run_with_no_failures_needs_no_such_promise(tmp_path: Path) -> None:
    entries = {FIRST: entry()}
    checks = sign_off.gate(
        opened(workspace_of(tmp_path, entries)), failures_understood=False
    )

    assert checks[3].verdict == sign_off.GO


def test_the_gate_command_exits_one_when_a_row_blocks(tmp_path: Path) -> None:
    workspace_of(tmp_path)

    assert sign_off.main(["gate", "--workspace", str(tmp_path)]) == ExitCode.FAILED


# --------------------------------------------------------------------------- #
# The primary metric
# --------------------------------------------------------------------------- #


def test_the_primary_metric_is_completed_first_time_and_unpaused(
    tmp_path: Path,
) -> None:
    """Three conversations: one clean, one that took two attempts, one failed."""
    assert sign_off.unattended(opened(workspace_of(tmp_path))) == sign_off.Number(1, 3)


def test_a_conversation_a_person_was_asked_about_is_not_unattended(
    tmp_path: Path,
) -> None:
    """Even on the first attempt: the pause is the intervention, and `run.json`
    has forgotten it by the time `resume` finishes. The run log has not."""
    root = workspace_of(tmp_path, {FIRST: entry()})
    log_line(
        root,
        event=sign_off.INTERVENTION_EVENT,
        conversation_id="11112222",
        reason="captcha",
    )

    assert sign_off.unattended(opened(root)) == sign_off.Number(0, 1)


def test_an_open_pause_counts_too(tmp_path: Path) -> None:
    """A run that is still paused has no log line for it in a finished file yet,
    and `run.json` is where that ask lives."""
    root = workspace_of(tmp_path, {FIRST: entry()})
    store = state.StateStore(root)
    store.set_paused(
        PauseRecord(conversation_uuid=FIRST, reason="auth_required", since=state.now())
    )

    assert sign_off.unattended(opened(root)) == sign_off.Number(0, 1)


def test_a_half_written_log_line_is_skipped(tmp_path: Path) -> None:
    """The drill kills the process mid-run, so the last line of a log is
    routinely half a record. That is not a reason to refuse to report."""
    root = workspace_of(tmp_path, {FIRST: entry()})
    path = root / "logs" / "run-20260101T000000Z.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"event": "retry", "conversation_id": "1111', encoding="utf-8")

    assert sign_off.unattended(opened(root)) == sign_off.Number(1, 1)


# --------------------------------------------------------------------------- #
# The metrics table
# --------------------------------------------------------------------------- #


def test_every_19_metric_has_a_row(tmp_path: Path) -> None:
    """Written out here as well as in `METRIC_NAMES`, so that renaming a metric
    is a change somebody makes on purpose — `test_scale_up_doc.py` checks the
    same tuple against the write-up, and the three have to agree."""
    rows = sign_off.metrics(opened(workspace_of(tmp_path)), recoveries=None)

    assert [row.name for row in rows] == list(sign_off.METRIC_NAMES)
    assert list(sign_off.METRIC_NAMES) == [
        "Primary: migrated without human intervention",
        "semantic fidelity",
        "migration speed",
        "browser reliability",
        "recovery rate",
        "attachment coverage",
        "manual interventions",
    ]


def test_the_primary_row_carries_its_two_terms(tmp_path: Path) -> None:
    """`21`: the primary metric is "stated as a percentage with its numerator and
    denominator"."""
    rows = sign_off.metrics(opened(workspace_of(tmp_path)), recoveries=None)

    assert rows[0].number == "33.3%"
    assert rows[0].terms == "1 ÷ 3"


def test_fidelity_is_unmeasured_without_a_verdict(tmp_path: Path) -> None:
    rows = sign_off.metrics(opened(workspace_of(tmp_path)), recoveries=None)

    assert rows[1].number == sign_off.UNMEASURED
    assert "grade the sample" in rows[1].note


def test_fidelity_counts_the_judge_s_verdicts(tmp_path: Path) -> None:
    root = workspace_of(tmp_path)
    verdicts(root, "pass", "pass", "weak")
    rows = sign_off.metrics(opened(root), recoveries=None)

    assert rows[1].number == "66.7%"
    assert rows[1].terms == "2 ÷ 3"


def test_browser_reliability_says_what_it_is_missing(tmp_path: Path) -> None:
    """The in-run recovery rows are only in a transcript, so the denominator is
    incomplete until somebody counts them. It prints `—`, not the half it has."""
    workspace = opened(workspace_of(tmp_path, counters={"retries": 4}))

    assert sign_off.metrics(workspace, recoveries=None)[3].number == (
        sign_off.UNMEASURED
    )
    assert sign_off.metrics(workspace, recoveries=6)[3].terms == "0 ÷ 10"


def test_recovery_rate_counts_only_the_conversations_that_needed_one(
    tmp_path: Path,
) -> None:
    """`SECOND` took two attempts and completed; nothing else needed anything."""
    rows = sign_off.metrics(opened(workspace_of(tmp_path)), recoveries=None)

    assert rows[4].terms == "1 ÷ 1"
    assert rows[4].number == "100.0%"


def test_speed_is_summed_over_finished_sessions(tmp_path: Path) -> None:
    root = workspace_of(tmp_path)
    store = state.StateStore(root)
    run = store.run()
    assert run.runs[0].ended is not None
    assert sign_off.elapsed_hours(run) >= 0


def test_an_unfinished_session_contributes_no_time(tmp_path: Path) -> None:
    """The session a SIGKILL ended has no `ended`, and a duration this script
    guessed for it would be the drill's own damage reported as speed."""
    root = workspace_of(tmp_path)
    store = state.StateStore(root)
    store.start_run(state.Selection())

    assert sign_off.elapsed_hours(store.run()) == sign_off.elapsed_hours(
        state.StateStore(root).run()
    )


def test_intervention_reasons_are_counted_by_name(tmp_path: Path) -> None:
    root = workspace_of(tmp_path, counters={"human_interventions": 2})
    log_line(
        root,
        event=sign_off.INTERVENTION_EVENT,
        conversation_id="11112222",
        reason="captcha",
    )
    log_line(
        root,
        event=sign_off.INTERVENTION_EVENT,
        conversation_id="33334444",
        reason="captcha",
    )
    rows = sign_off.metrics(opened(root), recoveries=None)

    assert rows[6].number == "2"
    assert rows[6].note == "captcha 2"


def test_the_run_logs_are_parsed_once_per_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three rows need what the logs remember, and a workspace of a thousand
    conversations has one log per session: reading them per conversation is what
    would make this command unusable on the run it is for. (Raised by Copilot in
    review on #30.)"""
    root = workspace_of(tmp_path)
    log_line(
        root,
        event=sign_off.INTERVENTION_EVENT,
        conversation_id="11112222",
        reason="captcha",
    )
    reads = 0
    original = sign_off.log_records

    def counted(workspace: Path) -> object:
        nonlocal reads
        reads += 1
        return original(workspace)

    monkeypatch.setattr(sign_off, "log_records", counted)
    rows = sign_off.metrics(opened(root), recoveries=None)

    assert reads == 1
    # And the one parse is still the one the rows use: the pause above is
    # `FIRST`'s, which was the only conversation that had made it unattended.
    assert rows[0].terms == "0 ÷ 3"
    assert rows[6].note == "captcha 1"


def test_the_metrics_command_reports_what_it_could_not_measure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace_of(tmp_path)
    code = sign_off.main(["metrics", "--workspace", str(tmp_path)])
    printed = capsys.readouterr().out

    assert code == ExitCode.FAILED
    assert "| §19 metric | Number |" in printed
    assert printed.splitlines()[-1].startswith("unmeasured: semantic fidelity")
    assert "browser reliability" in printed.splitlines()[-1]


# --------------------------------------------------------------------------- #
# The drill
# --------------------------------------------------------------------------- #


def test_the_drill_passes_on_a_run_with_no_duplicates(tmp_path: Path) -> None:
    entries = {
        FIRST: entry(),
        SECOND: entry(destination=Destination(conversation_id="chat-2")),
    }
    root = workspace_of(tmp_path, entries)
    state.StateStore(root).bump_counter("interrupted")
    checks = sign_off.drill(opened(root))

    assert [check.verdict for check in checks] == [sign_off.GO] * 5


def test_two_entries_sharing_a_chat_is_the_failure_the_drill_looks_for(
    tmp_path: Path,
) -> None:
    """A conversation migrated twice after a kill would land as two entries on
    one chat, or as one entry with a second chat behind it. Both are counted."""
    entries = {FIRST: entry(), SECOND: entry()}
    checks = sign_off.drill(opened(workspace_of(tmp_path, entries)))

    assert checks[0].verdict == sign_off.NO_GO
    assert "chat-1" in checks[0].terms


def test_a_conversation_left_pending_is_not_accounted_for(tmp_path: Path) -> None:
    entries = {FIRST: entry(), SECOND: entry(status=Status.PENDING, attempts=0)}
    checks = sign_off.drill(opened(workspace_of(tmp_path, entries)))

    assert checks[2].verdict == sign_off.NO_GO


def test_a_workspace_with_no_interruption_says_the_drill_has_not_run(
    tmp_path: Path,
) -> None:
    entries = {FIRST: entry()}
    checks = sign_off.drill(opened(workspace_of(tmp_path, entries)))

    assert checks[3].verdict == sign_off.UNKNOWN


def test_a_superseded_chat_is_reported_rather_than_hidden(tmp_path: Path) -> None:
    """`--force` leaves the old chat at the destination (§17 forbids deleting
    it), so it is a fact about the account the write-up has to carry."""
    root = workspace_of(tmp_path, {FIRST: entry()})
    state.StateStore(root).remember_destination(FIRST, "chat-0")
    state.StateStore(root).bump_counter("interrupted")
    checks = sign_off.drill(opened(root))

    assert checks[4].verdict == sign_off.UNKNOWN
    assert sign_off.main(["drill", "--workspace", str(root)]) == ExitCode.FAILED


# --------------------------------------------------------------------------- #
# The safety audit
# --------------------------------------------------------------------------- #


def history_of(profile: Path, *urls: str) -> None:
    """A Chrome history database with a `urls` table, and a title beside each
    URL — which is what the audit must not read."""
    profile.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(profile / "History")
    with connection:
        connection.execute("CREATE TABLE urls (id INTEGER, url TEXT, title TEXT)")
        connection.executemany(
            "INSERT INTO urls VALUES (?, ?, ?)",
            [(index, url, "a conversation title") for index, url in enumerate(urls)],
        )
    connection.close()


def test_the_history_audit_accepts_new_and_the_chats_this_workspace_made(
    tmp_path: Path,
) -> None:
    root = workspace_of(tmp_path)
    profile = root / "browser-profile" / "Default"
    history_of(
        profile,
        "https://claude.ai/new",
        "https://claude.ai/chat/chat-1?utm=x",
        "https://claude.ai/chat/chat-2",
    )
    checks = sign_off.safety(
        opened(root), export=None, profile=root / "browser-profile"
    )

    assert [check.name for check in checks] == list(sign_off.SAFETY_CHECKS)
    assert named(checks, sign_off.HISTORY_CHECKS[0]).number == "3"
    assert [check.verdict for check in checks[1:]] == [sign_off.GO] * 4


def test_a_chat_this_workspace_never_created_fails_the_audit(tmp_path: Path) -> None:
    root = workspace_of(tmp_path)
    profile = root / "browser-profile" / "Default"
    history_of(profile, "https://claude.ai/chat/somebody-elses")
    checks = sign_off.safety(
        opened(root), export=None, profile=root / "browser-profile"
    )

    assert named(checks, sign_off.HISTORY_CHECKS[1]).verdict == sign_off.NO_GO


def test_another_host_fails_the_audit(tmp_path: Path) -> None:
    root = workspace_of(tmp_path)
    history_of(root / "browser-profile" / "Default", "https://example.com/anything")
    checks = sign_off.safety(
        opened(root), export=None, profile=root / "browser-profile"
    )

    foreign = named(checks, sign_off.HISTORY_CHECKS[2])
    assert foreign.verdict == sign_off.NO_GO
    assert foreign.terms == "example.com"


def test_another_claude_path_is_reported_for_a_person_to_judge(
    tmp_path: Path,
) -> None:
    """`login` really does visit `/login`, and a path the tool never asks for is
    a finding a human makes, not one this script asserts."""
    root = workspace_of(tmp_path)
    history_of(root / "browser-profile" / "Default", "https://claude.ai/login?next=/")
    checks = sign_off.safety(
        opened(root), export=None, profile=root / "browser-profile"
    )

    other = named(checks, sign_off.HISTORY_CHECKS[3])
    assert other.verdict == sign_off.UNKNOWN
    assert other.terms == "/login"


def test_the_audit_never_prints_a_query_string_or_a_title(tmp_path: Path) -> None:
    """§10: a claude.ai page title is somebody's conversation, and a query can
    carry anything at all."""
    root = workspace_of(tmp_path)
    history_of(
        root / "browser-profile" / "Default",
        "https://example.com/search?q=a+conversation+title",
    )
    checks = sign_off.safety(
        opened(root), export=None, profile=root / "browser-profile"
    )

    rendered = " ".join(f"{check.number} {check.terms}" for check in checks)
    assert "conversation" not in rendered
    assert "?" not in rendered


def test_a_missing_profile_is_unknown_rather_than_clean(tmp_path: Path) -> None:
    root = workspace_of(tmp_path)
    checks = sign_off.safety(opened(root), export=None, profile=root / "nowhere")

    assert [check.name for check in checks] == [
        sign_off.EXPORT_CHECK,
        "browser history",
    ]
    assert [check.verdict for check in checks] == [sign_off.UNKNOWN] * 2


def test_an_unnamed_export_is_a_row_and_not_a_silence(tmp_path: Path) -> None:
    """`safety` answers "was anything outside this migration touched", so an
    audit that simply left the export out when nobody named one would read as a
    §17 pass that had checked it. (Raised by Copilot in review on #30.)"""
    root = workspace_of(tmp_path)
    history_of(root / "browser-profile" / "Default", "https://claude.ai/new")
    checks = sign_off.safety(
        opened(root), export=None, profile=root / "browser-profile"
    )
    digest = named(checks, sign_off.EXPORT_CHECK)

    assert digest.number == sign_off.UNMEASURED
    assert "--export" in digest.terms
    assert digest.verdict == sign_off.UNKNOWN
    assert sign_off.main(["safety", "--workspace", str(root)]) == ExitCode.FAILED


def test_the_export_digest_is_compared_with_the_one_the_run_recorded(
    tmp_path: Path,
) -> None:
    root = workspace_of(tmp_path)
    export = tmp_path / "export"
    export.mkdir()
    (export / "conversations.json").write_text("[]", encoding="utf-8")
    checks = sign_off.safety(
        opened(root), export=export, profile=root / "browser-profile"
    )

    assert checks[0].name == "export sha-256 unchanged"
    assert checks[0].verdict == sign_off.NO_GO


def test_a_matching_digest_passes(tmp_path: Path) -> None:
    export = tmp_path / "export"
    export.mkdir()
    (export / "conversations.json").write_text("[]", encoding="utf-8")
    digest = sign_off.export_digest(export)
    root = tmp_path / "workspace"
    root.mkdir()
    workspace_of(root, fingerprint=digest)
    checks = sign_off.safety(opened(root), export=export, profile=root / "nowhere")

    assert checks[0].verdict == sign_off.GO


# --------------------------------------------------------------------------- #
# The sample
# --------------------------------------------------------------------------- #


def test_the_sample_is_every_completed_conversation_when_there_are_few(
    tmp_path: Path,
) -> None:
    assert sign_off.sample(opened(workspace_of(tmp_path)), size=20, seed=21) == [
        FIRST,
        SECOND,
    ]


def test_the_sample_is_reproducible(tmp_path: Path) -> None:
    """Twenty of a hundred, twice, and the same twenty: a write-up that cannot
    say which conversations it graded cannot be checked by anybody else."""
    entries = {
        f"{position:08d}-0000-4000-8000-000000000000": entry()
        for position in range(100)
    }
    workspace = opened(workspace_of(tmp_path, entries))

    first = sign_off.sample(workspace, size=20, seed=21)
    assert len(first) == 20
    assert first == sign_off.sample(workspace, size=20, seed=21)
    assert first != sign_off.sample(workspace, size=20, seed=22)


def test_the_sample_command_prints_a_short_id_and_a_uuid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace_of(tmp_path)
    code = sign_off.main(["sample", "--workspace", str(tmp_path)])

    assert code == ExitCode.OK
    assert capsys.readouterr().out.splitlines()[0] == f"11112222  {FIRST}"


# --------------------------------------------------------------------------- #
# Printing
# --------------------------------------------------------------------------- #


def test_the_safety_command_runs_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every row of the §17 audit, passing: the export re-digests to what the
    run recorded, and the history holds one `/new` and nothing else."""
    export = tmp_path / "export"
    export.mkdir()
    (export / "conversations.json").write_text("[]", encoding="utf-8")
    root = tmp_path / "workspace"
    root.mkdir()
    workspace_of(root, fingerprint=sign_off.export_digest(export))
    history_of(root / "browser-profile" / "Default", "https://claude.ai/new")
    code = sign_off.main(["safety", "--workspace", str(root), "--export", str(export)])

    assert code == ExitCode.OK
    assert "go: 5 checks passed" in capsys.readouterr().out


def test_columns_are_padded_but_the_last_one_is_not() -> None:
    assert list(sign_off.columns([["a", "one"], ["bbb", "two"]])) == [
        "a    one",
        "bbb  two",
    ]
