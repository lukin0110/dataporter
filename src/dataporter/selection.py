"""What the flags choose, and the plan that choice produces.

`23` moved this out of `cli`: three functions that turn `--only`, `--limit` and
`--all` into the record `06` selects from, and one that classifies the part of an
export a selection kept. None of them prints, and none of them knows what a flag
is called — the CLI passes values, and a Python caller passes the same values.

What is refused here is refused with `errors.UsageError`, which the CLI prints
as `error: <text>` and exits `2` for, so the words an operator reads are the
words written here.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from dataporter import state, summary
from dataporter.config import Settings, with_attachments_dir, with_skip_attachments
from dataporter.console import DISCARD, Sink
from dataporter.errors import UsageError
from dataporter.exit_codes import ExitCode
from dataporter.export import Conversation, Export, load_export
from dataporter.plan import MigrationPlan, build_plan

TOO_MANY = "use --all to migrate more than {limit} conversations in one run"
"""`15`'s usage error. The ceiling is `run.max_conversations`, and it is named in
the message because it is configurable and the operator may not know it."""

EXPORT_NOT_FOUND = "export not found: {export}"


def export_path(export: str) -> Path:
    """Check the export path exists, echoing it back exactly as the operator typed
    it — `str(Path("./nowhere"))` is `"nowhere"`, which would break the message."""
    path = Path(export)
    if not path.exists():
        raise UsageError(EXPORT_NOT_FOUND.format(export=export))
    return path


def selected_conversations(export: Export, only: Sequence[str]) -> list[Conversation]:
    """The conversations `--only` names, or all of them, in export order.

    Export order rather than the order the flags were typed: two runs of the same
    command must write the same files and print the same lines. Resolution — full
    uuid or `06`'s 8-character short id, and an unknown value as an error rather
    than as an empty selection — is `state.resolve_only`, so `seeds --only` and
    `import --only` accept exactly the same things.

    This is the selection for the commands that have no state to consult (`04`'s
    `seeds`). `import` uses `state.select`, which also reads what earlier runs
    recorded.
    """
    if not only:
        return list(export.conversations)
    wanted = set(state.resolve_only([item.uuid for item in export.conversations], only))
    return [item for item in export.conversations if item.uuid in wanted]


def selection_for(
    settings: Settings,
    *,
    only: Sequence[str],
    limit: int | None,
    all_conversations: bool = False,
    retry_failed: bool = False,
    retry_partial: bool = False,
    force: bool = False,
    skip_attachments: bool = False,
    pilot: Sequence[state.PilotChoice] = (),
) -> state.Selection:
    """The flags, as the record `06` selects from and `run.json` keeps.

    `--limit` is resolved here rather than in `state`: an unset flag means
    `run.max_conversations`, and it is the effective number — the one that shaped
    the run — that belongs in the record. The flag itself stays `None` in the
    signature so that `15` can tell an explicit `--limit 10` from a default.

    `15`'s ceiling is the point of that distinction. `run.max_conversations` is
    not only a default but a limit on what one invocation may do to an account,
    so a `--limit` above it is a usage error naming the flag that lifts it rather
    than a number quietly honoured. `--all` alone is no limit at all; `--all`
    with a `--limit` is that limit, because an operator who typed both has asked
    for a number and knows the ceiling exists.

    `pilot` is `20`'s record of *why* each conversation is in `only`, carried
    through unchanged: the selection is made before this is called, and nothing
    here re-derives it.
    """
    ceiling = settings.run.max_conversations
    if limit is None:
        effective = None if all_conversations else ceiling
    else:
        if limit > ceiling and not all_conversations:
            raise UsageError(TOO_MANY.format(limit=ceiling))
        effective = limit
    return state.Selection(
        only=list(only),
        limit=effective,
        retry_failed=retry_failed,
        retry_partial=retry_partial,
        force=force,
        skip_attachments=skip_attachments,
        pilot=list(pilot),
    )


def plan_for(
    settings: Settings,
    export: Export,
    *,
    uuids: Sequence[str] | None = None,
    attachments_dir: Path | None = None,
    skip_attachments: bool = False,
) -> MigrationPlan:
    """Classify a parsed export, or the part of it a selection kept.

    The selection is applied *before* the plan is built, so what the dry run
    counts is what this run would do rather than what the export happens to
    contain. The fingerprint stays the export's: it identifies the file, not the
    subset of it somebody asked about.
    """
    effective = with_skip_attachments(
        with_attachments_dir(settings, attachments_dir), skip_attachments
    )
    conversations = (
        list(export.conversations)
        if uuids is None
        else [item for item in export.conversations if item.uuid in set(uuids)]
    )
    return build_plan(
        export.model_copy(update={"conversations": conversations}), effective
    )


@dataclass(frozen=True)
class InspectOutcome:
    """What `inspect` amounted to: the plan, and exit `0`."""

    plan: MigrationPlan
    exit_code: ExitCode = ExitCode.OK


def inspect_export(
    settings: Settings,
    export: str,
    *,
    attachments_dir: Path | None = None,
    json_output: bool = False,
    sink: Sink = DISCARD,
) -> InspectOutcome:
    """Report what an export contains and what can be migrated (`05`).

    Reads the export and writes nothing — no run log, no workspace — for the
    reason a dry run writes nothing: this answers a question about a file.
    """
    plan = plan_for(
        settings, load_export(export_path(export)), attachments_dir=attachments_dir
    )
    if json_output:
        # The plan itself, and nothing else on stdout: this is what `12` and `19`
        # read, so a header line would be a header line in somebody's `jq`.
        sink.line(plan.model_dump_json(indent=2))
    else:
        # An empty export prints a block of zeros rather than exiting `4`:
        # `inspect` answers a question about a file, and "it contains nothing" is
        # the answer, not a refusal to run.
        sink.block(summary.inspect_report(plan))
    return InspectOutcome(plan=plan)
