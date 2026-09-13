"""The §16 block, the per-failure records under it, and `report.json`.

What a migration amounted to, in three parts and one model:

- the nine numbers §16 prints, plus `Pending` when a run left anything behind;
- one line per conversation that did not complete — source id, status, last
  successful step, error, retry recommendation, which is §16's per-failure
  record exactly;
- what the destination could not hold, by name and by conversation.

Two properties are the whole module. The first is that everything here is a
pure function of four files: `state.json`, `run.json`, `plan.json` and
`logs/actions.jsonl`. `report` opens no browser and runs no Hermes, so the
account is not touched by the command that reports on it and a workspace
carried off a machine still reports the same numbers. The second is that the
text is derived from `Report` and never assembled from the files twice:
`report --json` prints the model, `render` prints the model, and a round trip
through JSON gives the same bytes back — which is what makes the report
something an operator can keep.

The alignment is `06`'s, deliberately: `summary` owns the rule that puts a
right-aligned value against a label, and this block is that rule with a wider
floor. Nothing here re-implements it, so §9's block, §10's counters and §16's
report cannot drift apart.

§10's rule holds here as it does everywhere else: no title and no message
reaches the text or the JSON. What a failure line carries is a short id, a
status, a step name, a category and `ErrorRecord.detail` — which is `13`'s own
operator-facing words, and never content.
"""

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from dataporter import state, summary
from dataporter.browser import helpers as browser_helpers
from dataporter.config import Settings
from dataporter.console import DISCARD, Sink
from dataporter.errors import Category
from dataporter.exit_codes import ExitCode
from dataporter.plan import PLAN_FILENAME, SKIPPED_BY_FLAG, MigrationPlan
from dataporter.render import short_id
from dataporter.state import (
    ConversationState,
    Instant,
    MigrationState,
    RunFile,
    RunRecord,
    Status,
)
from dataporter.steps import Step

REPORT_FILENAME = "report.json"

TITLE = "Claude migration complete"
"""§16's first line, and the only sentence the block spends on itself."""

MIN_WIDTH = 32
"""Narrowest the §16 block ever gets.

The brief's example is hand-aligned — see the spec's design notes — and 32 is
the smallest width that fits every line of it. The floor aside, the rule is
`summary`'s: `max(MIN_WIDTH, longest label + 1 + longest value)`, so a bigger
export widens every line of the block rather than losing a separator.
"""

SOURCE_LABEL = "Source conversations:"
STATUS_LABELS: tuple[tuple[str, str], ...] = (
    ("Created:", "created"),
    ("Partial:", "partial"),
    ("Failed:", "failed"),
)
PENDING_LABEL = "Pending:"
AUTO_SIGNINS_LABEL = "Automatic sign-ins:"
"""`24`'s line, after `Human interventions:` and only when there were any — the
other thing about the block that changes shape, for `Pending`'s reason."""
"""Written after `Failed:` and only when it is not zero.

A finished migration that printed `Pending: 0` would invite the question the
line exists to answer; a run that stopped early has to say how much it left.
"""

FAILURES_HEADER = "Failures and partial migrations:"
LIMITATIONS_HEADER = "Limitations:"

STATUS_WIDTH = 9
"""What the status column of a failure line is padded to, plus one space.

Nine because `completed` is the longest of §7's five statuses, even though a
failure line never carries that one: the column is the same width in every
report, so two of them can be read side by side.
"""

STEP_WIDTH = 10
"""What follows `step=`, padded. `new_chat` is the longest step name."""

DETAIL_GUTTER = 4
"""Between the longest `category: detail` in the list and the `retry=` column."""

NONE_RECORDED = "-"
"""Stands in for a step no entry reached, and for a `partial` with no error of
its own — the one crash recovery leaves behind. A dash says the file holds
nothing here; anything else would be this module inventing a reason.
"""

RETRY = {True: "yes", False: "no", None: "unknown"}
"""`retry=` from `ErrorRecord.retry_recommended`. `None` is `01`'s "per
instance, and nobody decided" — reported as unknown rather than as no."""

GUTTER = "  "
"""Between the short id and the status, as `18`'s event lines space them."""


# --------------------------------------------------------------------------- #
# The model
# --------------------------------------------------------------------------- #


class ReportModel(BaseModel):
    """Base for everything in `report.json`: immutable, and closed.

    `extra="forbid"` for `plan.json`'s reason: the shape is ours, a report is
    read back by `20` and by `21`, and an unexpected key is a bug in us.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class ReportTotals(ReportModel):
    """The nine numbers §16 prints, and the tenth a run that stopped needs."""

    source_conversations: int
    created: int
    partial: int
    failed: int
    pending: int
    messages_represented: int
    attachments_migrated: int
    browser_actions: int
    retries: int
    human_interventions: int
    auto_signins: int = 0
    """`24`'s counter. Rendered only when non-zero: §16's block is a golden
    string, and a run nobody signed in for prints it unchanged."""


class FailureRecord(ReportModel):
    """§16's per-failure record: one conversation that did not complete."""

    uuid: str
    short_id: str
    status: Status
    last_step: Step | None = None
    category: Category | None = None
    """`None` for an entry with no error record — see `NONE_RECORDED`."""
    detail: str = ""
    retry_recommended: bool | None = None
    destination_conversation_id: str | None = None
    """The chat to go and look at, where one was created. Not a title: §10 keeps
    those off an operator's terminal, and the id is what `state.json` already
    holds."""

    def describe(self) -> str:
        """Return `generation: response never completed`, uncut.

        `18`'s progress line shows at most 60 characters of the same string
        because a terminal redraw depends on a line's height; a report has no
        such constraint and §16 asks for the error, so this is the whole of it.
        """
        if self.category is None:
            return NONE_RECORDED
        detail = " ".join(self.detail.split())
        return f"{self.category}: {detail}" if detail else str(self.category)


class AttachmentTotals(ReportModel):
    """What became of the export's files (`16`).

    `found` is what `plan.json` counted; the four outcomes beside it sum to it
    once every planned conversation has been attempted, which is `16`'s
    reconciliation — until then the difference is the files of the conversations
    the `Pending:` line counts. `skipped` is not a fifth outcome but a reading of
    one: the `unsupported` files an operator's `--skip-attachments` refused, as
    opposed to the ones whose bytes were never there.
    """

    found: int
    inline: int
    uploaded: int
    unsupported: int
    failed: int
    skipped: int


class Report(ReportModel):
    """`<workspace>/report.json`, and everything the text block renders from."""

    generated_at: Instant
    export_fingerprint: str
    totals: ReportTotals
    failures: list[FailureRecord] = []
    limitations: dict[str, int] = {}
    attachments: AttachmentTotals
    verification: dict[str, int] = {}
    runs: list[RunRecord] = []


# --------------------------------------------------------------------------- #
# Reading the workspace
# --------------------------------------------------------------------------- #


def _describe(exc: ValidationError) -> str:
    """Return a pydantic error as `loc: msg`, with the offending value left out.

    Same shape as `config._describe` and `state._describe`, deliberately
    re-written rather than imported for the reason `02` gives: a private name is
    not a cross-module contract.
    """
    parts = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"]) or "(root)"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)


def read_plan(workspace: Path) -> MigrationPlan:
    """`plan.json`, which is where "source conversations" comes from.

    A workspace without one has never had a run in it, and a report is about a
    run: exit `2` and the command that makes one, rather than a block of zeros
    that reads like a migration of nothing.

    That is `FileNotFoundError` and nothing else. Any other `OSError` — a
    permission, a directory where the file should be — is a filesystem problem
    an operator can see and fix, and "no plan.json" would send them to `import`,
    which would fail on the same file for the same reason. Reported the way
    `state` reports an unreadable `state.json`, because it is the same sentence.
    """
    path = workspace / PLAN_FILENAME
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise state.StateError(f"no {PLAN_FILENAME} in {workspace} — run `import` first") from None
    except OSError as exc:
        raise state.StateError(f"cannot read {path}: {exc.strerror or exc}") from exc
    try:
        return MigrationPlan.model_validate_json(raw)
    except ValidationError as exc:
        raise state.StateError(f"invalid {PLAN_FILENAME}: {path}: {_describe(exc)}") from exc


def browser_actions(workspace: Path, run: RunFile) -> int:
    """`logs/actions.jsonl`'s records, with `run.json`'s tally as a floor.

    The file is the record — our helpers write one line each, and `12` decided
    against `HermesResult.actions`, which is what the agent believes it did —
    but a log that was rotated or truncated must not make a run look idler than
    it was, and `run.json` counted the same lines as they were written.
    """
    return max(browser_helpers.count_actions(workspace), run.browser_actions)


# --------------------------------------------------------------------------- #
# Counting
# --------------------------------------------------------------------------- #


def totals_of(plan: MigrationPlan, migration: MigrationState, run: RunFile, actions: int) -> ReportTotals:
    """§16's numbers.

    `Pending` is the remainder rather than a tally, for `18`'s reason and one of
    its own: `Created + Partial + Failed + Pending == Source conversations` is a
    criterion of this slice, and a subtraction cannot break it — a `running`
    entry a crash left behind, or a conversation `--limit` never reached, is
    pending whether or not `state.json` has an entry saying so.
    """
    counts = state.status_counts(migration)
    source = plan.totals.conversations
    return ReportTotals(
        source_conversations=source,
        created=counts["completed"],
        partial=counts["partial"],
        failed=counts["failed"],
        pending=source - counts["completed"] - counts["partial"] - counts["failed"],
        messages_represented=sum(
            entry.messages_represented
            for entry in migration.values()
            if entry.status in {Status.COMPLETED, Status.PARTIAL}
        ),
        attachments_migrated=sum(entry.attachments.uploaded + entry.attachments.inline for entry in migration.values()),
        browser_actions=actions,
        retries=run.retries,
        human_interventions=run.human_interventions,
        auto_signins=run.auto_signins,
    )


def failures_of(migration: MigrationState) -> list[FailureRecord]:
    """Every conversation that did not complete, in `state.json`'s order.

    Which is the export's, so two reports of one workspace list them the same
    way round. `partial` is in the list as well as `failed`: §16 asks for the
    partial migrations by name, and the operator's next command is the same one
    either way.
    """
    return [
        FailureRecord(
            uuid=uuid,
            short_id=short_id(uuid),
            status=entry.status,
            last_step=entry.last_step,
            category=entry.error.category if entry.error else None,
            detail=entry.error.detail if entry.error else "",
            retry_recommended=entry.error.retry_recommended if entry.error else None,
            destination_conversation_id=entry.destination.conversation_id,
        )
        for uuid, entry in migration.items()
        if entry.status in {Status.PARTIAL, Status.FAILED}
    ]


def limitation_name(slug: str) -> str:
    """`thinking_omitted:3` is the limitation `thinking_omitted`.

    `04` records how many blocks it dropped from one conversation and `17`
    records a bare name; the report's column counts conversations either way, so
    the two spellings are folded here. The per-conversation number is still in
    `state.json`, where the conversation it belongs to is.
    """
    return slug.split(":", 1)[0]


def limitations_of(migration: MigrationState) -> dict[str, int]:
    """How many conversations carry each limitation, most common first.

    Conversations and not occurrences: a column that meant "blocks" for one name
    and "chats" for the next would be two columns printed as one. Ties break on
    the name, so the block is stable across runs.
    """
    counts = Counter(
        # By name and not by slug: one conversation with `thinking_omitted:3`
        # and `thinking_omitted:1` against it is one conversation.
        name
        for entry in migration.values()
        for name in dict.fromkeys(limitation_name(slug) for slug in entry.limitations)
    )
    return dict(sorted(counts.items(), key=lambda row: (-row[1], row[0])))


def attachments_of(plan: MigrationPlan, migration: MigrationState) -> AttachmentTotals:
    """`16`'s four outcomes against the number `plan.json` planned.

    `skipped` reads the detail rather than `run.json`'s flag: the flag says an
    operator asked for it on *some* run, and the detail entry says this file was
    refused for that reason rather than for want of bytes.
    """
    entries = list(migration.values())
    return AttachmentTotals(
        found=plan.totals.attachments,
        inline=sum(entry.attachments.inline for entry in entries),
        uploaded=sum(entry.attachments.uploaded for entry in entries),
        unsupported=sum(entry.attachments.unsupported for entry in entries),
        failed=sum(entry.attachments.failed for entry in entries),
        skipped=sum(
            1
            for entry in entries
            for item in entry.attachments.detail
            if item.klass == "unsupported" and item.reason == SKIPPED_BY_FLAG
        ),
    )


def verified(entry: ConversationState) -> bool:
    return entry.verified_at is not None


def verification_failed(entry: ConversationState) -> bool:
    """Whether the workspace records a failed check against this conversation.

    `17` writes a `verification` error only where the run left no reason of its
    own — a chat that failed a step *and* its check keeps the step's reason, and
    is reported under that category in the failures list. So this counts the
    conversations whose recorded reason is the check, which is what "verified,
    failed, not run" can honestly say from the file.
    """
    return not verified(entry) and entry.error is not None and entry.error.category is Category.VERIFICATION


def verification_of(migration: MigrationState) -> dict[str, int]:
    """`17`'s second opinion, over every chat there is one of.

    The population is the conversations with a destination id: a chat that
    exists is a chat that can be read back, and one that never landed has
    nothing to verify rather than a verification that has not happened. The
    three numbers sum to it, so `not_run` is the remainder.
    """
    landed = [entry for entry in migration.values() if entry.destination.conversation_id is not None]
    passed = sum(1 for entry in landed if verified(entry))
    failed = sum(1 for entry in landed if verification_failed(entry))
    return {
        "verified": passed,
        "failed": failed,
        "not_run": len(landed) - passed - failed,
    }


# --------------------------------------------------------------------------- #
# Building it
# --------------------------------------------------------------------------- #


def build(workspace: Path) -> Report:
    """Return the whole report, from the four files and nothing else.

    `generated_at` is the one thing in it that is not read off the workspace,
    and it is deliberately not rendered into the text: that is what lets two
    invocations print identical bytes, and a report kept beside a workspace
    still has to say when it was taken.
    """
    store = state.StateStore(workspace)
    # `run.json` first, like `status`: a workspace written by a build with a
    # different state schema stops the command here rather than being reported
    # with half its numbers missing.
    run = store.run()
    migration = store.load()
    plan = read_plan(workspace)
    return Report(
        generated_at=state.now(),
        export_fingerprint=run.export_fingerprint or plan.export_fingerprint,
        totals=totals_of(plan, migration, run, browser_actions(workspace, run)),
        failures=failures_of(migration),
        limitations=limitations_of(migration),
        attachments=attachments_of(plan, migration),
        verification=verification_of(migration),
        runs=list(run.runs),
    )


def write(workspace: Path, report: Report) -> Path:
    """Write `report.json`, atomically, like every other workspace file.

    `import` is what calls this, at the end of a run and under the lock. The
    `report` command does not: it answers a question about a workspace, and a
    command that rewrites what it was asked to read cannot be run beside a
    migration that is still going.
    """
    path = workspace / REPORT_FILENAME
    state.write_atomically(path, report.model_dump_json(indent=2) + "\n")
    return path


# --------------------------------------------------------------------------- #
# Rendering it
# --------------------------------------------------------------------------- #


def totals_groups(totals: ReportTotals) -> list[list[tuple[str, str]]]:
    """§16's three groups, as label and rendered value.

    `Pending` joins the first group only when there is any, which is the one
    thing about the block that changes shape.
    """
    statuses = [(label, summary.number(getattr(totals, key))) for label, key in STATUS_LABELS]
    if totals.pending:
        statuses.append((PENDING_LABEL, summary.number(totals.pending)))
    activity = [
        ("Browser actions:", summary.number(totals.browser_actions)),
        ("Retries:", summary.number(totals.retries)),
        ("Human interventions:", summary.number(totals.human_interventions)),
    ]
    if totals.auto_signins:
        activity.append((AUTO_SIGNINS_LABEL, summary.number(totals.auto_signins)))
    return [
        [(SOURCE_LABEL, summary.number(totals.source_conversations)), *statuses],
        [
            ("Messages represented:", summary.number(totals.messages_represented)),
            ("Attachments migrated:", summary.number(totals.attachments_migrated)),
        ],
        activity,
    ]


def totals_lines(totals: ReportTotals) -> list[str]:
    """Return the title, a blank, and §16's three groups under `06`'s alignment rule."""
    return [
        TITLE,
        "",
        *summary.aligned_groups(totals_groups(totals), MIN_WIDTH),
    ]


def block(totals: ReportTotals) -> str:
    """Return the §16 block on its own, newline-terminated.

    What a golden test compares against the brief, and the first lines of every
    report. `render` is the whole of one; this is the part §16 fixes.
    """
    return "".join(f"{line}\n" for line in totals_lines(totals))


def failure_lines(failures: Sequence[FailureRecord]) -> list[str]:
    """§16's per-failure records, one line each, under their own header.

    The error column is as wide as the widest in *this* list, so the `retry=`
    column lines up down the block and a report of one failure does not carry
    the padding of a report of a hundred.

    Nothing at all for an empty list, header included: `05`'s rule for
    `inspect`'s reasons, which is that an empty section is a question an
    operator has to answer ("did it not count, or is it none?") where no section
    is an answer. It is also what makes this safe to call on any report.
    """
    if not failures:
        return []
    width = max(len(record.describe()) for record in failures) + DETAIL_GUTTER
    return [
        FAILURES_HEADER,
        *(
            f"{summary.INDENT}{record.short_id}{GUTTER}"
            f"{record.status:<{STATUS_WIDTH}} "
            f"step={record.last_step or NONE_RECORDED:<{STEP_WIDTH}}"
            f"{record.describe():<{width}}"
            f"retry={RETRY[record.retry_recommended]}"
            for record in failures
        ),
    ]


def limitation_lines(limitations: Mapping[str, int]) -> list[str]:
    """Return what the destination could not hold, by name and by conversation.

    `06`'s breakdown rule, the same one `inspect` prints its reasons with: the
    name column is the longest name plus a gutter and the count is right-aligned
    beside it. Nothing at all when nothing was recorded, for the reason
    `failure_lines` gives.
    """
    if not limitations:
        return []
    return summary.breakdown_lines(LIMITATIONS_HEADER, list(limitations.items()))


def lines(report: Report) -> list[str]:
    """Every line of the report, the blank lines between its blocks included.

    A section that rendered nothing takes its blank line with it, which is the
    whole of what a report with no failures and no limitations looks like: §16's
    block, and an end.
    """
    rendered = totals_lines(report.totals)
    for section in (
        failure_lines(report.failures),
        limitation_lines(report.limitations),
    ):
        if section:
            rendered += ["", *section]
    return rendered


def render(report: Report) -> str:
    """Return the §16 block and what follows it, newline-terminated.

    A pure function of the model, which is the criterion: the text `import`
    prints, the text `report` prints and the text a `report.json` read back
    renders to are the same bytes by construction.
    """
    return "".join(f"{line}\n" for line in lines(report))


# --------------------------------------------------------------------------- #
# The `status` and `report` commands (`23`)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StatusOutcome:
    """`status`: the state file and the counters beside it. Always exit `0`."""

    migration: MigrationState
    counters: Mapping[str, int]
    exit_code: ExitCode = ExitCode.OK


@dataclass(frozen=True)
class ReportOutcome:
    """`report`: §16's account of the workspace. Always exit `0`."""

    report: Report
    exit_code: ExitCode = ExitCode.OK


def status(settings: Settings, *, json_output: bool = False, sink: Sink = DISCARD) -> StatusOutcome:
    """Show migration progress recorded in the workspace.

    Both files are read before anything is printed: this is where a workspace
    written by a build with a different state schema stops the command instead
    of being reported with half its numbers missing. A workspace nothing has run
    in yet is an empty object and four zeros, not an error: `status` answers a
    question, and "nothing has happened here" is an answer.

    Printed even under `--quiet`: `-q` suppresses progress, and this is the
    command's whole result. No bar: `18` draws one while a run moves, and a
    picture that is redrawn once says nothing the numbers under it do not.
    """
    store = state.StateStore(settings.workspace)
    run = store.run()
    migration = store.load()
    counters = {**state.status_counts(migration), **run.counters()}
    if json_output:
        payload = {"state": migration.model_dump(mode="json"), "counters": counters}
        sink.line(json.dumps(payload, indent=2))
    else:
        sink.block(summary.status_report(migration))
    return StatusOutcome(migration=migration, counters=counters)


def show(settings: Settings, *, json_output: bool = False, sink: Sink = DISCARD) -> ReportOutcome:
    """Print the end-of-migration report.

    Reads `state.json`, `run.json`, `plan.json` and `logs/actions.jsonl`, and
    writes nothing: no lock, no browser, no Hermes. A report is a question about
    a workspace, and one that rewrote what it was asked to read could not be run
    beside a migration that is still going — `import` is what writes
    `report.json`, at the end of a run and under the lock.
    """
    built = build(settings.workspace)
    if json_output:
        sink.line(built.model_dump_json(indent=2))
    else:
        # Printed even under `--quiet`, like `status`: `-q` suppresses progress,
        # and this block is the command's whole result.
        sink.block(render(built))
    return ReportOutcome(report=built)
