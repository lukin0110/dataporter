"""The four documents `21` exists to produce, kept honest.

`21`'s deliverable is mostly not code: it is a full run, the numbers it produced,
and the four documents a person reads afterwards — `README.md`,
`docs/runbook.md`, `docs/experiment-02.md` and the finalised
`docs/LIMITATIONS.md`. A document is the one kind of deliverable that can look
finished while saying nothing, so this module checks the shape the way
`test_experiment_doc.py` checks `20`'s and `test_spike_docs.py` checks `10`'s:

- every §19 metric has a row and exactly one marked number, and the rows are the
  ones `spikes/sign_off.py` prints — so a metric renamed on one side fails here;
- while the write-up says no full run has happened, nothing in it may carry a
  number from one;
- every command the two operator documents name is a command that exists, in the
  CLI or in the sign-off script;
- `README.md` carries the §17 boundary and says where content ends up, which are
  the two things a reader has to know before running anything;
- every limitation name the code can print has a heading in `LIMITATIONS.md`
  with a count and a kind.

What is deliberately not checked is whether an answer is any good. That is what
a reviewer is for; this is what stops one being asked to review a blank.
"""

import re
import sys
from dataclasses import fields
from pathlib import Path

import pytest
import typer

from dataporter import PROGRAM_NAME, cli, render
from dataporter import verify as verifying

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "spikes"))

import sign_off  # noqa: E402  — after the path insert, as `10`'s scripts are

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

README = ROOT / "README.md"
RUNBOOK = DOCS / "runbook.md"
EXPERIMENT = DOCS / "experiment-02.md"
LIMITATIONS = DOCS / "LIMITATIONS.md"

OPERATOR_DOCS = (README, RUNBOOK, EXPERIMENT)

TEXT = EXPERIMENT.read_text(encoding="utf-8")

CODE = re.compile(r"`[^`\n]*`|```.*?```", re.DOTALL)
PROSE = CODE.sub("", TEXT)
"""Inline code and fenced blocks, stripped before the marks are counted. The
document explains its own marking, and `*measured on <date>*` inside backticks is
a mention of a mark rather than one — `test_experiment_doc.py`'s rule."""

NOT_RUN = "**Full run:** none."
MARK = re.compile(r"\*(not yet run|measured on \d{4}-\d{2}-\d{2})\*")
MEASURED = re.compile(r"\*measured on \d{4}-\d{2}-\d{2}\*")

SECTIONS = (
    "## The gate",
    "## The full run",
    "## The metrics (§19)",
    "## The interruption drill",
    "## Safety (§17)",
    "## What was not observed",
    "## Was §19's criterion met?",
    "## Slice statuses",
)
"""`21`'s *In scope*, one heading each. The last two are the ones a write-up
quietly drops: what a run never met, and which slices it left unfinished."""

KINDS = ("UI limit", "export limit", "tool choice")
"""`21`: each limitation is one of these three. A limitation with no kind is a
complaint rather than a finding."""


def section(text: str, heading: str) -> list[str]:
    """The lines under `heading`, up to the next heading of the same level."""
    lines = text.splitlines()
    level = heading.split(" ", 1)[0] + " "
    start = lines.index(heading)
    end = next(
        (
            position
            for position, line in enumerate(lines[start + 1 :], start + 1)
            if line.startswith(level)
        ),
        len(lines),
    )
    return lines[start + 1 : end]


def rows(lines: list[str]) -> list[list[str]]:
    """The body rows of the *first* table in `lines`, cell by cell.

    The first and not all of them: a section here carries its own table and then
    a subsection with another — attachment coverage by class, the probe grades —
    and a check that swept them together would count rows nobody meant.
    """
    found: list[list[str]] = []
    for line in lines:
        if not line.startswith("|"):
            if found:
                break
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if all(cell and set(cell) <= {"-", ":"} for cell in cells):
            continue  # the separator row
        found.append(cells)
    return found[1:]


def commands_named(text: str) -> set[str]:
    """The commands a document tells an operator to run.

    `[a-z][a-z-]*` rather than `[a-z-]+`, which `20`'s write-up can afford:
    these documents name `--version` and `--dry-run` too, and a flag read as a
    command name would fail this for saying something true."""
    return set(re.findall(rf"{PROGRAM_NAME} ([a-z][a-z-]*)", text))


def cli_commands() -> set[str]:
    group = typer.main.get_command(cli.app)
    return set(getattr(group, "commands", {}))


# --------------------------------------------------------------------------- #
# experiment-02.md — the numbers
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("heading", SECTIONS)
def test_the_write_up_has_every_section_21_asks_for(heading: str) -> None:
    assert f"\n{heading}\n" in TEXT


def test_every_19_metric_has_a_row() -> None:
    """And the rows are the script's own labels: the table is pasted from
    `sign_off.py metrics`, so the two cannot be allowed to drift."""
    table = rows(section(TEXT, "## The metrics (§19)"))
    assert [row[0] for row in table] == list(sign_off.METRIC_NAMES)


def test_every_metric_row_carries_a_measure_and_one_mark() -> None:
    """A metric with no measure is an opinion; two marks is a row that has been
    half updated."""
    for row in rows(section(TEXT, "## The metrics (§19)")):
        assert len(row) == 5, row
        assert row[1], f"{row[0]} does not say how it is measured"
        assert len(MARK.findall(row[-1])) == 1, row


def test_the_primary_metric_asks_for_its_two_terms() -> None:
    """`21`: "the primary metric is stated as a percentage with its numerator and
    denominator". A percentage column alone would satisfy the eye and not the
    criterion."""
    table = rows(section(TEXT, "## The metrics (§19)"))
    header = [
        line
        for line in section(TEXT, "## The metrics (§19)")
        if line.startswith("| §19 metric")
    ]
    assert header, "the metrics table has no header"
    assert "Terms" in header[0]
    assert table[0][0].startswith("Primary:")


def test_the_gate_has_a_row_per_threshold() -> None:
    """`21`'s four: two rates, one grade, and the judgement a person makes."""
    table = rows(section(TEXT, "## The gate"))
    assert len(table) == 4
    assert [row[1] for row in table[:2]] == ["≥ 90 %", "≥ 90 %"]
    assert "no `fail`" in table[2][1]
    assert all(MARK.search(row[-1]) for row in table)


def test_the_safety_table_has_a_row_per_check_the_script_prints() -> None:
    """`sign_off.py safety` reports the export digest and four history buckets
    apart, so a table with one "anything else" row would have to be aggregated
    by hand out of the script's own output. (Raised by Copilot in review on
    #30.)"""
    table = rows(section(TEXT, "## Safety (§17)"))
    assert [row[0].split("`")[1] for row in table] == list(sign_off.SAFETY_CHECKS)
    assert all(MARK.search(row[-1]) for row in table)


def test_the_drill_reports_duplicates_and_losses() -> None:
    body = " ".join(section(TEXT, "## The interruption drill"))
    assert "Distinct `/chat/<id>` ids" in body
    assert "Conversations lost" in body
    assert "**Verdict:**" in body


def test_every_mark_in_the_document_is_one_of_the_two() -> None:
    for found in re.findall(r"\*(?!\*)([^*\n]+)\*", PROSE):
        if found.startswith(("not yet run", "measured on")):
            assert MARK.fullmatch(f"*{found}*") is not None, found


def test_nothing_claims_a_measurement_while_no_run_has_happened() -> None:
    """The rule that makes the marks worth anything, and `20`'s rule before it."""
    if NOT_RUN not in TEXT:
        return
    assert MEASURED.search(PROSE) is None, (
        "a number claims a measurement while the status line still says none"
    )


def test_the_criterion_is_answered_in_a_sentence() -> None:
    """§19 is met or it is not. A section that described the numbers again
    instead of answering would be the one thing the sign-off cannot do."""
    body = section(TEXT, "## Was §19's criterion met?")
    assert any(MARK.search(line) for line in body)


# --------------------------------------------------------------------------- #
# The commands the documents name
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", OPERATOR_DOCS, ids=lambda path: path.name)
def test_every_command_named_exists(path: Path) -> None:
    """A runbook that names a command nobody implemented is worse than none."""
    named = commands_named(path.read_text(encoding="utf-8"))
    assert named, f"{path.name} names no commands at all"
    assert named <= cli_commands(), f"not commands: {sorted(named - cli_commands())}"


@pytest.mark.parametrize("path", OPERATOR_DOCS, ids=lambda path: path.name)
def test_every_sign_off_subcommand_named_exists(path: Path) -> None:
    named = set(re.findall(r"sign_off\.py ([a-z-]+)", path.read_text(encoding="utf-8")))
    # The difference, not `named`: a message listing every subcommand the
    # document names reads as though the valid ones were wrong too. (Raised by
    # Copilot in review on #30.)
    unknown = named - set(sign_off.COMMANDS)
    assert not unknown, f"not subcommands: {sorted(unknown)}"


@pytest.mark.parametrize("name", sign_off.COMMANDS)
def test_the_script_really_takes_each_subcommand(name: str) -> None:
    parsed = sign_off.parser().parse_args([name, "--workspace", "somewhere"])
    assert parsed.command == name


def test_the_readme_gets_a_reader_to_a_pilot() -> None:
    """`21`'s criterion: a reader who has never seen the project can run `login`,
    `import --dry-run` and `import --pilot` from `README.md` alone."""
    text = README.read_text(encoding="utf-8")
    for step in (
        f"{PROGRAM_NAME} setup",
        f"{PROGRAM_NAME} doctor",
        f"{PROGRAM_NAME} login",
        f"{PROGRAM_NAME} import <export> --dry-run",
        f"{PROGRAM_NAME} import <export> --pilot",
        f"{PROGRAM_NAME} import <export> --all",
    ):
        assert step in text, step


def test_the_readme_says_what_the_tool_will_never_do() -> None:
    """§17's boundary, in the file a reader meets first."""
    text = README.read_text(encoding="utf-8").casefold()
    for promise in ("delete source conversations", "billing", "security settings"):
        assert promise in text, promise
    assert "never deletes" in text


def test_the_readme_says_where_content_ends_up_and_how_to_purge_it() -> None:
    """Three places, and each one purged by deleting a directory (§10)."""
    text = README.read_text(encoding="utf-8")
    for place in ("migration/", "~/.hermes/profiles/dataporter/", "seeds/"):
        assert place in text, place
    assert "rm -rf migration/" in text


@pytest.mark.parametrize(
    "topic",
    (
        "## Interrupting",
        "## Resuming a pause",
        "## Retrying failures",
        "## Cleaning up",
    ),
)
def test_the_runbook_covers_the_topics_21_names(topic: str) -> None:
    assert f"\n{topic}\n" in RUNBOOK.read_text(encoding="utf-8")


def test_the_runbook_says_the_tool_deletes_nothing_at_the_destination() -> None:
    """`21` asks for cleanup "by hand — the tool never deletes at the
    destination", which is a §17 promise and not a convenience."""
    assert "deletes nothing at the destination" in RUNBOOK.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# LIMITATIONS.md, finalised
# --------------------------------------------------------------------------- #


def limitation_names() -> list[str]:
    """Every slug the report can print, from the code that writes them."""
    return [field.name for field in fields(render.Limitations)] + [
        verifying.TIMESTAMPS_NOT_PRESERVED,
        verifying.TITLE_NOT_SET,
    ]


@pytest.mark.parametrize("name", limitation_names())
def test_every_limitation_name_has_a_heading_with_a_count_and_a_kind(
    name: str,
) -> None:
    text = LIMITATIONS.read_text(encoding="utf-8")
    heading = f"### `{name}`"
    assert heading in text, name
    table = rows(section(text, heading))
    assert len(table) == 1, f"{name} has {len(table)} count rows"
    count, kind, mark = table[0]
    assert count, name
    assert kind in KINDS, f"{name}: {kind!r} is not one of {KINDS}"
    assert MARK.search(mark), f"{name}'s count is unmarked"
