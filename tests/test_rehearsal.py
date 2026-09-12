"""The rehearsal's own pieces, without a mock, a browser or a subprocess.

A rehearsal itself is `29`'s command and takes minutes; what is here is
everything about it that can be checked in milliseconds — the export it
migrates, the `hermes` that stands where Hermes stands, the arithmetic of §25's
pass criteria, and the record §26 asks for.

The three procedures those criteria are *about* — `11`'s, `24`'s and `20`'s —
are tested where they live, against a fake page, in `test_skill_dry_run.py`,
`test_signin.py` and `test_followup.py`. Nothing here re-tests them.
"""

import json
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from rehearsal import export as exporting
from rehearsal import hermes as scripted
from rehearsal import run as running

from dataporter.hermes.client import parse_config
from dataporter.hermes.profile import configured_model
from dataporter.hermes.version import at_least, parse_version
from fake_agent import ScriptedProbe

DATE = "2026-09-12"


# --------------------------------------------------------------------------- #
# `28`: the export
# --------------------------------------------------------------------------- #


def test_the_export_covers_every_category_24_names(tmp_path: Path) -> None:
    export, attachments = exporting.build(tmp_path)
    conversations = json.loads(
        (export / "conversations.json").read_text(encoding="utf-8")
    )
    by_uuid = {item["uuid"]: item for item in conversations}

    assert len(conversations) == len(exporting.MIGRATABLE) + 1
    assert set(exporting.MIGRATABLE) <= set(by_uuid)
    # More than `20`'s selection can take, so the `--all` run the drill
    # interrupts has work to do (§23).
    assert len(exporting.MIGRATABLE) > 8
    assert by_uuid[exporting.UNSUPPORTED]["chat_messages"] == []
    # Over the tool's default 50,000-character seed budget, so the seed is two
    # parts. Measured on the rendered text, not asserted as a part count: the
    # budget belongs to `10`.
    longest = sum(
        len(message["text"]) for message in by_uuid[exporting.LONG]["chat_messages"]
    )
    assert longest > 50_000
    first = by_uuid[exporting.ATTACHED]["chat_messages"][0]
    assert [item["file_name"] for item in first["attachments"]] == [
        exporting.INLINE_FILE,
        exporting.UNSUPPORTED_FILE,
    ]
    assert [item["file_name"] for item in first["files"]] == [exporting.UPLOAD_FILE]
    assert (attachments / exporting.ATTACHED / exporting.UPLOAD_FILE).exists()


def test_the_export_is_the_same_export_every_time(tmp_path: Path) -> None:
    """`plan.json` is reproducible only if the export it is built from is."""
    first, _ = exporting.build(tmp_path / "one")
    again, _ = exporting.build(tmp_path / "two")
    assert (first / "conversations.json").read_bytes() == (
        again / "conversations.json"
    ).read_bytes()


def test_no_real_account_appears_in_it(tmp_path: Path) -> None:
    export, _ = exporting.build(tmp_path)
    text = (export / "users.json").read_text(encoding="utf-8")
    assert "example.invalid" in text


# --------------------------------------------------------------------------- #
# `27`: the scripted `hermes`
# --------------------------------------------------------------------------- #


@pytest.fixture
def profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "profile.json"
    monkeypatch.setenv(scripted.STATE_ENV_VAR, str(state))
    return state


def test_the_version_is_new_enough_for_doctor(
    profile: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert scripted.main(["--version"]) == 0
    found = parse_version(capsys.readouterr().out)
    assert found is not None and at_least(found)


def test_setup_creates_a_profile_and_reads_its_own_configuration(
    profile: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The round-trip `09`'s `setup` and `doctor` make: create, set, show."""
    assert scripted.main(["profile", "create", "dataporter"]) == 0
    assert (
        scripted.main(["-p", "dataporter", "config", "set", "browser.backend", "off"])
        == 0
    )
    assert (
        scripted.main(
            [
                "-p",
                "dataporter",
                "config",
                "set",
                "browser.cdp_url",
                "http://127.0.0.1:9222",
            ]
        )
        == 0
    )
    assert scripted.main(["profile", "list"]) == 0
    assert capsys.readouterr().out == "dataporter\n"

    assert scripted.main(["-p", "dataporter", "config", "show"]) == 0
    config = parse_config(capsys.readouterr().out)
    assert config["browser.backend"] == "off"
    assert config["browser.cdp_url"] == "http://127.0.0.1:9222"
    # `doctor` fails a profile with no model, and a rehearsal has none: the value
    # says exactly that rather than naming one that is not there.
    assert configured_model(config) == scripted.MODEL


def test_an_unknown_command_is_a_usage_error(profile: Path) -> None:
    assert scripted.main(["mimic", "a", "person"]) == 2


def test_a_task_it_does_not_know_is_a_failed_result(
    profile: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A result object the runner's contract can read, never a traceback."""
    assert scripted.main(["-p", "dataporter", "-z", "do something else"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["outcome"] == "failed"
    assert printed["error"]["category"] == "hermes"


def test_a_one_shot_accounts_for_the_tokens_it_did_not_spend(
    profile: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    usage = tmp_path / "usage.json"
    scripted.main(["-p", "dataporter", "-z", "nothing", "--usage-file", str(usage)])
    capsys.readouterr()
    assert json.loads(usage.read_text(encoding="utf-8")) == scripted.NO_TOKENS


def test_the_doctor_helper_task_runs_the_command_and_reports_its_ok(
    profile: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`doctor`'s second Hermes check, performed rather than answered."""
    helper = tmp_path / "helper.py"
    helper.write_text("print('{\"ok\": true}')\n", encoding="utf-8")
    prompt = (
        "Use the terminal tool to run exactly this command, once:\n\n"
        f"  python {helper}\n\n"
        "It prints one JSON object. Then reply with two lines: the word "
        'HCM-ABC123, then the value of that object\'s "ok" field.\n'
    )
    answer = scripted.helper_task(prompt)
    assert answer.splitlines() == ["HCM-ABC123", "true"]


def test_a_prompt_with_no_nonce_cannot_be_answered(profile: Path) -> None:
    with pytest.raises(scripted.AgentError):
        scripted.nonce_in("Use the terminal tool to run exactly this command, once:")


def test_the_executable_carries_the_interpreter_and_the_profile(
    tmp_path: Path,
) -> None:
    written = scripted.write_executable(
        tmp_path / "bin", repo=tmp_path / "repo", state=tmp_path / "bin" / "p.json"
    )
    body = written.read_text(encoding="utf-8")
    assert body.startswith("#!")
    assert str(tmp_path / "repo" / "tests") in body
    assert scripted.STATE_ENV_VAR in body
    assert written.stat().st_mode & 0o111


# --------------------------------------------------------------------------- #
# `20`'s probe procedure, performed by a script
# --------------------------------------------------------------------------- #

PROBE_PROMPT = """\
short_id: a1000001
conversation_id: 11111111-2222-4333-8444-555555555555
chat url: https://claude.ai/chat/11111111-2222-4333-8444-555555555555
question file: /w/pilot/question.txt
helper: hermes-claude-migrate --workspace /w browser …

Procedure.
"""


class Page:
    """A page that answers the probe's three moves."""

    def __init__(self) -> None:
        self.visited: list[str] = []

    def navigate(self, url: str) -> None:
        self.visited.append(url)

    def submit(self, expected_ack: str) -> None:
        self.visited.append("submit")

    def last_assistant_message(self) -> str:
        return "We discussed a migrated conversation."


def helpers_answering(**answers: Any) -> Any:
    calls: list[list[str]] = []

    def run(argv: Sequence[str]) -> tuple[int, dict[str, Any]]:
        calls.append(list(argv))
        return 0, answers.get(
            argv[-1] if argv[-1] in answers else argv[4], {"ok": True}
        )

    run.calls = calls  # ty: ignore[unresolved-attribute]
    return run


def test_the_probe_asks_once_in_the_chat_the_prompt_named() -> None:
    page = Page()
    helper = helpers_answering(
        probe={
            "ok": True,
            "composer_present": True,
            "conversation_id": "11111111-2222-4333-8444-555555555555",
        }
    )
    printed = ScriptedProbe(helper=helper, browser=page).run(PROBE_PROMPT)

    assert printed["outcome"] == "answered"
    assert printed["reply"] == "We discussed a migrated conversation."
    commands = [call[4] for call in helper.calls]
    assert commands == ["probe", "paste", "await-response"]
    # The question reaches the composer through `paste --seed`, as a seed does,
    # and never through anything that types.
    assert "--seed" in helper.calls[1]
    assert page.visited == [
        "https://claude.ai/chat/11111111-2222-4333-8444-555555555555",
        "submit",
    ]


def test_the_probe_stops_in_a_chat_that_is_not_the_one_it_was_given() -> None:
    helper = helpers_answering(
        probe={"ok": True, "composer_present": True, "conversation_id": "somewhere"}
    )
    printed = ScriptedProbe(helper=helper, browser=Page()).run(PROBE_PROMPT)
    assert printed["outcome"] == "failed"
    assert "reply" not in printed


def test_a_probe_prompt_that_does_not_add_up_is_refused() -> None:
    printed = ScriptedProbe(helper=helpers_answering(), browser=Page()).run("helper: x")
    assert printed["outcome"] == "failed"


# --------------------------------------------------------------------------- #
# `29`: the pass criteria and the record
# --------------------------------------------------------------------------- #

LEDGER = {
    "sign_ins": 1,
    "chats_created": len(exporting.MIGRATABLE),
    # One part each, and two for the conversation that is over the seed budget.
    "messages_received": len(exporting.MIGRATABLE) + 1,
    "files_accepted": 1,
    "renames": len(exporting.MIGRATABLE),
}


def workspace_of(tmp_path: Path, **changes: Any) -> running.Settings:
    """A finished rehearsal's workspace, as the three files §25 reads."""
    settings = running.Settings(root=tmp_path, mode="non-interactive")
    settings.workspace.mkdir(parents=True, exist_ok=True)
    state = {
        uuid: {
            "status": "completed",
            "attempts": 1,
            "chunks_acked": 2 if uuid == exporting.LONG else 1,
            "destination": {"conversation_id": f"chat-{index}"},
            "attachments": {"uploaded": 1 if uuid == exporting.ATTACHED else 0},
            "limitations": [],
        }
        for index, uuid in enumerate(exporting.MIGRATABLE)
    }
    state[exporting.UNSUPPORTED] = {
        "status": "failed",
        "attempts": 0,
        "chunks_acked": 0,
        "destination": {"conversation_id": None},
        "attachments": {"uploaded": 0},
        "limitations": [],
    }
    for uuid, fields in changes.get("state", {}).items():
        state[uuid].update(fields)
    (settings.workspace / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (settings.workspace / "run.json").write_text(
        json.dumps({"human_interventions": 0, "auto_signins": 0}), encoding="utf-8"
    )
    (settings.workspace / "report.json").write_text(
        json.dumps(
            {
                "totals": {
                    "source_conversations": len(state),
                    "created": len(exporting.MIGRATABLE),
                    "partial": 0,
                    "failed": 1,
                    "pending": 0,
                }
            }
        ),
        encoding="utf-8",
    )
    return settings


def ok(name: str, stdout: str = "") -> running.Outcome:
    return running.Outcome(
        name=name, argv=(name,), exit_code=0, seconds=1.0, stdout=stdout
    )


SAFETY = """\
Safety (§17)

  export sha-256 unchanged                      a9f3  recorded a9f3  go
  history: migration URLs                       9     /new and /chat  go
  history: chats this workspace did not create  0     none            go
  history: other hosts  0     none            go
  history: other claude.ai paths                1     /login          unknown
"""
"""What the audit prints after a run that signed in. Its own exit code is 1,
because the `/login` visit is counted for a person to judge; §25's criterion is
the two rows above it."""


def signed_off(safety: str = SAFETY) -> dict[str, running.Outcome]:
    return {"drill": ok("drill"), "safety": ok("safety", safety)}


def checks_for(settings: running.Settings, **changes: Any) -> list[running.Criterion]:
    return running.criteria(
        settings,
        counted=changes.get("counted", LEDGER),
        steps=changes.get("steps", [ok("login"), ok("verify")]),
        signs=changes.get("signs", signed_off()),
        interrupted=changes.get("interrupted", ()),
        drill=changes.get("drill", {}),
    )


def test_a_clean_rehearsal_passes_every_criterion(tmp_path: Path) -> None:
    settings = workspace_of(tmp_path)
    failed = [item for item in checks_for(settings) if not item.passed]
    assert failed == [], [(item.name, item.detail) for item in failed]


def test_the_drills_own_count_is_on_the_ledgers_side(tmp_path: Path) -> None:
    """The killed run created a chat the tool never learned the id of, and sent
    one part into it. Both are the mock's and neither is the tool's."""
    settings = workspace_of(tmp_path, state={exporting.SHORT: {"attempts": 2}})
    counted = dict(
        LEDGER,
        chats_created=LEDGER["chats_created"] + 1,
        messages_received=LEDGER["messages_received"] + 1,
    )
    checks = checks_for(
        settings,
        counted=counted,
        interrupted=[exporting.SHORT],
        drill={"chats_created": 1, "messages_received": 1},
    )
    failed = [item for item in checks if not item.passed]
    assert failed == [], [(item.name, item.detail) for item in failed]
    chats = next(item for item in checks if "chats created" in item.name)
    assert "the chat the killed run created and never recorded" in chats.detail


def test_a_conversation_that_took_two_attempts_fails_the_first_criterion(
    tmp_path: Path,
) -> None:
    settings = workspace_of(tmp_path, state={exporting.CODE: {"attempts": 2}})
    first = checks_for(settings)[0]
    assert not first.passed
    assert first.detail.startswith(f"{len(exporting.MIGRATABLE) - 1}/")


def test_a_ledger_that_does_not_reconcile_is_not_a_rehearsal(tmp_path: Path) -> None:
    settings = workspace_of(tmp_path)
    checks = checks_for(settings, counted=dict(LEDGER, messages_received=99))
    failed = [item.name for item in checks if not item.passed]
    assert failed == ["ledger: messages received == parts sent"]


def test_a_pause_is_a_failed_rehearsal(tmp_path: Path) -> None:
    settings = workspace_of(tmp_path)
    (settings.workspace / "run.json").write_text(
        json.dumps({"human_interventions": 1, "auto_signins": 0}), encoding="utf-8"
    )
    names = [item.name for item in checks_for(settings) if not item.passed]
    assert "no pause recorded" in names


def test_the_ledger_block_is_26s_block(tmp_path: Path) -> None:
    """The same columns the mock prints, rebuilt from its numbers — `26`'s golden
    string, which the mock's own tests pin and this one keeps in step with."""
    block = running.ledger_block(
        {
            "sign_ins": 2,
            "chats_created": 8,
            "messages_received": 11,
            "files_accepted": 2,
            "renames": 8,
        }
    )
    assert block == (
        "Mock claude.ai — ledger\n"
        "\n"
        "Sign-ins:                      2\n"
        "Chats created:                 8\n"
        "Messages received:            11\n"
        "Files accepted:                2\n"
        "Renames:                       8"
    )


def test_the_two_arguments_the_mock_printed_are_the_whole_of_the_way_in() -> None:
    settings = running.Settings(root=Path("/w"), mode="non-interactive")
    arguments = running.chrome_args(settings, "PIN=")
    assert arguments[0] == "--host-resolver-rules=MAP claude.ai 127.0.0.1:8443"
    assert arguments[1] == "--ignore-certificate-errors-spki-list=PIN="
    # Never the blanket one: a rehearsal browser that trusted every certificate
    # would be a much larger thing to switch off.
    assert "--ignore-certificate-errors" not in arguments


def test_the_config_names_a_browser_only_when_one_was_named(tmp_path: Path) -> None:
    """Left out, the tool runs its own discovery; written empty, it would be read
    as `Path(".")` and refused. (Raised by Copilot in review on #36.)"""
    settings = running.Settings(root=tmp_path, mode="non-interactive", cdp_port=9333)
    without = running.config_text(settings, pin="PIN=", attachments=tmp_path / "a")
    assert "executable" not in without
    assert "cdp_port = 9333" in without
    named = running.Settings(
        root=tmp_path, mode="non-interactive", chrome="/opt/chromium", cdp_port=9333
    )
    with_chrome = running.config_text(named, pin="PIN=", attachments=tmp_path / "a")
    assert 'executable = "/opt/chromium"' in with_chrome
    # Either way, the two lines the mock printed are there and no blanket trust is.
    for text in (without, with_chrome):
        assert "--host-resolver-rules=MAP claude.ai 127.0.0.1:8443" in text
        assert "--ignore-certificate-errors-spki-list=PIN=" in text
        assert '--ignore-certificate-errors"' not in text


@pytest.mark.slow
def test_a_run_the_drill_could_not_kill_is_still_bounded() -> None:
    """`finish` never waits past its bound: a tool that hung would otherwise take
    the whole rehearsal down with it. (Raised by Copilot in review on #36.)"""
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    started = time.monotonic()
    _, _, timed_out = running.finish(process, timeout_s=0.3)
    assert timed_out
    assert process.returncode is not None
    assert time.monotonic() - started < 5.0


@pytest.mark.slow
def test_a_run_that_ends_in_time_is_not_reported_as_timed_out() -> None:
    """Marked `slow` for what it does — spawn a process — not for how long it
    takes (`tests/conftest.py`)."""
    process = subprocess.Popen(
        [sys.executable, "-c", "print('done')"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    stdout, _, timed_out = running.finish(process, timeout_s=30.0)
    assert (stdout.strip(), timed_out) == ("done", False)


def test_the_record_carries_a_mark_on_every_number(tmp_path: Path) -> None:
    """§26: a claim without a number is not a record, and a number without a
    mark is not a measurement."""
    settings = workspace_of(tmp_path)
    checks = checks_for(settings)
    text = running.render(
        settings,
        number=1,
        date=DATE,
        steps=[ok("setup"), ok("login")],
        checks=checks,
        report_block="Claude migration complete\n\nSource conversations: 10\n",
        ledger_block=running.ledger_block(LEDGER),
        findings=running.findings_of([ok("setup")], checks),
        versions={
            "tool": "hermes-claude-migrate 0.1.0",
            "agent": "scripted agent 1.0.0",
            "chrome": "Chromium 141",
            "mock": "0.1.0",
        },
        extra_args=running.chrome_args(settings, "PIN="),
    )
    rows = [line for line in text.splitlines() if line.startswith("| every")]
    assert rows and all(f"*measured on {DATE}*" in row for row in rows)
    assert "**Verdict:** passed" in text
    assert "Claude migration complete" in text
    assert "Mock claude.ai — ledger" in text
    # §27, in the record rather than only in the brief.
    assert "Anything about claude.ai" in text
    assert "scripted agent 1.0.0" in text


def test_the_record_says_what_a_rehearsal_could_not_exercise(tmp_path: Path) -> None:
    settings = workspace_of(tmp_path)
    text = running.render(
        settings,
        number=2,
        date=DATE,
        steps=[ok("setup")],
        checks=checks_for(settings),
        report_block="",
        ledger_block="",
        findings=[],
        versions={},
        extra_args=[],
    )
    for absent in ("rate limit", "CAPTCHA", "judge", "no model"):
        assert absent in text


def test_the_standing_findings_are_always_reported(tmp_path: Path) -> None:
    """Each is something this arrangement discovered; a record that stopped
    reporting one would be a record of a rehearsal that stopped doing it."""
    found = running.findings_of([ok("setup")], [])
    assert len(found) == len(running.STANDING_FINDINGS)
    assert any("orphan" in item or "never learned the id" in item for item in found)


def test_a_foreign_host_in_the_history_fails_the_audit(tmp_path: Path) -> None:
    """§17's whole point: the tool drove nothing but claude.ai."""
    settings = workspace_of(tmp_path)
    checks = checks_for(
        settings,
        signs=signed_off(SAFETY.replace("other hosts  0", "other hosts  2")),
    )
    audit = next(item for item in checks if "safety audit" in item.name)
    assert not audit.passed
    assert "other hosts: 2" in audit.detail


def test_an_audit_that_printed_nothing_is_not_a_pass(tmp_path: Path) -> None:
    settings = workspace_of(tmp_path)
    checks = checks_for(settings, signs=signed_off(""))
    audit = next(item for item in checks if "safety audit" in item.name)
    assert not audit.passed


def test_a_deliberate_non_zero_exit_is_not_a_finding() -> None:
    """The run the drill kills, `doctor` before anybody has signed in, and the
    instruments whose last rows are for a person: each is explained once, in the
    standing findings, rather than twice."""
    killed = running.Outcome(
        name="import --all (interrupted)",
        argv=("import",),
        exit_code=-9,
        seconds=3.0,
        note="SIGKILL mid-conversation",
        deliberate=True,
    )
    broken = running.Outcome(name="verify", argv=("verify",), exit_code=1, seconds=1.0)
    found = running.findings_of([killed, broken], [])
    assert found[0].startswith("`verify` exited 1")
    assert not any("interrupted" in item for item in found)


# --------------------------------------------------------------------------- #
# The record this repository keeps
# --------------------------------------------------------------------------- #

RECORD = Path(__file__).resolve().parents[1] / "docs" / "rehearsal-01.md"


@pytest.mark.skipif(not RECORD.exists(), reason="no rehearsal has been recorded")
def test_the_committed_record_keeps_26s_discipline() -> None:
    """Every number marked, both blocks present, and §27 said in the record
    rather than only in the brief."""
    text = RECORD.read_text(encoding="utf-8")
    rows = [
        line
        for line in text.splitlines()
        # Parenthesised: `and` binds tighter than `or`, so without them a line
        # carrying " FAIL " anywhere in the record would be counted as a row of
        # the criteria table. (Raised by Copilot in review on #36.)
        if line.startswith("| ") and (" pass " in line or " FAIL " in line)
    ]
    assert rows
    assert all("*measured on " in row for row in rows)
    assert "Mock claude.ai — ledger" in text
    assert "Claude migration complete" in text
    assert "not evidence\nabout claude.ai" in text
    # §10: the record names conversations by short id and nothing else.
    for title in ("A short exchange", "A long exchange", "A conversation with"):
        assert title not in text
