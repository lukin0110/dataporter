"""The §9 block, the §10 counters, and the reasons behind them.

`05` is the first slice whose output an operator reads as a number rather than as
a file: `import --dry-run` prints what a run *would* do, and `inspect` prints the
same block plus why the unsupported ones are unsupported. Both are pure functions
of a `MigrationPlan` — nothing here opens an export, touches a workspace or
contacts anything.

Counting from the plan rather than from the export is the point. `12` executes the
same plan and `19` reports it, so the dry run's numbers, the progress block's
numbers and the report's numbers are the same numbers by construction rather than
by three counters agreeing.

`06` adds the four counter lines `status` prints, which are the same alignment
rule with a different floor — `18` builds the progress bar and the redraw on top
of them, and this is the module that owns the rule.

The formats are golden strings; `MIN_WIDTH`, `COUNTERS_MIN_WIDTH` and
`COUNT_WIDTH` are the whole rule, and `tests/test_summary.py` compares bytes. No
title, no message and no file name appears in anything this module returns: what
it prints is labels this file owns, reason slugs and counts.
"""

from collections import Counter
from collections.abc import Mapping, Sequence

from dataporter.plan import MigrationPlan, PlanTotals
from dataporter.render import AttachmentClass
from dataporter.state import MigrationState, status_counts

MIN_WIDTH = 27
"""Narrowest the §9 block ever gets.

The brief's example is hand-aligned: `Messages:             4,821` is 27 columns
wide and nothing in the fixture's own labels and values forces that, so the floor
is part of the rule rather than a consequence of it.
"""

COUNTERS_MIN_WIDTH = 13
"""Narrowest the §10 counters block ever gets.

`18`'s rule, and self-consistent with the brief's own block: `Completed:` is the
longest label at 10 columns, which with a two-digit count is exactly 13.
"""

COUNT_WIDTH = 5
"""Width the reason and class counts are right-aligned in."""

GUTTER = 2
"""Spaces between the longest label of a breakdown and its count column."""

INDENT = "  "
"""What a breakdown line is indented by, under its own header."""

ATTACHMENT_CLASSES: tuple[AttachmentClass, ...] = ("inline", "upload", "unsupported")
"""§14's three classes, in class order, always all three.

A run with no uploads still prints `upload 0`: a missing row would read as "not
counted" where a zero reads as "none of these", and the operator is looking at
this block precisely to find out which of the three a file landed in.
"""

UNSUPPORTED_REASONS_HEADER = "Unsupported reasons:"
ATTACHMENTS_HEADER = "Attachments:"

STATUS_LABELS: tuple[tuple[str, str], ...] = (
    ("Completed:", "completed"),
    ("Partial:", "partial"),
    ("Failed:", "failed"),
    ("Pending:", "pending"),
)
"""§10's four counter lines, in the brief's order, and the `status_counts` key
each one reads."""


def number(value: int) -> str:
    """A count as the block prints it: `,` thousands separators.

    Public because `18` prints counts this module does not own — the bar's
    `done/total`, the event line's — and a second spelling of the separator rule
    is how two blocks on one screen come to disagree about 1,234.
    """
    return f"{value:,}"


def _column_width(rows: Sequence[tuple[str, str]], minimum: int) -> int:
    """`max(minimum, longest label + 1 + longest value)`.

    One rule for both blocks: §9's five lines and §10's four are aligned the same
    way and differ only in their floor.
    """
    return max(
        minimum,
        max(len(label) for label, _ in rows)
        + 1  # at least one space between the longest label and its value
        + max(len(value) for _, value in rows),
    )


def _aligned(rows: Sequence[tuple[str, str]], width: int) -> list[str]:
    """`label`, spaces, right-aligned value, every line `width` columns wide."""
    return [f"{label}{value:>{width - len(label)}}" for label, value in rows]


def _groups(totals: PlanTotals) -> list[list[tuple[str, str]]]:
    """The five §9 rows, in their two groups, as label and rendered value."""
    return [
        [
            ("Conversations found:", number(totals.conversations)),
            ("Messages:", number(totals.messages)),
            ("Attachments:", number(totals.attachments)),
        ],
        [
            ("Migratable:", number(totals.migratable)),
            ("Unsupported:", number(totals.unsupported)),
        ],
    ]


def totals_lines(totals: PlanTotals) -> list[str]:
    """The §9 block: `label`, spaces, right-aligned value; a blank line between
    the two groups.

    Every line is `max(MIN_WIDTH, longest label + 1 + longest value)` columns
    wide, computed across both groups so the two align with each other. One rule
    for all five lines, which is why three lines of the brief's example do not
    come back byte-identical — see the spec's design notes.
    """
    groups = _groups(totals)
    width = _column_width([row for group in groups for row in group], MIN_WIDTH)
    lines: list[str] = []
    for index, group in enumerate(groups):
        if index:
            lines.append("")
        lines.extend(_aligned(group, width))
    return lines


def _breakdown_lines(header: str, rows: Sequence[tuple[str, int]]) -> list[str]:
    """A header and one indented `label  count` line per row.

    The label column is the longest label plus `GUTTER`; counts are right-aligned
    in `COUNT_WIDTH`, which is a minimum rather than a field — a six-figure count
    widens its own line instead of losing its separator.
    """
    width = max(len(label) for label, _ in rows) + GUTTER
    return [
        header,
        *(
            f"{INDENT}{label:<{width}}{number(count):>{COUNT_WIDTH}}"
            for label, count in rows
        ),
    ]


def unsupported_reasons(plan: MigrationPlan) -> list[tuple[str, int]]:
    """Why each unmigratable conversation is unmigratable, most common first.

    One reason per conversation — `ConversationPlan.reasons` leads with the
    blocking one and continues with limitation slugs, which are properties of a
    conversation that *is* being migrated — so these counts sum to
    `totals.unsupported` exactly. Ties break on the name, so two runs of the same
    command print the same lines.
    """
    counts = Counter(
        item.reasons[0] if item.reasons else "unknown"
        for item in plan.conversations
        if not item.migratable
    )
    return sorted(counts.items(), key=lambda row: (-row[1], row[0]))


def attachment_classes(plan: MigrationPlan) -> list[tuple[str, int]]:
    """How many files fall in each of §14's three classes, in class order."""
    counts = Counter(
        attachment.klass
        for item in plan.conversations
        for attachment in item.attachments
    )
    return [(klass, counts.get(klass, 0)) for klass in ATTACHMENT_CLASSES]


def dry_run_report(totals: PlanTotals) -> str:
    """What `import --dry-run` prints, newline-terminated."""
    return "".join(f"{line}\n" for line in totals_lines(totals))


def inspect_report(plan: MigrationPlan) -> str:
    """What `inspect` prints: the §9 block, the reasons, the attachment classes.

    The reasons section is omitted entirely when nothing is unsupported — an empty
    list under a header would be a question the operator has to answer ("did it
    not count, or is it none?") when there is nothing to ask.
    """
    lines = totals_lines(plan.totals)
    reasons = unsupported_reasons(plan)
    if reasons:
        lines += ["", *_breakdown_lines(UNSUPPORTED_REASONS_HEADER, reasons)]
    lines += ["", *_breakdown_lines(ATTACHMENTS_HEADER, attachment_classes(plan))]
    return "".join(f"{line}\n" for line in lines)


def counters_lines(counts: Mapping[str, int]) -> list[str]:
    """§10's four counter lines, from `state.status_counts`.

    `18` prints these under a progress bar and a header; `06`'s `status` prints
    them alone, because a bar that only ever redraws once is a picture of a number
    the line beside it already gives.
    """
    rows = [(label, number(counts[key])) for label, key in STATUS_LABELS]
    return _aligned(rows, _column_width(rows, COUNTERS_MIN_WIDTH))


def status_report(state: MigrationState) -> str:
    """What `status` prints, newline-terminated.

    Titles are in `state.json` because §7 puts them there. They never reach this
    block: §10 says no conversation content during normal operation, and a title
    is content.
    """
    return "".join(f"{line}\n" for line in counters_lines(status_counts(state)))
