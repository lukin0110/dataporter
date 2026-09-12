"""Trust the page, not the agent.

Everything up to `16` believes Hermes. It reports `completed`, `12` writes
`completed`, and the only evidence that the chat in the account holds the
conversation is the word of the thing that was asked to put it there. §11 asks
for the opposite habit — verify the important actions instead of assuming they
worked — and this module is that habit applied to the agent itself: after a run
says it finished, the tool navigates to the chat it named, reads the page through
our own CDP probe, and checks that every part and every acknowledgement is
actually there.

Four checks, in the order a failure is worth knowing about:

1. **The chat exists.** The page is a `/chat/<uuid>` and the uuid is the one the
   run recorded. Everything else is a question about a page that is not there.
2. **The history is there.** At least as many human messages as the conversation
   had parts, and the first one carries `Original conversation ID: <uuid>` —
   `04`'s header line, which is what ties a chat in the destination back to the
   export it came from.
3. **Every part was acknowledged.** For each part, some assistant message
   contains that part's `MIGRATION-ACK` line. An assistant turn is the only
   evidence that a part was received rather than merely sent.
4. **The title.** Not a check that can fail a conversation: a chat whose rename
   did not take is a chat with the wrong name and the right content, so it is
   recorded as the limitation `title_not_set` and §15's "semantic usability over
   structural metadata" is honoured rather than argued with.

No content crosses the wire in any of it. Every question is asked as "is this
string of *mine* in that turn" and answered by the page (`probe`), and the title
is compared in the page too — what comes back is a boolean and a length. The one
place a title exists in this process is the string we render from `state.json`
to ask about, and it goes no further than the CDP call and the prompt (`11`).

A verification failure is `partial`, never `failed`: a chat exists, an operator
can go and look at it, and the next attempt continues it rather than opening a
second one (§17). It is also `retry_recommended: true` — a missing part is
exactly what a resumed attempt knows how to fix.
"""

import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from dataporter import log, render, state
from dataporter.browser import helpers as browser_helpers
from dataporter.browser import probe as probing
from dataporter.browser.cdp import CdpClient
from dataporter.config import Settings
from dataporter.console import DISCARD, Sink
from dataporter.errors import BrowserError, Category, MigrationError
from dataporter.exit_codes import ExitCode
from dataporter.state import ConversationState, ErrorRecord, Status

_logger = log.get_logger(__name__)

POLL_S = 0.5
"""How often a reloaded chat is looked at while it renders.

Twice a second: a page load is a second or two and `timeouts.verify_s` is thirty,
so this is sixty round trips at the very worst and four in the ordinary case.
"""

ELLIPSIS = "…"
"""What a title too long for `fidelity.title_max_chars` ends in."""


# --------------------------------------------------------------------------- #
# What can go wrong, in the words the report prints
# --------------------------------------------------------------------------- #

CHAT_MISSING = "chat missing"
"""The URL is not this conversation's chat: a 404, a redirect, another chat."""

CHAT_UNREADABLE = "chat unreadable"
"""The page could not be read at all — no claude.ai tab, a browser that has gone
away, a URL the safety gate refuses. Distinct from `chat missing`, which is a
page that answered and was the wrong one."""

HISTORY_MISSING = "history missing"
"""Fewer human messages than the conversation has parts."""

SOURCE_ID_MISSING = "source id missing"
"""The first human message does not carry `04`'s `Original conversation ID:`
line, so whatever is in this chat, it is not this conversation's first part."""

ACK_MISSING = "ack {part}/{total} missing"
"""No assistant turn acknowledged this part."""

TIMESTAMPS_NOT_PRESERVED = "timestamps_not_preserved"
"""Recorded against every chat that lands (§15, `docs/LIMITATIONS.md`).

Always, and without looking: a message is timestamped when it is pasted and the
composer offers no way to say otherwise. It is written down per conversation
rather than only in `LIMITATIONS.md` so that `19`'s report of one conversation is
complete on its own.
"""

TITLE_NOT_SET = "title_not_set"
"""The chat is not called what the source conversation was called.

Either because `fidelity.rename_title` is off, or because the source title is
empty, or because the rename did not take. All three are the same fact about the
destination, which is what a limitation records.
"""


# --------------------------------------------------------------------------- #
# What a conversation is checked against
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Expected:
    """What one conversation's chat must hold, derived from what we recorded.

    Built from `state.json` and nothing else — not from the export, and not from
    the seed files, which a later run may have rewritten. The entry says how many
    parts the seed had and what the source was called; the short id and the
    acknowledgement lines follow from the uuid the way `04` built them.
    """

    conversation_uuid: str
    conversation_id: str
    parts: int
    title: str
    """The title the chat should end up with, already capped and squashed, or
    `""` when no rename was asked for."""

    @property
    def short_id(self) -> str:
        return render.short_id(self.conversation_uuid)

    @property
    def source_line(self) -> str:
        return render.source_id_line(self.conversation_uuid)

    @property
    def acks(self) -> tuple[str, ...]:
        return tuple(
            render.ack_line(self.short_id, part, self.parts)
            for part in range(1, self.parts + 1)
        )

    @property
    def expect(self) -> tuple[str, ...]:
        """Every string the page is asked about, in one list.

        One `--expect` list for the whole probe, because the page answers it per
        message: which turn carried which string is what the checks below read.
        """
        return (self.source_line, *self.acks)

    @property
    def url(self) -> str:
        return chat_url(self.conversation_id)


def chat_url(conversation_id: str) -> str:
    """Where a destination chat lives. One spelling, because two places build it:
    this module navigates to it and `20`'s probe sends an agent to it."""
    return f"https://{probing.CLAUDE_HOST}/chat/{conversation_id}"


def capped_title(title: str, limit: int) -> str:
    """A source title as it will be typed, and therefore as it is compared.

    Squashed first (`probe.normalise_title`), because that is how the page will
    spell it back, and truncated with an ellipsis rather than cut, so that a chat
    whose name is 200 characters of a longer one looks deliberate in the sidebar.
    """
    squashed = probing.normalise_title(title)
    if len(squashed) <= limit:
        return squashed
    return squashed[: limit - 1].rstrip() + ELLIPSIS


def intended_title(settings: Settings, title: str) -> str:
    """What this conversation's chat should be called, or `""` for "leave it".

    The one function that decides, so the title `11` tells Hermes to type and the
    title this module compares the page against cannot be two different strings.
    """
    if not settings.fidelity.rename_title:
        return ""
    return capped_title(title, settings.fidelity.title_max_chars)


def expected_for(
    settings: Settings, uuid: str, entry: ConversationState
) -> Expected | None:
    """What to check for this entry, or `None` when there is nothing to check.

    `None` for an entry with no destination chat — nothing landed, so there is no
    page to read — and for one the run never split into parts, which is an entry
    no attempt has got as far as writing a seed for.
    """
    conversation_id = entry.destination.conversation_id
    if conversation_id is None or entry.chunks_total < 1:
        return None
    return Expected(
        conversation_uuid=uuid,
        conversation_id=conversation_id,
        parts=entry.chunks_total,
        title=intended_title(settings, entry.title),
    )


def verifiable(
    settings: Settings, migration: state.MigrationState
) -> Iterator[tuple[str, Expected]]:
    """Every entry `verify` re-reads: `completed` or `partial`, with an id.

    In `state.json`'s own order, which is the export's, so two runs of `verify`
    print the same lines in the same order.
    """
    for uuid, entry in migration.items():
        if entry.status not in (Status.COMPLETED, Status.PARTIAL):
            continue
        expected = expected_for(settings, uuid, entry)
        if expected is not None:
            yield uuid, expected


# --------------------------------------------------------------------------- #
# What one verification found
# --------------------------------------------------------------------------- #


class Verification(BaseModel):
    """One conversation, read back off the page.

    Not a state entry and not written as one: `record` is what turns this into
    the two or three fields §7 keeps. Kept apart because `verify` prints these
    without writing anything if the workspace is busy, and because `19` reports
    the check by name.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_uuid: str
    conversation_id: str
    failed: str | None = None
    """The first check that did not pass, in the words above, or `None`."""
    limitations: tuple[str, ...] = ()
    """§15's, for this conversation: what the destination cannot hold."""
    title_set: bool = False
    """Whether the chat carries the source title. `False` whenever
    `title_not_set` is among the limitations, and the same fact said the other
    way round — `19` counts renamed chats and would otherwise count a slug."""

    @property
    def ok(self) -> bool:
        return self.failed is None

    @property
    def short_id(self) -> str:
        return render.short_id(self.conversation_uuid)

    def line(self) -> str:
        """One conversation's line of `verify` output.

        Two spaces between columns, like `seeds` and `18`'s progress lines: the
        output is read by a person and grepped by one, and no conversation
        identifier or check name contains a double space.
        """
        if self.ok:
            return f"{self.short_id}  verified"
        return f"{self.short_id}  FAILED  {self.failed}"


def checks(report: probing.PageReport, expected: Expected) -> Verification:
    """The four checks, against one look at one page. No browser in sight.

    Pure on purpose: what a page has to show for a conversation to count as
    migrated is the whole of `17`, and it is testable against a `PageReport`
    built by hand — no Chrome, no fixtures, no timing.
    """
    page = report.state
    found = (
        page.kind is probing.PageKind.CHAT
        and page.conversation_id == expected.conversation_id
    )
    # Title first in the reading, identity first in the logic: what a page that
    # is not this chat says it is called is not evidence about this chat. A
    # redirect to a chat somebody renamed the same way would otherwise be
    # recorded as a correctly titled conversation, which is the one thing a
    # limitation must never say wrongly — and `_unreadable` already answers the
    # same question the same way for a page that could not be read at all.
    limitations = [TIMESTAMPS_NOT_PRESERVED]
    title_set = found and expected.title != "" and report.title.matches is True
    if not title_set:
        limitations.append(TITLE_NOT_SET)

    def outcome(failed: str | None) -> Verification:
        return Verification(
            conversation_uuid=expected.conversation_uuid,
            conversation_id=expected.conversation_id,
            failed=failed,
            limitations=tuple(limitations),
            title_set=title_set,
        )

    if not found:
        return outcome(CHAT_MISSING)

    human = report.with_role("human")
    if len(human) < expected.parts:
        return outcome(HISTORY_MISSING)
    if expected.source_line not in human[0].contains:
        return outcome(SOURCE_ID_MISSING)

    assistant = report.with_role("assistant")
    for part, ack in enumerate(expected.acks, start=1):
        if not any(ack in message.contains for message in assistant):
            return outcome(ACK_MISSING.format(part=part, total=expected.parts))
    return outcome(None)


# --------------------------------------------------------------------------- #
# Reading the page it checks
# --------------------------------------------------------------------------- #


class Verifier:
    """Navigates to a chat and reads it back. One per run, or per `verify`.

    Holds no state of its own beyond the client and the settings: a verification
    is a question about a page, and asking it twice must give the same answer for
    the same page.
    """

    def __init__(
        self,
        settings: Settings,
        client: CdpClient,
        *,
        surface: browser_helpers.Surface = browser_helpers.CLAUDE,
        poll_s: float = POLL_S,
    ) -> None:
        self.settings = settings
        self.client = client
        self.surface = surface
        self.poll_s = poll_s

    def verify(self, expected: Expected) -> Verification:
        """Reload the chat and check it. Never raises for anything about a page.

        A browser that has gone away, a tab outside the migration surface and a
        target that no longer exists all come back as `chat unreadable` rather
        than as an exception, because the caller is either a loop migrating the
        next conversation or a command printing a line per chat — and neither of
        them is improved by a traceback about the third one.
        """
        try:
            report = self._read(expected)
        except MigrationError as exc:
            _logger.warning(
                "verification could not read the page",
                extra={
                    "conversation_id": expected.short_id,
                    "category": str(exc.category),
                },
            )
            return self._unreadable(expected)
        found = checks(report, expected)
        _logger.info(
            "verified" if found.ok else "verification failed",
            extra={
                "conversation_id": expected.short_id,
                "check": found.failed or "",
                "messages": len(report.messages),
                "title_chars": report.title.chars,
            },
        )
        return found

    def _unreadable(self, expected: Expected) -> Verification:
        return Verification(
            conversation_uuid=expected.conversation_uuid,
            conversation_id=expected.conversation_id,
            failed=CHAT_UNREADABLE,
            limitations=(TIMESTAMPS_NOT_PRESERVED, TITLE_NOT_SET),
        )

    def _read(self, expected: Expected) -> probing.PageReport:
        """Navigate, then poll until the chat has rendered or the time is up.

        The safety gate is applied to the URL before it is navigated to, not only
        by the helper that drives the tab: this is the one place in the tool that
        chooses a URL rather than reading one, and the id it builds it from comes
        out of `state.json`.
        """
        browser_helpers.guard(expected.url, self.surface)
        tab = browser_helpers.chosen_tab(self.client, surface=self.surface)
        if isinstance(tab, browser_helpers.Failure):
            raise BrowserError(detail=str(tab.error))
        deadline = time.monotonic() + self.settings.timeouts.verify_s
        with browser_helpers.driving(self.client, tab, self.surface) as page:
            page.navigate(expected.url)
            while True:
                report = probing.page_report(
                    page,
                    expect=expected.expect,
                    expect_title=expected.title or None,
                )
                # Re-checked every poll, as `08`'s `await-response` re-checks it:
                # a session that expires mid-verification redirects the tab to a
                # page no helper may read, and the wall is what stops us reading
                # it rather than waiting the deadline out on it.
                browser_helpers.guard(report.state.url, self.surface)
                if self._settled(report, expected) or time.monotonic() >= deadline:
                    return report
                time.sleep(self.poll_s)

    @staticmethod
    def _settled(report: probing.PageReport, expected: Expected) -> bool:
        """Whether the page has stopped being on its way somewhere.

        Three cases, because `Page.navigate` returns before the page it asked
        for is the page the tab shows:

        - **This chat.** Wait for a turn to render. A chat that is still drawing
          is at the right URL with an empty transcript, and reading that moment
          would report `history missing` — the failure of a migration rather
          than of a page load.
        - **Another chat.** Settled, and settled somewhere wrong. Nothing about
          it will change by waiting, so the wait ends here and `checks` reports
          `chat missing` in a second rather than in thirty. (Raised by Copilot
          in review on #26, which also caught this test the wrong way round: as
          first written it ended the wait on every page that was *not* a chat,
          so a navigation still in flight was reported as a missing chat and a
          tab in the wrong chat was waited out. Both halves are inverted here.)
        - **Not a chat at all.** `/new`, which is both what the tab shows while
          the navigation is in flight and where a chat that no longer exists
          redirects to. The two are indistinguishable from here, so this is the
          one case that is waited out — erring towards giving a slow page time
          rather than towards calling a conversation missing.
        """
        if report.state.conversation_id == expected.conversation_id:
            return bool(report.messages)
        return report.state.kind is probing.PageKind.CHAT


# --------------------------------------------------------------------------- #
# Writing it down
# --------------------------------------------------------------------------- #


def error_for(found: Verification) -> ErrorRecord:
    """A failed verification as §7's error record.

    `retry_recommended` is always `True` and is written here rather than read off
    the category, which is the third place in this tool where the two disagree
    (`12`'s `_record_failure` and `_attachment_failure` are the others).
    `verification` is one of `01`'s three per-instance categories — "it depends" —
    and for *these* instances it does not: every check that can fail is something
    a resumed attempt knows how to put right, by pasting the part that is missing
    or by reading a page that answered this time. `13` spends the conversation's
    budget on it, and `_exhausted` writes `false` when that budget is gone.
    """
    return ErrorRecord(
        category=Category.VERIFICATION,
        detail=found.failed or "",
        retry_recommended=True,
    )


def applied(
    found: Verification, status: Status, error: ErrorRecord | None
) -> tuple[Status, ErrorRecord | None]:
    """What a verification makes of the status and error a run reached.

    Two rules, and the second is the one worth writing down:

    - A failed check is `partial`, never `failed` and never `completed`. A chat
      exists — the checks that run at all ran against a page — so there is
      something for an operator to look at and for the next attempt to continue.
    - **A verification never overwrites a reason.** It replaces the error only
      when there is none to replace, which is exactly the case it exists for: a
      run that reported `completed` and was wrong. A run that already said why it
      stopped — a file that would not upload, a page outside the migration
      surface, a generation that never arrived — keeps that reason, because
      "ack 2/2 missing" is the *consequence* an operator already knows about and
      not the cause. It also keeps that reason's `retry_recommended`, which is
      what stops a verification from recommending another go at something `01`
      classified as not worth retrying.
    """
    if found.ok:
        return status, error
    return Status.PARTIAL, error if error is not None else error_for(found)


def merged_limitations(entry: ConversationState, found: Sequence[str]) -> list[str]:
    """`04`'s rendering limitations, then `17`'s, each one once.

    The rendering slugs (`thinking_omitted:3`) describe what the seed could not
    carry and are written when the seed is generated; these describe what the
    destination cannot hold. Both belong to the conversation, in that order,
    because the first group is about the export and the second about the account.
    """
    merged = list(entry.limitations)
    for slug in found:
        if slug not in merged:
            merged.append(slug)
    return merged


def fields(
    entry: ConversationState, found: Verification, *, at: datetime | None = None
) -> dict[str, object]:
    """What a verification writes about itself, and nothing else.

    The status and the error are `applied`'s, because they belong to the run as
    much as to the check; these two fields belong to the check alone. `12` folds
    them into the update that records the attempt and `verify` writes them on
    their own, which is why this is a dict and not a write.

    `last_step` is not among them either way: `17` checks what a run produced and
    never restates where that run got to.
    """
    return {
        "limitations": merged_limitations(entry, found.limitations),
        # Stamped only by a check that passed, and cleared by one that did not:
        # the field says "this chat was read back and held everything", which is
        # a statement a failed check withdraws rather than qualifies.
        "verified_at": (at if at is not None else state.now()) if found.ok else None,
    }


def record(
    store: state.StateStore, uuid: str, found: Verification
) -> ConversationState:
    """Apply one verification to `state.json`. The whole of what `verify` writes.

    Never repairs anything: a failed check changes a status, an error and a
    timestamp, and nothing about the account. Re-migrating what it found is
    `import --retry-partial`, which is a separate decision and a separate run.
    """
    entry = store.load()[uuid]
    status, error = applied(found, entry.status, entry.error)
    return store.update(uuid, **fields(entry, found), status=status, error=error)


# --------------------------------------------------------------------------- #
# The `verify` command (`23`)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class VerifyOutcome:
    """Every chat re-read, with what was found; exit `1` if any check failed and
    `4` if there was nothing to check."""

    found: tuple[tuple[str, Verification], ...]
    exit_code: ExitCode


def verify_all(
    settings: Settings, *, only: Sequence[str] = (), sink: Sink = DISCARD
) -> VerifyOutcome:
    """Check that migrated conversations exist in the destination account (`17`).

    Nothing migrated, or nothing selected, is exit `4` rather than the `0` that
    "everything verified" would give it, for `06`'s reason: an empty selection is
    not a success. Under the lock: this writes `state.json`, and a `verify` racing
    an `import` would overwrite the status of a conversation being migrated as it
    reads it.
    """
    from dataporter import signin
    from dataporter.browser import launcher

    if settings.non_interactive:
        signin.require_credentials(settings)
    log.enable_run_log(settings.workspace)
    store = state.StateStore(settings.workspace)
    # Read before anything is printed, like `status`: a workspace written by a
    # build with a different state schema stops the command here.
    store.run()
    wanted = list(verifiable(settings, store.load()))
    if only:
        chosen = set(state.resolve_only([uuid for uuid, _ in wanted], only))
        wanted = [item for item in wanted if item[0] in chosen]
    if not wanted:
        return VerifyOutcome(found=(), exit_code=ExitCode.NOTHING_TO_DO)

    lock = state.WorkspaceLock(settings.workspace)
    lock.acquire()
    found: list[tuple[str, Verification]] = []
    try:
        # The browser is opened here and not by an `Importer`: `verify` runs
        # without Hermes at all — no profile, no subprocess, no model — because
        # the whole point of it is to check the account rather than to ask the
        # thing that wrote to the account what it did. `launch` adopts the
        # browser already on the port when it is ours, so a `verify` run beside
        # a window the operator left open reuses it.
        browser = launcher.launch(settings, probing.NEW_CHAT_URL)
        try:
            # Exit `3` when signed out — after `24`'s one unattended sign-in,
            # in that mode: a signed-out session makes every chat unreadable,
            # and reporting a hundred failed verifications would bury the one
            # fact that matters.
            signin.ensure_signed_in(settings, browser)
            verifier = Verifier(settings, browser.client)
            for uuid, expected in wanted:
                result = verifier.verify(expected)
                record(store, uuid, result)
                found.append((uuid, result))
                # Printed even under `--quiet`, for the reason `status`'s block
                # is: `-q` suppresses progress, and these lines are the result.
                sink.line(result.line())
        finally:
            # A browser this command started is one it closes; one that was
            # already running belongs to whoever started it (`12`, `07`).
            if not browser.adopted:
                browser.close()
    finally:
        lock.release()
    failures = sum(0 if result.ok else 1 for _, result in found)
    return VerifyOutcome(
        found=tuple(found),
        exit_code=ExitCode.FAILED if failures else ExitCode.OK,
    )
