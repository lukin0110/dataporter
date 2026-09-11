"""The pilot's write-up, kept honest.

`20`'s deliverable is not only code: it is `docs/experiment-01.md`, with a number
against each of §18's six questions and a grade against each migrated
conversation. A document is the one kind of deliverable that can look finished
while saying nothing, so this module checks its shape the way
`test_spike_docs.py` checks `10`'s — and for the same reason: forgetting to
answer a question has to look different from answering it "not yet run".

What is checked is the shape and the marking, never the content of an answer:

- each of §18's six questions has a section, a measure, an evidence line and
  exactly one marked number;
- the only marks are `*not yet run*` and `*measured on <date>*`, so an impression
  cannot pass for a measurement;
- while the document says no pilot has run, nothing in it may claim one has;
- the step checklist has a row for every step of `11`, because a step nobody
  looked at is exactly the one a reviewer would skip;
- every command the document tells an operator to run is a command the CLI has.
"""

import re
from pathlib import Path

import pytest
import typer

from dataporter import PROGRAM_NAME, cli, pilot
from dataporter.steps import ORDER

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

EXPERIMENT = DOCS / "experiment-01.md"
TRANSCRIPTS = DOCS / "spike" / "pilot"

TEXT = EXPERIMENT.read_text(encoding="utf-8")

CODE = re.compile(r"`[^`\n]*`|```.*?```", re.DOTALL)
"""Inline code and fenced blocks. Stripped before the marks are counted: the
document explains its own marking, and `*measured on <date>*` inside backticks is
a mention of a mark and not one."""

PROSE = CODE.sub("", TEXT)

QUESTIONS = (
    ("Q1", "Can Hermes reliably create chats?"),
    ("Q2", "Can it reliably submit large migration seeds?"),
    ("Q3", "Does Claude correctly understand the reconstructed history?"),
    ("Q4", "How often does the browser agent require recovery?"),
    ("Q5", "How much human intervention is required?"),
    ("Q6", "What Claude UI limitations prevent faithful migration?"),
)
"""§18's six, in §18's words and §18's order. Written out rather than parsed out
of the brief: the brief is prose, and a question quietly reworded here should
have to be reworded here."""

NOT_RUN = "**Pilot run:** none."
"""What the document says until somebody has run one. `10`'s spike documents say
the same thing about themselves, in the same words."""

MARK = re.compile(r"\*(not yet run|measured on \d{4}-\d{2}-\d{2})\*")
MEASURED = re.compile(r"\*measured on \d{4}-\d{2}-\d{2}\*")

NO_SESSIONS = "**Sessions here:** none."


def section(heading: str) -> list[str]:
    """The lines under `heading`, up to the next heading of the same level."""
    lines = TEXT.splitlines()
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
    """The body rows of the first table in `lines`, cell by cell."""
    found: list[list[str]] = []
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if all(set(cell) <= {"-", ":"} and cell for cell in cells):
            continue  # the separator row
        found.append(cells)
    return found[1:] if found else found


# --------------------------------------------------------------------------- #
# The six questions
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("label", "question"), QUESTIONS)
def test_every_18_question_has_a_section(label: str, question: str) -> None:
    assert f"\n### {label} — {question}\n" in TEXT


@pytest.mark.parametrize(("label", "question"), QUESTIONS)
def test_every_question_has_a_measure_evidence_and_one_marked_number(
    label: str, question: str
) -> None:
    """A question with no measure is an opinion, and one with no evidence path
    is a number nobody can check."""
    lines = section(f"### {label} — {question}")
    body = " ".join(lines)
    assert "**Measure:**" in body, f"{label} says how it is not measured"
    assert "**Evidence:**" in body, f"{label} does not say where to look"
    numbers = [line for line in lines if line.startswith("**Number:**")]
    assert len(numbers) == 1, f"{label} has {len(numbers)} numbers"
    assert MARK.search(numbers[0]) is not None, f"{label}'s number is unmarked"


def test_every_mark_in_the_document_is_one_of_the_two() -> None:
    """An asterisked aside that is not a mark would read like one."""
    for found in re.findall(r"\*(?!\*)([^*\n]+)\*", PROSE):
        if found.startswith(("not yet run", "measured on")):
            assert MARK.fullmatch(f"*{found}*") is not None, found


def test_nothing_claims_a_measurement_while_no_pilot_has_run() -> None:
    """The rule that makes the marks worth anything: a document that says no run
    has happened may not carry a number from one."""
    if NOT_RUN not in TEXT:
        return
    assert MEASURED.search(PROSE) is None, (
        "a number claims a measurement while the status line still says none"
    )


# --------------------------------------------------------------------------- #
# The tables
# --------------------------------------------------------------------------- #


def test_the_selection_table_has_a_row_per_category() -> None:
    """The categories are the experiment's design, so a category added to
    `pilot.CATEGORIES` and not to the write-up fails here."""
    found = rows(section("## The selection"))
    assert [(row[0], row[1]) for row in found] == [
        (str(category.number), category.name) for category in pilot.CATEGORIES
    ]


def test_the_checklist_has_a_row_per_step_of_11() -> None:
    """`20` asks whether each step's verify condition was observed before the
    next act, which is a question per step and not per conversation."""
    found = rows(section("## Transcript review checklist"))
    assert [row[0] for row in found] == [f"`{step}`" for step in ORDER]


def test_the_grades_table_is_there_for_a_row_per_conversation() -> None:
    found = rows(section("## Semantic probe grades"))
    assert found, "no grade table"
    header = section("## Semantic probe grades")
    assert "Hand grade" in " ".join(header)
    assert "Judge" in " ".join(header)


# --------------------------------------------------------------------------- #
# What it tells an operator to run
# --------------------------------------------------------------------------- #


def test_every_command_it_names_exists() -> None:
    """A runbook that names a command nobody implemented is worse than none."""
    group = typer.main.get_command(cli.app)
    known = set(getattr(group, "commands", {}))
    named = set(re.findall(rf"{PROGRAM_NAME} ([a-z-]+)", TEXT))
    assert named, "the document names no commands at all"
    assert named <= known, f"not commands: {sorted(named - known)}"


def test_it_names_the_two_commands_20_added() -> None:
    assert f"{PROGRAM_NAME} followup" in TEXT
    assert f"{PROGRAM_NAME} judge" in TEXT
    assert "--pilot" in TEXT


# --------------------------------------------------------------------------- #
# The transcripts
# --------------------------------------------------------------------------- #


def test_the_transcript_directory_says_what_is_stripped() -> None:
    readme = (TRANSCRIPTS / "README.md").read_text(encoding="utf-8")
    for rule in ("Remove every snapshot body", "Remove the reply", "Remove account"):
        assert rule in readme, f"the transcript rules do not say: {rule}"


def test_it_stops_saying_there_are_none_once_there_are() -> None:
    readme = (TRANSCRIPTS / "README.md").read_text(encoding="utf-8")
    saved = [
        path
        for path in TRANSCRIPTS.iterdir()
        if path.is_file() and path.name != "README.md"
    ]
    if saved:
        assert NO_SESSIONS not in readme, (
            "transcripts are here and the README denies it"
        )
    else:
        assert NO_SESSIONS in readme
