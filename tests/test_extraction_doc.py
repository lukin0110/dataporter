"""The first asks' write-ups, kept honest (`31`, `47`).

`test_experiment_doc.py` does this for `20`'s pilot and `test_spike_docs.py` for
`10`'s four documents; this is the same rule applied to brief `03`'s own record,
and for the same reason. `31` can be `Built` with every test passing and still
have asked nothing of a real account, so the one thing that must not be possible
is for the document to look finished while saying nothing.

What is checked is the shape and the marking, never the content of an answer:
the three §39 questions this document owns each have a measure, an evidence line
and exactly one marked number; the only marks are `*not yet run*` and
`*measured on <date>*`; while the document says no extraction has run, nothing in
it may claim one; and every command it tells an operator to run is a command the
CLI has.
"""

import re
from pathlib import Path

import pytest
import typer

from dataporter import PROGRAM_NAME, cli

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

QUESTIONS_01 = (
    ("Q1", "Does the ask work, in each mode, and does an email arrive?"),
    ("Q2", "Does the fetched archive match the one a person downloads?"),
    (
        "Q5",
        "How long does the link live, and what does the tool say when it has died?",
    ),
)
"""The three of §39 that the *ask* answers, in §39's order. Written out rather
than parsed out of the brief: the brief is prose, and a question quietly reworded
here should have to be reworded here."""

QUESTIONS_02 = (
    ("Q1", "Does the ask work, in each mode, and does an email or a text arrive?"),
    ("Q2", "Does the fetched archive match the one a person downloads?"),
    ("Q5", "How long does the link live, and what does the tool say when it has died?"),
    ("Q7", "Does the real link need the session?"),
    ("Q8", "What is the redirect chain from the link to the bytes?"),
    ("Q9", "What is the zip's file name, by length and suffix?"),
    ("Q10", "Where is the Data controls page, and is it the shape the mock serves?"),
    ("Q11", "What does the auth host show, and does the walk get through it?"),
    ("Q12", "How long did the export take to arrive?"),
    ("Q13", "What does the site show when an export is already requested, and when a link has expired?"),
)
"""The ten `docs/extraction-02.md` owns (`47`, brief `06` §69): §39's three, and §69's seven."""

DOCUMENTS = {
    "extraction-01.md": (QUESTIONS_01, ["yes", "yes", "no", "no", "yes", "no"]),
    "extraction-02.md": (QUESTIONS_02, ["yes", "yes", "no", "no", "yes", "no", *["yes"] * 7]),
}
"""Each record, the questions it owns, and which rows of its table it answers."""

TEXTS = {name: (DOCS / name).read_text(encoding="utf-8") for name in DOCUMENTS}

CODE = re.compile(r"`[^`\n]*`|```.*?```", re.DOTALL)
"""Inline code and fenced blocks, stripped before the marks are counted: the
document explains its own marking, and a mark inside backticks is a mention."""

NOT_RUN = "**Extraction run:** none."
"""What the document says until somebody has asked a real account. `10`'s spike
documents and `20`'s write-up say the same thing about themselves."""

MARK = re.compile(r"\*(not yet run|measured on \d{4}-\d{2}-\d{2})\*")
MEASURED = re.compile(r"\*measured on \d{4}-\d{2}-\d{2}\*")


def section(text: str, heading: str) -> list[str]:
    """Return the lines under `heading`, up to the next heading of the same level."""
    lines = text.splitlines()
    level = heading.split(" ", 1)[0] + " "
    start = lines.index(heading)
    end = next(
        (position for position, line in enumerate(lines[start + 1 :], start + 1) if line.startswith(level)),
        len(lines),
    )
    return lines[start + 1 : end]


def questions_of() -> list[tuple[str, str, str]]:
    return [(name, label, question) for name, (questions, _) in DOCUMENTS.items() for label, question in questions]


def rows(lines: list[str]) -> list[list[str]]:
    """Return the body rows of the first table in `lines`, cell by cell."""
    found: list[list[str]] = []
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if all(set(cell) <= {"-", ":"} and cell for cell in cells):
            continue  # the separator row
        found.append(cells)
    return found[1:] if found else found


@pytest.mark.parametrize(("name", "label", "question"), questions_of())
def test_every_question_it_owns_has_a_section(name: str, label: str, question: str) -> None:
    assert f"\n### {label} — {question}\n" in TEXTS[name]


@pytest.mark.parametrize(("name", "label", "question"), questions_of())
def test_every_question_has_a_measure_evidence_and_one_marked_number(name: str, label: str, question: str) -> None:
    lines = section(TEXTS[name], f"### {label} — {question}")
    body = " ".join(lines)
    assert "**Measure:**" in body, f"{label} says how it is not measured"
    assert "**Evidence:**" in body, f"{label} does not say where to look"
    numbers = [line for line in lines if line.startswith("**Number:**")]
    assert len(numbers) == 1, f"{label} has {len(numbers)} numbers"
    assert MARK.search(numbers[0]) is not None, f"{label}'s number is unmarked"


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_every_mark_in_the_document_is_one_of_the_two(name: str) -> None:
    for found in re.findall(r"\*(?!\*)([^*\n]+)\*", CODE.sub("", TEXTS[name])):
        if found.startswith(("not yet run", "measured on")):
            assert MARK.fullmatch(f"*{found}*") is not None, found


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_nothing_claims_a_measurement_while_no_extraction_has_run(name: str) -> None:
    if NOT_RUN not in TEXTS[name]:
        return
    assert MEASURED.search(CODE.sub("", TEXTS[name])) is None, (
        "a number claims a measurement while the status line still says none"
    )


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_it_says_which_of_the_questions_are_somebody_else_s(name: str) -> None:
    """§39 asks six and the ask answers three; §69 asks seven more of ChatGPT.

    A document that quietly dropped the other three would read as if extraction were
    finished.
    """
    lines = TEXTS[name].splitlines()
    found = rows(lines[: lines.index("## How it is run")])
    answered = DOCUMENTS[name][1]
    assert [row[0] for row in found] == [str(number) for number in range(1, len(answered) + 1)]
    assert [row[2] for row in found] == answered


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_page_table_is_there_for_the_ui_map_rows(name: str) -> None:
    found = rows(section(TEXTS[name], "## What the page did"))
    assert found
    assert all(MARK.search(" ".join(row)) for row in found)


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_every_command_it_names_exists(name: str) -> None:
    """A runbook that names a command nobody implemented is worse than none."""
    group = typer.main.get_command(cli.app)
    known = set(getattr(group, "commands", {}))
    named = set(re.findall(rf"{PROGRAM_NAME} ([a-z-]+)", TEXTS[name]))
    assert named, "the document names no commands at all"
    assert named <= known, f"not commands: {sorted(named - known)}"


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_it_names_the_account_option_the_slice_added(name: str) -> None:
    assert "--account" in TEXTS[name]
    assert f"{PROGRAM_NAME} extract" in TEXTS[name]


def test_the_chatgpt_record_names_the_source_and_carries_no_link() -> None:
    text = TEXTS["extraction-02.md"]
    assert "--source chatgpt" in text
    assert "__mock" not in text
    assert "https://chatgpt.com" not in text
