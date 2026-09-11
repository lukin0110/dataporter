"""The import loop: one conversation, start to finish, and then the next one.

Everything before this slice produced a piece of a migration — a plan (`03`), a
seed (`04`), a state file (`06`), a browser (`07`, `08`), a Hermes runner (`09`)
and a prompt (`11`). This is the module that spends them, in the order §6 Phase 3
lays out, one conversation at a time.

Three properties are the point:

- **Nothing is recomputed.** The plan is built once and written to
  `<workspace>/plan.json`; `state.json` gets an entry per planned conversation
  before the first Hermes run starts. The numbers the dry run printed, the
  numbers this prints and the numbers `19` will report are the same numbers.
- **One conversation's failure is one conversation's failure.** Every error a
  conversation can raise is recorded against that conversation and the run moves
  on. What ends a run early is never about one conversation: the workspace lock,
  the export fingerprint, a browser that cannot be brought back, and — once `15`
  lands — the circuit breaker.
- **No content, anywhere.** Titles go into `state.json` because §7 puts them
  there. Stdout gets a short id, a status and two counts; the log gets ids and
  numbers; Hermes's own stdout stays in the workspace file `09` wrote it to.

What this slice deliberately does not do is react: a failure is recorded and the
loop continues, with no retry, no pause and no rate-limit wait. `13`, `14` and
`15` are those three, and the mapping table below has a row marked for each.
"""

import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from dataporter import log, render, state, summary
from dataporter import seed as seeding
from dataporter.browser import helpers as browser_helpers
from dataporter.browser import launcher, probe
from dataporter.browser import session as browser_session
from dataporter.config import Settings
from dataporter.errors import (
    ERROR_CLASSES,
    AuthError,
    BrowserError,
    Category,
    HermesError,
    MigrationError,
    UnsupportedError,
)
from dataporter.exit_codes import ExitCode
from dataporter.export import Conversation, Export, load_export
from dataporter.hermes import doctor as hermes_doctor
from dataporter.hermes import prompt as prompting
from dataporter.hermes import runner as hermes_running
from dataporter.plan import MigrationPlan, build_plan
from dataporter.seed import Seed
from dataporter.state import ConversationState, ErrorRecord, Status
from dataporter.steps import Step

_logger = log.get_logger(__name__)

PLAN_FILENAME = "plan.json"

DELAY_BETWEEN_CONVERSATIONS_S = 20.0
"""The gap between one conversation and the next.

`15` owns this as `pacing.delay_between_conversations_s`; twenty seconds is the
placeholder until it does. A number rather than a setting on purpose — a pacing
parameter an operator can tune before there is any evidence about what the
destination account tolerates is a parameter they will tune wrongly.
"""

NO_CONVERSATION_ID = "no conversation id"
"""Why a `completed` run with no destination id is recorded as `partial`."""

UNREPORTED = "hermes reported {outcome} without an error"
"""A result that stopped and did not say why. The contract requires an `error`
for every outcome that is not `completed`, so its absence is Hermes's shortfall
and is recorded as one rather than as a blank."""

RATE_LIMITED = "rate limited"
NOT_RELAUNCHABLE = "the browser is gone and could not be started again"

NEEDS_HUMAN_CATEGORIES: dict[str, Category] = {
    "auth_required": Category.AUTH,
    "captcha": Category.CAPTCHA,
    "security_challenge": Category.SECURITY_CHALLENGE,
    "ambiguous_ui": Category.UI,
    "browser_error": Category.BROWSER,
    "confirmation_required": Category.SAFETY,
}
"""`09`'s six `needs_human` reasons, as the error categories `01` fixed.

`14` turns these into a pause; until it does they are recorded like any other
failure, and the category is what tells an operator — and `19` — which of the six
it was. A test reads `runner.NEEDS_HUMAN_REASONS` against this, so a seventh
reason cannot arrive without a category to put it in.
"""

_NOT_IN_A_RUN_ID = re.compile(r"[^A-Za-z0-9]")
FALLBACK_RUN_ID = "conversation"
RUN_ID_CHARS = 16


def run_id_for(short_id: str, attempt: int) -> str:
    """`<short id>-<attempt>`: what a run's three files are named (`09`).

    The short id comes off a uuid in an export we do not control and the run id
    becomes three filenames, so anything that is not a letter or a digit is
    dropped rather than trusted. `09` checks the result as well; this makes the
    check something that cannot fire instead of something that ends a run.
    """
    token = _NOT_IN_A_RUN_ID.sub("", short_id)[:RUN_ID_CHARS] or FALLBACK_RUN_ID
    return hermes_running.check_run_id(f"{token}-{attempt}")


def pause(seconds: float) -> None:
    """Wait between conversations. `15` replaces this with real pacing."""
    if seconds > 0:
        time.sleep(seconds)


# --------------------------------------------------------------------------- #
# Reading a result as a state entry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Mapped:
    """What one `HermesResult` means for `state.json`."""

    status: Status
    last_step: Step | None
    error: ErrorRecord | None


def retry_recommended(category: Category) -> bool | None:
    """Whether retrying this category is worth it, as `01` fixed it.

    Read off the error class rather than decided here: `errors` says `transient`
    is a property of the class so that `13` and `19` never have to guess, and
    `None` — the three "per instance" rows — is the `retry=unknown` `19` prints.
    """
    return ERROR_CLASSES[category].default_transient


def _error(category: Category, detail: str) -> ErrorRecord:
    return ErrorRecord(
        category=category, detail=detail, retry_recommended=retry_recommended(category)
    )


def interpret(result: hermes_running.HermesResult, *, landed: bool) -> Mapped:
    """`12`'s mapping table, as a function of the result and one fact.

    `landed` is "there is a chat at the destination" — a conversation id, from
    this run or from the one being resumed. It is the difference between
    `partial` and `failed` everywhere except the two rows that name a status
    outright, because that is what §7 means by the two words: `partial` is a chat
    that does not hold everything, `failed` is no chat at all.
    """
    outcome = result.outcome
    if outcome == "completed":
        if landed:
            return Mapped(Status.COMPLETED, Step.DONE, None)
        # The agent believes it finished and cannot say where. Something may well
        # be in the account, so this is not `failed`; `17` re-verifies from the
        # page, and until then the detail is what an operator has to go on.
        return Mapped(
            Status.PARTIAL,
            result.step,
            _error(Category.VERIFICATION, NO_CONVERSATION_ID),
        )
    stopped = Status.PARTIAL if landed else Status.FAILED
    if outcome == "rate_limited":
        # `15` waits and retries; until then it is a failure like any other, and
        # `retry_after_s` is kept in the detail rather than thrown away.
        detail = _detail(result) or RATE_LIMITED
        if result.retry_after_s is not None:
            detail = f"{detail}; retry after {result.retry_after_s}s"
        return Mapped(Status.FAILED, result.step, _error(Category.RATE_LIMIT, detail))
    if outcome == "needs_human":
        # `14` pauses on these. The reason is the category, so that a run an
        # operator reads afterwards says which of the six stopped it.
        reason = result.needs_human_reason
        category = NEEDS_HUMAN_CATEGORIES.get(reason or "", Category.UI)
        return Mapped(
            stopped, result.step, _error(category, _detail(result) or reason or "")
        )
    return Mapped(
        stopped,
        result.step,
        _error(
            result.error.category if result.error else Category.HERMES,
            _detail(result) or UNREPORTED.format(outcome=outcome),
        ),
    )


def _detail(result: hermes_running.HermesResult) -> str:
    return result.error.detail if result.error else ""


# --------------------------------------------------------------------------- #
# What a run says while it runs
# --------------------------------------------------------------------------- #


class Progress(Protocol):
    """Where a run's progress goes. `18` implements the §10 block against this."""

    def conversation(
        self, short_id: str, status: Status, counts: Mapping[str, int]
    ) -> None: ...

    def finish(self, counts: Mapping[str, int]) -> None: ...


@dataclass(frozen=True)
class LineProgress:
    """Until `18`: one line per conversation, then the counters block.

    The line is `18`'s non-TTY event line without its detail column, and the
    final block is `06`'s, which is §10's four counters. Neither carries a title
    or a message — the short id is a uuid's first eight characters and the rest
    are numbers.
    """

    quiet: bool = False

    def conversation(
        self, short_id: str, status: Status, counts: Mapping[str, int]
    ) -> None:
        if self.quiet:
            return
        done = counts["total"] - counts["pending"]
        print(f"{short_id}  {status}  ({done}/{counts['total']})")

    def finish(self, counts: Mapping[str, int]) -> None:
        # Printed under `--quiet` for the reason `status` is: `-q` suppresses
        # progress, and this is what the run amounts to.
        print("".join(f"{line}\n" for line in summary.counters_lines(counts)), end="")


@dataclass(frozen=True)
class RunSummary:
    """What one `import` amounted to."""

    total: int
    """Conversations in the plan — §10's "conversations found", not the selection."""
    selected: tuple[str, ...]
    outcomes: Mapping[str, Status]
    """The status each selected conversation ended at, in selection order."""
    counts: Mapping[str, int]
    """`state.status_counts` over the whole workspace, after the run."""
    exit_code: ExitCode


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #


class Importer:
    """`import`, without the flag parsing.

    One instance per invocation: it holds the workspace lock, the browser it
    launched and the store it writes through, and none of those outlive a run.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        progress: Progress | None = None,
        force_unlock: bool = False,
    ) -> None:
        self.settings = settings
        self.progress: Progress = progress if progress is not None else LineProgress()
        self.force_unlock = force_unlock
        self.store = state.StateStore(settings.workspace)
        self.runner = hermes_running.HermesRunner(settings)
        self.seeds = seeding.SeedGenerator(settings)
        self.session: launcher.BrowserSession | None = None

    # -- the run ------------------------------------------------------------ #

    def run(self, export_path: Path, selection: state.Selection) -> RunSummary:
        """Migrate what `selection` chooses out of the export at `export_path`."""
        parsed = load_export(export_path)
        lock = state.WorkspaceLock(self.settings.workspace)
        lock.acquire(force_unlock=self.force_unlock)
        try:
            return self._locked(parsed, selection)
        finally:
            # Both, on every path: a browser left running holds the next run's
            # debug port, and a lock left behind makes the next run exit `2`.
            self._close_browser()
            lock.release()

    def _locked(self, parsed: Export, selection: state.Selection) -> RunSummary:
        self.store.bind_export(parsed.fingerprint)
        self.store.recover()
        self._preflight()

        plan = self._write_plan(parsed)
        conversations = {item.uuid: item for item in parsed.conversations}
        self._create_entries(plan, conversations)

        order = [item.uuid for item in parsed.conversations]
        chosen = state.select(order, self.store.load(), selection)
        index = self.store.start_run(selection.model_copy(update={"uuids": chosen}))
        result = self._migrate_all(chosen, conversations, plan)
        self.store.finish_run(index, int(result.exit_code))
        return result

    # -- 1. preflight ------------------------------------------------------- #

    def _preflight(self) -> None:
        """Refuse to start unless the whole chain is there (`09`, `07`, §8).

        The local half of `doctor` rather than all of it: the two checks that run
        a real Hermes task cost a minute each and a migration is about to prove
        the same thing with work that counts.
        """
        failure = hermes_doctor.local_failure(self.settings)
        if failure is not None:
            raise HermesError(detail=f"{failure.label}: {failure.detail}")
        self.session = launcher.launch(self.settings, probe.NEW_CHAT_URL)
        if not browser_session.signed_in(self.session):
            raise AuthError(detail=browser_session.SIGNED_OUT)
        # Blank and duplicate new-chat tabs only, never a conversation (`08`).
        # Hermes picks its tab by looking, and one candidate is what makes that
        # unambiguous.
        browser_helpers.close_extra_tabs(self.session.client, self.settings)

    # -- 2. plan ------------------------------------------------------------ #

    def _write_plan(self, parsed: Export) -> MigrationPlan:
        """The whole export's plan, in the workspace, before anything runs.

        The whole export and not the selection: §10's "conversations found" is
        what the file holds, `19` accounts for every one of them, and a plan that
        changed shape with every `--only` would not be a record of anything.
        """
        plan = build_plan(parsed, self.settings)
        state.write_atomically(
            self.settings.workspace / PLAN_FILENAME, plan.model_dump_json(indent=2)
        )
        return plan

    def _create_entries(
        self, plan: MigrationPlan, conversations: Mapping[str, Conversation]
    ) -> None:
        """An entry per planned conversation, without touching a finished one.

        Unsupported conversations are written as `failed` rather than left out,
        so that `Created + Partial + Failed = Source conversations` holds in `19`
        with no special case — and so that `status` counts them as done rather
        than as forever pending.
        """
        for item in plan.conversations:
            title = conversations[item.uuid].name
            if item.migratable:
                self.store.ensure(item.uuid, title=title, chunks_total=item.chunk_count)
                continue
            self.store.ensure(
                item.uuid,
                title=title,
                status=Status.FAILED,
                error=ErrorRecord(
                    category=Category.UNSUPPORTED,
                    detail=item.reasons[0] if item.reasons else "",
                    retry_recommended=False,
                ),
            )

    # -- 3. one conversation at a time -------------------------------------- #

    def _migrate_all(
        self,
        chosen: Sequence[str],
        conversations: Mapping[str, Conversation],
        plan: MigrationPlan,
    ) -> RunSummary:
        migratable = {item.uuid for item in plan.conversations if item.migratable}
        outcomes: dict[str, Status] = {}
        for position, uuid in enumerate(chosen):
            if uuid in migratable:
                status = self._migrate(conversations[uuid])
            else:
                # Selected by `--retry-failed` over an entry `_create_entries`
                # wrote. There is no seed to paste, so there is nothing to run;
                # the entry already says why, and the line says so again.
                status = self.store.load()[uuid].status
            outcomes[uuid] = status
            counts = state.status_counts(self.store.load())
            self.progress.conversation(render.short_id(uuid), status, counts)
            if position + 1 < len(chosen):
                pause(DELAY_BETWEEN_CONVERSATIONS_S)

        counts = state.status_counts(self.store.load())
        self.progress.finish(counts)
        finished = all(status is Status.COMPLETED for status in outcomes.values())
        return RunSummary(
            total=len(plan.conversations),
            selected=tuple(chosen),
            outcomes=outcomes,
            counts=counts,
            # An empty selection is `4` — `06`'s rule — and not the `0` that
            # "every selected conversation completed" would otherwise give it.
            exit_code=ExitCode.NOTHING_TO_DO
            if not chosen
            else (ExitCode.OK if finished else ExitCode.FAILED),
        )

    def _migrate(self, conversation: Conversation) -> Status:
        """One conversation: seed, prompt, Hermes, state. Never raises upward
        for anything that is about this conversation rather than about the run."""
        uuid = conversation.uuid
        self._ensure_browser()
        entry = self._begin(uuid)
        actions = self._action_count()
        try:
            seed, result = self._run_hermes(conversation, entry)
        except MigrationError as exc:
            _logger.warning(
                "conversation failed",
                extra={
                    "conversation_id": render.short_id(uuid),
                    "category": str(exc.category),
                },
            )
            return self._record_failure(uuid, entry, exc)
        finally:
            self._count_actions(actions)
        return self._record(uuid, entry, seed, result)

    def _begin(self, uuid: str) -> ConversationState:
        """Mark the entry `running` and hand back what it looked like before.

        The `before` picture is what the rest of the conversation reads: which
        chat to resume, how many parts are already acknowledged, which attempt
        this is. Reading it after the update would read our own write.
        """
        before = self.store.load()[uuid]
        resume = resuming(before)
        if before.destination.conversation_id is not None and resume is None:
            # `--force` over a finished conversation. §17 deletes nothing, so the
            # chat that already exists is remembered rather than replaced.
            self.store.remember_destination(uuid, before.destination.conversation_id)
        attempts = before.attempts + 1
        self.store.update(
            uuid,
            status=Status.RUNNING,
            attempts=attempts,
            error=None,
            destination=state.Destination(conversation_id=resume),
            chunks_acked=before.chunks_acked if resume is not None else 0,
        )
        if attempts > 1:
            self.store.bump_counter("retries")
        return before

    def _run_hermes(
        self, conversation: Conversation, before: ConversationState
    ) -> tuple[Seed, hermes_running.HermesResult]:
        """Write this attempt's seed, render the prompt, run the task.

        Seeds are written on every attempt rather than cached: they are cheap,
        and a changed `seed.max_chars` must not leave a run pasting parts nobody
        planned.
        """
        uuid = conversation.uuid
        outcome = self.seeds.seed(conversation)
        if outcome.seed is None:
            # The plan already refused every unmigratable conversation, so the
            # one reason left is a uuid that cannot be a directory name (`04`).
            raise UnsupportedError(detail=outcome.reason or "no seed")
        seed = outcome.seed
        files = seeding.write_seed(seed, self.settings.seeds_dir)
        self.store.update(
            uuid, chunks_total=len(seed.chunks), limitations=list(seed.limitations)
        )

        resume = resuming(before)
        if resume is None:
            # A new chat: the procedure starts at `open` and pastes every part.
            acknowledged, resume_from = 0, Step.OPEN
        else:
            # `11`'s two resume fields. The count is clipped to the seed this
            # attempt just wrote, which may have fewer parts than the one the
            # earlier attempt pasted from, and `last_step` is the last step whose
            # verification passed — `open` when the entry has none.
            acknowledged = min(before.chunks_acked, len(seed.chunks))
            resume_from = before.last_step or Step.OPEN
        prompt = prompting.for_seed(
            seed,
            seed_files=files,
            workspace=self.settings.workspace,
            resume_from=resume_from,
            conversation_id=resume,
            acknowledged=acknowledged,
        )
        run_id = run_id_for(seed.short_id, before.attempts + 1)
        try:
            return seed, self.runner.run(
                prompt, run_id=run_id, timeout_s=self.settings.timeouts.hermes_task_s
            )
        finally:
            # A run that timed out still spent tokens, so this is read on every
            # path rather than only on the one that produced a result.
            self._record_usage(run_id)

    # -- what a conversation leaves behind ---------------------------------- #

    def _record(
        self,
        uuid: str,
        before: ConversationState,
        seed: Seed,
        result: hermes_running.HermesResult,
    ) -> Status:
        acked = max(0, min(result.chunks_acked, len(seed.chunks)))
        conversation_id = result.conversation_id or resuming(before)
        mapped = interpret(result, landed=conversation_id is not None)
        self.store.update(
            uuid,
            status=mapped.status,
            destination=state.Destination(conversation_id=conversation_id),
            last_step=mapped.last_step,
            chunks_acked=acked,
            # The messages in the parts that were acknowledged, and no others: a
            # message split across two parts belongs to neither until both land.
            messages_represented=sum(
                len(chunk.message_uuids) for chunk in seed.chunks[:acked]
            ),
            error=mapped.error,
        )
        if result.actions:
            _logger.debug(
                "hermes reported actions",
                extra={"conversation_id": seed.short_id, "actions": result.actions},
            )
        return mapped.status

    def _record_failure(
        self, uuid: str, before: ConversationState, exc: MigrationError
    ) -> Status:
        """An exception, as one conversation's entry.

        `partial` when a chat already exists, `failed` otherwise — the same rule
        the result mapping uses, and for the same reason: `failed` means there is
        nothing at the destination to go and look at.
        """
        resume = resuming(before)
        status = Status.PARTIAL if resume is not None else Status.FAILED
        self.store.update(
            uuid,
            status=status,
            error=ErrorRecord(
                category=exc.category,
                detail=exc.detail or type(exc).__name__,
                retry_recommended=exc.transient,
            ),
        )
        return status

    # -- the run's own housekeeping ----------------------------------------- #

    def _ensure_browser(self) -> None:
        """The browser is still there, or this run is over.

        Checked before each conversation rather than after each failure: a dead
        Chrome found here costs one HTTP call, and found later costs a Hermes run
        that had nowhere to go. A browser that cannot be started again is the one
        browser failure that ends the run (exit `6`).
        """
        session = self.session
        if session is not None and session.client.responding():
            return
        _logger.warning("browser not responding; starting it again")
        self.session = None
        try:
            self.session = launcher.launch(self.settings, probe.NEW_CHAT_URL)
        except BrowserError as exc:
            raise BrowserError(
                detail=f"{NOT_RELAUNCHABLE}: {exc.detail or type(exc).__name__}"
            ) from exc

    def _close_browser(self) -> None:
        """Close a browser this run started; leave one it adopted alone."""
        session, self.session = self.session, None
        if session is not None and not session.adopted:
            session.close()

    def _record_usage(self, run_id: str) -> None:
        usage = hermes_running.read_usage(self.runner.usage_path(run_id))
        if usage.empty:
            return
        self.store.add_usage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=usage.cost_usd,
        )

    def _action_count(self) -> int:
        """How many helper calls `<workspace>/logs/actions.jsonl` has recorded.

        Ours, not the agent's: `HermesResult.actions` is what Hermes believes it
        did, and `09` says why the file is the better number — our helpers write
        it, and a run that never called one cannot inflate it.
        """
        path = browser_helpers.actions_path(self.settings.workspace)
        try:
            with open(path, encoding="utf-8") as handle:
                return sum(1 for line in handle if line.strip())
        except OSError:
            return 0

    def _count_actions(self, before: int) -> None:
        added = self._action_count() - before
        if added > 0:
            self.store.bump_counter("browser_actions", added)


def resuming(entry: ConversationState) -> str | None:
    """The chat to continue, or `None` when this attempt starts a new one.

    Only a `partial` entry is resumed. A `completed` one re-run under `--force`
    gets a new chat (§17 keeps the old one), and a `failed` one has no chat by
    definition — `06`'s crash recovery is what turns an interrupted run with a
    destination id into the `partial` this reads.
    """
    if entry.status is not Status.PARTIAL:
        return None
    return entry.destination.conversation_id
