"""`17`: the chat the tool goes back and reads for itself.

Three layers, and they are deliberately separate:

- **The checks**, which are a pure function of one `PageReport` and one
  `Expected`. What a chat has to hold for a conversation to count as migrated is
  the whole of this slice, and it is tested here with no browser, no fixtures and
  no clock — a report built by hand, and an answer.
- **The verifier**, which navigates a tab and reads the page back through the
  real probe and the real safety gate, against the modelled claude.ai page `08`
  and `11` are tested against.
- **The two callers**: the import loop, which must record `partial` over a Hermes
  that claimed `completed` for a chat missing a part, and the `verify` command,
  which must do the same thing from a cold workspace without Hermes anywhere near
  it.

The acceptance criteria of `17` are the four tests under *Acceptance*.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataporter import cli, render, state
from dataporter import intervention as intervening
from dataporter import verify as verifying
from dataporter.browser import launcher, probe
from dataporter.browser.session import SIGNED_OUT
from dataporter.config import FidelitySettings, SeedSettings, Settings
from dataporter.errors import Category
from dataporter.exit_codes import ExitCode
from dataporter.state import ConversationState, ErrorRecord, Status
from fake_composer import Browser, FakePage, Turn
from world import LONG, World, cli_env, completed, needs_human

SOURCE = "aa000001-1111-4111-8111-111111111111"
SHORT = "aa000001"
CHAT = "b6f0a2d4-1c88-4e3a-9a1f-2f0e5d7c8b91"
CHAT_URL = f"https://claude.ai/chat/{CHAT}"
NEW_URL = "https://claude.ai/new"
TITLE = "Notes on pooling"

SOURCE_LINE = render.source_id_line(SOURCE)
ACK_1 = render.ack_line(SHORT, 1, 2)
ACK_2 = render.ack_line(SHORT, 2, 2)


def expected(**fields: object) -> verifying.Expected:
    """What a two-part conversation's chat has to hold, unless a test says else."""
    return verifying.Expected(
        **{
            "conversation_uuid": SOURCE,
            "conversation_id": CHAT,
            "parts": 2,
            "title": TITLE,
            **fields,
        }  # type: ignore[arg-type]
    )


def turn(role: str, *contains: str, chars: int = 40) -> probe.LastMessage:
    return probe.LastMessage(role=role, chars=chars, contains=contains)  # type: ignore[arg-type]


def report(
    *messages: probe.LastMessage,
    url: str = CHAT_URL,
    title_matches: bool | None = True,
) -> probe.PageReport:
    """One look at a page, built rather than read off a browser."""
    page_state = probe.PageState(
        url=url,
        kind=probe.kind_of(url),
        logged_in=True,
        composer_present=True,
        composer_chars=0,
        generating=False,
        send_enabled=False,
        dialogs=(),
        conversation_id=probe.conversation_id_of(url),
        tab_count=1,
    )
    return probe.PageReport(
        state=page_state,
        last_message=messages[-1] if messages else turn("assistant"),
        messages=messages,
        title=probe.TitleMatch(chars=len(TITLE), source="chat", matches=title_matches),
    )


def migrated() -> probe.PageReport:
    """A chat holding both parts and both acknowledgements."""
    return report(
        turn("human", SOURCE_LINE),
        turn("assistant", ACK_1),
        turn("human"),
        turn("assistant", ACK_2),
    )


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #


def test_a_chat_that_holds_everything_verifies() -> None:
    found = verifying.checks(migrated(), expected())
    assert found.ok
    assert found.failed is None
    assert found.title_set
    assert found.limitations == (verifying.TIMESTAMPS_NOT_PRESERVED,)
    assert found.line() == f"{SHORT}  verified"


def test_a_missing_acknowledgement_names_the_part() -> None:
    found = verifying.checks(
        report(
            turn("human", SOURCE_LINE),
            turn("assistant", ACK_1),
            turn("human"),
            turn("assistant"),
        ),
        expected(),
    )
    assert found.failed == "ack 2/2 missing"
    assert found.line() == f"{SHORT}  FAILED  ack 2/2 missing"


def test_a_url_that_is_not_this_chat_is_a_missing_chat() -> None:
    """The id in the URL is the whole identity of a destination chat (§7)."""
    other = f"https://claude.ai/chat/{'c7e1b3f5-2d99-4f4b-8b2a-3a1f6e8d9c02'}"
    found = verifying.checks(migrated_at(other), expected())
    assert found.failed == verifying.CHAT_MISSING


def migrated_at(url: str) -> probe.PageReport:
    return report(
        turn("human", SOURCE_LINE),
        turn("assistant", ACK_1),
        turn("human"),
        turn("assistant", ACK_2),
        url=url,
    )


def test_a_page_that_is_not_a_chat_at_all_is_a_missing_chat() -> None:
    assert verifying.checks(report(url=NEW_URL), expected()).failed == (
        verifying.CHAT_MISSING
    )


def test_fewer_human_messages_than_parts_is_missing_history() -> None:
    found = verifying.checks(
        report(turn("human", SOURCE_LINE), turn("assistant", ACK_1, ACK_2)),
        expected(),
    )
    assert found.failed == verifying.HISTORY_MISSING


def test_a_first_message_without_the_source_id_is_somebody_elses_chat() -> None:
    """Two parts are there and the header line is not: whatever this chat holds,
    it is not this conversation."""
    found = verifying.checks(
        report(
            turn("human"),
            turn("assistant", ACK_1),
            turn("human"),
            turn("assistant", ACK_2),
        ),
        expected(),
    )
    assert found.failed == verifying.SOURCE_ID_MISSING


def test_the_source_id_is_looked_for_in_the_first_message_only() -> None:
    """`04` writes the header into every part, but the first human turn is the
    one that says this chat *starts* with this conversation."""
    found = verifying.checks(
        report(
            turn("human"),
            turn("human", SOURCE_LINE),
            turn("assistant", ACK_1, ACK_2),
        ),
        expected(),
    )
    assert found.failed == verifying.SOURCE_ID_MISSING


def test_an_acknowledgement_counts_only_from_an_assistant_turn() -> None:
    """The ack line is in the seed, so it is in the human message too. A chat
    where only the human said it is a chat where nobody answered."""
    found = verifying.checks(
        report(
            turn("human", SOURCE_LINE, ACK_1),
            turn("human", ACK_2),
            turn("assistant", ACK_1),
        ),
        expected(),
    )
    assert found.failed == "ack 2/2 missing"


# --------------------------------------------------------------------------- #
# The title, which is a limitation and never a failure
# --------------------------------------------------------------------------- #


def test_a_title_that_did_not_take_is_recorded_and_not_failed() -> None:
    found = verifying.checks(migrated_title(False), expected())
    assert found.ok
    assert not found.title_set
    assert verifying.TITLE_NOT_SET in found.limitations


def migrated_title(matches: bool | None) -> probe.PageReport:
    return report(
        turn("human", SOURCE_LINE),
        turn("assistant", ACK_1),
        turn("human"),
        turn("assistant", ACK_2),
        title_matches=matches,
    )


def test_no_title_to_set_is_the_same_limitation() -> None:
    """`fidelity.rename_title = false`, or a source conversation with no name."""
    found = verifying.checks(migrated_title(None), expected(title=""))
    assert found.ok
    assert found.limitations == (
        verifying.TIMESTAMPS_NOT_PRESERVED,
        verifying.TITLE_NOT_SET,
    )


def test_a_chat_that_is_not_this_one_is_never_correctly_titled() -> None:
    """A page we could not identify says nothing about *this* conversation.

    The `matches` below is `true` — a redirect to a chat somebody renamed the
    same way, or a title element that outlived the navigation — and it must not
    become "the title was set", because the only thing this page established is
    that the chat is missing. (Raised by Copilot in review on #26.)
    """
    found = verifying.checks(migrated_at(NEW_URL), expected())
    assert found.failed == verifying.CHAT_MISSING
    assert not found.title_set
    assert verifying.TITLE_NOT_SET in found.limitations


def test_timestamps_are_a_limitation_of_every_chat_that_lands() -> None:
    """Even one that failed a check: the messages that *are* there were still
    timestamped when they were pasted."""
    found = verifying.checks(report(url=NEW_URL), expected())
    assert verifying.TIMESTAMPS_NOT_PRESERVED in found.limitations


# --------------------------------------------------------------------------- #
# What gets typed, and what gets compared
# --------------------------------------------------------------------------- #


def test_a_title_is_squashed_before_it_is_compared() -> None:
    """The rename field takes what it is given; the header renders it with
    whatever spacing the layout wants."""
    assert verifying.capped_title("  Notes   on\npooling ", 200) == TITLE


def test_a_long_title_is_truncated_with_an_ellipsis() -> None:
    capped = verifying.capped_title("x" * 300, 200)
    assert len(capped) == 200
    assert capped.endswith(verifying.ELLIPSIS)


def test_renaming_can_be_switched_off() -> None:
    settings = Settings(
        workspace=Path("/tmp/nowhere"),
        fidelity=FidelitySettings(rename_title=False),
    )
    assert verifying.intended_title(settings, TITLE) == ""


def test_the_cap_is_configurable() -> None:
    settings = Settings(
        workspace=Path("/tmp/nowhere"), fidelity=FidelitySettings(title_max_chars=5)
    )
    assert verifying.intended_title(settings, "abcdefgh") == "abcd…"


# --------------------------------------------------------------------------- #
# Choosing what to verify
# --------------------------------------------------------------------------- #


def entry(**fields: object) -> ConversationState:
    return ConversationState.model_validate(
        {
            "title": TITLE,
            "status": Status.COMPLETED,
            "destination": {"conversation_id": CHAT},
            "chunks_total": 2,
            **fields,
        }
    )


def settings_for(tmp_path: Path) -> Settings:
    return Settings(workspace=tmp_path)


def test_an_entry_with_no_chat_has_nothing_to_verify(tmp_path: Path) -> None:
    assert (
        verifying.expected_for(settings_for(tmp_path), SOURCE, entry(destination={}))
        is None
    )


def test_an_entry_with_no_parts_has_nothing_to_verify(tmp_path: Path) -> None:
    """An attempt that never got as far as writing a seed. There is no part to
    look for, so "every part is there" is not a question about this chat."""
    assert (
        verifying.expected_for(settings_for(tmp_path), SOURCE, entry(chunks_total=0))
        is None
    )


def test_only_completed_and_partial_entries_are_verifiable(tmp_path: Path) -> None:
    migration = state.MigrationState(
        root={
            "a" + SOURCE[1:]: entry(status=Status.COMPLETED),
            "b" + SOURCE[1:]: entry(status=Status.PARTIAL),
            "c" + SOURCE[1:]: entry(status=Status.FAILED),
            "d" + SOURCE[1:]: entry(status=Status.PENDING),
            "e" + SOURCE[1:]: entry(status=Status.COMPLETED, destination={}),
        }
    )
    chosen = [
        uuid for uuid, _ in verifying.verifiable(settings_for(tmp_path), migration)
    ]
    assert chosen == ["a" + SOURCE[1:], "b" + SOURCE[1:]]


def test_the_expectations_come_off_the_entry(tmp_path: Path) -> None:
    found = verifying.expected_for(settings_for(tmp_path), SOURCE, entry())
    assert found is not None
    assert found.url == CHAT_URL
    assert found.short_id == SHORT
    assert found.acks == (ACK_1, ACK_2)
    assert found.expect == (SOURCE_LINE, ACK_1, ACK_2)


# --------------------------------------------------------------------------- #
# What it writes down
# --------------------------------------------------------------------------- #


def verification(**fields: object) -> verifying.Verification:
    return verifying.Verification.model_validate(
        {"conversation_uuid": SOURCE, "conversation_id": CHAT, **fields}
    )


def test_a_passed_check_stamps_the_time_and_keeps_the_status(tmp_path: Path) -> None:
    store = state.StateStore(tmp_path)
    store.update(SOURCE, **entry().model_dump())
    written = verifying.record(store, SOURCE, verification(limitations=("a", "b")))
    assert written.status is Status.COMPLETED
    assert written.verified_at is not None
    assert written.limitations == ["a", "b"]


def test_a_failed_check_writes_partial_over_completed(tmp_path: Path) -> None:
    store = state.StateStore(tmp_path)
    store.update(SOURCE, **entry().model_dump())
    written = verifying.record(store, SOURCE, verification(failed="ack 2/2 missing"))
    assert written.status is Status.PARTIAL
    assert written.verified_at is None
    assert written.error == ErrorRecord(
        category=Category.VERIFICATION,
        detail="ack 2/2 missing",
        retry_recommended=True,
    )


def test_a_failed_check_never_overwrites_a_reason(tmp_path: Path) -> None:
    """A run that already said why it stopped keeps that reason — and keeps its
    `retry_recommended`, so a verification cannot recommend another go at
    something `01` classified as not worth retrying."""
    refused = ErrorRecord(
        category=Category.SAFETY,
        detail="off the migration surface",
        retry_recommended=False,
    )
    store = state.StateStore(tmp_path)
    store.update(SOURCE, **entry(status=Status.PARTIAL, error=refused).model_dump())
    written = verifying.record(
        store, SOURCE, verification(failed=verifying.CHAT_MISSING)
    )
    assert written.error == refused
    assert written.status is Status.PARTIAL


def test_the_rendering_limitations_keep_their_place(tmp_path: Path) -> None:
    """`04`'s slugs describe the export, `17`'s describe the account, and both
    belong to the conversation — in that order, each one once."""
    store = state.StateStore(tmp_path)
    store.update(SOURCE, **entry(limitations=["thinking_omitted:3"]).model_dump())
    written = verifying.record(
        store,
        SOURCE,
        verification(
            limitations=("thinking_omitted:3", verifying.TIMESTAMPS_NOT_PRESERVED)
        ),
    )
    assert written.limitations == ["thinking_omitted:3", "timestamps_not_preserved"]


# --------------------------------------------------------------------------- #
# Reading a real page, through the real probe and the real gate
# --------------------------------------------------------------------------- #


def transcript() -> list[Turn]:
    """A chat holding both parts, as the modelled page renders them."""
    return [
        Turn("human", f"{SOURCE_LINE}\nPart 1 of 2"),
        Turn("assistant", ACK_1),
        Turn("human", "part 2"),
        Turn("assistant", ACK_2),
    ]


@pytest.fixture
def chat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[tuple[Browser, FakePage]]:
    """One tab, on a new chat, whose chat URL holds a migrated conversation."""
    page = FakePage(url=NEW_URL, composer="", transcript=transcript(), title=TITLE)
    browser = Browser(page)
    browser.__enter__()
    monkeypatch.setenv("HCM_BROWSER__CDP_PORT", str(browser.chrome.port))
    try:
        yield browser, page
    finally:
        browser.chrome.stop()


def verifier(browser: Browser, tmp_path: Path) -> verifying.Verifier:
    return verifying.Verifier(browser.settings(tmp_path), browser.client, poll_s=0.01)


@pytest.mark.slow
def test_the_tab_is_navigated_to_the_chat_and_read_back(
    chat: tuple[Browser, FakePage], tmp_path: Path
) -> None:
    browser, page = chat
    found = verifier(browser, tmp_path).verify(expected())
    assert found.ok, found.failed
    assert page.url == CHAT_URL


@pytest.mark.slow
def test_a_transcript_without_the_second_ack_fails_the_second_part(
    chat: tuple[Browser, FakePage], tmp_path: Path
) -> None:
    browser, page = chat
    page.transcript = transcript()[:3]
    assert verifier(browser, tmp_path).verify(expected()).failed == "ack 2/2 missing"


@pytest.mark.slow
def test_a_tab_that_cannot_be_read_is_not_a_verified_chat(
    chat: tuple[Browser, FakePage], tmp_path: Path
) -> None:
    """The browser is gone. A verification that cannot look does not pass, and
    does not raise into a run that is migrating the next conversation."""
    browser, _ = chat
    browser.chrome.stop()
    found = verifier(browser, tmp_path).verify(expected())
    assert found.failed == verifying.CHAT_UNREADABLE
    assert found.limitations == (
        verifying.TIMESTAMPS_NOT_PRESERVED,
        verifying.TITLE_NOT_SET,
    )


@pytest.mark.slow
def test_a_transcript_that_has_not_rendered_yet_is_waited_for(
    chat: tuple[Browser, FakePage], tmp_path: Path
) -> None:
    """A reloaded chat is at its URL before its messages are in the DOM, and
    reading that moment would call a migrated conversation empty."""
    browser, page = chat
    full, page.transcript = transcript(), []

    def render_after_two(current: FakePage, views: int) -> None:
        if views >= 2:
            current.transcript = full

    page.on_view = render_after_two
    assert verifier(browser, tmp_path).verify(expected()).ok


@pytest.mark.slow
def test_a_navigation_still_in_flight_is_not_a_missing_chat(
    chat: tuple[Browser, FakePage], tmp_path: Path
) -> None:
    """`Page.navigate` returns before the tab shows the page it asked for.

    The tab is still on `/new` for the first two reads, which is what a slow
    load looks like from here — and calling that `chat missing` would fail a
    conversation for the speed of a page.
    """
    browser, page = chat
    page.follows_navigation = False

    def arrive(current: FakePage, views: int) -> None:
        if views >= 2:
            current.url = CHAT_URL

    page.on_view = arrive
    assert verifier(browser, tmp_path).verify(expected()).ok


@pytest.mark.slow
def test_landing_in_another_chat_ends_the_wait_at_once(
    chat: tuple[Browser, FakePage], tmp_path: Path
) -> None:
    """A tab that settled in somebody else's chat is settled: waiting out
    `timeouts.verify_s` would add half a minute to a verification whose answer
    is already known. (Raised by Copilot in review on #26.)"""
    browser, page = chat
    page.url = f"https://claude.ai/chat/{'c7e1b3f5-2d99-4f4b-8b2a-3a1f6e8d9c02'}"
    page.follows_navigation = False

    found = verifier(browser, tmp_path).verify(expected())

    assert found.failed == verifying.CHAT_MISSING
    # One look at the page, not `verify_s` divided by the poll interval.
    assert page.views == 1


@pytest.mark.slow
def test_a_session_that_expires_mid_verification_stops_the_read(
    chat: tuple[Browser, FakePage], tmp_path: Path
) -> None:
    """The wall is re-checked on every poll, as `08`'s response wait checks it:
    a tab redirected to a page no helper may read is not read."""
    browser, page = chat
    # The chat is reached and is still rendering, so the poll goes round again —
    # and by then the tab is on a sign-in page.
    page.transcript = []

    def expire(current: FakePage, views: int) -> None:
        if views >= 2:
            current.url = "https://claude.ai/login?returnTo=/chat"

    page.on_view = expire

    found = verifier(browser, tmp_path).verify(expected())

    assert found.failed == verifying.CHAT_UNREADABLE
    assert page.views == 2


@pytest.mark.slow
def test_a_browser_with_no_claude_tab_cannot_be_read_through(
    chat: tuple[Browser, FakePage], tmp_path: Path
) -> None:
    """`08`'s tab rules are `17`'s too: there is nothing to navigate."""
    browser, _ = chat
    browser.visit("about:blank")
    found = verifier(browser, tmp_path).verify(expected())
    assert found.failed == verifying.CHAT_UNREADABLE


@pytest.mark.slow
def test_it_will_not_read_a_chat_through_a_tab_outside_the_surface(
    chat: tuple[Browser, FakePage], tmp_path: Path
) -> None:
    """§17's wall, which `17` is behind like every other helper: the tab is on a
    settings page, so nothing navigates it anywhere."""
    browser, page = chat
    browser.visit("https://claude.ai/settings/profile")
    found = verifier(browser, tmp_path).verify(expected())
    assert found.failed == verifying.CHAT_UNREADABLE
    assert page.url == "https://claude.ai/settings/profile"


# --------------------------------------------------------------------------- #
# Acceptance
# --------------------------------------------------------------------------- #


def workspace_with(
    tmp_path: Path, browser: Browser, monkeypatch: pytest.MonkeyPatch, **fields: object
) -> state.StateStore:
    """A workspace holding one migrated conversation, and a browser to read it."""
    settings = Settings(workspace=tmp_path / "migration")
    profile = launcher.ensure_profile(settings)
    launcher.write_marker(
        profile,
        launcher.ProfileMarker(
            port=browser.chrome.port,
            browser_id=browser.chrome.browser_id,
            pid=1,
            started="now",
        ),
    )
    monkeypatch.setenv("HCM_WORKSPACE", str(settings.workspace))
    monkeypatch.setenv("HCM_BROWSER__CDP_PORT", str(browser.chrome.port))
    monkeypatch.setenv("HCM_TIMEOUTS__CDP_CALL_S", "2")
    monkeypatch.setenv("HCM_TIMEOUTS__VERIFY_S", "1")
    store = state.StateStore(settings.workspace)
    store.update(SOURCE, **{**entry().model_dump(), **fields})
    return store


@pytest.mark.slow
def test_verify_passes_and_stamps_the_time(
    chat: tuple[Browser, FakePage],
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`17`'s first acceptance criterion: two parts, both acks, `verified`."""
    browser, _ = chat
    store = workspace_with(tmp_path, browser, monkeypatch)

    result = runner.invoke(cli.app, ["verify"], catch_exceptions=False)

    assert result.exit_code == ExitCode.OK
    assert result.stdout == f"{SHORT}  verified\n"
    assert state.StateStore(store.workspace).load()[SOURCE].verified_at is not None


@pytest.mark.slow
def test_verify_reports_the_check_that_failed(
    chat: tuple[Browser, FakePage],
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same fixture with one acknowledgement removed."""
    browser, page = chat
    page.transcript = transcript()[:3]
    store = workspace_with(tmp_path, browser, monkeypatch)

    result = runner.invoke(cli.app, ["verify"], catch_exceptions=False)

    assert result.exit_code == ExitCode.FAILED
    assert result.stdout == f"{SHORT}  FAILED  ack 2/2 missing\n"
    written = state.StateStore(store.workspace).load()[SOURCE]
    assert written.status is Status.PARTIAL
    assert written.verified_at is None


@pytest.mark.slow
def test_verify_reports_a_chat_that_is_not_there(
    chat: tuple[Browser, FakePage],
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The id in the entry names a chat this browser does not end up in."""
    browser, page = chat
    page.url = NEW_URL
    store = workspace_with(
        tmp_path,
        browser,
        monkeypatch,
        destination={"conversation_id": "c7e1b3f5-2d99-4f4b-8b2a-3a1f6e8d9c02"},
    )
    # The modelled page follows a navigation; this one refuses to, which is what
    # a chat that 404s or redirects looks like from here.
    page.follows_navigation = False

    result = runner.invoke(cli.app, ["verify"], catch_exceptions=False)

    assert result.exit_code == ExitCode.FAILED
    assert result.stdout == f"{SHORT}  FAILED  chat missing\n"
    assert state.StateStore(store.workspace).load()[SOURCE].status is Status.PARTIAL


def test_verify_has_nothing_to_do_in_an_empty_workspace(
    runner: CliRunner, workspace: Path
) -> None:
    """No browser is started for a question with no conversations in it."""
    result = runner.invoke(cli.app, ["verify"], catch_exceptions=False)
    assert result.exit_code == ExitCode.NOTHING_TO_DO
    assert result.stdout == ""


@pytest.mark.slow
def test_verify_refuses_a_signed_out_session(
    chat: tuple[Browser, FakePage],
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every chat would read as missing, so the one fact that matters is said
    once — with `07`'s words and `01`'s exit code."""
    browser, page = chat
    page.composer = None
    workspace_with(tmp_path, browser, monkeypatch)

    result = runner.invoke(cli.app, ["verify"], catch_exceptions=False)

    assert result.exit_code == ExitCode.NOT_AUTHENTICATED
    assert result.stderr.endswith(f"{SIGNED_OUT}\n")
    assert result.stdout == ""


@pytest.mark.slow
def test_a_browser_verify_started_is_a_browser_verify_closes(
    chat: tuple[Browser, FakePage],
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rule `12` follows: what this command opened, it shuts."""
    browser, _ = chat
    workspace_with(tmp_path, browser, monkeypatch)
    started = launcher.BrowserSession(
        client=browser.client, profile=tmp_path / "migration" / "browser-profile"
    )
    monkeypatch.setattr(launcher, "launch", lambda settings, url: started)

    result = runner.invoke(cli.app, ["verify"], catch_exceptions=False)

    assert result.exit_code == ExitCode.OK
    assert browser.chrome.closed


@pytest.mark.slow
def test_verify_runs_without_hermes(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`17`'s third criterion: `verify --only` never starts an agent.

    The world's Hermes is a real executable that records every call, so "no run"
    is checked rather than asserted about a mock.
    """
    world.answers(completed())
    world.run(only=[LONG], limit=1)
    before = len(world.hermes.one_shots)
    cli_env(world, monkeypatch)

    runner = CliRunner()
    result = runner.invoke(
        cli.app, ["verify", "--only", LONG[:8]], catch_exceptions=False
    )

    assert result.exit_code == ExitCode.OK
    assert result.stdout == f"{LONG[:8]}  verified\n"
    assert len(world.hermes.one_shots) == before


@pytest.mark.slow
def test_a_hermes_that_claims_too_much_is_recorded_as_partial(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`17`'s second criterion, and the reason the slice exists.

    Hermes says `completed` for a two-part conversation; the page holds part one
    and one acknowledgement. The entry ends `partial`, category `verification`,
    and worth retrying — a resumed attempt is exactly what pastes part two.
    """
    world.settings.seed = SeedSettings(max_chars=4_000)
    short = LONG[:8]
    world.page.transcript = [
        Turn("human", f"{render.source_id_line(LONG)}\nPart 1 of 2"),
        Turn("assistant", render.ack_line(short, 1, 2)),
        Turn("human", "part 2"),
        Turn("assistant", "I have read it."),
    ]
    world.answers(completed(chunks_acked=2))
    world.retries(max_attempts=2, backoff_s=())

    summary = world.run(only=[LONG], limit=1)

    entry_ = world.entry(LONG)
    assert summary.exit_code is ExitCode.FAILED
    assert entry_.status is Status.PARTIAL
    assert entry_.error is not None
    assert entry_.error.category is Category.VERIFICATION
    assert entry_.error.detail == "ack 2/2 missing"
    assert entry_.verified_at is None
    # `retry_recommended` is what the verification wrote (`record` is tested on
    # that above), and `13` spent it: the conversation was attempted again, and
    # the flag reads `false` at the end only because the budget ran out.
    assert world.store().run().retries == 1
    assert entry_.error.retry_recommended is False


@pytest.mark.slow
def test_a_verified_conversation_records_what_the_destination_cannot_hold(
    world: World,
) -> None:
    """§15's limitations, per conversation, beside `04`'s rendering slugs."""
    world.answers(completed())

    world.run(only=[LONG], limit=1)

    entry_ = world.entry(LONG)
    assert entry_.status is Status.COMPLETED
    assert entry_.verified_at is not None
    assert verifying.TIMESTAMPS_NOT_PRESERVED in entry_.limitations


@pytest.mark.slow
def test_a_chat_that_is_not_called_what_the_conversation_was(world: World) -> None:
    """The rename did not take. The conversation is still migrated, and the
    limitation says what the operator will not find in the sidebar."""
    world.answers(completed())
    world.page.title = "Untitled"

    world.run(only=[LONG], limit=1)

    entry_ = world.entry(LONG)
    assert entry_.status is Status.COMPLETED
    assert verifying.TITLE_NOT_SET in entry_.limitations


@pytest.mark.slow
def test_the_title_reaches_the_agent_through_the_prompt(world: World) -> None:
    """`17` renames through Hermes, so the title is a field of the task prompt —
    the one piece of a conversation's metadata that is."""
    world.answers(completed())

    world.run(only=[LONG], limit=1)

    prompt = world.hermes.one_shots[-1].prompt
    assert f"title: {world.entry(LONG).title}" in prompt


class Nobody:
    """An intervention with nobody behind it: `14`'s non-interactive case."""

    def ask(self, request: intervening.Request) -> bool:
        return False

    def retry(self, message: str) -> bool:
        return False

    def note(self, message: str) -> None:
        return None


@pytest.mark.slow
def test_a_run_that_needs_a_human_is_not_verified(world: World) -> None:
    """Somebody else owns what happens next, and a chat that is waiting for them
    is not a chat that failed a check."""
    world.answers(needs_human(conversation_id=CHAT))

    world.importer(intervention=Nobody()).run(
        world.export, state.Selection(only=[LONG], limit=1)
    )

    entry_ = world.entry(LONG)
    assert entry_.verified_at is None
    assert entry_.error is not None
    assert entry_.error.category is Category.AUTH
