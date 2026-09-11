"""One migration, end to end, without Hermes and without a browser.

`11`'s third acceptance criterion: a dry run that follows the skill against a
stubbed page reaches `identify` and comes back `completed` with the stubbed uuid.
Hermes is the one part that cannot be installed in CI, so `fake_agent` stands in
for it — it reads the rendered prompt and performs the procedure, and everything
below it is the real thing: the real CLI, the real helpers, the real page model
`08` is tested against.

What each test is for:

- the happy path, which is the criterion, and which also proves the two seeds
  reached the composer whole (the `paste` records in `logs/actions.jsonl` are
  written by the helper, not by the agent);
- a page with no composer, which must become `needs_human` rather than a run that
  pastes a conversation into whatever is on screen;
- a composer somebody else was using, which must stop before any seed is
  inserted;
- a seed part whose file is gone, which must leave a `partial` that names the
  chat and counts only the acknowledgements it really saw;
- a resumed run, which must continue the chat it is given and never open a second
  one for the same conversation — and must refuse to continue one whose
  transcript does not hold the acknowledgement it was told to expect.
"""

import json
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dataporter import cli
from dataporter import seed as seeding
from dataporter.browser import helpers
from dataporter.hermes import prompt as prompting
from dataporter.hermes.runner import HermesResult
from dataporter.steps import Step
from fake_agent import ScriptedAgent
from fake_composer import Browser, FakePage

CHAT_ID = "b6f0a2d4-1c88-4e3a-9a1f-2f0e5d7c8b91"
NEW_URL = "https://claude.ai/new"
CHAT_URL = f"https://claude.ai/chat/{CHAT_ID}"

ANSWER_AFTER = 2
"""How many reads of the page happen before the stub finishes answering. More
than one, so `await-response` really does have to poll."""


class Ui:
    """The page, as the two actions the skill leaves to the agent change it.

    This is the stub the criterion asks for: submitting clears the composer,
    records a human turn, sets the tab generating, moves a new chat to its
    `/chat/<uuid>` URL, and then — a couple of polls later — answers with the
    acknowledgement line. Nothing here is a claim about the real claude.ai;
    `docs/claude-ui-map.md` holds those, and every row of it is still `*unknown*`.
    """

    def __init__(self, browser: Browser) -> None:
        self.browser = browser
        self.visited: list[str] = []

    @property
    def page(self) -> FakePage:
        return self.browser.page()

    def navigate(self, url: str) -> None:
        self.visited.append(url)
        self.browser.visit(url)
        if self.page.composer is not None:
            # A fresh page has an empty composer — unless it had none to begin
            # with, which is what a signed-out tab looks like to `probe`.
            self.page.composer = ""
        self.page.on_view = None

    def submit(self, expected_ack: str) -> None:
        page = self.page
        page.composer = ""
        page.last_role = "human"
        page.last_text = "(what the helper inserted)"
        page.generating = True
        if page.url == NEW_URL:
            self.browser.visit(CHAT_URL)
        answers_at = page.views + ANSWER_AFTER

        def answer(current: FakePage, views: int) -> None:
            if views >= answers_at:
                current.generating = False
                current.last_role = "assistant"
                current.last_text = expected_ack

        page.on_view = answer


def helper_runner(runner: CliRunner) -> Callable[[Sequence[str]], Any]:
    """Run a helper call the way Hermes would: the prompt's argv, as a command."""

    def call(argv: Sequence[str]) -> tuple[int, dict[str, Any]]:
        # argv[0] is the program name; `CliRunner` is already the program.
        result = runner.invoke(cli.app, list(argv[1:]), catch_exceptions=False)
        assert len(result.stdout.splitlines()) == 1, result.stdout
        return result.exit_code, json.loads(result.stdout)

    return call


@pytest.fixture
def seed_files(two_part_seed: seeding.Seed, tmp_path: Path) -> list[Path]:
    return seeding.write_seed(two_part_seed, tmp_path / "migration" / "seeds")


@pytest.fixture
def quick_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    """The poll interval, not the logic. Three stable polls still have to pass."""
    monkeypatch.setattr(helpers, "RESPONSE_POLL_S", 0.01)


def browser_with(page: FakePage, monkeypatch: pytest.MonkeyPatch) -> Browser:
    """A fake browser the CLI can find on the port the environment names."""
    browser = Browser(page)
    browser.__enter__()
    monkeypatch.setenv("HCM_BROWSER__CDP_PORT", str(browser.chrome.port))
    monkeypatch.setenv("HCM_TIMEOUTS__CDP_CALL_S", "5")
    monkeypatch.setenv("HCM_TIMEOUTS__RESPONSE_S", "5")
    return browser


@pytest.fixture
def new_chat(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Browser, FakePage]]:
    """One tab, signed in, on an empty new chat."""
    page = FakePage(url=NEW_URL, composer="", send_enabled=True)
    browser = browser_with(page, monkeypatch)
    try:
        yield browser, page
    finally:
        browser.chrome.stop()


def migrate(
    browser: Browser,
    runner: CliRunner,
    two_part_seed: seeding.Seed,
    seed_files: list[Path],
    tmp_path: Path,
    **fields: Any,
) -> tuple[dict[str, Any], Ui]:
    """Render the prompt `12` will render, and run the procedure on it."""
    task = prompting.for_seed(
        two_part_seed,
        seed_files=seed_files,
        workspace=tmp_path / "migration",
        **fields,
    )
    ui = Ui(browser)
    agent = ScriptedAgent(helper=helper_runner(runner), browser=ui)
    return agent.run(task), ui


# --------------------------------------------------------------------------- #
# Acceptance: the dry run
# --------------------------------------------------------------------------- #


@pytest.mark.usefixtures("quick_polls")
def test_a_dry_run_reaches_identify_and_completes(
    new_chat: tuple[Browser, FakePage],
    runner: CliRunner,
    two_part_seed: seeding.Seed,
    seed_files: list[Path],
    tmp_path: Path,
) -> None:
    browser, _ = new_chat
    printed, _ = migrate(browser, runner, two_part_seed, seed_files, tmp_path)

    result = HermesResult.model_validate(printed)
    assert result.outcome == "completed"
    assert result.conversation_id == CHAT_ID
    assert result.step is Step.DONE
    assert result.chunks_acked == 2


@pytest.mark.usefixtures("quick_polls")
def test_both_seeds_reached_the_composer_whole(
    new_chat: tuple[Browser, FakePage],
    runner: CliRunner,
    two_part_seed: seeding.Seed,
    seed_files: list[Path],
    tmp_path: Path,
) -> None:
    """The hashes are the helper's, and it is the helper that recorded them."""
    browser, _ = new_chat
    migrate(browser, runner, two_part_seed, seed_files, tmp_path)

    records = [
        json.loads(line)
        for line in helpers.actions_path(tmp_path / "migration")
        .read_text()
        .splitlines()
    ]
    pastes = [item for item in records if item["helper"] == "paste"]
    assert len(pastes) == 2
    assert all(item["ok"] for item in records)


# --------------------------------------------------------------------------- #
# The three ways it stops
# --------------------------------------------------------------------------- #


def test_a_page_with_no_composer_needs_a_human(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    two_part_seed: seeding.Seed,
    seed_files: list[Path],
    tmp_path: Path,
) -> None:
    """Signed out looks like this to `probe`: a page with nothing to type into."""
    page = FakePage(url=NEW_URL, composer=None)
    browser = browser_with(page, monkeypatch)
    try:
        printed, ui = migrate(browser, runner, two_part_seed, seed_files, tmp_path)
    finally:
        browser.chrome.stop()

    result = HermesResult.model_validate(printed)
    assert result.outcome == "needs_human"
    assert result.needs_human_reason == "auth_required"
    assert result.chunks_acked == 0
    assert ui.page.uploaded == []


def test_a_composer_someone_else_was_using_stops_before_the_paste(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    two_part_seed: seeding.Seed,
    seed_files: list[Path],
    tmp_path: Path,
) -> None:
    """`new_chat` is what catches a draft, and it catches it before the seed."""
    page = FakePage(url=NEW_URL, composer="")
    browser = browser_with(page, monkeypatch)

    class Draft(Ui):
        def navigate(self, url: str) -> None:
            super().navigate(url)
            self.page.composer = "someone was in the middle of something"

    try:
        agent = ScriptedAgent(helper=helper_runner(runner), browser=Draft(browser))
        printed = agent.run(
            prompting.for_seed(
                two_part_seed,
                seed_files=seed_files,
                workspace=tmp_path / "migration",
            )
        )
    finally:
        browser.chrome.stop()

    result = HermesResult.model_validate(printed)
    assert result.outcome == "failed"
    assert result.conversation_id is None
    assert result.step is Step.OPEN
    assert page.text_reads == 0  # `paste` never ran, so nothing was inserted


@pytest.mark.usefixtures("quick_polls")
def test_a_missing_seed_part_leaves_a_partial_migration(
    new_chat: tuple[Browser, FakePage],
    runner: CliRunner,
    two_part_seed: seeding.Seed,
    seed_files: list[Path],
    tmp_path: Path,
) -> None:
    """Part one lands, part two has no file: `partial`, with the chat recorded.

    The helper is what notices — `paste` answers `seed_not_found` rather than
    inserting something else — and the count that reaches `12` is the number of
    acknowledgements actually seen, not the number of parts attempted.
    """
    browser, _ = new_chat
    seed_files[1].unlink()
    printed, _ = migrate(browser, runner, two_part_seed, seed_files, tmp_path)

    result = HermesResult.model_validate(printed)
    assert result.outcome == "partial"
    assert result.conversation_id == CHAT_ID
    assert result.step is Step.ACK
    assert result.chunks_acked == 1


@pytest.mark.usefixtures("quick_polls")
def test_a_resumed_run_continues_the_chat_it_was_given(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    two_part_seed: seeding.Seed,
    seed_files: list[Path],
    tmp_path: Path,
) -> None:
    """Part one is already there, so only part two is pasted — into that chat."""
    first_ack = two_part_seed.chunks[0].ack
    page = FakePage(
        url=CHAT_URL, composer="", last_role="assistant", last_text=first_ack
    )
    browser = browser_with(page, monkeypatch)
    try:
        printed, ui = migrate(
            browser,
            runner,
            two_part_seed,
            seed_files,
            tmp_path,
            resume_from=Step.PASTE,
            conversation_id=CHAT_ID,
            acknowledged=1,
        )
    finally:
        browser.chrome.stop()

    result = HermesResult.model_validate(printed)
    assert result.outcome == "completed"
    assert result.conversation_id == CHAT_ID
    assert result.chunks_acked == 2
    assert ui.visited == [CHAT_URL]  # never `/new`: that would be a second chat


def test_a_chat_that_does_not_hold_the_acknowledgement_is_not_resumed(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    two_part_seed: seeding.Seed,
    seed_files: list[Path],
    tmp_path: Path,
) -> None:
    """The count says one part landed; the page says otherwise. Nothing is pasted."""
    page = FakePage(url=CHAT_URL, composer="", last_role="assistant", last_text="hello")
    browser = browser_with(page, monkeypatch)
    try:
        printed, _ = migrate(
            browser,
            runner,
            two_part_seed,
            seed_files,
            tmp_path,
            resume_from=Step.PASTE,
            conversation_id=CHAT_ID,
            acknowledged=1,
        )
    finally:
        browser.chrome.stop()

    result = HermesResult.model_validate(printed)
    assert result.outcome == "partial"
    assert result.error is not None and result.error.category == "verification"
    assert page.text_reads == 0  # nothing was inserted, so nothing was read back
