"""The extraction rehearsal's own pieces (`46`), without a mock, a browser or a subprocess.

The protocol itself is `rehearsal.run --protocol extraction` and takes minutes; what is
here is the arithmetic of §68's criteria, the record, the masking of the link, and the
runner's second place to look for traces.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from rehearsal import extraction
from rehearsal import run as running

from dataporter import store

DATE = "2026-09-14"
LINKS = [
    "https://chatgpt.com/__mock/exports/0123456789abcdef0123456789abcdef.zip",
    "https://chatgpt.com/__mock/exports/fedcba9876543210fedcba9876543210.zip",
]
LEDGER = {
    "sign_ins": 2,
    "chats_created": 3,
    "messages_received": 3,
    "files_accepted": 1,
    "renames": 0,
    "exports_requested": 2,
    "links_minted": 0,
}
CLAUDE_LEDGER = {**LEDGER, "links_minted": 2}
"""The mock claude.ai signs in by link (`49`): one link for the seeding, one for the tool."""

HEADER = {
    "trace": 1,
    "kind": "header",
    "ts": "2026-09-14T10:00:00.000Z",
    "command": "login",
    "flags": [],
    "source": "chatgpt",
    "host": "chatgpt.com",
    "account": "rehearsal",
    "export_fingerprint": None,
    "tool": "dataporter 0.1.0",
    "chrome": "Chrome/141.0.0.0",
    "agent": None,
    "chrome_arguments": [],
    "root": "/r",
}


def line(**fields: Any) -> str:
    return json.dumps(fields, separators=(",", ":"))


def snapshot(store_root: Path, source: str, stamp: str, *, gaps: int, files: int | None) -> Path:
    directory = store_root / source / extraction.ACCOUNT / stamp
    directory.mkdir(parents=True)
    (directory / store.ARCHIVE_NAME).write_bytes(b"PK\x03\x04" + stamp.encode())
    manifest = store.Snapshot(
        source=source,
        account=extraction.ACCOUNT,
        stamp=stamp,
        origin="ask",
        filed_at=running.datetime(2026, 9, 14, 10, 0, tzinfo=running.UTC),
        tool_version="0.1.0",
        counts=store.Counts(conversations=3, files=files),
        gaps=[store.Gap(kind="bytes_not_in_export", count=gaps, reason="files")] if gaps else [],
    )
    (directory / store.MANIFEST_NAME).write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (directory / store.COMPLETE_NAME).write_bytes(b"")
    return directory


def half_for(tmp_path: Path, mock: extraction.Mock = extraction.CHATGPT, **changes: Any) -> extraction.Half:
    """Return a finished half, as the files §68's criteria read: two snapshots, traces, outcomes."""
    settings = running.Settings(root=tmp_path / mock.source, mode="non-interactive", port=mock.port)
    settings.workspace.mkdir(parents=True, exist_ok=True)
    store_root = tmp_path / "store"
    gaps = changes.get("gaps", LEDGER["files_accepted"] * mock.files_per_upload)
    snapshot(
        store_root,
        mock.source,
        "2026-09-14T10-00-01Z",
        gaps=gaps,
        files=changes.get("files", 0 if mock.session_bound else None),
    )
    snapshot(
        store_root,
        mock.source,
        "2026-09-14T10-00-02Z",
        gaps=gaps,
        files=changes.get("files", 0 if mock.session_bound else None),
    )
    heading = f"{mock.display_name} extraction — rehearsal\n\n"
    names = [
        "login",
        *(["login --link"] if mock.link_signin else []),
        "extract (ask 1)",
        "extract --link (fetch 1)",
        "extract (ask 2)",
        "extract --link (fetch 2)",
        "session status",
        "session logout",
        "snapshots",
    ]
    driving = (
        {"login", "extract (ask 1)", "extract (ask 2)"}
        | ({"extract --link (fetch 1)", "extract --link (fetch 2)"} if mock.session_bound else set())
        | ({"login --link"} if mock.link_signin else set())
    )
    steps: list[running.Outcome] = []
    traces = settings.root / "traces"
    traces.mkdir(parents=True, exist_ok=True)
    for position, name in enumerate(names, 1):
        stdout = heading if name.startswith("extract") else ""
        if name == "login" and mock.link_signin:
            stdout = f"Claude sign-in — rehearsal\n…\n{running.LINK_SENT_LINE} …\nSigned in to Claude — rehearsal\n"
        if name == "snapshots":
            stdout = f"{mock.source}/rehearsal   2026-09-14T10-00-01Z   3 conversations   1 gap\n{mock.source}/rehearsal   2026-09-14T10-00-02Z   3 conversations   1 gap\n"
        outcome = running.Outcome(name=name, argv=(name,), exit_code=0, seconds=1.0, stdout=stdout)
        if name in driving:
            flags = ["--link"] if name.endswith("--link") or "--link" in name else []
            lines = [
                json.dumps({
                    **HEADER,
                    "command": name.split()[0],
                    "flags": flags,
                    "source": mock.source,
                    "host": mock.hosts[0],
                })
            ]
            if name == "login --link":
                lines.append(line(kind="move", helper="sign-in-link", ok=True))
            if name == "login" and not mock.link_signin:
                lines += [
                    line(kind="observation", what="navigation", host=mock.hosts[-1], path="/log-in", query=[]),
                    line(kind="observation", what="certificate", host=mock.hosts[0], issuer="x", subject="x"),
                    line(kind="observation", what="certificate", host=mock.hosts[-1], issuer="x", subject="x"),
                    line(kind="move", helper="password-step", ok=True),
                ]
            lines.append(line(kind="observation", what="end", exit=0))
            path = traces / f"{position:02d}-{name}.jsonl"
            path.write_text("".join(f"{item}\n" for item in lines), encoding="utf-8")
            outcome.trace = path.relative_to(settings.root)
            outcome.traces = 1
        steps.append(outcome)
    runner = running.Runner(settings=settings, env={}, steps=steps)
    return extraction.Half(
        mock=mock,
        settings=settings,
        runner=runner,
        extra_args=("--host-resolver-rules=MAP x 127.0.0.1:1",),
        seeded={"chats": 3, "files": 1},
        links=changes.get("links", list(LINKS)),
        counted=changes.get("counted", dict(CLAUDE_LEDGER if mock.link_signin else LEDGER)),
        first_digest=changes.get("first_digest", extraction.digest_of(store_root / mock.source / extraction.ACCOUNT)),
        blocks={"ask": heading + "Export requested …", "fetch 1": heading + "Downloaded 0.0 MB.", "fetch 2": heading},
    )


# --------------------------------------------------------------------------- #
# The runner's additions
# --------------------------------------------------------------------------- #


def test_the_link_is_masked_in_a_recorded_argv() -> None:
    argv = ["dataporter", "extract", "--link", LINKS[0]]
    assert running.masked(argv, (LINKS[0],)) == ("dataporter", "extract", "--link", "<link>")
    assert running.masked(argv, ()) == tuple(argv)
    assert running.masked(argv, ("",)) == tuple(argv)


def test_a_two_host_mock_gets_one_resolver_rule() -> None:
    settings = running.Settings(root=Path("/r"), mode="non-interactive", port=8444)
    arguments = running.chrome_args(settings, "PIN", hosts=("chatgpt.com", "auth.openai.com"))
    assert arguments[0] == "--host-resolver-rules=MAP chatgpt.com 127.0.0.1:8444, MAP auth.openai.com 127.0.0.1:8444"
    assert running.chrome_args(settings, "PIN")[0] == "--host-resolver-rules=MAP claude.ai 127.0.0.1:8444"


def test_traces_are_gathered_from_the_account_home_too(tmp_path: Path) -> None:
    settings = running.Settings(root=tmp_path, mode="non-interactive")
    settings.workspace.mkdir(parents=True)
    logs = settings.accounts_dir / "chatgpt" / "rehearsal" / "logs"
    logs.mkdir(parents=True)
    left = logs / "trace-20260914T100000Z.jsonl"
    left.write_text(json.dumps(HEADER) + "\n", encoding="utf-8")
    runner = running.Runner(settings=settings, env={})
    outcome = running.Outcome(name="extract (ask 1)", argv=("extract",), exit_code=0, seconds=1.0)

    runner.keep(outcome)

    assert not left.exists()
    assert outcome.trace == Path("traces/01-extract--ask-1.jsonl")
    assert outcome.traces == 1


def test_the_ledger_block_has_seven_rows_under_the_site_s_heading() -> None:
    assert extraction.ledger_block(extraction.CHATGPT, LEDGER) == (
        "Mock chatgpt.com — ledger\n"
        "\n"
        "Sign-ins:                      2\n"
        "Chats created:                 3\n"
        "Messages received:             3\n"
        "Files accepted:                1\n"
        "Renames:                       0\n"
        "Exports requested:             2\n"
        "Sign-in links minted:          0"
    )
    assert extraction.ledger_block(extraction.CLAUDE, CLAUDE_LEDGER).endswith("Sign-in links minted:          2")


# --------------------------------------------------------------------------- #
# §68's criteria
# --------------------------------------------------------------------------- #


def test_a_clean_half_passes_every_criterion(tmp_path: Path) -> None:
    half = half_for(tmp_path)
    checks = extraction.criteria(half, store=tmp_path / "store")
    assert [item.name for item in checks if not item.passed] == []
    assert len(checks) == 13


def test_the_claude_half_counts_each_file_twice_and_needs_no_crossing(tmp_path: Path) -> None:
    half = half_for(tmp_path, extraction.CLAUDE)
    checks = extraction.criteria(half, store=tmp_path / "store")
    assert [item.name for item in checks if not item.passed] == []
    assert len(checks) == 14
    gap = next(item for item in checks if item.name.startswith("ledger: the gap"))
    assert gap.detail == "gaps [2, 2] == 1 × 2, files carried [None, None]"


def test_the_claude_half_signs_in_with_two_commands_and_two_links(tmp_path: Path) -> None:
    """`49`: `login` and `login --link` both count, both leave a trace, and the mock minted two links."""
    half = half_for(tmp_path, extraction.CLAUDE)
    by_name = {item.name: item for item in extraction.criteria(half, store=tmp_path / "store")}
    assert by_name["login signs the source account in"].detail == "exit 0, login --link exit 0"
    assert by_name["ledger: sign-ins == the seeding's + the tool's"].detail == "2 == 1 + 1 (a link spent)"
    assert by_name["ledger: sign-in links minted == the seeding's + the tool's"].passed
    assert by_name["one trace per step that drove a tab, each naming the source"].detail == "[1, 1, 1, 1] for 4 steps"

    assert by_name["login saw the link sent and said so"].passed

    without = half_for(tmp_path / "b", extraction.CLAUDE)
    without.runner.steps = [step for step in without.runner.steps if step.name != "login --link"]
    for step in without.runner.steps:
        if step.name == "login":
            step.stdout = "Claude sign-in — rehearsal\n"
    names = {item.name for item in extraction.criteria(without, store=tmp_path / "b" / "store") if not item.passed}
    assert "login signs the source account in" in names
    assert "ledger: sign-ins == the seeding's + the tool's" in names
    assert "login saw the link sent and said so" in names


def test_a_first_snapshot_the_second_fetch_changed_fails(tmp_path: Path) -> None:
    half = half_for(tmp_path, first_digest=("0" * 64, "0" * 64))
    checks = extraction.criteria(half, store=tmp_path / "store")
    assert [item.name for item in checks if not item.passed] == ["the first snapshot is unchanged by the second"]


def test_a_link_left_in_a_file_fails(tmp_path: Path) -> None:
    half = half_for(tmp_path)
    (half.settings.root / "protocol").mkdir()
    (half.settings.root / "protocol" / "03-fetch.err").write_text(LINKS[0], encoding="utf-8")
    checks = extraction.criteria(half, store=tmp_path / "store")
    failed = {item.name: item.detail for item in checks if not item.passed}
    assert failed == {"the link is in no file the run left": "protocol/03-fetch.err"}


def test_a_ledger_that_does_not_reconcile_fails(tmp_path: Path) -> None:
    half = half_for(tmp_path, counted={**LEDGER, "chats_created": 4, "sign_ins": 5})
    checks = extraction.criteria(half, store=tmp_path / "store")
    assert sorted(item.name for item in checks if not item.passed) == [
        "ledger: conversations == chats created",
        "ledger: sign-ins == the seeding's + the tool's",
    ]


def test_one_link_for_two_asks_fails(tmp_path: Path) -> None:
    half = half_for(tmp_path, links=[LINKS[0]])
    checks = extraction.criteria(half, store=tmp_path / "store")
    assert [item.name for item in checks if not item.passed] == ["the mock minted one link per ask"]


# --------------------------------------------------------------------------- #
# The record
# --------------------------------------------------------------------------- #


def test_the_record_carries_both_halves_and_a_mark_on_every_number(tmp_path: Path) -> None:
    half = half_for(tmp_path / "a", extraction.CLAUDE)
    halves = [(half, extraction.criteria(half, store=tmp_path / "a" / "store"))]
    text = extraction.render(
        halves,
        number=3,
        date=DATE,
        mode="non-interactive",
        versions={
            "tool": "dataporter 0.1.0",
            "agent": "scripted agent 1.0.0",
            "chrome": "Chrome 1",
            "claude-mock": "0.1.0",
            "chatgpt-mock": "0.1.0",
        },
        findings=extraction.findings_of(halves),
    )
    assert text.startswith("# Rehearsal 03 — extraction\n")
    assert "## The mock claude.ai" in text
    assert "Mock claude.ai — ledger" in text
    assert "**Verdict:** passed. *measured on 2026-09-14*" in text
    for row in text.splitlines():
        if row.startswith("| ") and " pass |" in row:
            assert row.endswith(f"| *measured on {DATE}* |"), row
    assert "The seeding signs in to the mock" in text
    assert "## What it could not exercise" in text
    assert LINKS[0] not in text


def test_a_failed_criterion_is_a_finding(tmp_path: Path) -> None:
    half = half_for(tmp_path, links=[LINKS[0]])
    checks = extraction.criteria(half, store=tmp_path / "store")
    found = extraction.findings_of([(half, checks)])
    assert found[0].startswith("chatgpt.com: the mock minted one link per ask: 1 links listed")


def test_digest_of_reads_the_oldest_snapshot(tmp_path: Path) -> None:
    store_root = tmp_path / "store"
    first = snapshot(store_root, "chatgpt", "2026-09-14T10-00-01Z", gaps=0, files=0)
    snapshot(store_root, "chatgpt", "2026-09-14T10-00-02Z", gaps=0, files=0)
    archive, manifest = extraction.digest_of(store_root / "chatgpt" / extraction.ACCOUNT)
    assert archive == hashlib.sha256((first / store.ARCHIVE_NAME).read_bytes()).hexdigest()
    assert manifest == hashlib.sha256((first / store.MANIFEST_NAME).read_bytes()).hexdigest()
    assert extraction.digest_of(tmp_path / "nowhere") == ("", "")


RECORD = Path(__file__).resolve().parents[1] / "docs" / "rehearsal-03.md"


@pytest.mark.skipif(not RECORD.exists(), reason="no extraction rehearsal has been recorded")
def test_the_committed_record_keeps_the_discipline() -> None:
    """Every criterion row marked, both halves present, and no link anywhere in it (§66)."""
    text = RECORD.read_text(encoding="utf-8")
    rows = [row for row in text.splitlines() if row.startswith("| ") and ("| pass |" in row or "| FAIL |" in row)]
    assert rows, "no criteria rows"
    assert all(re.search(r"\| \*measured on \d{4}-\d{2}-\d{2}\* \|$", row) for row in rows)
    assert "## The mock claude.ai" in text
    assert "## The mock chatgpt.com" in text
    assert "Exports requested:             2" in text
    assert "__mock/exports" not in text
    assert "**Chrome:** unknown" not in text
