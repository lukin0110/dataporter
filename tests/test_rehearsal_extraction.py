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
    "skills_listed": 0,
    "skills_served": 0,
}
CLAUDE_LEDGER = {**LEDGER, "links_minted": 2, "skills_listed": 3, "skills_served": 9}
"""The mock claude.ai signs in by link (`49`): one link for the seeding, one for the
tool. And its account has skills (`67`): three `extract-skills` runs read the list
three times and take the three servable skills each time."""

SKILLS = [
    {"id": "skill_a", "name": "research-helper", "creator_type": "user", "refused": False, "served": 3},
    {"id": "skill_b", "name": "standup-notes", "creator_type": "user", "refused": False, "served": 3},
    {"id": "skill_c", "name": "plugin-helper", "creator_type": "user", "refused": False, "served": 3},
    {"id": "skill_d", "name": "broken-skill", "creator_type": "user", "refused": True, "served": 0},
    {"id": "skill_e", "name": "docs", "creator_type": "anthropic", "refused": False, "served": 0},
    {"id": "skill_f", "name": "shared-thing", "creator_type": "organization", "refused": False, "served": 0},
]
"""What the mock claude.ai's witness says after a clean run: the mix it seeds, served as `67` expects."""
OURS = ["plugin-helper", "research-helper", "standup-notes"]

HEADER = {
    "trace": 1,
    "kind": "header",
    "ts": "2026-09-14T10:00:00.000Z",
    "command": "login",
    "flags": [],
    "source": "chatgpt",
    "host": "127.0.0.1",
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


def snapshot(
    store_root: Path,
    source: str,
    stamp: str,
    *,
    gaps: int,
    files: int | None,
    skills: list[str] | None = None,
    skill_gap: int = 0,
    origin: str = "ask",
) -> Path:
    directory = store_root / source / extraction.ACCOUNT / stamp
    directory.mkdir(parents=True)
    if origin != "skills":
        (directory / store.ARCHIVE_NAME).write_bytes(b"PK\x03\x04" + stamp.encode())
    every_gap = [store.Gap(kind="bytes_not_in_export", count=gaps, reason="files")] if gaps else []
    if skill_gap:
        every_gap.append(
            store.Gap(kind="skill_not_downloaded", count=skill_gap, reason="skill could not be downloaded")
        )
    manifest = store.Snapshot(
        source=source,
        account=extraction.ACCOUNT,
        stamp=stamp,
        origin=origin,  # type: ignore[arg-type]
        filed_at=running.datetime(2026, 9, 14, 10, 0, tzinfo=running.UTC),
        tool_version="0.1.0",
        counts=store.Counts(
            conversations=0 if origin == "skills" else 3, files=files, skills=len(skills or []) or None
        ),
        skills=[
            store.SkillFile(name=name, filename=f"{name}.skill", bytes=5, sha256="a" * 64) for name in skills or []
        ],
        gaps=every_gap,
    )
    (directory / store.MANIFEST_NAME).write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (directory / store.COMPLETE_NAME).write_bytes(b"")
    return directory


def _snapshots_for(store_root: Path, mock: extraction.Mock, changes: dict[str, Any]) -> Path:
    """File the two archive snapshots §68 expects, and — for a mock with skills — what `67` adds; return the first."""
    gaps = changes.get("gaps", LEDGER["files_accepted"] * mock.files_per_upload)
    files = changes.get("files", 0 if mock.session_bound else None)
    filed_skills = changes.get("skills", list(OURS)) if mock.has_skills else None
    skill_gap = changes.get("skill_gap", 1) if mock.has_skills else 0
    first = snapshot(
        store_root,
        mock.source,
        "2026-09-14T10-00-01Z",
        gaps=gaps,
        files=files,
        skills=filed_skills,
        skill_gap=skill_gap,
    )
    snapshot(store_root, mock.source, "2026-09-14T10-00-02Z", gaps=gaps, files=files)
    if mock.has_skills:
        snapshot(
            store_root,
            mock.source,
            "2026-09-14T10-00-03Z",
            gaps=0,
            files=None,
            skills=filed_skills,
            skill_gap=skill_gap,
            origin="skills",
        )
    return first


def _stdout_for(name: str, mock: extraction.Mock, heading: str) -> str:
    """Return what a modelled step printed: enough of each block for the criteria to read."""
    if name == "login" and mock.link_signin:
        return f"Claude sign-in — rehearsal\n…\n{running.LINK_SENT_LINE} …\nSigned in to Claude — rehearsal\n"
    if name == "snapshots":
        rows = (
            f"{mock.source}/rehearsal   2026-09-14T10-00-01Z   3 conversations   1 gap\n"
            f"{mock.source}/rehearsal   2026-09-14T10-00-02Z   3 conversations   1 gap\n"
        )
        if mock.has_skills:
            rows += f"{mock.source}/rehearsal   2026-09-14T10-00-03Z   3 skills          1 gap\n"
        return rows
    if name.startswith("extract-skills"):
        return f"{mock.display_name} skills — rehearsal\n\nDownloaded 3 skills in 2s.\n3 skills.\n"
    return heading if name.startswith("extract") else ""


def _trace_for(position: int, name: str, mock: extraction.Mock, traces: Path) -> Path:
    """Write the trace a modelled step left — a header, the moves the criteria look for, an end — and return where."""
    flags = ["--link"] if "--link" in name else []
    lines = [
        json.dumps({
            **HEADER,
            "command": name.split(maxsplit=1)[0],
            "flags": flags,
            "source": mock.source,
            "host": extraction.TRACE_HOST,
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
    return path


def half_for(tmp_path: Path, mock: extraction.Mock = extraction.CHATGPT, **changes: Any) -> extraction.Half:
    """Return a finished half, as the files §68's criteria read: the snapshots, the traces, the outcomes."""
    settings = running.Settings(root=tmp_path / mock.source, mode="non-interactive", port=mock.port)
    settings.workspace.mkdir(parents=True, exist_ok=True)
    store_root = tmp_path / "store"
    first = _snapshots_for(store_root, mock, changes)
    archive_digest = hashlib.sha256((first / store.ARCHIVE_NAME).read_bytes()).hexdigest()
    heading = f"{mock.display_name} extraction — rehearsal\n\n"
    names = [
        "login",
        *(["login --link"] if mock.link_signin else []),
        "extract (ask 1)",
        "extract --link (fetch 1)",
        *(extraction.SKILLS_STEPS if mock.has_skills else []),
        "extract (ask 2)",
        "extract --link (fetch 2)",
        "session status",
        "logout",
        "snapshots",
    ]
    driving = (
        {"login", "extract (ask 1)", "extract (ask 2)"}
        | ({"extract --link (fetch 1)", "extract --link (fetch 2)"} if mock.session_bound else set())
        | ({"login --link"} if mock.link_signin else set())
        | (set(extraction.SKILLS_STEPS) if mock.has_skills else set())
    )
    traces = settings.root / "traces"
    traces.mkdir(parents=True, exist_ok=True)
    steps: list[running.Outcome] = []
    for position, name in enumerate(names, 1):
        refused = name == "extract-skills (again)"
        outcome = running.Outcome(
            name=name,
            argv=(name,),
            exit_code=2 if refused else 0,
            seconds=1.0,
            stdout=_stdout_for(name, mock, heading),
            stderr="error: snapshot already exists: …/skills/research-helper.skill\n" if refused else "",
        )
        if name in driving:
            outcome.trace = _trace_for(position, name, mock, traces).relative_to(settings.root)
            outcome.traces = 1
        steps.append(outcome)
    runner = running.Runner(settings=settings, env={}, steps=steps)
    return extraction.Half(
        mock=mock,
        settings=settings,
        runner=runner,
        extra_args=("--no-sandbox",),
        seeded={"chats": 3, "files": 1},
        links=changes.get("links", list(LINKS)),
        counted=changes.get("counted", dict(CLAUDE_LEDGER if mock.link_signin else LEDGER)),
        first_digest=changes.get("first_digest", extraction.digest_of(store_root / mock.source / extraction.ACCOUNT)),
        blocks={"ask": heading + "Export requested …", "fetch 1": heading + "Downloaded 0.0 MB.", "fetch 2": heading},
        archive_digest=changes.get("archive_digest", archive_digest),
        skills=changes.get("witness", [dict(item) for item in SKILLS]) if mock.has_skills else [],
    )


# --------------------------------------------------------------------------- #
# The runner's additions
# --------------------------------------------------------------------------- #


def test_the_link_is_masked_in_a_recorded_argv() -> None:
    argv = ["dataporter", "extract", "--link", LINKS[0]]
    assert running.masked(argv, (LINKS[0],)) == ("dataporter", "extract", "--link", "<link>")
    assert running.masked(argv, ()) == tuple(argv)
    assert running.masked(argv, ("",)) == tuple(argv)


def test_a_two_origin_mock_needs_nothing_of_chromes() -> None:
    """`65`: the second origin is a second port, not a second name to map.

    One resolver rule used to map both of the mock chatgpt.com's host names onto
    its single socket. There is no rule and no mapping now — the tool is told
    where to go by `--mock` — so the auth origin is simply another address it
    already knows.
    """
    settings = running.Settings(root=Path("/r"), mode="non-interactive", port=8444)
    arguments = running.chrome_args(settings)
    assert not [item for item in arguments if "resolver" in item or "certificate" in item]
    # What is left is the machine's, not the mock's.
    assert set(arguments) <= {"--no-proxy-server", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"}
    assert extraction.CHATGPT.hosts == ("chatgpt.com", "auth.openai.com")


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


def test_the_ledger_block_has_nine_rows_under_the_site_s_heading() -> None:
    assert extraction.ledger_block(extraction.CHATGPT, LEDGER) == (
        "Mock chatgpt.com — ledger\n"
        "\n"
        "Sign-ins:                      2\n"
        "Chats created:                 3\n"
        "Messages received:             3\n"
        "Files accepted:                1\n"
        "Renames:                       0\n"
        "Exports requested:             2\n"
        "Sign-in links minted:          0\n"
        "Skill lists read:              0\n"
        "Skills served:                 0"
    )
    assert extraction.ledger_block(extraction.CLAUDE, CLAUDE_LEDGER).endswith(
        "Sign-in links minted:          2\nSkill lists read:              3\nSkills served:                 9"
    )


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
    assert len(checks) == 21
    gap = next(item for item in checks if item.name.startswith("ledger: the gap"))
    assert gap.detail == "gaps [2, 2] == 1 × 2, files carried [0, 0]"


def test_the_claude_half_signs_in_with_two_commands_and_two_links(tmp_path: Path) -> None:
    """`49`: `login` and `login --link` both count, both leave a trace, and the mock minted two links."""
    half = half_for(tmp_path, extraction.CLAUDE)
    by_name = {item.name: item for item in extraction.criteria(half, store=tmp_path / "store")}
    assert by_name["login signs the source account in"].detail == "exit 0, login --link exit 0"
    assert by_name["ledger: sign-ins == the seeding's + the tool's"].detail == "2 == 1 + 1 (a link spent)"
    assert by_name["ledger: sign-in links minted == the seeding's + the tool's"].passed
    # Nine: `49`'s four, Claude's two fetches — a real link answered 403 to a
    # request without the session (`f9e0310`) — and `67`'s three skills runs.
    assert (
        by_name["one trace per step that drove a tab, each naming the source"].detail
        == "[1, 1, 1, 1, 1, 1, 1, 1, 1] for 9 steps"
    )

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


def test_the_skills_criteria_read_the_witness_and_the_manifests(tmp_path: Path) -> None:
    """`67`: what the tool filed against what the mock listed and served, in seven checks."""
    half = half_for(tmp_path, extraction.CLAUDE)
    by_name = {item.name: item for item in extraction.criteria(half, store=tmp_path / "store")}
    assert by_name["extract-skills files the account's own skills beside the archive"].detail == (
        f"{OURS} == {OURS}, counts.skills 3"
    )
    assert by_name["the gap is the one skill the mock refused"].detail == "gaps [1, 1] == 1 refused (broken-skill)"
    assert by_name["ledger: the mock served only the skills the account wrote, once per run"].detail == (
        "lists read 3 == 3, served 9 == 3 × 3"
    )
    assert by_name["a second extract-skills into the same stamp is refused"].detail == "exit 2"
    assert by_name["no skill's name is in a trace"].passed


def test_a_skill_that_is_not_ours_but_was_served_fails_the_ledger(tmp_path: Path) -> None:
    witness = [dict(item) for item in SKILLS]
    witness[4]["served"] = 3
    half = half_for(tmp_path, extraction.CLAUDE, witness=witness, counted={**CLAUDE_LEDGER, "skills_served": 12})
    failed = {item.name: item.detail for item in extraction.criteria(half, store=tmp_path / "store") if not item.passed}
    assert failed == {
        "ledger: the mock served only the skills the account wrote, once per run": (
            "lists read 3 == 3, served 12 == 3 × 3, served though not ours: docs"
        )
    }


def test_an_archive_the_append_changed_fails(tmp_path: Path) -> None:
    half = half_for(tmp_path, extraction.CLAUDE, archive_digest="0" * 64)
    failed = [item.name for item in extraction.criteria(half, store=tmp_path / "store") if not item.passed]
    assert failed == ["the append left the archive untouched"]


def test_a_second_run_that_was_not_refused_fails(tmp_path: Path) -> None:
    half = half_for(tmp_path, extraction.CLAUDE)
    for step in half.runner.steps:
        if step.name == "extract-skills (again)":
            step.exit_code = 0
            step.stderr = ""
    failed = [item.name for item in extraction.criteria(half, store=tmp_path / "store") if not item.passed]
    assert failed == ["a second extract-skills into the same stamp is refused"]


def test_a_name_in_a_skills_trace_fails(tmp_path: Path) -> None:
    half = half_for(tmp_path, extraction.CLAUDE)
    step = next(item for item in half.runner.steps if item.name == extraction.SKILLS_STEPS[0])
    assert step.trace is not None
    with (half.settings.root / step.trace).open("a", encoding="utf-8") as handle:
        handle.write(line(kind="sketch", controls=[{"role": "button", "label": "View standup-notes"}]) + "\n")
    failed = {item.name: item.detail for item in extraction.criteria(half, store=tmp_path / "store") if not item.passed}
    assert failed == {"no skill's name is in a trace": "standup-notes"}


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
    assert "Skills served:                 9" in text
    assert "extract-skills` into that snapshot" in text
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


RECORDS = tuple(sorted((Path(__file__).resolve().parents[1] / "docs").glob("rehearsal-0[3-9].md")))
"""Every extraction rehearsal recorded so far: `03` (`46`) and `04` (`67`)."""


@pytest.mark.skipif(not RECORDS, reason="no extraction rehearsal has been recorded")
@pytest.mark.parametrize("record", RECORDS, ids=lambda path: path.stem)
def test_the_committed_record_keeps_the_discipline(record: Path) -> None:
    """Every criterion row marked, both halves present, and no link anywhere in it (§66)."""
    text = record.read_text(encoding="utf-8")
    rows = [row for row in text.splitlines() if row.startswith("| ") and ("| pass |" in row or "| FAIL |" in row)]
    assert rows, "no criteria rows"
    assert all(re.search(r"\| \*measured on \d{4}-\d{2}-\d{2}\* \|$", row) for row in rows)
    assert "## The mock claude.ai" in text
    assert "## The mock chatgpt.com" in text
    assert "Exports requested:             2" in text
    assert "__mock/exports" not in text
    assert "**Chrome:** unknown" not in text
    if record.stem == "rehearsal-04":
        # `67`: the mock claude.ai served nine skill files over three runs, and its
        # ledger and its two blocks say so; the mock chatgpt.com has none to serve.
        assert "Skills served:                 9" in text
        assert "Skills served:                 0" in text
        assert text.count("Gaps: 1 skill could not be downloaded") == 2
        assert "no skill's name is in a trace | none | pass |" in text
