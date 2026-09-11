"""`13`: what a failure makes the migration do.

Two halves, because the recovery table has two kinds of row.

**Rows a page can show.** A fixture page per row — a composer that is not there,
a modal, a sign-in redirect, a click that does not land, a tab that wandered off,
a chat that never answers — driven through the real helpers by `fake_agent`'s
scripted reader of the skill. Each one asserts the outcome the table's last
column names, and that the recovery the table allows is the one that fired. This
is what makes the table checkable rather than advisory: a signal it names that no
page can actually show would fail here.

**Rows only an agent can see.** Rate limiting, a CAPTCHA and a security challenge
are read off a snapshot — claude.ai's own words, which `docs/claude-ui-map.md`
still records as `*unknown*`. No script can classify those, so what is tested is
the other half of their row: a Hermes that reports one produces the state, the
category and the policy the table gives it. `20` is the first time anybody sees
the pages themselves.

Then the tool-side policy `13` wraps around all of them: the retry budget, the
backoff waits, the record an exhausted budget leaves, and the circuit breaker
that stops a run whose conversations keep failing the same way.
"""

import json
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dataporter import cli
from dataporter import importer as importing
from dataporter import seed as seeding
from dataporter.browser import helpers
from dataporter.config import RetrySettings, RunSettings
from dataporter.errors import Category
from dataporter.exit_codes import ExitCode
from dataporter.hermes import prompt as prompting
from dataporter.hermes.runner import HermesResult
from dataporter.state import ErrorRecord, Status
from dataporter.steps import Step
from fake_agent import ScriptedAgent
from fake_chrome import FakeTarget
from fake_composer import Browser, FakePage
from world import FIRST, LONG, THIRD, World, completed, result

CHAT_ID = "b6f0a2d4-1c88-4e3a-9a1f-2f0e5d7c8b91"
OTHER_ID = "c7e1b3f5-2d99-4f4b-8b2a-3a1f6e8d9c02"
NEW_URL = "https://claude.ai/new"
CHAT_URL = f"https://claude.ai/chat/{CHAT_ID}"
OTHER_URL = f"https://claude.ai/chat/{OTHER_ID}"
LOGIN_URL = "https://claude.ai/login"
ERROR_URL = "chrome-error://chromewebdata/"

ANSWER_AFTER = 2
"""Reads of the page before the stub finishes answering. More than one, so
`await-response` really has to poll."""


# --------------------------------------------------------------------------- #
# The page each row needs
# --------------------------------------------------------------------------- #


class Ui:
    """A claude.ai that behaves, and the base every misbehaving one starts from.

    The same stub `11`'s dry run uses: submitting clears the composer, records a
    human turn, moves a new chat to its `/chat/<uuid>` URL, and answers with the
    acknowledgement line a couple of polls later. Each subclass below breaks
    exactly one thing, which is what makes a row's assertion about that row.
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
        self.answer_after(page, expected_ack)

    def answer_after(self, page: FakePage, ack: str) -> None:
        answers_at = page.views + ANSWER_AFTER

        def answer(current: FakePage, views: int) -> None:
            if views >= answers_at:
                current.generating = False
                current.last_role = "assistant"
                current.last_text = ack

        page.on_view = answer


class MissingComposer(Ui):
    """`/new` renders without a composer, and reloading does not bring one."""

    def navigate(self, url: str) -> None:
        super().navigate(url)
        self.page.composer = None


class Expired(Ui):
    """The session is gone: every navigation lands on the sign-in page."""

    def navigate(self, url: str) -> None:
        super().navigate(url)
        self.browser.visit(LOGIN_URL)


class Modal(Ui):
    """Something is over the page — an announcement, a consent box, an upsell."""

    def navigate(self, url: str) -> None:
        super().navigate(url)
        self.page.dom_dialogs = 1


class DeadClick(Ui):
    """Enter does nothing at all. The composer still holds what was pasted."""

    def submit(self, expected_ack: str) -> None:
        return


class SilentSend(Ui):
    """The message goes somewhere: the composer clears and no turn appears."""

    def submit(self, expected_ack: str) -> None:
        self.page.composer = ""


class Unplugged(Ui):
    """The tab is on a browser error page, and a reload does not fix it."""

    def navigate(self, url: str) -> None:
        self.visited.append(url)
        self.browser.visit(ERROR_URL)


class Wandered(Ui):
    """Once this run has a chat, the tab keeps ending up in somebody else's.

    After the first part, not before: the id a run adopts is the one its own
    first submit produced, and a tab that was never in this run's chat is the
    missing-composer or the network row rather than this one.
    """

    def __init__(self, browser: Browser) -> None:
        super().__init__(browser)
        self.submits = 0

    def submit(self, expected_ack: str) -> None:
        self.submits += 1
        super().submit(expected_ack)
        self.wander()

    def navigate(self, url: str) -> None:
        super().navigate(url)
        self.wander()

    def wander(self) -> None:
        if self.submits > 1:
            self.browser.visit(OTHER_URL)


class NeverAnswers(Ui):
    """The message is sent, generation starts, and nothing ever comes back."""

    def answer_after(self, page: FakePage, ack: str) -> None:
        page.on_view = None


# --------------------------------------------------------------------------- #
# Running one migration against one of them
# --------------------------------------------------------------------------- #


def helper_runner(runner: CliRunner) -> Callable[[Sequence[str]], Any]:
    """Run a helper call the way Hermes would: the prompt's argv, as a command."""

    def call(argv: Sequence[str]) -> tuple[int, dict[str, Any]]:
        outcome = runner.invoke(cli.app, list(argv[1:]), catch_exceptions=False)
        assert len(outcome.stdout.splitlines()) == 1, outcome.stdout
        return outcome.exit_code, json.loads(outcome.stdout)

    return call


@pytest.fixture
def seed_files(two_part_seed: seeding.Seed, tmp_path: Path) -> list[Path]:
    return seeding.write_seed(two_part_seed, tmp_path / "migration" / "seeds")


@pytest.fixture(autouse=True)
def quick_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Poll intervals, not logic. Every wait still has to run out on its own."""
    monkeypatch.setattr(helpers, "RESPONSE_POLL_S", 0.01)
    monkeypatch.setattr(helpers, "CHIP_POLL_S", 0.01)


@pytest.fixture
def page() -> FakePage:
    """One tab, signed in, on an empty new chat."""
    return FakePage(url=NEW_URL, composer="", send_enabled=True)


@pytest.fixture
def browser(page: FakePage, monkeypatch: pytest.MonkeyPatch) -> Iterator[Browser]:
    opened = Browser(page)
    opened.__enter__()
    monkeypatch.setenv("HCM_BROWSER__CDP_PORT", str(opened.chrome.port))
    monkeypatch.setenv("HCM_TIMEOUTS__CDP_CALL_S", "5")
    monkeypatch.setenv("HCM_TIMEOUTS__RESPONSE_S", "0.2")
    try:
        yield opened
    finally:
        opened.chrome.stop()


@pytest.fixture
def migrate(
    browser: Browser,
    runner: CliRunner,
    two_part_seed: seeding.Seed,
    seed_files: list[Path],
    tmp_path: Path,
) -> Callable[..., tuple[HermesResult, ScriptedAgent]]:
    """Render `12`'s prompt and perform it against `ui`, whatever `ui` does."""

    def run(ui: type[Ui] = Ui, **fields: Any) -> tuple[HermesResult, ScriptedAgent]:
        prompt = prompting.for_seed(
            two_part_seed,
            seed_files=seed_files,
            workspace=tmp_path / "migration",
            **fields,
        )
        agent = ScriptedAgent(helper=helper_runner(runner), browser=ui(browser))
        return HermesResult.model_validate(agent.run(prompt)), agent

    return run


Migrate = Callable[..., tuple[HermesResult, ScriptedAgent]]


# --------------------------------------------------------------------------- #
# One test per row a page can show
# --------------------------------------------------------------------------- #


def test_a_failed_click_is_tried_once_more_and_then_reported(
    migrate: Migrate, page: FakePage
) -> None:
    """Row 1. The composer still holds the part, so the click did not land."""
    outcome, agent = migrate(DeadClick)

    assert outcome.outcome == "failed"
    assert outcome.error is not None and outcome.error.category == Category.UI
    assert outcome.chunks_acked == 0
    assert outcome.step is Step.PASTE
    # Once more, and only once: "at most once per step" is the whole budget.
    assert agent.recoveries == ["failed_click"]


def test_a_missing_composer_is_reloaded_once_and_then_reported(
    migrate: Migrate,
) -> None:
    """Row 2. A page with nothing to type into that a reload does not fix."""
    outcome, agent = migrate(MissingComposer)

    assert outcome.outcome == "failed"
    assert outcome.error is not None and outcome.error.category == Category.UI
    assert outcome.step is Step.OPEN
    assert agent.recoveries == ["missing_composer"]


def test_a_dialog_in_the_way_needs_a_human(migrate: Migrate, page: FakePage) -> None:
    """Row 3. Nothing is clicked: the table forbids guessing at a modal."""
    outcome, _ = migrate(Modal)

    assert outcome.outcome == "needs_human"
    assert outcome.needs_human_reason == "ambiguous_ui"
    assert outcome.step is Step.OPEN
    assert page.text_reads == 0


def test_an_expired_session_needs_a_human(migrate: Migrate, page: FakePage) -> None:
    """Row 4. The login page is outside the surface, so the wall is the signal."""
    outcome, agent = migrate(Expired)

    assert outcome.outcome == "needs_human"
    assert outcome.needs_human_reason == "auth_required"
    assert helpers.OUTSIDE_MIGRATION_SURFACE in agent.errors
    # Not retried, and nothing typed into a page we were refused.
    assert agent.recoveries == []
    assert page.text_reads == 0


def test_a_generation_that_never_arrives_is_awaited_twice(migrate: Migrate) -> None:
    """Row 6. Part one is sent and never answered: no ack, so nothing landed."""
    outcome, agent = migrate(NeverAnswers)

    assert outcome.outcome == "partial"
    assert outcome.error is not None
    assert outcome.error.category == Category.GENERATION
    assert outcome.chunks_acked == 0
    assert outcome.step is Step.SUBMIT
    # A chat exists — the submit created one — so this is `partial`, not `failed`.
    assert outcome.conversation_id == CHAT_ID
    assert agent.recoveries == ["generation"]
    assert agent.errors.count(helpers.RESPONSE_TIMEOUT) == 2


def test_a_tab_that_cannot_be_read_is_reloaded_once_and_then_reported(
    migrate: Migrate,
) -> None:
    """Row 7. A browser error page is not a claude.ai tab any more."""
    outcome, agent = migrate(Unplugged)

    assert outcome.outcome == "failed"
    assert outcome.error is not None and outcome.error.category == Category.NETWORK
    assert outcome.step is Step.OPEN
    assert agent.recoveries == ["network"]
    assert agent.errors == [helpers.NO_CLAUDE_TAB, helpers.NO_CLAUDE_TAB]


def test_a_tab_that_wandered_into_another_chat_is_brought_back_once(
    migrate: Migrate,
) -> None:
    """Row 8. The id under the tab is not the one this run is working in.

    Part one landed, so there is a chat and a `partial`; part two is not pasted
    into whatever chat the tab ended up in, which is the whole point of the row.
    """
    outcome, agent = migrate(Wandered)

    assert outcome.outcome == "partial"
    assert outcome.error is not None
    assert outcome.error.category == Category.NAVIGATION
    assert outcome.conversation_id == CHAT_ID
    assert outcome.step is Step.PASTE
    assert outcome.chunks_acked == 1
    assert agent.recoveries == ["navigation"]


def test_a_send_that_leaves_no_turn_behind_needs_a_human(migrate: Migrate) -> None:
    """Row 9. The composer cleared, so it went somewhere; there is no row for
    where. That is a UI this procedure no longer describes."""
    outcome, agent = migrate(SilentSend)

    assert outcome.outcome == "needs_human"
    assert outcome.needs_human_reason == "ambiguous_ui"
    assert outcome.step is Step.PASTE
    # Not a failed click: nothing is clicked twice, because something did happen.
    assert agent.recoveries == []


def test_a_second_claude_tab_is_closed_rather_than_guessed_between(
    migrate: Migrate, browser: Browser
) -> None:
    """Not a §11 row, but the helper error the table gives its own recovery to.

    `08` refuses to choose between two claude.ai tabs; the skill's answer is one
    `close-extra-tabs` and the same call again, which is what a run that adopted
    a browser with a stray tab has to do before it can do anything else.
    """
    browser.chrome.targets.append(FakeTarget(id="page-2", url=NEW_URL))

    outcome, agent = migrate()

    assert outcome.outcome == "completed"
    assert agent.recoveries[0] == "ambiguous_tab"
    assert helpers.AMBIGUOUS_TAB in agent.errors


# --------------------------------------------------------------------------- #
# The rows only an agent can see
# --------------------------------------------------------------------------- #


def reported(**fields: Any) -> HermesResult:
    payload: dict[str, Any] = {"outcome": "failed", "last_step": str(Step.SUBMIT)}
    payload.update(fields)
    return HermesResult.model_validate(payload)


def test_a_rate_limit_is_recorded_with_the_wait_the_page_named() -> None:
    """Row 5. `15` does the waiting; `13` only refuses to spend a retry on it."""
    mapped = importing.interpret(
        reported(outcome="rate_limited", retry_after_s=3600, conversation_id=CHAT_ID),
        landed=True,
    )

    assert mapped.status is Status.FAILED
    assert mapped.error is not None
    assert mapped.error.category is Category.RATE_LIMIT
    assert mapped.error.detail.endswith("retry after 3600s")
    assert mapped.deferred is True


@pytest.mark.parametrize(
    ("reason", "category"),
    [
        ("captcha", Category.CAPTCHA),
        ("security_challenge", Category.SECURITY_CHALLENGE),
    ],
)
def test_a_challenge_is_recorded_and_never_retried(
    reason: str, category: Category
) -> None:
    """Row 10. Neither is something a second identical attempt gets past."""
    mapped = importing.interpret(
        reported(outcome="needs_human", needs_human_reason=reason), landed=False
    )

    assert mapped.status is Status.FAILED
    assert mapped.error is not None and mapped.error.category is category
    assert mapped.deferred is True
    assert not attempt_from(mapped).retryable


def attempt_from(mapped: importing.Mapped) -> importing.Attempt:
    return importing.Attempt(
        status=mapped.status, error=mapped.error, attempts=1, deferred=mapped.deferred
    )


# --------------------------------------------------------------------------- #
# What the tool does about it: the retry budget
# --------------------------------------------------------------------------- #


def failure(category: str, **fields: Any) -> str:
    return result(error={"category": category, "detail": "x"}, **fields)


def test_two_transient_failures_are_retried_and_the_third_attempt_lands(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """`13`'s second acceptance criterion, backoff waits and all."""
    world.answers(failure("network"), failure("network"), completed())

    summary = world.run(limit=1)
    printed = capsys.readouterr().out

    assert summary.exit_code is ExitCode.OK
    entry = world.entry(FIRST)
    assert entry.status is Status.COMPLETED
    assert entry.attempts == 3
    assert entry.error is None
    assert world.store().run().retries == 2
    # The two waits, in the order and the shape `13` writes them.
    assert "waiting 30s (retry 2/3, network)\n" in printed
    assert "waiting 120s (retry 3/3, network)\n" in printed
    assert world.pauses[:2] == [30.0, 120.0]


def test_a_non_transient_failure_is_recorded_once_and_not_retried(
    world: World,
) -> None:
    """`13`'s third criterion. `unsupported` is not a busy account."""
    world.answers(failure("unsupported"))

    summary = world.run(limit=1)

    assert summary.exit_code is ExitCode.FAILED
    entry = world.entry(FIRST)
    assert entry.status is Status.FAILED
    assert entry.attempts == 1
    assert entry.error is not None
    assert entry.error.retry_recommended is False
    assert len(world.hermes.one_shots) == 1


def test_an_exhausted_budget_stops_recommending_a_retry(world: World) -> None:
    """Three goes at a transient failure, and then the record says so.

    `19` prints this field, and a `true` on a conversation nothing is going to
    try again is an instruction to an operator that the run has already refused.
    """
    world.answers(failure("network"))

    world.run(limit=1)

    entry = world.entry(FIRST)
    assert entry.status is Status.FAILED
    assert entry.attempts == 3
    assert entry.error is not None
    assert entry.error.category is Category.NETWORK
    assert entry.error.retry_recommended is False
    assert len(world.hermes.one_shots) == 3


def test_an_unknown_transience_is_left_unknown(world: World) -> None:
    """`ui` is `01`'s "per instance": the skill already spent its one recovery
    on the page, and not knowing does not become knowing by trying again."""
    world.answers(failure("ui"))

    world.run(limit=1)

    entry = world.entry(FIRST)
    assert entry.attempts == 1
    assert entry.error is not None
    assert entry.error.retry_recommended is None
    assert len(world.hermes.one_shots) == 1


def test_a_needs_human_result_is_not_a_retry(world: World) -> None:
    """`14` owns it, and a person is not made available by waiting 30 seconds."""
    world.answers(
        result(outcome="needs_human", needs_human_reason="confirmation_required")
    )

    world.run(limit=1)

    assert world.entry(FIRST).attempts == 1
    assert world.store().run().retries == 0
    assert world.pauses == []


def test_a_rate_limited_result_is_not_a_retry(world: World) -> None:
    """`15` owns the wait, and `13` must not spend three attempts inside it."""
    world.answers(result(outcome="rate_limited", retry_after_s=3600))

    world.run(limit=1)

    entry = world.entry(FIRST)
    assert entry.attempts == 1
    assert entry.error is not None
    assert entry.error.category is Category.RATE_LIMIT
    assert len(world.hermes.one_shots) == 1


def test_a_partial_retry_resumes_the_chat_rather_than_opening_a_second(
    world: World,
) -> None:
    """§17's rule, under `13`'s budget: the second attempt continues the chat
    the first one left behind, from the step that last verified."""
    world.answers(
        result(
            outcome="partial",
            conversation_id=CHAT_ID,
            last_step=str(Step.ACK),
            chunks_acked=1,
            error={"category": "generation", "detail": "part 2 never answered"},
        ),
        completed(CHAT_ID, chunks_acked=2),
    )

    world.run(limit=1)

    prompts = [call.prompt for call in world.hermes.one_shots]
    assert len(prompts) == 2
    assert "existing conversation_id: none" in prompts[0]
    assert f"existing conversation_id: {CHAT_ID}" in prompts[1]
    assert f"resume_from: {Step.ACK}" in prompts[1]
    assert world.entry(FIRST).status is Status.COMPLETED


def test_a_hermes_that_cannot_be_invoked_is_never_retried(world: World) -> None:
    """`HermesUsageError`: the same wrong invocation, made again later.

    Category `hermes`, which is transient as a class — so this is the one place
    the decision comes off the instance rather than off the table.
    """
    world.answers("")
    world.exits(2)

    world.run(limit=1)

    entry = world.entry(FIRST)
    assert entry.attempts == 1
    assert entry.error is not None
    assert entry.error.category is Category.HERMES
    assert entry.error.retry_recommended is False


# --------------------------------------------------------------------------- #
# The budget itself
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [(1, 30.0), (2, 120.0), (3, 300.0), (4, 300.0), (9, 300.0)],
)
def test_backoff_repeats_its_last_value_rather_than_running_out(
    attempt: int, expected: float
) -> None:
    assert importing.backoff_for(RetrySettings(), attempt) == expected


def test_an_empty_backoff_schedule_means_no_wait() -> None:
    assert importing.backoff_for(RetrySettings(backoff_s=()), 1) == 0.0


def test_one_attempt_means_no_retries(world: World) -> None:
    """An operator who sets the budget to one gets one try and a `false`."""
    world.retries(max_attempts=1)
    world.answers(failure("network"))

    world.run(limit=1)

    assert len(world.hermes.one_shots) == 1
    entry = world.entry(FIRST)
    assert entry.error is not None
    assert entry.error.retry_recommended is False


def test_a_completed_attempt_is_never_retryable() -> None:
    finished = importing.Attempt(status=Status.COMPLETED, error=None, attempts=1)
    assert not finished.retryable


def test_an_attempt_with_no_error_is_never_retryable() -> None:
    """A `partial` the mapping table gave no error is not a failure to repeat."""
    unexplained = importing.Attempt(status=Status.PARTIAL, error=None, attempts=1)
    assert not unexplained.retryable


# --------------------------------------------------------------------------- #
# The circuit breaker
# --------------------------------------------------------------------------- #


def test_three_failures_in_a_row_stop_the_run(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """`13`'s fourth criterion, with the message byte for byte."""
    world.retries(max_attempts=1)
    world.answers(failure("network"))

    summary = world.run(limit=5)
    printed = capsys.readouterr().out

    assert summary.exit_code is ExitCode.FAILED
    assert summary.stopped is True
    assert "stopping: 3 consecutive failures (network) — see report\n" in printed
    # Three attempted, and the rest of the selection untouched.
    assert len(world.hermes.one_shots) == 3
    assert [world.entry(uuid).status for uuid in (FIRST, LONG, THIRD)] == [
        Status.FAILED,
        Status.FAILED,
        Status.FAILED,
    ]
    assert world.store().load()["dd000004-4444-4444-8444-444444444444"].status is (
        Status.PENDING
    )


def test_the_stop_line_survives_quiet(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """`-q` suppresses progress; what became of the run is not progress."""
    world.retries(max_attempts=1)
    world.answers(failure("network"))

    world.importer(progress=importing.LineProgress(quiet=True)).run(
        world.export, importing.state.Selection(limit=5)
    )
    printed = capsys.readouterr().out

    assert "aa000001" not in printed
    assert printed.startswith("stopping: 3 consecutive failures (network)")


def test_a_different_category_is_not_the_same_streak(world: World) -> None:
    """Three failures that are not the same failure are three conversations
    going wrong, which is what a run of an experiment looks like."""
    world.retries(max_attempts=1)
    world.answers(failure("network"), failure("generation"), failure("network"))

    summary = world.run(limit=4)

    assert summary.stopped is False
    assert len(world.hermes.one_shots) == 4


def test_a_partial_does_not_feed_the_breaker(world: World) -> None:
    """A chat exists at the destination, so the run is working, not broken."""
    world.retries(max_attempts=1)
    world.answers(
        result(
            outcome="partial",
            conversation_id=CHAT_ID,
            error={"category": "network", "detail": "x"},
        )
    )

    summary = world.run(limit=4)

    assert summary.stopped is False
    assert world.entry(FIRST).status is Status.PARTIAL


def test_an_unsupported_conversation_does_not_feed_the_breaker(world: World) -> None:
    """It was never handed to Hermes, so it says nothing about the destination."""
    world.retries(max_attempts=1)
    world.answers(failure("network"), failure("network"))
    world.run(limit=2)  # two `network` failures, and an unsupported entry waiting

    summary = world.run(
        only=[
            "ff000006-6666-4666-8666-666666666666",
            FIRST,
        ],
        retry_failed=True,
    )

    assert summary.stopped is False


def test_the_breaker_can_be_switched_off(world: World) -> None:
    world.retries(max_attempts=1)
    world.settings.run = RunSettings(
        max_conversations=10, stop_after_consecutive_failures=0
    )
    world.answers(failure("network"))

    summary = world.run(limit=4)

    assert summary.stopped is False
    assert len(world.hermes.one_shots) == 4


def streak_of(*categories: str | None) -> importing.FailureStreak:
    streak = importing.FailureStreak()
    for category in categories:
        streak.record(
            importing.Attempt(
                status=Status.COMPLETED if category is None else Status.FAILED,
                error=None
                if category is None
                else ErrorRecord(category=Category(category)),
                attempts=1,
            )
        )
    return streak


def test_a_success_between_failures_breaks_the_streak() -> None:
    assert streak_of("network", None, "network").tripped(3) is None
    assert streak_of("network", "network", "network").tripped(3) is Category.NETWORK


def test_a_failure_with_no_category_breaks_the_streak() -> None:
    """`12` records one for every stop, but the streak is not the place to
    assume it: a count without a category names nothing in the stop line."""
    streak = streak_of("network", "network")
    streak.record(importing.Attempt(status=Status.FAILED, error=None, attempts=1))
    assert streak.tripped(1) is None


# --------------------------------------------------------------------------- #
# What the operator sees
# --------------------------------------------------------------------------- #


def test_the_wait_line_is_suppressed_by_quiet(
    capsys: pytest.CaptureFixture[str],
) -> None:
    importing.LineProgress(quiet=True).waiting(30.0, "retry 2/3, network")
    assert capsys.readouterr().out == ""


def test_the_wait_line_has_no_trailing_zeros(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`30`, not `30.0`: the line is read by a person watching a run."""
    importing.LineProgress().waiting(30.0, "retry 2/3, network")
    assert capsys.readouterr().out == "waiting 30s (retry 2/3, network)\n"


def test_the_retry_is_logged_with_its_numbers(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    """`13`'s record: the conversation, the attempt, the category and the wait —
    and a short id, because §10 keeps the log reading like the terminal."""
    world.answers(failure("network"), completed())

    with caplog.at_level("INFO", logger="dataporter.importer"):
        world.run(limit=1)

    retries = [record for record in caplog.records if record.message == "retry"]
    assert len(retries) == 1
    assert retries[0].conversation_id == "aa000001"
    assert retries[0].attempt == 1
    assert retries[0].category == "network"
    assert retries[0].backoff_s == 30.0


def test_nothing_a_recovery_prints_is_content(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """§10 again, on the lines `13` added: a wait and a stop are numbers."""
    world.retries(max_attempts=2)
    world.answers(failure("network"))

    world.run(limit=5)
    captured = capsys.readouterr()

    for phrase in ("Listing files", "Postgres questions", "Naming the tool"):
        assert phrase not in captured.out
        assert phrase not in captured.err


def test_the_stop_line_names_the_category_that_tripped_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    importing.LineProgress().stopping(3, Category.GENERATION)
    assert capsys.readouterr().out == (
        "stopping: 3 consecutive failures (generation) — see report\n"
    )
