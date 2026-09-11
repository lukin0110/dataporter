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
  the export fingerprint, a browser that cannot be brought back, and `13`'s
  circuit breaker — which is about the run's failures rather than about any one
  of them.
- **No content, anywhere.** Titles go into `state.json` because §7 puts them
  there. Stdout gets a short id, a status, two counts and a failure's own
  category; the log gets ids and numbers; Hermes's own stdout stays in the
  workspace file `09` wrote it to.

`13` is what taught it to react. A conversation whose failure is the kind that
another attempt could fix is tried again, after a growing wait, until the
per-conversation budget is spent; a category that no attempt would fix is
recorded once; and a run whose conversations keep failing the same way stops
itself rather than spending an account's quota proving it.

`14` taught it the other kind of second try: the one a *person* makes. A
`needs_human` result is not a failure and not a retry — the run writes a pause
record, asks whoever is at the keyboard to finish the step in the browser window
that is already open, and then attempts *the same conversation from its last
successful step*. It is the same loop `13` retries in, entered through a
different door, and `resume` is that door from a second process.

`17` added the second opinion. A run that comes back `completed` or `partial`
with a chat behind it is not believed on its own: the tool navigates to that
chat, reads it back through our own probe and checks that every part and every
acknowledgement is there (`verify.py`). What the page says is what is recorded —
a verification that fails writes `partial` over the agent's `completed` — and it
is folded into the one state write the attempt already makes, so an entry is
never briefly finished before being un-finished.

`15` filled in the third door, and slowed everything down. A `rate_limited`
result is waited out rather than retried: the account named a time, so the run
sleeps until then and attempts the same conversation again, and only a wait
longer than `pacing.max_rate_limit_wait_s` — or a third refusal of the same
conversation — is put to a person as `14`'s ask. The gaps are `15`'s too: the
delay between conversations, the delay between parts the agent spends inside one
run, and the deadline on the one intervention whose resolution this process can
check for itself.

`18` took the talking away. Every line this loop used to print is now a call on
`progress.Progress`, and `progress.Reporter` decides whether it becomes a redraw
of §10's block or a line down a pipe. The loop's part of that is naming the
moments — a run starting, a conversation ending, a wait, an ask that is about to
take the screen, a run stopping — and reading the counts it hands over from
`state.json` rather than from a tally of its own.
"""

import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from dataporter import PROGRAM_NAME, log, render, state
from dataporter import intervention as intervening
from dataporter import progress as reporting
from dataporter import seed as seeding
from dataporter import verify as verifying
from dataporter.browser import helpers as browser_helpers
from dataporter.browser import launcher, probe
from dataporter.browser import session as browser_session
from dataporter.config import RetrySettings, Settings
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
from dataporter.plan import (
    PLAN_FILENAME,
    AttachmentPlan,
    ConversationPlan,
    MigrationPlan,
    build_plan,
    upload_paths,
)
from dataporter.report import Report
from dataporter.report import build as build_report
from dataporter.report import write as write_report
from dataporter.seed import Seed
from dataporter.state import ConversationState, ErrorRecord, Status
from dataporter.steps import Step

_logger = log.get_logger(__name__)

RATE_LIMIT_PROBE_S = 60.0
"""How long a rate-limit wait sleeps before looking at the page again.

A wait an hour long that cannot be cut short is an hour of a migration spent on a
limit that may have lifted in ten minutes, so the sleep is sliced and the page is
read between slices (`probe.rate_limited`). A minute rather than something
shorter because the check costs a CDP round trip and the thing it is watching for
changes on the account's clock, not ours.
"""

RATE_LIMIT_WAITS = 3
"""How many times in a row one conversation may be waited out.

`15`'s rule for the refusal that names no time — each of those is waited on
`13`'s backoff, which is a guess, and three guesses in a row is a page that is
not going to tell us — extended to the refusals that *do* name a time, because a
conversation refused three times running is an account that will not let this run
finish however long the tool sits still. The third hands the conversation to `14`
instead, which is the difference between a run that is waiting and one that is
stuck.
"""

UNTIL_FORMAT = "%H:%M UTC"
"""How a wait's end is written, as `15` prints it: `rate limit until 15:00 UTC`.

UTC, and said so: every other instant this tool writes is UTC, and a bare `15:00`
on a terminal in another timezone is a number an operator will read wrongly.
Minutes, because the waits are quarters of an hour and longer.
"""

NO_CONVERSATION_ID = "no conversation id"
"""Why a `completed` run with no destination id is recorded as `partial`."""

ATTACHMENT_UPLOAD_FAILED = "attachment upload failed: {file_name}"
"""`16`'s detail for a conversation whose chat is missing one of its files.

The conversation is worth more than the attachment, so the run carries on and
this is what it is recorded as: a `partial` that names the file, because a chat
that is missing a page of a PDF is not a chat anybody should be told is finished.
"""

NOT_REPORTED = "not_reported"
"""A planned upload the run said nothing about.

Neither uploaded nor refused: the agent was given the file and its answer
mentions it in neither list. `16` counts evidence, so what nobody confirmed is
not counted as done — an operator reading `failed: 1, not_reported` goes and
looks at the chat, which is the right thing to do.
"""

ATTACHMENTS_README_FILENAME = "README.txt"
ATTACHMENTS_README = """\
Attachment bytes go here.

A Claude export names the files a conversation carried but does not contain
them, so this directory is how you supply the ones you still have. Anything
found here is uploaded through the claude.ai UI before the conversation's first
message is sent; anything missing is recorded as bytes_not_in_export, and the
migrated conversation says the file was not reproduced.

The layout is one directory per source conversation:

    attachments/<conversation-uuid>/<file name>

A file placed directly in this directory is used by any conversation that names
it, which is the fallback for bytes you have without knowing which chat they
came from. The file name must match the export exactly.

The uuids and the file names are in plan.json, and

    hermes-claude-migrate inspect <export>

lists every attachment and what would become of it.

This file is the only thing the tool writes here; your files are read and never
changed. Deleting what is in this directory only means those files are not
migrated.
"""
"""What `import` leaves in the default attachments directory.

Written because the directory is otherwise an empty folder whose convention
lives in a spec the operator has not read, and because `02` expects the export
to carry no attachment bytes at all — so this file is the only instruction
anybody gets about the one thing they can do about that.
"""

NOT_ATTEMPTED = "not_attempted"
"""A planned upload in a conversation that was never migrated.

The chat it belonged to does not exist — the conversation is unmigratable
(`03`) — so the file is not in the account and never will be by this route.
"""

UNREPORTED = "hermes reported {outcome} without an error"
"""A result that stopped and did not say why. The contract requires an `error`
for every outcome that is not `completed`, so its absence is Hermes's shortfall
and is recorded as one rather than as a blank."""

RATE_LIMITED = "rate limited"
NOT_RELAUNCHABLE = "the browser is gone and could not be started again"

NOTHING_TO_RESUME = "nothing to resume"
"""What `resume` says when `run.json` holds no pause record."""

NEEDS_HUMAN_CATEGORIES: dict[str, Category] = {
    "auth_required": Category.AUTH,
    "captcha": Category.CAPTCHA,
    "security_challenge": Category.SECURITY_CHALLENGE,
    "ambiguous_ui": Category.UI,
    "browser_error": Category.BROWSER,
    "confirmation_required": Category.SAFETY,
}
"""`09`'s six `needs_human` reasons, as the error categories `01` fixed.

`14` turns these into a pause rather than a finished conversation, and this is
what it records against the entry while the human is being asked. `13` spends no
retry on one, because none of the six is something a second identical attempt
clears — only a person's action in the window changes the page. The category is
what tells an operator — and `19` — which of the six it was. A test reads
`runner.NEEDS_HUMAN_REASONS` against this, so a seventh reason cannot arrive
without a category to put it in.
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
    """Sleep. The one seam every wait in this module goes through (`15`).

    A function rather than `time.sleep` at each call site so that a test can
    record what a run *would* have waited without waiting it — which is the only
    way an acceptance criterion about a twenty-second gap is checkable at all.
    """
    if seconds > 0:
        time.sleep(seconds)


def until(seconds: float, *, now: datetime | None = None) -> str:
    """When a wait of `seconds` ends, as `15`'s line and ask write it."""
    return (
        (now if now is not None else state.now()) + timedelta(seconds=seconds)
    ).strftime(UNTIL_FORMAT)


# --------------------------------------------------------------------------- #
# Reading a result as a state entry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Mapped:
    """What one `HermesResult` means for `state.json`."""

    status: Status
    last_step: Step | None
    error: ErrorRecord | None
    deferred: bool = False
    """`needs_human` or `rate_limited`: the two outcomes this run does not try
    again, because somebody else owns what happens next — a person (`14`) or a
    clock (`15`). Recorded here rather than re-read from the outcome so that
    `13`'s retry policy and `12`'s mapping table are the same table."""

    needs_human: bool = False
    """The deferral `14` owns, told apart from `15`'s.

    Both are `deferred` and neither is retried, but only this one is answered by
    asking: the run pauses, a person acts in the window, and the conversation is
    attempted again from where it stopped. `deferred` alone would make the loop
    ask what the outcome was again, which is the re-reading the field exists to
    avoid."""

    rate_limited: bool = False
    """`15`'s deferral: the account asked to be left alone for a while.

    The other half of the pair `needs_human` splits `deferred` into. What answers
    it is a clock, so the loop waits rather than asks — and `retry_after_s` below
    is how long, when the page said.
    """

    retry_after_s: float | None = None
    """Seconds the page named, or `None` when it named none.

    `None` is not zero: it is the difference between a wait `15` can make and a
    guess it has to make on `13`'s backoff, and three guesses in a row become an
    ask. Carried as a field as well as in the error's detail because the detail is
    prose for an operator and this is the number the run acts on.
    """


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


def attachments_of(
    item: ConversationPlan,
    result: hermes_running.HermesResult | None = None,
) -> state.AttachmentCounts:
    """§14's classes for one conversation, as the run left them (`16`).

    Every attachment the plan named ends in exactly one of the four counts, so
    `uploaded + inline + unsupported + failed` is the number of attachments
    `plan.json` found — the reconciliation `19` reports on. Everything that is
    not an upload is detailed as well, with the reason it is not, because §14's
    rule is that nothing is silently ignored.

    `result` is `None` for a conversation nothing ran: its planned uploads are
    `not_attempted` rather than missing from the account for a reason of their
    own.

    A duplicate (`03`, and `16`'s deduplication) is accounted under the name its
    bytes were uploaded as, because that is the one chip the chat has and the one
    name the agent can have reported.
    """
    uploaded: set[str] = set()
    refused: dict[str, str] = {}
    if result is not None:
        uploaded = set(result.attachments_uploaded)
        refused = {
            failure.file_name: failure.error for failure in result.attachments_failed
        }

    counts = {"uploaded": 0, "inline": 0, "unsupported": 0, "failed": 0}
    detail: list[state.AttachmentDetail] = []
    for attachment in item.attachments:
        klass, reason = _became(attachment, uploaded, refused, ran=result is not None)
        counts[klass] += 1
        if klass != "uploaded":
            detail.append(
                state.AttachmentDetail(
                    file_name=log.safe_token(attachment.file_name),
                    klass=klass,
                    reason=reason,
                )
            )
    return state.AttachmentCounts(**counts, detail=detail)


def _became(
    attachment: AttachmentPlan,
    uploaded: set[str],
    refused: Mapping[str, str],
    *,
    ran: bool,
) -> tuple[Literal["uploaded", "inline", "unsupported", "failed"], str | None]:
    """What became of one attachment, and why — `attachments_of`'s one decision."""
    if attachment.klass == "inline":
        # Reproduced in the seed, so there is nothing to explain.
        return "inline", None
    if attachment.klass == "unsupported":
        return "unsupported", attachment.reason
    chip = attachment.duplicate_of or attachment.file_name
    if not ran:
        return "failed", NOT_ATTEMPTED
    if chip in refused:
        return "failed", refused[chip] or NOT_REPORTED
    if chip in uploaded:
        return "uploaded", None
    return "failed", NOT_REPORTED


def _attachment_failure(result: hermes_running.HermesResult) -> ErrorRecord | None:
    """`16`'s record for a run that could not put a file in the chat.

    `retry_recommended` is `True` and is written here rather than read off the
    category, which is the second place in this module where the two disagree
    (`_record_failure` is the first). The category is `unsupported` because that
    is §14's word for a file the destination would not take; the transience is
    not the category's, though — an upload that was refused once may well work
    from a chat with room in it, or after the operator replaces the file, and a
    record saying otherwise would stop `13` from ever finding out.
    """
    if not result.attachments_failed:
        return None
    first = result.attachments_failed[0]
    return ErrorRecord(
        category=Category.UNSUPPORTED,
        detail=ATTACHMENT_UPLOAD_FAILED.format(
            file_name=log.safe_token(first.file_name)
        ),
        retry_recommended=True,
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
            # `16`: a chat that is missing one of its files is not finished, and
            # a run that said `completed` while listing a file it could not
            # attach has told us both things. The list is what decides, not the
            # word: the skill is asked to report `partial` here itself, and a
            # conversation recorded as done is a conversation nobody looks at
            # again.
            missing = _attachment_failure(result)
            if missing is not None:
                return Mapped(Status.PARTIAL, result.step, missing)
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
        # `15` waits and then attempts the same conversation again. Retrying it
        # on `13`'s budget would spend three attempts inside the window the
        # account asked us to wait out, so the row is deferred; `retry_after_s`
        # is kept — in the detail an operator reads and in the field the loop
        # acts on — because it is the number `15` waits.
        #
        # `stopped`, and not the `failed` `13` wrote here while nothing waited:
        # once the wait is followed by another attempt, a rate limit that
        # interrupted a chat has to read as `partial`, or `resuming` sees a
        # `failed` entry, opens a second chat for the same conversation, and
        # §17's one unfixable mistake is made by the slice that was being
        # careful. `15`'s design notes hold the correction.
        detail = _detail(result) or RATE_LIMITED
        if result.retry_after_s is not None:
            detail = f"{detail}; retry after {result.retry_after_s}s"
        return Mapped(
            stopped,
            result.step,
            _error(Category.RATE_LIMIT, detail),
            deferred=True,
            rate_limited=True,
            retry_after_s=result.retry_after_s,
        )
    if outcome == "needs_human":
        # `14` pauses on these. The reason is the category, so that a run an
        # operator reads afterwards says which of the six stopped it.
        reason = result.needs_human_reason
        category = NEEDS_HUMAN_CATEGORIES.get(reason or "", Category.UI)
        return Mapped(
            stopped,
            result.step,
            _error(category, _detail(result) or reason or ""),
            deferred=True,
            needs_human=True,
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
# `13`: what to do about it
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Attempt:
    """What one try at one conversation ended as.

    The pair `12` already wrote down — a status and an error record — plus the
    two numbers `13` decides with: which attempt this was, and whether somebody
    else owns the outcome.
    """

    status: Status
    error: ErrorRecord | None
    attempts: int
    """The entry's `attempts` after this try. What the budget is measured
    against, and it is §7's cumulative count rather than a per-run one."""
    deferred: bool = False
    """`needs_human` or `rate_limited`. Not a failure to try again: `14` waits
    for a person and `15` waits for a clock, and neither wait is a retry."""

    request: "intervening.Request | None" = None
    """`14`'s ask, when this try ended by needing a person.

    The attempt is over either way; this is what the loop puts to whoever is at
    the keyboard before attempting the same conversation again. `None` for every
    other outcome, including `15`'s deferral, which is answered by waiting — and
    which only becomes an ask at the two edges `_rate_limited` names."""

    rate_limited: bool = False
    retry_after_s: float | None = None
    """`15`'s deferral, and the wait the page named for it. Read off `Mapped`
    rather than off the outcome again, so that the loop's policy and `12`'s
    mapping table stay one table."""

    @property
    def retryable(self) -> bool:
        """Whether another attempt is worth making, as the record already says.

        `retry_recommended` is the whole decision. `01` made `transient` a
        property of the error class precisely so that this is a lookup and not a
        judgement: `interpret` reads it off the class and `_record_failure` off
        the exception, which is where the one `hermes` failure that is *not*
        worth retrying — `HermesUsageError`, the same wrong invocation made again
        at a later time — gets its `False`.

        `None` is "unknown", the three per-instance categories `ui`, `browser`
        and `verification`, and it does not retry: the skill has already spent
        this failure's one in-run recovery on the page, and a record that came
        back `null` must still read `null` in the report rather than the `false`
        an exhausted budget would leave.
        """
        return (
            not self.deferred
            and self.status in (Status.FAILED, Status.PARTIAL)
            and self.error is not None
            and self.error.retry_recommended is True
        )


def backoff_for(retries: RetrySettings, attempt: int) -> float:
    """How long to wait after `attempt` failed, before making the next one.

    `13` indexes `backoff_s` by the attempt that just failed. A schedule shorter
    than `max_attempts` repeats its last value rather than running off the end:
    the wait is meant to grow and then stay long, and an operator who shortened
    the list did not ask for the waits to stop.
    """
    schedule = retries.backoff_s
    if not schedule:
        return 0.0
    return schedule[min(max(attempt, 1), len(schedule)) - 1]


@dataclass
class FailureStreak:
    """`13`'s circuit breaker: how many conversations in a row failed alike.

    Only `failed` counts, and only a conversation the loop actually attempted. A
    `partial` left a chat at the destination, and an unsupported entry was never
    handed to Hermes; neither is evidence that the next conversation would go the
    same way, which is the only thing this number is for.
    """

    category: Category | None = None
    count: int = 0

    def record(self, attempt: Attempt) -> None:
        category = attempt.error.category if attempt.error is not None else None
        if attempt.status is not Status.FAILED or category is None:
            self.category, self.count = None, 0
            return
        if category is self.category:
            self.count += 1
            return
        self.category, self.count = category, 1

    def reset(self) -> None:
        """A conversation the loop skipped says nothing either way."""
        self.category, self.count = None, 0

    def tripped(self, limit: int) -> Category | None:
        """The category that has failed `limit` times running, or `None`.

        Returns the category rather than a boolean so that the caller cannot
        reach for `self.category` and find the `None` that would mean no streak.
        A limit of zero or less switches the breaker off.
        """
        if limit > 0 and self.count >= limit and self.category is not None:
            return self.category
        return None


# --------------------------------------------------------------------------- #
# `15`: when the account asks to be left alone
# --------------------------------------------------------------------------- #


RATE_LIMIT_UNNAMED = "rate limit, no time given"
"""The waiting line's reason when the page refused and named no time.

`13`'s backoff is what gets waited instead, so the line has to say that the
number in front of it is ours and not the account's — `waiting 30s (rate limit,
no time given)` beside `waiting 1740s (rate limit until 15:00 UTC)`.
"""


@dataclass
class RateLimitWaits:
    """How many times running this conversation has been refused.

    Per conversation, because the loop that waits is per conversation and the
    escalation hands *that* conversation to a person: a run in which two
    conversations were each refused twice is not a run being stonewalled. Reset
    on an escalation, so that a conversation a person has unblocked gets the same
    patience again rather than an ask after every further refusal.
    """

    waits: int = 0

    def refused(self) -> int:
        """Record a refusal, and say how many that is in a row."""
        self.waits += 1
        return self.waits

    def reset(self) -> None:
        """The count has been spent on an ask, and starts again from there."""
        self.waits = 0


def _why_asking(seconds: float | None, count: int, *, too_long: bool) -> str:
    """The ask's detail: which edge was reached, and what is known about it.

    One wait that is too long to make says only that; a third refusal says how
    many, and then says what it knows about this one — a time, or that there was
    none. An operator deciding whether to sit a wait out is deciding about the
    wait in front of them, so the time goes in the sentence wherever there is one
    to put there.
    """
    if too_long and seconds is not None:
        return intervening.RATE_LIMIT_UNTIL.format(until=until(seconds))
    if seconds is None:
        return intervening.RATE_LIMIT_NO_TIME.format(waits=count)
    return intervening.RATE_LIMIT_AGAIN.format(waits=count, until=until(seconds))


# --------------------------------------------------------------------------- #
# `14`: when only a person can clear it
# --------------------------------------------------------------------------- #


class RunPaused(Exception):
    """A conversation is waiting for a human and there is nobody to ask.

    Not a `MigrationError`: nothing failed. The pause record and the `running`
    entry are the state, `resume` is the continuation, and exit `5` is what the
    run reports. Never leaves `Importer.run` or `Importer.resume`.
    """


class InterventionsExhausted(Exception):
    """`run.max_interventions` asks have been made in one run. Same rules.

    `13`'s breaker ends a run that keeps failing; this ends one that keeps
    asking. Both stop cleanly, and both leave what is left of the selection
    untouched.
    """


class NothingToResume(Exception):
    """`resume` was run over a workspace with no pause to continue (exit `4`)."""


class LoginTimedOut(Exception):
    """An `auth_required` ask outlived `timeouts.login_s` (`15`, exit `3`).

    The third way a run ends early, and the only one that names a cause outside
    the migration: the destination account is not signed in and the person who
    was asked to sign in has not. Like the other two it stops cleanly — the pause
    record stays, so `resume` picks the same conversation up once they have.
    """


# --------------------------------------------------------------------------- #
# What a run comes back with — what it says while it runs is `progress.py`
# --------------------------------------------------------------------------- #


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
    report: Report | None = None
    """§16's account of the workspace, as it stood when the run released the lock.

    `_under_lock` puts it there on the way out, so every summary `import` and
    `resume` hand back carries one — a run that ended badly included, since that
    is the one an operator reads the failure list of. The default is for the
    summaries this class builds on its way to that point.
    """
    stopped: bool = False
    """The run ended before its selection did — `13`'s circuit breaker, or one of
    `14`'s two: a pause nobody was there to answer, and an intervention budget
    spent. Everything the selection had left is still `pending`, so the next
    invocation picks it up with no flags at all."""


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
        progress: reporting.Progress | None = None,
        intervention: intervening.Intervention | None = None,
        force_unlock: bool = False,
    ) -> None:
        self.settings = settings
        self.progress: reporting.Progress = (
            progress if progress is not None else reporting.Reporter()
        )
        self.intervention: intervening.Intervention = (
            intervention if intervention is not None else intervening.Console()
        )
        self.force_unlock = force_unlock
        self.store = state.StateStore(settings.workspace)
        self.runner = hermes_running.HermesRunner(settings)
        self.seeds = seeding.SeedGenerator(settings)
        self.session: launcher.BrowserSession | None = None
        self.plans: dict[str, ConversationPlan] = {}
        """The plan, by conversation, as `_prepare` wrote it.

        Held rather than passed down because every step from `_migrate` to
        `_record` needs one field of it — which files to upload, and what became
        of them — and the alternative is the same object threaded through four
        signatures that have nothing else to do with attachments."""
        self.interventions = 0
        """How many times *this* run has stopped to ask (`14`).

        Per run rather than per workspace, like `13`'s streak and unlike its
        per-conversation budget: the cumulative number in `run.json` is what `19`
        reports, and a migration that took ten runs and asked once in each is not
        a migration that asked ten times."""

    # -- the run ------------------------------------------------------------ #

    def run(self, export_path: Path, selection: state.Selection) -> RunSummary:
        """Migrate what `selection` chooses out of the export at `export_path`."""
        parsed = load_export(export_path)
        return self._under_lock(lambda: self._locked(parsed, export_path, selection))

    def resume(self) -> RunSummary:
        """Continue the run a `needs_human` pause stopped (`14`, §6 Phase 4).

        No export argument, because §8's command surface gives `resume` none: the
        export the paused run was reading is recorded in `run.json`, and the
        fingerprint check that every run makes is what proves it is still the
        same one.
        """
        paused = self._pause_to_resume()
        export_path = self._recorded_export()
        parsed = load_export(export_path)
        return self._under_lock(
            lambda: self._locked_resume(parsed, export_path, paused)
        )

    def _under_lock(self, work: Callable[[], RunSummary]) -> RunSummary:
        lock = state.WorkspaceLock(self.settings.workspace)
        lock.acquire(force_unlock=self.force_unlock)
        try:
            return replace(work(), report=self._write_report())
        finally:
            # Both, on every path: a browser left running holds the next run's
            # debug port, and a lock left behind makes the next run exit `2`.
            # A paused run releases both as well — §12 asks the human to act in
            # the browser window, and `resume` opens a new one.
            self._close_browser()
            lock.release()

    def _locked(
        self, parsed: Export, export_path: Path, selection: state.Selection
    ) -> RunSummary:
        self.store.bind_export(parsed.fingerprint, export_path)
        self.store.recover()
        self._offer_resume()
        self._preflight()

        plan, conversations = self._prepare(parsed)

        order = [item.uuid for item in parsed.conversations]
        chosen = state.select(order, self.store.load(), selection)
        index = self.store.start_run(selection.model_copy(update={"uuids": chosen}))
        result = self._migrate_all(chosen, conversations, plan)
        self.store.finish_run(index, int(result.exit_code))
        return result

    def _locked_resume(
        self, parsed: Export, export_path: Path, paused: state.PauseRecord
    ) -> RunSummary:
        """`import`'s loop, entered in the middle of somebody else's selection.

        The plan is written before the preflight here, where `_locked` does it the
        other way around. Both are cheap and local, and this order is what lets a
        `resume` that finds the page still blocked report a run — `14` says it
        keeps the pause and exits `5`, and a `RunSummary` is how this class says
        anything at all.
        """
        self.store.bind_export(parsed.fingerprint, export_path)
        # Every other interrupted entry is converted; the paused one is not one.
        self.store.recover(keep=paused.conversation_uuid)
        plan, conversations = self._prepare(parsed)

        chosen, offset, total = self._rest_of(paused)
        index = self.store.start_run(self._resumed_selection(chosen))
        try:
            self._preflight(cleared_by=self._request(paused, offset + 1, total))
        except RunPaused:
            result = self._stopped_before_starting(plan, ExitCode.PAUSED)
        except LoginTimedOut:
            self._note_login_timeout()
            result = self._stopped_before_starting(plan, ExitCode.NOT_AUTHENTICATED)
        else:
            result = self._migrate_all(
                chosen, conversations, plan, offset=offset, total=total
            )
        self.store.finish_run(index, int(result.exit_code))
        return result

    def _prepare(
        self, parsed: Export
    ) -> tuple[MigrationPlan, Mapping[str, Conversation]]:
        """The plan on disk and an entry per planned conversation, before any run."""
        self._attachments_directory()
        plan = self._write_plan(parsed)
        self.plans = {item.uuid: item for item in plan.conversations}
        conversations = {item.uuid: item for item in parsed.conversations}
        self._create_entries(plan, conversations)
        return plan, conversations

    def _attachments_directory(self) -> None:
        """Make the default attachments directory, and say what goes in it (`16`).

        Only the default one, inside the workspace: a directory the operator
        named with `--attachments-dir` is theirs, and writing a README into it
        would be this tool leaving litter in somebody else's folder. The export
        is expected to carry no attachment bytes at all (`02`), so an empty
        directory with an explanation in it is the whole mechanism by which an
        operator can supply them.
        """
        if self.settings.attachments.dir is not None:
            return
        directory = self.settings.attachments_dir
        try:
            directory.mkdir(parents=True, exist_ok=True)
            readme = directory / ATTACHMENTS_README_FILENAME
            if not readme.exists():
                readme.write_text(ATTACHMENTS_README, encoding="utf-8", newline="")
        except OSError as exc:
            # Not fatal: a migration without attachments is still a migration,
            # and `03` reports every file it could not find as
            # `bytes_not_in_export` either way.
            _logger.warning("attachments directory", extra={"error": str(exc)})

    # -- 1. preflight ------------------------------------------------------- #

    def _preflight(self, *, cleared_by: intervening.Request | None = None) -> None:
        """Refuse to start unless the whole chain is there (`09`, `07`, §8).

        The local half of `doctor` rather than all of it: the two checks that run
        a real Hermes task cost a minute each and a migration is about to prove
        the same thing with work that counts.

        `cleared_by` is `14`'s resume: the human was asked to fix something in
        this browser and has said they did, so the window comes up first and the
        ask is re-checked before the ordinary sign-in guard runs. Without that
        order a `resume` after a login expiry would exit `3` — "run `login`" —
        at the very moment the operator is being told to log in right there.
        """
        failure = hermes_doctor.local_failure(self.settings)
        if failure is not None:
            raise HermesError(detail=f"{failure.label}: {failure.detail}")
        if cleared_by is None:
            self._open_browser()
            return
        self._launch()
        if not self._cleared(cleared_by, acted=True):
            raise RunPaused
        self._require_signed_in()
        browser_helpers.close_extra_tabs(self._session().client, self.settings)

    def _open_browser(self) -> None:
        """Launch or adopt Chrome, prove the session, leave one tab to drive.

        The mid-run relaunch comes through here too, because a browser that came
        back is as unproven as one that has just started: a Chrome that died may
        never have written the profile that kept it signed in, and one restarted
        over the same `--user-data-dir` can restore the tabs it had open — which
        is the `ambiguous_tab` that `close-extra-tabs` exists to clear.

        A session that is signed out ends the run (exit `3`) wherever it is
        noticed: every remaining conversation would fail the same way, and
        nothing has been asked of anyone yet — `login` is the fix, and it is what
        the message says. `14`'s pause is the other case, where a run that was
        *already under way* met a sign-in form: there a chat may exist, a step is
        half done, and the operator is asked to log in in the window in front of
        them rather than made to start again.
        """
        self._launch()
        self._require_signed_in()
        # Blank and duplicate new-chat tabs only, never a conversation (`08`).
        # Hermes picks its tab by looking, and one candidate is what makes that
        # unambiguous.
        browser_helpers.close_extra_tabs(self._session().client, self.settings)

    def _launch(self) -> None:
        self.session = launcher.launch(self.settings, probe.NEW_CHAT_URL)

    def _require_signed_in(self) -> None:
        if not self._signed_in():
            raise AuthError(detail=browser_session.SIGNED_OUT)

    def _signed_in(self) -> bool:
        return browser_session.signed_in(self._session())

    def _session(self) -> launcher.BrowserSession:
        session = self.session
        if session is None:  # pragma: no cover - nothing asks before the launch
            raise BrowserError(detail="no browser session")
        return session

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

    def _write_report(self) -> Report:
        """`19`'s report, built and written before the lock is released.

        Under the lock because `report.json` is a workspace file like the other
        three, and after `finish_run` because the run that has just ended is one
        of the runs it accounts for. The CLI is what prints it: `18` took the
        formatting out of this module and this slice does not put any back.
        """
        report = build_report(self.settings.workspace)
        write_report(self.settings.workspace, report)
        return report

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
                # A conversation that will not be migrated takes its files with
                # it, and `16` says so rather than leaving four zeros that read
                # as a conversation with no attachments.
                attachments=attachments_of(item),
            )

    # -- 3. one conversation at a time -------------------------------------- #

    def _migrate_all(
        self,
        chosen: Sequence[str],
        conversations: Mapping[str, Conversation],
        plan: MigrationPlan,
        *,
        offset: int = 0,
        total: int | None = None,
    ) -> RunSummary:
        """The selection, one conversation at a time, until it ends or stops.

        `offset` and `total` are `14`'s: a `resume` runs the tail of somebody
        else's selection, and "conversation 12 of 127" has to keep meaning the
        same thing across the pause. They change nothing about what runs.
        """
        migratable = {item.uuid for item in plan.conversations if item.migratable}
        of = len(chosen) + offset if total is None else total
        # §10's header, from the workspace rather than from this selection: the
        # count is every conversation the plan found, and the block under it
        # starts at whatever earlier runs already finished (`18`).
        self.progress.start(state.status_counts(self.store.load()))
        outcomes: dict[str, Status] = {}
        streak = FailureStreak()
        stopped = False
        exit_code: ExitCode | None = None
        for position, uuid in enumerate(chosen):
            if uuid in migratable:
                try:
                    attempt = self._migrate(
                        conversations[uuid], position=offset + position + 1, total=of
                    )
                except RunPaused:
                    # The pause is on disk and the conversation is still
                    # `running`: `resume` is what finishes it, and nothing else
                    # was started.
                    exit_code, stopped = ExitCode.PAUSED, True
                    break
                except InterventionsExhausted:
                    self.intervention.note(intervening.TOO_MANY_INTERVENTIONS)
                    exit_code, stopped = ExitCode.FAILED, True
                    break
                except LoginTimedOut:
                    # `15`: the ask was `auth_required` and `timeouts.login_s`
                    # ran out. The pause record stays, so this is still a run
                    # `resume` continues — but the code says what is wrong with
                    # the account rather than that a person is being waited on.
                    self._note_login_timeout()
                    exit_code, stopped = ExitCode.NOT_AUTHENTICATED, True
                    break
                status = attempt.status
                streak.record(attempt)
            else:
                # Selected by `--retry-failed` over an entry `_create_entries`
                # wrote. There is no seed to paste, so there is nothing to run;
                # the entry already says why, and the line says so again. It is
                # also not a failure of the destination, so the breaker forgets
                # rather than counts it.
                status = self.store.load()[uuid].status
                streak.reset()
            outcomes[uuid] = status
            current = self.store.load()
            counts = state.status_counts(current)
            # The entry's own error rather than the attempt's: a `partial` this
            # run wrote and a `failed` `--retry-failed` re-read are the same
            # line, and §7's record is what `19` will report either way.
            self.progress.conversation(
                render.short_id(uuid), status, counts, current[uuid].error
            )
            tripped = streak.tripped(self.settings.run.stop_after_consecutive_failures)
            if tripped is not None:
                self._stop(streak.count, tripped)
                stopped = True
                break
            if position + 1 < len(chosen):
                # §13's gap, between conversations and not after the last one:
                # the delay exists to space out what the account sees, and there
                # is nothing after the last conversation to space it from.
                pause(self.settings.pacing.delay_between_conversations_s)

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
            exit_code=exit_code
            if exit_code is not None
            else (
                ExitCode.NOTHING_TO_DO
                if not chosen
                else (ExitCode.OK if finished else ExitCode.FAILED)
            ),
            stopped=stopped,
        )

    def _stopped_before_starting(
        self, plan: MigrationPlan, exit_code: ExitCode
    ) -> RunSummary:
        """A `resume` that never got past the ask, as a summary (`14`).

        Two codes reach it: `5` when there was nobody to answer, and `3` when
        somebody answered and the account is still signed out (`15`).
        """
        return RunSummary(
            total=len(plan.conversations),
            selected=(),
            outcomes={},
            counts=state.status_counts(self.store.load()),
            exit_code=exit_code,
            stopped=True,
        )

    def _stop(self, failures: int, category: Category) -> None:
        """End the run early, cleanly: the state is written, the lock is released
        by `run`'s `finally`, and what is left of the selection is untouched."""
        _logger.warning(
            "stopping after consecutive failures",
            extra={"failures": failures, "category": str(category)},
        )
        self.progress.stopping(failures, category)

    def _migrate(
        self, conversation: Conversation, *, position: int, total: int
    ) -> Attempt:
        """One conversation, with `13`'s retry budget and `14`'s pause around it.

        The loop is here and not inside `_attempt` because every attempt is a
        whole attempt: it re-reads the entry, writes this attempt's seed, renders
        a prompt that resumes from wherever the last one stopped, and runs Hermes
        again. A retry of a `partial` therefore continues the chat that exists
        rather than opening a second one (§17) — `_begin` and `resuming` are what
        make that true, and they are read afresh each time round.

        Two doors into the same loop. `13`'s is a failure another try could fix,
        waited out on a backoff; `14`'s is a page only a person can clear, waited
        out on that person. They never compete: a `needs_human` result is
        `deferred`, so `retryable` is false for it, and the ask is put before the
        budget is consulted — a conversation can still be unblocked by hand after
        its retries are gone.

        `15` added the third door: a `rate_limited` result is waited out and the
        same conversation attempted again, and only at the two edges
        `_rate_limited` names does it become `14`'s ask. It shares the door with
        `14` because both are the same shape — an attempt nobody failed, followed
        by another attempt at the same conversation.

        `spared` is what keeps the budgets apart. Every attempt increments §7's
        `attempts`, which is what `13` measures `max_attempts` against, so
        without it a conversation a person unblocked twice — or one the account
        made wait twice — would have spent its retries on being helped, and
        `_exhausted` would then write `retry_recommended: false` about a failure
        that is nothing of the kind. `13` counts attempts a failure caused; the
        ones a person did and the ones a clock did are discounted here. Only this
        run's: §7's count is cumulative and records no reason, so a deferral in
        an earlier run is still counted against the budget in this one, which
        errs towards trying less rather than more.
        """
        budget = self.settings.retries
        spared = 0
        waits = RateLimitWaits()
        # Whether the attempt about to be made would count as a retry in
        # `run.json`. True to begin with, because an entry that already has an
        # attempt behind it is being tried again — `--retry-partial` over an
        # earlier run's chat is a retry and always was. It goes false only for
        # the attempt that follows a wait or an ask, which are `15`'s and `14`'s
        # counters rather than `13`'s, and `19` reports the three apart.
        counted = True
        while True:
            attempt = self._attempt(
                conversation, position=position, total=total, counted=counted
            )
            counted = True
            if attempt.rate_limited:
                # A wait, or — too long, or too often — an ask.
                request = self._rate_limited(
                    conversation.uuid, attempt, waits, position=position, total=total
                )
                if request is not None:
                    self._intervene(request)
                spared += 1
                counted = False
                continue
            if attempt.request is not None:
                # Raises to end the run if there is nobody to ask, or if this run
                # has asked too often; otherwise a person has acted and the same
                # conversation is tried again from its last successful step.
                self._intervene(attempt.request)
                spared += 1
                counted = False
                continue
            if not attempt.retryable:
                return attempt
            # What `13` counts: attempts this conversation spent on a failure.
            # It is the budget, the backoff's index and the number the waiting
            # line prints, all three, because all three mean "which retry".
            tried = attempt.attempts - spared
            if tried >= budget.max_attempts:
                return self._exhausted(conversation.uuid, attempt)
            wait = backoff_for(budget, tried)
            self._announce_retry(
                conversation.uuid, attempt, wait, budget.max_attempts, tried
            )
            pause(wait)

    def _attempt(
        self,
        conversation: Conversation,
        *,
        position: int,
        total: int,
        counted: bool = True,
    ) -> Attempt:
        """One try: seed, prompt, Hermes, state. Never raises upward for anything
        that is about this conversation rather than about the run.

        `counted` is false for the try that follows a wait `15` made or an ask
        `14` put: neither is a failure tried again, and `run.json`'s `retries`
        counts only failures tried again.
        """
        uuid = conversation.uuid
        self._ensure_browser()
        entry = self._begin(uuid, counted=counted)
        attempts = entry.attempts + 1
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
            return self._record_failure(uuid, entry, exc, attempts)
        finally:
            self._count_actions(actions)
        return self._record(
            uuid, entry, seed, result, attempts, position=position, total=total
        )

    def _announce_retry(
        self,
        uuid: str,
        attempt: Attempt,
        wait: float,
        max_attempts: int,
        tried: int,
    ) -> None:
        """Say what is about to be waited for, in the log and on stdout.

        The log record is `13`'s: the conversation, the attempt that failed, its
        category and the wait. The short id and not the uuid, because that is the
        identifier every other record in this module carries and §10 keeps the
        two files reading alike.

        `attempt.attempts` is §7's cumulative count and names the run's files;
        `tried` is how many of those this conversation spent failing, which is
        what `retry n/max` is counting. They differ only once `14` has been asked
        about this conversation — and a line reading `retry 4/3` would be the
        giveaway that the two had been confused.
        """
        category = attempt.error.category if attempt.error is not None else None
        _logger.info(
            "retry",
            extra={
                "conversation_id": render.short_id(uuid),
                "attempt": attempt.attempts,
                "category": str(category),
                "backoff_s": wait,
            },
        )
        self.progress.waiting(wait, f"retry {tried + 1}/{max_attempts}, {category}")

    def _exhausted(self, uuid: str, attempt: Attempt) -> Attempt:
        """Write down that the budget is spent, so nothing recommends a retry.

        `13`'s rule for the field: `false` when the category is non-transient
        **or** the attempts are gone. Only a `true` is rewritten — a `null` means
        the transience was never known, and spending a budget does not turn not
        knowing into knowing.
        """
        if attempt.error is None:  # pragma: no cover - `retryable` implies one
            return attempt
        spent = attempt.error.model_copy(update={"retry_recommended": False})
        self.store.update(uuid, error=spent)
        _logger.info(
            "retries exhausted",
            extra={
                "conversation_id": render.short_id(uuid),
                "attempts": attempt.attempts,
                "category": str(spent.category),
            },
        )
        return replace(attempt, error=spent)

    def _begin(self, uuid: str, *, counted: bool = True) -> ConversationState:
        """Mark the entry `running` and hand back what it looked like before.

        The `before` picture is what the rest of the conversation reads: which
        chat to resume, how many parts are already acknowledged, which attempt
        this is. Reading it after the update would read our own write.

        `counted` is what `run.json`'s `retries` counts, and it defaults to the
        rule that held before `15`: a second attempt on an entry that already has
        one is a retry. `_migrate` passes `False` for the attempt that follows a
        rate-limit wait or a human's Enter, because neither is a failure tried
        again — `19` reports the three counters apart and would otherwise report
        the same event twice.
        """
        # A pause is an open question about one conversation, and starting that
        # conversation again is the answer — whether a `resume` did it or a later
        # `import` picked the conversation up on its own.
        paused = self.store.run().paused
        if paused is not None and paused.conversation_uuid == uuid:
            self.store.set_paused(None)
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
        if attempts > 1 and counted:
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
            # `16`: the class 2 files, each one once, in message order. The
            # plan decided which they are — offline, before the run — so a
            # conversation's upload list cannot change between the dry run that
            # showed it and the run that performs it.
            attachments=self._uploads(uuid),
            resume_from=resume_from,
            conversation_id=resume,
            acknowledged=acknowledged,
            # §13's other gap. Ours to send and the agent's to spend: the
            # per-part loop is inside the run this line is about to start.
            delay_between_parts_s=self.settings.pacing.delay_between_parts_s,
            # `17`: what the chat should be called. Capped and squashed by the
            # same function that later compares the page against it, and empty —
            # `none` in the prompt, no rename step at all — when the source had
            # no title or `fidelity.rename_title` is off.
            title=verifying.intended_title(self.settings, before.title),
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

    def _uploads(self, uuid: str) -> list[Path]:
        """The files this conversation's prompt lists, or none.

        A conversation with no plan entry has no uploads rather than an error:
        `_prepare` writes one for every conversation in the export, so the only
        way here is a caller of `_attempt` that never went through it — a test,
        and one that is not about attachments.
        """
        item = self.plans.get(uuid)
        return [] if item is None else upload_paths(item)

    # -- what a conversation leaves behind ---------------------------------- #

    def _record(
        self,
        uuid: str,
        before: ConversationState,
        seed: Seed,
        result: hermes_running.HermesResult,
        attempts: int,
        *,
        position: int,
        total: int,
    ) -> Attempt:
        acked = max(0, min(result.chunks_acked, len(seed.chunks)))
        conversation_id = result.conversation_id or resuming(before)
        mapped = interpret(result, landed=conversation_id is not None)
        status, error = mapped.status, mapped.error
        # `14`: a conversation waiting for a person is not finished, so its entry
        # keeps the status it has. Everything else about where it got to is
        # written either way — the resume reads it back.
        reached = {
            "destination": state.Destination(conversation_id=conversation_id),
            "last_step": mapped.last_step,
            "chunks_acked": acked,
            # The messages in the parts that were acknowledged, and no others: a
            # message split across two parts belongs to neither until both land.
            "messages_represented": sum(
                len(chunk.message_uuids) for chunk in seed.chunks[:acked]
            ),
            "error": error,
        }
        item = self.plans.get(uuid)
        if item is not None:
            # `16`: what became of every file, from the plan that named them and
            # the two lists the run answered with. Written on every outcome,
            # `needs_human` included — a file that was attached before the page
            # blocked is attached, and the resume will not attach it twice.
            reached["attachments"] = attachments_of(item, result)
        if mapped.needs_human:
            self.store.update(uuid, **reached)
        else:
            # `17`: the page, not the agent. Folded into this one update rather
            # than written after it, so that a chat the page says is incomplete
            # is never `completed` in the file for the length of a CDP call — and
            # so that `verified_at` and the status it belongs to are stamped
            # together.
            found = self._verify(uuid, before, seed, result, conversation_id)
            if found is not None:
                status, error = verifying.applied(found, status, error)
                reached.update(verifying.fields(self.store.load()[uuid], found))
            self.store.update(uuid, **{**reached, "status": status, "error": error})
        if result.actions:
            _logger.debug(
                "hermes reported actions",
                extra={"conversation_id": seed.short_id, "actions": result.actions},
            )
        return Attempt(
            status=status,
            error=error,
            attempts=attempts,
            deferred=mapped.deferred,
            rate_limited=mapped.rate_limited,
            retry_after_s=mapped.retry_after_s,
            request=self._pause(
                uuid,
                reason=result.needs_human_reason or intervening.DEFAULT_REASON,
                detail=mapped.error.detail if mapped.error else "",
                # The step a resume starts from, which is what `_run_hermes` will
                # use: `open` when Hermes named a step no procedure of ours has.
                last_step=mapped.last_step or Step.OPEN,
                conversation_id=conversation_id,
                position=position,
                total=total,
            )
            if mapped.needs_human
            else None,
        )

    def _verify(
        self,
        uuid: str,
        before: ConversationState,
        seed: Seed,
        result: hermes_running.HermesResult,
        conversation_id: str | None,
    ) -> verifying.Verification | None:
        """Read the chat back, or say why there was nothing to read (`17`).

        `None` — no verification at all — in the two cases `17` names: a run that
        reported neither `completed` nor `partial`, and a run with no chat to
        navigate to. The first is the more interesting: `rate_limited` and
        `needs_human` are conversations somebody else still owns, and `failed` is
        a run that already said what went wrong and where it got to — reading its
        chat back would find exactly the parts it told us were missing.
        """
        if conversation_id is None or result.outcome not in ("completed", "partial"):
            return None
        expected = verifying.Expected(
            conversation_uuid=uuid,
            conversation_id=conversation_id,
            parts=len(seed.chunks),
            title=verifying.intended_title(self.settings, before.title),
        )
        return verifying.Verifier(self.settings, self._session().client).verify(
            expected
        )

    def _record_failure(
        self, uuid: str, before: ConversationState, exc: MigrationError, attempts: int
    ) -> Attempt:
        """An exception, as one conversation's entry.

        `partial` when a chat already exists, `failed` otherwise — the same rule
        the result mapping uses, and for the same reason: `failed` means there is
        nothing at the destination to go and look at.

        `retry_recommended` comes off the *instance* here rather than off the
        category, which is the one place the two disagree: `HermesUsageError` is
        category `hermes` and never worth retrying, and `13` reads this field as
        the retry decision.
        """
        resume = resuming(before)
        status = Status.PARTIAL if resume is not None else Status.FAILED
        error = ErrorRecord(
            category=exc.category,
            detail=exc.detail or type(exc).__name__,
            retry_recommended=exc.transient,
        )
        self.store.update(uuid, status=status, error=error)
        return Attempt(status=status, error=error, attempts=attempts)

    # -- 4. when only a person can clear it (§12) ---------------------------- #

    def _pause(
        self,
        uuid: str,
        *,
        reason: str,
        detail: str,
        last_step: Step,
        conversation_id: str | None,
        position: int,
        total: int,
    ) -> intervening.Request:
        """Write down what is being asked for, and count the ask.

        The entry stays `running` — `_record` is what does not change it — because
        nothing about this conversation is settled, a chat may already exist, and
        §7's five statuses have no word for "waiting for a person". The pause
        record in `run.json` is that word, which is why it lives there: the §7
        file keeps its shape.

        Takes the four fields rather than a `HermesResult`, because `15` raises
        an ask about a result that asked for nothing: a rate limit too long to
        wait out is `confirmation_required` with a detail this class writes. One
        pause record, one counter and one `resume` either way.
        """
        self.store.set_paused(
            state.PauseRecord(
                conversation_uuid=uuid,
                reason=reason,
                detail=detail,
                last_step=last_step,
                conversation_id=conversation_id,
                since=state.now(),
            )
        )
        self.interventions += 1
        self.store.bump_counter("human_interventions")
        _logger.warning(
            "human intervention required",
            extra={
                "conversation_id": render.short_id(uuid),
                "reason": reason,
                "step": str(last_step),
            },
        )
        return intervening.Request(
            short_id=render.short_id(uuid),
            reason=reason,
            detail=detail,
            last_step=last_step,
            position=position,
            total=total,
        )

    # -- 5. when the account asks to be left alone (§13) --------------------- #

    def _rate_limited(
        self,
        uuid: str,
        attempt: Attempt,
        waits: RateLimitWaits,
        *,
        position: int,
        total: int,
    ) -> intervening.Request | None:
        """Wait the limit out, or hand it to a person. `None` when it waited.

        §13's "wait as instructed": when the page named a time, that time is what
        is waited — not a backoff of ours, and not a retry, because the account
        has told us what it wants and doing something else is how a migration
        earns a longer limit. When it named none, `13`'s backoff is waited
        instead, and the line says whose number it is.

        Two things end the waiting rather than extend it, and both are the point
        at which sitting still stops being a considered act. A wait longer than
        `pacing.max_rate_limit_wait_s` is the operator's call and not ours. A
        third refusal in a row is an account that is not going to let this run
        finish, whether or not it says when — so it is put to a person, who can
        see what the tool cannot.
        """
        seconds = attempt.retry_after_s
        count = waits.refused()
        cap = self.settings.pacing.max_rate_limit_wait_s
        too_long = seconds is not None and seconds > cap
        if too_long or count >= RATE_LIMIT_WAITS:
            waits.reset()
            return self._ask_to_wait(
                uuid,
                _why_asking(seconds, count, too_long=too_long),
                position=position,
                total=total,
            )
        if seconds is None:
            # `13`'s schedule, indexed by how many times this has happened: the
            # waits grow, so a page that keeps refusing is not asked again
            # immediately.
            self._wait_out(
                uuid, backoff_for(self.settings.retries, count), RATE_LIMIT_UNNAMED
            )
            return None
        self._wait_out(
            uuid, seconds, intervening.RATE_LIMIT_UNTIL.format(until=until(seconds))
        )
        return None

    def _wait_out(self, uuid: str, seconds: float, reason: str) -> None:
        """Sleep, in slices, watching for a limit that lifted early.

        The whole wait is announced once, before the first slice, because it is
        what the run is doing and an operator watching a terminal should not have
        to add sixty-second lines up. `18` may draw it as a countdown; the line
        it replaces is this one.
        """
        self.store.bump_counter("rate_limit_waits")
        _logger.info(
            "waiting out a rate limit",
            extra={"conversation_id": render.short_id(uuid), "wait_s": seconds},
        )
        self.progress.waiting(seconds, reason)
        remaining = seconds
        while remaining > 0:
            slice_s = min(remaining, RATE_LIMIT_PROBE_S)
            pause(slice_s)
            remaining -= slice_s
            if remaining > 0 and self._can_send_again():
                _logger.info("rate limit lifted early", extra={"left_s": remaining})
                return

    def _can_send_again(self) -> bool:
        """Whether the page would take a submit now. `False` when it cannot tell.

        Conservative in both directions: a browser that cannot be read is not
        evidence of anything, and neither is an idle empty composer
        (`probe.rate_limited` answers `None` for that one). The cost of being
        wrong here is a wait that runs its full course, which is what the account
        asked for anyway; the cost of the opposite would be submitting into a
        limit that is still in force.
        """
        try:
            return (
                probe.rate_limited(browser_session.current_state(self._session()))
                is False
            )
        except BrowserError:
            # `_ensure_browser` is what deals with a browser that has gone; this
            # is only deciding whether to stop waiting early.
            _logger.debug("could not read the page while waiting out a rate limit")
            return False

    def _ask_to_wait(
        self, uuid: str, detail: str, *, position: int, total: int
    ) -> intervening.Request:
        """Turn a rate limit into `14`'s ask, from what the entry already says.

        The entry is read rather than passed because `_record` has just written
        where this conversation got to, and a pause record that disagreed with it
        would send the resume to a different chat or a different step.
        """
        entry = self.store.load()[uuid]
        return self._pause(
            uuid,
            reason=intervening.CONFIRMATION_REQUIRED,
            detail=detail,
            last_step=entry.last_step or Step.OPEN,
            conversation_id=entry.destination.conversation_id,
            position=position,
            total=total,
        )

    def _intervene(self, request: intervening.Request) -> None:
        """Ask, and come back only when a human says they have acted.

        Raises rather than returns a verdict because both ways out end the run
        and neither is this conversation's own outcome: the conversation is
        exactly as unfinished as it was, and something above has to stop.
        """
        if self.interventions > self.settings.run.max_interventions:
            raise InterventionsExhausted
        if not self._cleared(request):
            raise RunPaused

    def _cleared(self, request: intervening.Request, *, acted: bool = False) -> bool:
        """Wait until the reason for the pause no longer holds. `False` to stop.

        `acted` skips the ask: `resume` *is* the human saying they have acted, so
        the block would be printed at somebody who has already read it, and a
        `retry` is itself a wait — asking twice for one Enter would swallow it.
        Both still go through the same check, and are told again if it fails.

        `15` put a clock on the one reason that has a check behind it: an
        `auth_required` ask that is still not signed in `timeouts.login_s` after
        it was first put raises `LoginTimedOut`, and the run ends with exit `3`
        rather than trading Enters forever. The deadline is read where the
        human's answer comes back and not while the prompt is waiting for it,
        because the ask is a blocking read on a terminal and nothing here can
        interrupt one — a person who never answers is `Console`'s case, not this
        one, and a pipe that cannot answer has already said so.
        """
        deadline = (
            time.monotonic() + self.settings.timeouts.login_s
            if request.reason == intervening.AUTH_REQUIRED
            else None
        )
        # The ask is printed where `18`'s block redraws itself, so the block
        # stands aside for it and is drawn again underneath — however this
        # returns, and including the paths that end the run: a person reading a
        # stopped terminal is owed the numbers it stopped at.
        self.progress.interrupted()
        try:
            while True:
                if not acted and not self.intervention.ask(request):
                    return False
                if request.reason != intervening.AUTH_REQUIRED or self._signed_in():
                    return True
                if deadline is not None and time.monotonic() >= deadline:
                    raise LoginTimedOut
                if not self.intervention.retry(intervening.STILL_NOT_LOGGED_IN):
                    return False
                acted = True
        finally:
            self.progress.resumed()

    def _note_login_timeout(self) -> None:
        """Say why the run stopped on an ask it had been answering (`15`)."""
        self.intervention.note(
            intervening.LOGIN_TIMED_OUT.format(seconds=self.settings.timeouts.login_s)
        )

    def _offer_resume(self) -> None:
        """Point an `import` at the pause an earlier run left behind."""
        paused = self.store.run().paused
        if paused is not None:
            self.intervention.note(
                intervening.offer(render.short_id(paused.conversation_uuid))
            )

    def _pause_to_resume(self) -> state.PauseRecord:
        """The pause `resume` continues, or nothing to continue."""
        paused = self.store.run().paused
        if paused is None:
            raise NothingToResume
        entry = self.store.load().get(paused.conversation_uuid)
        if entry is not None and entry.status is Status.COMPLETED:
            # Somebody finished it another way — an `import` that selected it, a
            # second operator. Resuming would open a second chat for a
            # conversation that already has one, which §17 has no way to undo.
            self.store.set_paused(None)
            raise NothingToResume
        return paused

    def _recorded_export(self) -> Path:
        recorded = self.store.run().export_path
        if not recorded:
            raise state.StateError(
                f"{state.RUN_FILENAME} does not say which export this workspace "
                f"came from — run {PROGRAM_NAME} import <export> instead"
            )
        path = Path(recorded)
        if not path.exists():
            raise state.StateError(f"export not found: {recorded}")
        return path

    def _rest_of(self, paused: state.PauseRecord) -> tuple[list[str], int, int]:
        """What is left of the paused run: its uuids, where they resume, how many.

        The tail of the last run's selection rather than a fresh one, because
        §12 is about continuing *that* run: a selection recomputed now would drop
        the paused conversation (it is `running`, which nothing selects) and pick
        up whatever has become pending since.
        """
        runs = self.store.run().runs
        uuids = list(runs[-1].selection.uuids) if runs else []
        if paused.conversation_uuid in uuids:
            offset = uuids.index(paused.conversation_uuid)
            return uuids[offset:], offset, len(uuids)
        # A pause with no selection behind it — a `run.json` written by hand, or
        # a record that outlived its run. The conversation it names is still the
        # thing to continue, and it is all there is.
        return [paused.conversation_uuid], 0, 1

    def _resumed_selection(self, chosen: Sequence[str]) -> state.Selection:
        """The paused run's flags, over what is left of its selection."""
        runs = self.store.run().runs
        previous = runs[-1].selection if runs else state.Selection()
        return previous.model_copy(update={"uuids": list(chosen)})

    def _request(
        self, paused: state.PauseRecord, position: int, total: int
    ) -> intervening.Request:
        """The pause record, as the ask a `resume` re-checks."""
        return intervening.Request(
            short_id=render.short_id(paused.conversation_uuid),
            reason=paused.reason,
            detail=paused.detail,
            last_step=paused.last_step or Step.OPEN,
            position=position,
            total=total,
        )

    # -- the run's own housekeeping ----------------------------------------- #

    def _ensure_browser(self) -> None:
        """The browser is still there, or this run is over.

        Checked before each conversation rather than after each failure: a dead
        Chrome found here costs one HTTP call, and found later costs a Hermes run
        that had nowhere to go. A browser that cannot be started again is the one
        browser failure that ends the run (exit `6`); one that comes back is put
        through the same two checks the preflight makes, since nothing about a
        replacement browser is known until it has answered them.
        """
        session = self.session
        if session is not None and session.client.responding():
            return
        _logger.warning("browser not responding; starting it again")
        self.session = None
        try:
            self._open_browser()
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
        it, and a run that never called one cannot inflate it. `19` counts the
        same file the same way, through the same function.
        """
        return browser_helpers.count_actions(self.settings.workspace)

    def _count_actions(self, before: int) -> None:
        added = self._action_count() - before
        if added > 0:
            self.store.bump_counter("browser_actions", added)


RESUMABLE: frozenset[Status] = frozenset({Status.PARTIAL, Status.RUNNING})
"""The two statuses whose chat a new attempt continues instead of replacing.

`partial` is a chat that does not hold everything. `running` is `14`'s: a
conversation this run paused on, or one a `resume` kept out of crash recovery —
either way a human has just been asked to unblock the chat that is on the screen,
and opening a second one is the restart §12 says not to do. No other status can
be `running` by the time an attempt begins: `recover` converts the ones a crash
left, and it runs before the first conversation does.
"""


def resuming(entry: ConversationState) -> str | None:
    """The chat to continue, or `None` when this attempt starts a new one.

    A `completed` entry re-run under `--force` gets a new chat (§17 keeps the old
    one), and a `failed` one has no chat by definition — `06`'s crash recovery is
    what turns an interrupted run with a destination id into the `partial` this
    reads.
    """
    if entry.status not in RESUMABLE:
        return None
    return entry.destination.conversation_id
