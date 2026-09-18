"""`extract-skills` (`66`, brief `09`): two reads, no clicks, and a snapshot that grows.

The refusals and the names are the fast half — nothing here needs a browser to
refuse a stamp or slug a name. Everything that opens the source session is
`slow` and runs against `fake_skills_page`, which answers the two reads by tag
and serves each skill's address the way Chrome serves a download.
"""

import hashlib
import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from dataporter import extract, extract_skills, log, store
from dataporter.browser import launcher, sites
from dataporter.browser import skills as reading
from dataporter.browser.cdp import CdpClient
from dataporter.browser.launcher import BrowserSession
from dataporter.config import (
    AccountsSettings,
    BrowserSettings,
    HermesSettings,
    Settings,
    StoreSettings,
    TimeoutSettings,
    with_account,
)
from dataporter.console import Collected
from dataporter.errors import AuthError, BrowserError, StoreError, UsageError
from dataporter.exit_codes import ExitCode
from dataporter.sources.claude import CLAUDE
from fake_chrome import FakeChrome, FakeTarget
from fake_skills_page import ORG, FakeSkillsPage, browser, entry

ACCOUNT = "work"
STAMP = "2026-09-18T09-14-02Z"

RESEARCH = b"PK\x03\x04" + b"r" * 4096
STANDUP = b"PK\x03\x04" + b"s" * 2696
"""4100 and 2700 bytes: `4.1 KB` and `2.7 KB` in `pretty_bytes`'s spelling."""


def four_entries() -> list[dict[str, object]]:
    """Two the account wrote — one switched off, inside a plugin — one of Anthropic's, one nobody's."""
    return [
        entry("skill_01a", "research-helper"),
        entry("skill_01b", "standup-notes", enabled=False, plugin="plugin_019x"),
        entry("skill_01c", "docs", "anthropic"),
        entry("skill_01d", "shared-thing", "acme"),
    ]


@pytest.fixture
def page() -> FakeSkillsPage:
    return FakeSkillsPage(entries=four_entries(), bodies={"skill_01a": RESEARCH, "skill_01b": STANDUP})


@pytest.fixture
def chrome(page: FakeSkillsPage) -> Iterator[FakeChrome]:
    with browser(page) as fake:
        yield fake


@pytest.fixture
def launches(monkeypatch: pytest.MonkeyPatch, chrome: FakeChrome) -> list[str]:
    urls: list[str] = []

    def fake_launch(settings: Settings, url: str) -> BrowserSession:
        urls.append(url)
        return BrowserSession(
            client=CdpClient(port=chrome.port, timeout=2.0),
            profile=settings.browser_profile_dir,
            adopted=True,
        )

    monkeypatch.setattr(launcher, "launch", fake_launch)
    return urls


def make_settings(port: int, tmp_path: Path, *, headless: bool | None = None, idle_s: float = 1.0) -> Settings:
    return with_account(
        Settings(
            workspace=tmp_path / "migration",
            accounts=AccountsSettings(dir=tmp_path / "accounts"),
            store=StoreSettings(dir=tmp_path / "store"),
            browser=BrowserSettings(cdp_port=port, headless=headless),
            hermes=HermesSettings(executable=tmp_path / "no-hermes-here", home=tmp_path / "hermes-home"),
            timeouts=TimeoutSettings(cdp_call_s=2.0, ask_s=0.5, login_s=0.5, download_idle_s=idle_s),
        ),
        "claude",
        ACCOUNT,
    )


@pytest.fixture
def settings(chrome: FakeChrome, tmp_path: Path) -> Settings:
    return make_settings(chrome.port, tmp_path)


def plain_settings(tmp_path: Path) -> Settings:
    """Return settings for a refusal that must happen before any browser: no port a fake answers on."""
    return make_settings(1, tmp_path)


def no_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(settings: Settings, url: str) -> BrowserSession:
        raise AssertionError("a browser was launched")

    monkeypatch.setattr(launcher, "launch", refuse)


def run(
    settings: Settings, *, stamp: str | None = None, **kwargs: object
) -> tuple[extract_skills.SkillsOutcome, Collected]:
    sink = Collected()
    outcome = extract_skills.extract_skills_command(
        settings,
        extract_skills.SkillsRequest(stamp=stamp),
        sink=sink,
        **kwargs,  # type: ignore[arg-type]
    )
    return outcome, sink


def snapshot_dir(settings: Settings, stamp: str) -> Path:
    return settings.store_dir / "claude" / ACCOUNT / stamp


def download_url(skill_id: str) -> str:
    return sites.skills_download_url(CLAUDE, ORG, skill_id)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- #
# Refused before a browser opens
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("stamp", ["yesterday", "../../x", "2026-09-18T09:14:02Z", ""])
def test_a_stamp_that_is_not_one_is_refused_before_a_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stamp: str
) -> None:
    """A stamp and nothing else (§89): the store orders by it, and `../..` is not a moment."""
    no_browser(monkeypatch)

    with pytest.raises(UsageError) as raised:
        run(plain_settings(tmp_path), stamp=stamp)

    assert str(raised.value) == extract_skills.BAD_STAMP.format(stamp=stamp)


def test_a_source_without_skills_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    no_browser(monkeypatch)
    settings = with_account(plain_settings(tmp_path), "chatgpt", ACCOUNT)

    with pytest.raises(UsageError) as raised:
        run(settings)

    assert str(raised.value) == "ChatGPT has no skills to extract"


def test_an_invocation_with_no_account_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    no_browser(monkeypatch)

    with pytest.raises(UsageError) as raised:
        run(Settings(workspace=tmp_path / "migration"))

    assert str(raised.value) == extract_skills.ACCOUNT_REQUIRED


# --------------------------------------------------------------------------- #
# Names
# --------------------------------------------------------------------------- #


def test_a_name_becomes_a_slug_and_a_collision_takes_a_number() -> None:
    """The vendor's own rule made a filename, with `-1`, `-2` where two names agree (§91)."""
    listed = [
        reading.Listed("a", "research-helper", "user"),
        reading.Listed("b", "Research Helper!", "user"),
        reading.Listed("c", "research-helper", "user"),
        reading.Listed("d", "", "user"),
        reading.Listed("e", "../etc/passwd", "user"),
    ]

    assert extract_skills.filenames_for(listed) == {
        "a": "research-helper.skill",
        "b": "research-helper-1.skill",
        "c": "research-helper-2.skill",
        "d": "skill.skill",
        "e": "etc-passwd.skill",
    }


def test_the_same_list_names_the_same_files_twice() -> None:
    """Deterministic by construction, which is what lets a second run be refused rather than re-suffixed."""
    listed = [reading.Listed("a", "x", "user"), reading.Listed("b", "x", "user")]
    assert extract_skills.filenames_for(listed) == extract_skills.filenames_for(list(listed))


# --------------------------------------------------------------------------- #
# In the account
# --------------------------------------------------------------------------- #


@pytest.mark.slow
def test_the_skills_the_account_wrote_are_fetched_and_the_rest_are_not(
    settings: Settings, page: FakeSkillsPage, launches: list[str]
) -> None:
    """Two of four: `creator_type == "user"` and nothing else decides (§90).

    Anthropic's is not fetched, and neither is one with a `creator_type` the
    tool does not know — an unknown value is somebody else's until a person
    says otherwise. Switched off and inside a plugin are recorded, never filtered.
    """
    outcome, _ = run(settings)

    assert launches == [sites.export_page_url(CLAUDE)]
    assert page.fetched == [download_url("skill_01a"), download_url("skill_01b")]
    assert page.reads[:2] != [reading.LIST_TAG, reading.ORG_TAG]
    assert outcome.exit_code == ExitCode.OK
    assert outcome.skills == 2
    assert outcome.snapshot is not None
    assert outcome.path is not None
    assert outcome.path.name == store.SKILLS_DIRNAME
    assert (outcome.path / "research-helper.skill").read_bytes() == RESEARCH
    assert (outcome.path / "standup-notes.skill").read_bytes() == STANDUP
    assert outcome.snapshot.skills == [
        store.SkillFile(name="research-helper", filename="research-helper.skill", bytes=4100, sha256=sha256(RESEARCH)),
        store.SkillFile(
            name="standup-notes",
            filename="standup-notes.skill",
            bytes=2700,
            sha256=sha256(STANDUP),
            enabled=False,
            plugin=True,
        ),
    ]
    assert outcome.snapshot.origin == "skills"
    assert outcome.snapshot.archive == store.Archive()
    assert outcome.snapshot.counts.skills == 2
    assert outcome.snapshot.gaps == []
    # Staged under the account home on the way, and gone once filed.
    home = settings.accounts_dir / "claude" / ACCOUNT
    assert list((home / extract.TMP_DIRNAME).iterdir()) == []


@pytest.mark.slow
def test_the_block_is_the_brief_block(settings: Settings, page: FakeSkillsPage, launches: list[str]) -> None:
    """§94's block, byte for byte, with `60`'s line per skill before it and the clock pinned."""
    outcome, sink = run(settings, stamp=STAMP, clock=iter((0.0, 4.0)).__next__)

    assert outcome.path is not None
    assert sink.stdout == (
        "downloaded  research-helper.skill  4.1 KB\n"
        "downloaded  standup-notes.skill  2.7 KB\n"
        "Claude skills — work\n"
        "\n"
        "Downloaded 2 skills in 4s.\n"
        "2 skills.\n"
        "\n"
        f"Snapshot: {settings.store_dir}/claude/work/{STAMP}/skills\n"
    )
    assert not sink.stderr


@pytest.mark.slow
def test_quiet_drops_the_lines_and_keeps_the_block(settings: Settings, launches: list[str]) -> None:
    _, sink = run(settings, quiet=True)

    assert sink.stdout.startswith("Claude skills — work\n")
    assert "downloaded" not in sink.stdout


@pytest.mark.slow
def test_one_skill_is_one_skill(settings: Settings, page: FakeSkillsPage, launches: list[str]) -> None:
    page.entries = [entry("skill_01a", "research-helper")]

    _, sink = run(settings, stamp=STAMP, clock=iter((0.0, 0.2)).__next__)

    assert "Downloaded 1 skill in 0s.\n1 skill.\n" in sink.stdout


@pytest.mark.slow
def test_a_skill_that_will_not_download_is_a_gap_and_the_run_succeeds(
    settings: Settings, page: FakeSkillsPage, launches: list[str]
) -> None:
    """Listed and not landed is a gap (§93): recorded, counted, and not fatal."""
    del page.bodies["skill_01b"]

    outcome, sink = run(settings, stamp=STAMP, clock=iter((0.0, 1.0)).__next__)

    assert outcome.exit_code == ExitCode.OK
    assert outcome.skills == 1
    assert outcome.snapshot is not None
    assert outcome.snapshot.gaps == [
        store.Gap(kind=extract_skills.NOT_DOWNLOADED, count=1, reason="skill could not be downloaded")
    ]
    assert outcome.snapshot.counts.skills == 1
    assert sink.stdout == (
        "downloaded  research-helper.skill  4.1 KB\n"
        "Claude skills — work\n"
        "\n"
        "Downloaded 1 skill in 1s.\n"
        "1 skill.\n"
        "Gaps: 1 skill could not be downloaded\n"
        "\n"
        f"Snapshot: {settings.store_dir}/claude/work/{STAMP}/skills\n"
    )
    assert store.Store(settings.store_dir).rows()[0].gaps == 1


@pytest.mark.slow
def test_a_download_that_stalls_is_the_same_gap(
    chrome: FakeChrome, page: FakeSkillsPage, launches: list[str], tmp_path: Path
) -> None:
    page.stalls.add("skill_01a")
    settings = make_settings(chrome.port, tmp_path, idle_s=0.4)

    outcome, _ = run(settings)

    assert outcome.snapshot is not None
    assert [skill.name for skill in outcome.snapshot.skills] == ["standup-notes"]
    assert outcome.snapshot.gap_count == 1


@pytest.mark.slow
def test_an_account_that_wrote_none_is_a_success_and_no_snapshot(
    settings: Settings, page: FakeSkillsPage, launches: list[str]
) -> None:
    """§94's other block: nothing filed, nothing fetched, and no directory that records an absence."""
    page.entries = [entry("skill_01c", "docs", "anthropic")]

    outcome, sink = run(settings)

    assert outcome.exit_code == ExitCode.OK
    assert outcome.snapshot is None
    assert page.fetched == []
    assert sink.stdout == "Claude skills — work\n\nNo skills of your own to extract.\n"
    assert not settings.store_dir.exists()


@pytest.mark.slow
def test_stamp_adds_beside_an_archive_and_leaves_the_archive_alone(
    settings: Settings, page: FakeSkillsPage, launches: list[str], export_zip: Path
) -> None:
    """`--stamp` names the morning's snapshot, and the skills join it (§91, ADR 0011).

    Everything the archive extraction wrote is byte-identical afterwards — the
    archive, its fingerprint, its parts, its counts — and the manifest names
    both halves.
    """
    first = extract.file(settings, export_zip)
    assert first.path is not None
    stamp = first.path.name
    archive_before = (first.path / store.ARCHIVE_NAME).read_bytes()

    outcome, _ = run(settings, stamp=stamp)

    assert outcome.snapshot is not None
    assert first.snapshot is not None
    after = store.read_manifest(first.path / store.MANIFEST_NAME)
    assert after == outcome.snapshot
    assert (first.path / store.ARCHIVE_NAME).read_bytes() == archive_before
    assert after.archive == first.snapshot.archive
    assert after.parts == first.snapshot.parts
    assert after.export_fingerprint == first.snapshot.export_fingerprint
    assert after.counts.conversations == first.snapshot.counts.conversations
    assert after.counts.skills == 2
    assert after.origin == "file"
    assert (first.path / store.COMPLETE_NAME).exists()
    row = store.Store(settings.store_dir).rows()[0]
    assert (row.state, row.conversations, row.skills) == ("complete", first.snapshot.counts.conversations, 2)


@pytest.mark.slow
def test_a_second_run_into_the_same_stamp_refuses_and_rewrites_nothing(
    chrome: FakeChrome, page: FakeSkillsPage, launches: list[str], tmp_path: Path
) -> None:
    """Refused by the store, and the snapshot is byte for byte what the first run left.

    Two browsers, because a run closes the one it opened — Chrome flushes its
    cookie jar on exit — so the second run is a second fake on the same port.
    """
    settings = make_settings(chrome.port, tmp_path)
    outcome, _ = run(settings, stamp=STAMP)
    assert outcome.path is not None
    directory = outcome.path.parent
    before = {item.name: item.read_bytes() for item in directory.rglob("*") if item.is_file()}

    again = FakeSkillsPage(entries=four_entries(), bodies=dict(page.bodies))
    with browser(again, port=chrome.port), pytest.raises(StoreError) as raised:
        run(settings, stamp=STAMP)

    assert str(raised.value) == f"snapshot already exists: {directory / 'skills' / 'research-helper.skill'}"
    assert {item.name: item.read_bytes() for item in directory.rglob("*") if item.is_file()} == before
    assert (directory / store.COMPLETE_NAME).exists()


@pytest.mark.slow
def test_a_stamp_that_does_not_exist_is_created_and_listed_complete(
    settings: Settings, page: FakeSkillsPage, launches: list[str]
) -> None:
    outcome, _ = run(settings, stamp=STAMP)

    directory = snapshot_dir(settings, STAMP)
    assert outcome.path == directory / store.SKILLS_DIRNAME
    assert sorted(item.name for item in directory.iterdir()) == ["COMPLETE", "skills", "snapshot.json"]
    rows = store.Store(settings.store_dir).rows()
    assert [(row.stamp, row.state, row.conversations, row.skills) for row in rows] == [(STAMP, "complete", 0, 2)]
    assert store.listing(rows) == f"claude/work   {STAMP}   2 skills   complete\n"


@pytest.mark.slow
def test_signed_out_is_exit_3_and_nothing_is_read(
    settings: Settings, page: FakeSkillsPage, launches: list[str]
) -> None:
    """A source signed in by a link has no unattended sign-in: `login` is the remedy, and no read is made."""
    page.signed_out = True

    with pytest.raises(AuthError) as raised:
        run(settings)

    assert raised.value.detail == "not logged in — run: dataporter login --source claude --account work"
    assert reading.LIST_TAG not in page.reads
    assert page.fetched == []


@pytest.mark.slow
def test_two_tabs_on_the_surface_is_a_refusal_before_any_read(
    chrome: FakeChrome, settings: Settings, page: FakeSkillsPage, launches: list[str]
) -> None:
    """`08`'s rule, kept: exactly one tab, or no."""
    chrome.targets.append(FakeTarget(id="page-2", url=page.url))

    with pytest.raises(BrowserError) as raised:
        run(settings)

    assert raised.value.detail == "ambiguous_tab"
    assert page.reads.count(reading.ORG_TAG) == 0


@pytest.mark.slow
def test_a_list_that_cannot_be_read_files_nothing(
    settings: Settings, page: FakeSkillsPage, launches: list[str]
) -> None:
    """The list that will not be read is an error, not a gap (§93)."""
    page.list_status = 503

    with pytest.raises(BrowserError) as raised:
        run(settings)

    assert raised.value.detail == "could not read the account's skills (HTTP 503)"
    assert page.fetched == []
    assert not settings.store_dir.exists()


@pytest.mark.slow
def test_headless_names_the_bot_check_when_a_read_fails(
    chrome: FakeChrome, page: FakeSkillsPage, launches: list[str], tmp_path: Path
) -> None:
    """The same hint the ask gives: the page is the app shell, and headless never reaches it."""
    page.org = None
    settings = make_settings(chrome.port, tmp_path, headless=True)

    with pytest.raises(BrowserError) as raised:
        run(settings)

    # `HTTP 200` and not `no answer`: the site answered, and with nothing usable,
    # which is what an interstitial's page looks like to a same-origin `fetch`.
    assert raised.value.detail == (
        "could not read the account's organisation (HTTP 200)"
        "; headless Chrome is served a bot check on this page — try without --non-interactive"
    )


@pytest.mark.slow
def test_no_name_reaches_the_log_or_the_trace(settings: Settings, page: FakeSkillsPage, launches: list[str]) -> None:
    """Names go on stdout and into the manifest, and nowhere else (§38, §46).

    The run log carries the staging path, which is a guid; the trace carries
    the download address as a path and its query's names, so a skill's `id`
    is not there either.
    """
    log.configure_logging()
    _, sink = run(settings)

    logs = Path(settings.logs_dir) / "logs"
    written = "\n".join(path.read_text(encoding="utf-8") for path in sorted(logs.glob("*.jsonl")))
    assert "research-helper" in sink.stdout
    for secret in ("research-helper", "standup-notes", "skill_01a", "A description the tool never reads"):
        assert secret not in written
    trace = [json.loads(line) for path in sorted(logs.glob("trace-*.jsonl")) for line in path.read_text().splitlines()]
    moves = [line for line in trace if line.get("kind") == "move"]
    assert [move["helper"] for move in moves] == [
        reading.ORG_ACTION,
        reading.LIST_ACTION,
        "download",
        "download",
    ]
    assert moves[2]["result"]["query"] == ["skill_id"]
    assert re.fullmatch(r"/api/organizations/[0-9a-f-]{36}/skills/download-dot-skill-file", moves[2]["result"]["path"])
