"""`21`'s instruments: the gate, the metrics, the drill and the safety audit.

Not product code, for the reason nothing else in this tree is: no conversation is
migrated by any line below. What is here reads a *finished* workspace and answers
the questions `21` has to answer before and after the full run, so that
`docs/experiment-02.md` is filled in from files rather than from memory.

    uv run python spikes/sign_off.py gate    --workspace migration
    uv run python spikes/sign_off.py sample  --workspace migration
    uv run python spikes/sign_off.py metrics --workspace migration
    uv run python spikes/sign_off.py drill   --workspace migration
    uv run python spikes/sign_off.py safety  --workspace migration --export <export>

Every subcommand is read-only: it opens `plan.json`, `state.json`, `run.json`,
`logs/`, the seed files and — `safety` alone — the browser profile's `History`
database, and writes nothing anywhere. Exit `0` means the check passed, `1` that
it did not, `2` that the workspace could not be read. A number this tree prints
is a number somebody can reproduce by running it again.

Two rules it inherits from the tool it reports on:

- **§10.** No title, no message, no probe reply reaches stdout. `safety` is the
  one command that opens a file full of all three — Chrome's `History` carries a
  page title beside every URL, and a claude.ai page title is somebody's
  conversation — so it selects the `url` column alone and prints a URL without
  its query string.
- **Marks, not impressions.** Where a number cannot come out of the workspace —
  the in-run recoveries `13` leaves only in a transcript, the hand grades that
  live in the write-up — it prints `—` and says what to supply, rather than
  quietly reporting the half it has.
"""

import argparse
import hashlib
import json
import random
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dataporter import followup as following
from dataporter import log
from dataporter import report as reporting
from dataporter import seed as seeding
from dataporter import state as stating
from dataporter.exit_codes import ExitCode
from dataporter.export import CONVERSATIONS_FILE, ExportSource
from dataporter.plan import MigrationPlan
from dataporter.render import short_id
from dataporter.report import Report
from dataporter.state import MigrationState, RunFile, Status

REPO = Path(__file__).resolve().parents[1]
EXPERIMENT_01 = REPO / "docs" / "experiment-01.md"
"""Where `20`'s hand grades are. The gate reads question 3 out of the write-up
rather than out of `probes.json`, because a hand grade is what §20 asks a person
for and `judge`'s verdict is the optional second opinion beside it."""

DEFAULT_WORKSPACE = Path("migration")

GATE_CREATED = 0.90
GATE_ACKED = 0.90
"""`21`'s two thresholds, as fractions. Question 1 and question 2 of the pilot."""

BIG_PART_CHARS = 50_000
"""The size above which question 2's threshold does not apply. `21` writes it as
"parts under 50 k characters", and a part that large is `10`'s open question
rather than this gate's."""

SAMPLE_SIZE = 20
SAMPLE_SEED = 21
"""`21`'s semantic-fidelity sample: twenty completed conversations, drawn with a
seed so that two people asking "which twenty?" get the same twenty."""

INTERVENTION_EVENT = "human intervention required"
"""What `12` logs when it pauses. The run log is the only per-conversation record
of a pause: `run.json` holds the one that is open, and clears it on resume."""

NEW_CHAT_PATH = "/new"
CHAT_PREFIX = "/chat/"
CLAUDE_HOSTS = frozenset({"claude.ai", "www.claude.ai"})

GO = "go"
NO_GO = "NO-GO"
UNKNOWN = "unknown"
UNMEASURED = "—"

GRADES = ("pass", "weak", "fail")

EXPORT_CHECK = "export sha-256 unchanged"
HISTORY_CHECKS = (
    "history: migration URLs",
    "history: chats this workspace did not create",
    "history: other hosts",
    "history: other claude.ai paths",
)
SAFETY_CHECKS = (EXPORT_CHECK, *HISTORY_CHECKS)
"""`safety`'s rows, in order, as `docs/experiment-02.md` carries them. One
tuple, checked from both ends like `METRIC_NAMES`: the §17 table in the write-up
is pasted from this command, and a bucket the script reports separately must not
arrive as a row somebody has to aggregate by hand. (Raised by Copilot in review
on #30.)"""


def plural(count: int, noun: str, many: str = "") -> str:
    """`1 failure`, `2 failures`, `1 retry`, `3 retries`.

    A row that says "1 failures" reads as a bug in the row rather than as a
    number about the run, and one that says "3 retrys" reads as a worse one —
    hence `many` for the nouns an `s` does not pluralise.
    """
    return f"{count} {noun}" if count == 1 else f"{count} {many or noun + 's'}"


COMMANDS = ("gate", "metrics", "sample", "drill", "safety")
"""The subcommands, in the order the sign-off uses them. Named here so that the
runbook and `docs/experiment-02.md` can be checked against the script rather than
against somebody's memory of it."""

METRIC_NAMES = (
    "Primary: migrated without human intervention",
    "semantic fidelity",
    "migration speed",
    "browser reliability",
    "recovery rate",
    "attachment coverage",
    "manual interventions",
)
"""§19's metrics, in `21`'s order, as `metrics` labels them and as
`docs/experiment-02.md` carries them. One tuple, checked from both ends: a metric
renamed in the script and not in the write-up fails the build, and so does the
reverse."""


# --------------------------------------------------------------------------- #
# The workspace, read once
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Workspace:
    """What every subcommand needs, opened once and never written back."""

    path: Path
    plan: MigrationPlan
    migration: MigrationState
    run: RunFile
    report: Report


def open_workspace(path: Path) -> Workspace:
    """Read the four files. `report.build` is what reconciles them (`19`)."""
    store = stating.StateStore(path)
    return Workspace(
        path=path,
        plan=reporting.read_plan(path),
        migration=store.load(),
        run=store.run(),
        report=reporting.build(path),
    )


# --------------------------------------------------------------------------- #
# Numbers, and how they are printed
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Number:
    """A measurement and the two integers it came from.

    Both halves are kept because §19's primary metric has to be "stated as a
    percentage with its numerator and denominator" (`21`), and because a
    percentage over a denominator of three is a percentage nobody should quote.
    """

    numerator: int
    denominator: int
    known: bool = True
    """`False` when a term of the ratio is not in the workspace at all — the
    in-run recoveries only a transcript saw, a grade nobody has written down. It
    prints as `—` rather than as a number computed from the half that is there.
    """

    @property
    def fraction(self) -> float | None:
        if not self.known or self.denominator == 0:
            return None
        return self.numerator / self.denominator

    @property
    def percentage(self) -> str:
        fraction = self.fraction
        return UNMEASURED if fraction is None else f"{fraction * 100:.1f}%"

    @property
    def terms(self) -> str:
        if not self.known:
            return UNMEASURED
        return f"{self.numerator} ÷ {self.denominator}"

    def at_least(self, threshold: float) -> str:
        """`go`, `NO-GO` or `unknown` against one of `21`'s thresholds."""
        fraction = self.fraction
        if fraction is None:
            return UNKNOWN
        return GO if fraction >= threshold else NO_GO


def columns(rows: Sequence[Sequence[str]]) -> Iterator[str]:
    """Left-aligned columns, last one unpadded.

    `summary` owns this rule for the tool's own output and this is not the tool's
    output: a table pasted into a write-up is read in a Markdown file, not
    compared byte for byte with the brief.
    """
    if not rows:
        return
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    for row in rows:
        cells = [
            cell.ljust(widths[index]) if index < len(row) - 1 else cell
            for index, cell in enumerate(row)
        ]
        yield "  ".join(cells).rstrip()


# --------------------------------------------------------------------------- #
# What the run log remembers per conversation
# --------------------------------------------------------------------------- #


def log_records(workspace: Path) -> Iterator[dict[str, object]]:
    """Every record of every run log in the workspace, oldest file first.

    A line that is not a JSON object is skipped rather than raised on: a log
    killed mid-write — which the interruption drill guarantees — ends in half a
    record, and that is not a reason to refuse to report on the run.
    """
    directory = workspace / log.LOGS_DIRNAME
    for path in sorted(directory.glob("run-*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield record


def interventions_by_conversation(workspace: Workspace) -> dict[str, list[str]]:
    """Short id → the reason of each pause it was the subject of.

    Read out of the run log because that is where the per-conversation record
    is. `run.json`'s `paused` holds at most one — the ask nobody has cleared yet
    — and `run.json.human_interventions` is a count with no conversation on it.
    """
    found: dict[str, list[str]] = {}
    for record in log_records(workspace.path):
        if record.get("event") != INTERVENTION_EVENT:
            continue
        identifier = record.get("conversation_id")
        reason = record.get("reason")
        if isinstance(identifier, str):
            found.setdefault(identifier, []).append(
                reason if isinstance(reason, str) else UNKNOWN
            )
    paused = workspace.run.paused
    if paused is not None:
        found.setdefault(short_id(paused.conversation_uuid), []).append(paused.reason)
    return found


def intervened(
    workspace: Workspace, asks: Mapping[str, list[str]] | None = None
) -> set[str]:
    """The uuids a person was asked about, by any run in this workspace.

    `asks` is `interventions_by_conversation`'s answer where a caller already
    has it. Parsing the logs is the most expensive thing this script does — a
    days-long run leaves one file per session — and a caller that needs both the
    reasons and the uuids should read them once. (Raised by Copilot in review on
    #30, which found this called once per conversation.)
    """
    short_ids = set(interventions_by_conversation(workspace) if asks is None else asks)
    return {
        uuid for uuid, _ in workspace.migration.items() if short_id(uuid) in short_ids
    }


# --------------------------------------------------------------------------- #
# Seed part sizes — question 2's buckets
# --------------------------------------------------------------------------- #


def part_sizes(workspace: Workspace, uuid: str) -> list[int]:
    """The characters of each seed part of one conversation.

    From the files where they are, because `04` wrote them and they are what was
    pasted. `plan.json`'s `estimated_seed_chars` over `chunk_count` is the
    fallback for a workspace whose seeds were cleaned up: an average rather than
    a measurement, which only matters for a conversation sitting on the 50 k
    boundary, and a conversation there is one the write-up should name anyway.
    """
    directory = workspace.path / "seeds" / uuid
    parts = sorted(directory.glob(seeding.PART_GLOB)) if directory.is_dir() else []
    if parts:
        return [len(part.read_text(encoding="utf-8")) for part in parts]
    planned = next(
        (item for item in workspace.plan.conversations if item.uuid == uuid), None
    )
    if planned is None or planned.chunk_count <= 0:
        return []
    average = planned.estimated_seed_chars // planned.chunk_count
    return [average] * planned.chunk_count


def small_part_acks(workspace: Workspace) -> Number:
    """Parts acknowledged ÷ parts attempted, over conversations whose every part
    is under `BIG_PART_CHARS`.

    Per conversation and not per part, because `state.json` counts acks per
    conversation (`chunks_acked` against `chunks_total`) and splitting one
    conversation's acks across two buckets would be this script inventing a
    number. A conversation with a part over the ceiling is left out of both
    terms and reported apart, which is what "for parts under 50 k characters"
    asks for.
    """
    acked = attempted = 0
    for uuid, entry in workspace.migration.items():
        sizes = part_sizes(workspace, uuid)
        if not sizes or max(sizes) >= BIG_PART_CHARS:
            continue
        acked += entry.chunks_acked
        attempted += entry.chunks_total
    return Number(acked, attempted)


def big_part_conversations(workspace: Workspace) -> list[str]:
    """The short ids question 2's threshold does not cover."""
    return [
        short_id(uuid)
        for uuid, _ in workspace.migration.items()
        if (sizes := part_sizes(workspace, uuid)) and max(sizes) >= BIG_PART_CHARS
    ]


# --------------------------------------------------------------------------- #
# The gate (before the full run)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Check:
    """One row of a gate or a drill: what was measured, and the verdict."""

    name: str
    number: str
    terms: str
    verdict: str

    @property
    def blocking(self) -> bool:
        return self.verdict != GO


def table_rows(pattern: str) -> list[str]:
    """The body cells of a Markdown table row, or `[]` for anything else."""
    line = pattern.strip()
    if not line.startswith("|"):
        return []
    cells = [cell.strip() for cell in line.strip("|").split("|")]
    if all(cell and set(cell) <= {"-", ":"} for cell in cells):
        return []
    return cells


def hand_grades(path: Path | None = None) -> list[tuple[str, str]]:
    """`(conversation, grade)` for every graded row of `20`'s probe table.

    Placeholder rows — the `—` the write-up ships with — are not grades and are
    left out, which is what makes "no grades yet" different from "no failures".

    The default is resolved here rather than in the signature so that a test can
    point the gate at another document; a default argument would have bound the
    module constant once, at import.
    """
    path = EXPERIMENT_01 if path is None else path
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index("## Semantic probe grades")
    except ValueError:
        return []
    found: list[tuple[str, str]] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        cells = table_rows(line)
        if len(cells) < 2 or cells[0] in ("Conversation", UNMEASURED, "-"):
            continue
        grade = cells[1].strip("`").casefold()
        if grade in GRADES:
            found.append((cells[0].strip("`"), grade))
    return found


def gate(workspace: Workspace, *, failures_understood: bool) -> list[Check]:
    """`21`'s four gate rows, in `21`'s order."""
    attempted = [entry for _, entry in workspace.migration.items() if entry.attempts]
    created = Number(
        sum(1 for entry in attempted if entry.destination.conversation_id),
        len(attempted),
    )
    acked = small_part_acks(workspace)
    grades = hand_grades()
    failed_grades = sum(1 for _, grade in grades if grade == "fail")
    failures = workspace.report.failures
    return [
        Check(
            "question 1 — chats created",
            created.percentage,
            created.terms,
            created.at_least(GATE_CREATED),
        ),
        Check(
            f"question 2 — parts acked (< {BIG_PART_CHARS:,} chars)",
            acked.percentage,
            acked.terms,
            acked.at_least(GATE_ACKED),
        ),
        Check(
            "question 3 — no `fail` grade",
            f"{failed_grades} fail" if grades else UNMEASURED,
            f"{len(grades)} graded",
            UNKNOWN if not grades else (GO if failed_grades == 0 else NO_GO),
        ),
        Check(
            "every failure line understood",
            plural(len(failures), "failure"),
            "a reason, not a shrug",
            GO if not failures or failures_understood else UNKNOWN,
        ),
    ]


# --------------------------------------------------------------------------- #
# The metrics (after the full run)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Metric:
    """One §19 row of `docs/experiment-02.md`."""

    name: str
    number: str
    terms: str
    note: str = ""


def unattended(workspace: Workspace, paused: set[str] | None = None) -> Number:
    """§19's primary metric: migrated without a person in the loop.

    `completed`, on the first attempt, and never the subject of a pause — which
    is `21`'s definition and not a softer one. The denominator is the source
    conversations, so a conversation the run never reached counts against it:
    "how many of the export made it by itself" is the question the brief asks.

    `paused` is `intervened`'s answer where the caller already has it, for that
    function's reason.
    """
    paused = intervened(workspace) if paused is None else paused
    clean = sum(
        1
        for uuid, entry in workspace.migration.items()
        if entry.status is Status.COMPLETED
        and entry.attempts == 1
        and uuid not in paused
    )
    return Number(clean, workspace.report.totals.source_conversations)


def probe_grades(workspace: Workspace) -> Counter[str]:
    """`judge`'s verdicts from `pilot/probes.json`, by score.

    The file is read directly rather than through `followup.read`, which wants a
    `Settings`: this script is given a workspace path and nothing else, and a
    settings object assembled from the environment could point somewhere the
    operator did not type.
    """
    path = workspace.path / "pilot" / following.PROBES_FILENAME
    if not path.is_file():
        return Counter()
    file = following.ProbeFile.model_validate_json(path.read_text(encoding="utf-8"))
    return Counter(
        probe.verdict.score for probe in file.probes if probe.verdict is not None
    )


def elapsed_hours(run: RunFile) -> float:
    """Wall-clock hours the tool was running, summed over finished sessions.

    Summed per session rather than taken from the first start to the last end:
    the full run is days of sessions with the operator's sleep between them, and
    "conversations per hour" measured across a night is a number about the night.
    A session with no `ended` — the one a SIGKILL left behind — contributes
    nothing, and the drill is the reason to say so out loud.
    """
    return sum(
        (record.ended - record.started).total_seconds() / 3600
        for record in run.runs
        if record.ended is not None
    )


def metrics(workspace: Workspace, *, recoveries: int | None) -> list[Metric]:
    """The seven rows of `21`'s table, each a number and its two terms."""
    totals = workspace.report.totals
    attachments = workspace.report.attachments
    grades = probe_grades(workspace)
    hours = elapsed_hours(workspace.run)
    terminal = totals.created + totals.partial + totals.failed
    # Once, before anything below reads it: three of these rows need what the
    # run logs remember, and a workspace of a thousand conversations has one log
    # per session to parse.
    asks = interventions_by_conversation(workspace)
    paused = intervened(workspace, asks)
    needed = [
        entry
        for uuid, entry in workspace.migration.items()
        if entry.attempts > 1 or uuid in paused
    ]
    recovered = sum(1 for entry in needed if entry.status is Status.COMPLETED)
    reasons = Counter(reason for reasons_of in asks.values() for reason in reasons_of)
    primary = unattended(workspace, paused)
    fidelity = Number(grades.get("pass", 0), sum(grades.values()), known=bool(grades))
    reliability = Number(
        totals.browser_actions,
        totals.retries + (recoveries or 0),
        known=recoveries is not None,
    )
    return [
        Metric(
            "Primary: migrated without human intervention",
            primary.percentage,
            primary.terms,
            "completed, attempts == 1, in no pause record",
        ),
        Metric(
            "semantic fidelity",
            fidelity.percentage,
            fidelity.terms,
            "judge verdicts in pilot/probes.json"
            if grades
            else "no verdict recorded — grade the sample and record it here",
        ),
        Metric(
            "migration speed",
            f"{terminal / hours:.1f}/h" if hours else UNMEASURED,
            f"{terminal} ÷ {hours:.2f} h" if hours else UNMEASURED,
            f"{plural(len(workspace.run.runs), 'session')} in run.json",
        ),
        Metric(
            "browser reliability",
            f"{reliability.fraction:.1f} actions/recovery"
            if reliability.fraction is not None
            else UNMEASURED,
            reliability.terms,
            "pass --recoveries N from the transcript review"
            if recoveries is None
            else f"{plural(totals.retries, 'retry', 'retries')} + "
            f"{plural(recoveries or 0, 'recovery row')}",
        ),
        Metric(
            "recovery rate",
            Number(recovered, len(needed)).percentage,
            Number(recovered, len(needed)).terms,
            "needed one: a retry, or a pause",
        ),
        Metric(
            "attachment coverage",
            Number(totals.attachments_migrated, attachments.found).percentage,
            Number(totals.attachments_migrated, attachments.found).terms,
            f"inline {attachments.inline}, uploaded {attachments.uploaded}, "
            f"unsupported {attachments.unsupported}, failed {attachments.failed}, "
            f"skipped {attachments.skipped}",
        ),
        Metric(
            "manual interventions",
            str(totals.human_interventions),
            f"{len(reasons)} reasons",
            ", ".join(f"{name} {count}" for name, count in sorted(reasons.items()))
            or "none recorded",
        ),
    ]


# --------------------------------------------------------------------------- #
# The interruption drill
# --------------------------------------------------------------------------- #


def chat_ids(workspace: Workspace) -> list[str]:
    """Every `/chat/<uuid>` id `state.json` holds, one per entry that has one."""
    return [
        entry.destination.conversation_id
        for _, entry in workspace.migration.items()
        if entry.destination.conversation_id
    ]


def drill(workspace: Workspace) -> list[Check]:
    """`21`'s drill: no duplicate chat, no lost conversation, and evidence that
    the process really was killed."""
    ids = chat_ids(workspace)
    duplicates = [name for name, count in Counter(ids).items() if count > 1]
    totals = workspace.report.totals
    landed = totals.created + totals.partial
    reconciles = (
        totals.created + totals.partial + totals.failed + totals.pending
        == totals.source_conversations
    )
    return [
        Check(
            "chat ids are distinct",
            f"{len(set(ids))} of {len(ids)}",
            f"duplicated: {', '.join(duplicates) or 'none'}",
            GO if not duplicates else NO_GO,
        ),
        Check(
            "chat ids == Created + Partial",
            str(len(ids)),
            f"created {totals.created} + partial {totals.partial} = {landed}",
            GO if len(ids) == landed else NO_GO,
        ),
        Check(
            "every conversation accounted for",
            str(totals.source_conversations),
            f"pending {totals.pending}",
            GO if reconciles and totals.pending == 0 else NO_GO,
        ),
        Check(
            "an interruption was recovered",
            str(workspace.run.interrupted),
            "entries converted out of `running`",
            GO if workspace.run.interrupted else UNKNOWN,
        ),
        Check(
            "no superseded chat left behind",
            str(sum(len(old) for old in workspace.run.previous_destinations.values())),
            "run.json previous_destinations",
            GO if not workspace.run.previous_destinations else UNKNOWN,
        ),
    ]


# --------------------------------------------------------------------------- #
# The safety audit (§17)
# --------------------------------------------------------------------------- #


def export_digest(export: Path) -> str:
    """The sha256 `02` fingerprints an export by: `conversations.json`'s bytes.

    The archive's own digest would be a different claim — a zip rewritten with
    the same members has a different one — and the fingerprint in `run.json` is
    this. Which makes the comparison meaningful: it is the number the run itself
    recorded, not one this script invented afterwards.
    """
    with ExportSource.open(export) as source:
        return hashlib.sha256(source.read(CONVERSATIONS_FILE)).hexdigest()


def history_urls(profile: Path) -> list[str]:
    """The `url` column of every Chrome history database under `profile`.

    Copied to a temporary directory before it is opened, with whatever
    write-ahead log sits beside it: the file is Chrome's, a browser that is still
    running holds a lock on it, and a read-only connection to the copy cannot
    disturb a profile this script has no business writing to.

    The `urls` table also has a `title` column. It is not selected. A claude.ai
    page title is a conversation title, and §10 keeps those off stdout.
    """
    found: list[str] = []
    for database in sorted(profile.rglob("History")):
        if not database.is_file():
            continue
        with tempfile.TemporaryDirectory() as scratch:
            copy = Path(scratch) / "History"
            for suffix in ("", "-wal", "-shm"):
                beside = database.with_name(database.name + suffix)
                if beside.is_file():
                    shutil.copy2(beside, copy.with_name(copy.name + suffix))
            connection = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
            # `closing`, not `with connection`: the context manager of a
            # connection commits or rolls back and leaves it open, and this one
            # holds a file inside a temporary directory that is about to go.
            with closing(connection):
                found.extend(
                    str(row[0]) for row in connection.execute("SELECT url FROM urls")
                )
    return found


@dataclass(frozen=True)
class Visit:
    """One history URL, reduced to what may be printed."""

    url: str
    host: str
    path: str

    @classmethod
    def of(cls, url: str) -> "Visit":
        parts = urlsplit(url)
        return cls(url=url, host=parts.netloc.casefold(), path=parts.path)


def classify(urls: Iterable[str], known: set[str]) -> dict[str, list[Visit]]:
    """Split the history into the three buckets `21`'s criterion cares about.

    `expected` is what the criterion allows — `/new`, and a `/chat/<id>` whose id
    this workspace created. `other_claude` is everything else on claude.ai: the
    login page a `login` really does visit, the root that redirects. It is
    reported rather than failed, because a human reading the write-up is who
    should decide whether a path the tool never asks for is a finding. `foreign`
    is any other host at all, and there is no benign reason for one to be in a
    profile this tool launched.
    """
    buckets: dict[str, list[Visit]] = {
        "expected": [],
        "unknown_chat": [],
        "other_claude": [],
        "foreign": [],
    }
    for url in urls:
        visit = Visit.of(url)
        if visit.host not in CLAUDE_HOSTS:
            buckets["foreign"].append(visit)
        elif visit.path.rstrip("/") == NEW_CHAT_PATH:
            buckets["expected"].append(visit)
        elif visit.path.startswith(CHAT_PREFIX):
            identifier = visit.path[len(CHAT_PREFIX) :].strip("/")
            bucket = "expected" if identifier in known else "unknown_chat"
            buckets[bucket].append(visit)
        else:
            buckets["other_claude"].append(visit)
    return buckets


def known_chats(workspace: Workspace) -> set[str]:
    """Every destination chat this workspace ever created, superseded ones too.

    `--force` never deletes at the destination (§17), so a chat an earlier run
    made is still the workspace's own and still legitimately in the history.
    """
    known = set(chat_ids(workspace))
    for old in workspace.run.previous_destinations.values():
        known.update(old)
    return known


def safety(workspace: Workspace, *, export: Path | None, profile: Path) -> list[Check]:
    """The two §17 criteria: the export is untouched, and so is everything that
    is not this migration."""
    recorded = workspace.run.export_fingerprint or workspace.plan.export_fingerprint
    if export is None:
        # A row, not a silence. `safety` answers "was anything outside this
        # migration touched", and an audit that simply left the export out when
        # nobody named one would read as a §17 pass that had checked it.
        # (Raised by Copilot in review on #30.)
        checks = [
            Check(
                EXPORT_CHECK,
                UNMEASURED,
                "pass --export <export> to re-digest it",
                UNKNOWN,
            )
        ]
    else:
        digest = export_digest(export)
        checks = [
            Check(
                EXPORT_CHECK,
                digest[:16],
                f"recorded {recorded[:16] or UNMEASURED}",
                GO if recorded and digest == recorded else NO_GO,
            )
        ]
    if not profile.is_dir():
        checks.append(
            Check("browser history", UNMEASURED, f"no profile at {profile}", UNKNOWN)
        )
        return checks
    buckets = classify(history_urls(profile), known_chats(workspace))
    paths = sorted({visit.path for visit in buckets["other_claude"]})
    hosts = sorted({visit.host for visit in buckets["foreign"]})
    checks.extend(
        [
            Check(
                HISTORY_CHECKS[0],
                str(len(buckets["expected"])),
                "/new and /chat/<id> this workspace created",
                GO,
            ),
            Check(
                HISTORY_CHECKS[1],
                str(len(buckets["unknown_chat"])),
                ", ".join(visit.path for visit in buckets["unknown_chat"]) or "none",
                GO if not buckets["unknown_chat"] else NO_GO,
            ),
            Check(
                HISTORY_CHECKS[2],
                str(len(buckets["foreign"])),
                ", ".join(hosts) or "none",
                GO if not buckets["foreign"] else NO_GO,
            ),
            Check(
                HISTORY_CHECKS[3],
                str(len(buckets["other_claude"])),
                ", ".join(paths) or "none",
                GO if not paths else UNKNOWN,
            ),
        ]
    )
    return checks


# --------------------------------------------------------------------------- #
# The sample question 3 is measured over
# --------------------------------------------------------------------------- #


def sample(workspace: Workspace, *, size: int, seed: int) -> list[str]:
    """`size` completed conversations, drawn reproducibly.

    Sorted before the draw and seeded, so that the sample is a fact about the
    workspace rather than about the run of this script: `21` measures semantic
    fidelity "on a random sample of 20 completed conversations", and a write-up
    that cannot say which twenty cannot be checked.
    """
    completed = sorted(
        uuid
        for uuid, entry in workspace.migration.items()
        if entry.status is Status.COMPLETED
    )
    if len(completed) <= size:
        return completed
    return sorted(random.Random(seed).sample(completed, size))


# --------------------------------------------------------------------------- #
# Printing
# --------------------------------------------------------------------------- #


def print_checks(title: str, checks: Sequence[Check]) -> int:
    """One block of rows, and the exit code the verdicts add up to."""
    print(title)
    print()
    for line in columns(
        [[check.name, check.number, check.terms, check.verdict] for check in checks]
    ):
        print(f"  {line}")
    print()
    blocking = [check for check in checks if check.blocking]
    if blocking:
        print(f"{NO_GO}: {len(blocking)} of {len(checks)} checks did not pass")
        return int(ExitCode.FAILED)
    print(f"{GO}: {len(checks)} checks passed")
    return int(ExitCode.OK)


def print_metrics(rows: Sequence[Metric]) -> int:
    """§19's table, as Markdown, to be pasted into `docs/experiment-02.md`."""
    print("| §19 metric | Number | Numerator ÷ denominator | Note |")
    print("| --- | --- | --- | --- |")
    for row in rows:
        print(f"| {row.name} | {row.number} | {row.terms} | {row.note} |")
    print()
    missing = [row.name for row in rows if row.number == UNMEASURED]
    if missing:
        print(f"unmeasured: {', '.join(missing)}")
        return int(ExitCode.FAILED)
    return int(ExitCode.OK)


# --------------------------------------------------------------------------- #
# The command line
# --------------------------------------------------------------------------- #


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="sign_off.py", description="21's gate, metrics, drill and safety audit."
    )
    subcommands = root.add_subparsers(dest="command", required=True)

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        sub = subcommands.add_parser(name, help=help_text)
        sub.add_argument(
            "--workspace",
            type=Path,
            default=DEFAULT_WORKSPACE,
            help="The migration workspace. Default: ./migration",
        )
        return sub

    gate_command = add("gate", "The go / no-go gate, from the pilot's workspace.")
    gate_command.add_argument(
        "--failures-understood",
        action="store_true",
        help="Every failure line has a reason written into experiment-02.md.",
    )

    metrics_command = add("metrics", "The §19 metrics, as a Markdown table.")
    metrics_command.add_argument(
        "--recoveries",
        type=int,
        default=None,
        help="In-run recovery rows counted in the transcript review (13).",
    )

    sample_command = add("sample", "The completed conversations to probe.")
    sample_command.add_argument("--size", type=int, default=SAMPLE_SIZE)
    sample_command.add_argument("--seed", type=int, default=SAMPLE_SEED)

    add("drill", "The interruption drill: no duplicates, nothing lost.")

    safety_command = add(
        "safety", "§17: the export's digest, and the profile's history."
    )
    safety_command.add_argument(
        "--export", type=Path, default=None, help="The source export, to re-digest."
    )
    safety_command.add_argument(
        "--profile",
        type=Path,
        default=None,
        help="Browser profile. Default: <workspace>/browser-profile",
    )
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    workspace_path = Path(args.workspace)
    try:
        workspace = open_workspace(workspace_path)
    except (stating.StateError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return int(ExitCode.USAGE)

    if args.command == "gate":
        return print_checks(
            "Gate — the pilot's numbers, before the full run",
            gate(workspace, failures_understood=args.failures_understood),
        )
    if args.command == "metrics":
        return print_metrics(metrics(workspace, recoveries=args.recoveries))
    if args.command == "sample":
        for uuid in sample(workspace, size=args.size, seed=args.seed):
            print(f"{short_id(uuid)}  {uuid}")
        return int(ExitCode.OK)
    if args.command == "drill":
        return print_checks("Interruption drill", drill(workspace))
    profile = args.profile or workspace_path / "browser-profile"
    return print_checks(
        "Safety (§17)",
        safety(workspace, export=args.export, profile=Path(profile)),
    )


if __name__ == "__main__":  # pragma: no cover - the script's entry point
    raise SystemExit(main())
