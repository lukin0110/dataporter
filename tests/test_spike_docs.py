"""The four documents `10` exists to produce, kept honest.

`10` is a spike: its deliverable is not code but recorded answers, and the rule
that makes the rest of the plan safe is that no slice from `11` onward starts
until every one of its ten questions has one. That rule is only worth something
if forgetting to answer a question looks different from answering it `unknown`,
so this module checks the shape rather than the content:

- the questions come from `10` itself, so an eleventh question added to the spec
  fails the build until a document answers it;
- every answer carries a mark, and the only marks are `*unknown*` and
  `*observed on <date>*`, so an impression cannot pass for an observation;
- a document that claims any observation may no longer say no spike has run.

It tests documents rather than modules, which is unusual here, but so does
`test_export_format_doc.py`, and for the same reason: the marking is an
acceptance criterion and a new unmarked row is exactly the kind of thing that
gets added without one.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SPEC = ROOT / "specs" / "impl" / "10-attach-spike.md"

ATTACH = DOCS / "hermes-attach.md"
UI_MAP = DOCS / "claude-ui-map.md"
SEED_LIMITS = DOCS / "seed-limits.md"
LIMITATIONS = DOCS / "LIMITATIONS.md"

ANSWER_DOCS = (ATTACH, UI_MAP, SEED_LIMITS)

OWNERS = {
    ATTACH: {"Q1", "Q2", "Q9"},
    UI_MAP: {"Q4", "Q5", "Q6", "Q7", "Q8", "Q10"},
    SEED_LIMITS: {"Q3"},
}
"""Which document `10`'s *Deliverables* section makes responsible for which
question. Written out rather than derived: the split is a decision of the spec,
and a question quietly moving between documents should have to be typed here."""

NOT_RUN = "**Spike run:** none."
"""What each document says until a human has watched something. The mirror of
`test_export_format_doc.py`'s "no export has been read"."""

MARK = re.compile(r"\*(unknown|observed on \d{4}-\d{2}-\d{2})\*")
OBSERVED = re.compile(r"\*observed on \d{4}-\d{2}-\d{2}\*")
LIMITATION_MARK = re.compile(
    r"\*(unknown|by construction|observed on \d{4}-\d{2}-\d{2})\*"
)
"""`LIMITATIONS.md` has a third mark: a limitation that follows from replaying a
conversation as pasted messages is not waiting on an observation, and marking it
`unknown` would put it in a queue it can never leave."""


# --------------------------------------------------------------------------- #
# Reading the documents
# --------------------------------------------------------------------------- #


def section(path: Path, heading: str) -> list[str]:
    """The lines under `heading`, up to the next heading of the same level."""
    lines = path.read_text().splitlines()
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


def bullets(lines: list[str], prefix: str) -> list[str]:
    """The bullets starting with `prefix`, each joined with its wrapped lines.

    A mark usually sits on the last line of a wrapped bullet, so a per-line check
    would read every multi-line entry as unmarked.
    """
    found: list[str] = []
    open_bullet = False
    for line in lines:
        if line.startswith(prefix):
            found.append(line.strip())
            open_bullet = True
        elif open_bullet and line.strip():
            found[-1] += " " + line.strip()
        else:
            open_bullet = False
    return found


def answers(path: Path) -> dict[str, str]:
    """`{"Q1": "the whole answer bullet", ...}` for one document."""
    found: dict[str, str] = {}
    for bullet in bullets(section(path, "## Answers"), "- **Q"):
        label = re.match(r"- \*\*(Q\d+)", bullet)
        assert label is not None, bullet
        assert label.group(1) not in found, f"answered twice: {label.group(1)}"
        found[label.group(1)] = bullet
    return found


def marked_rows(path: Path) -> list[str]:
    """Every row of every table whose last column is `Mark`.

    Scoped to those tables so that the ladder in `hermes-attach.md`, which has no
    mark column because a rung is not an observation, is left alone.
    """
    rows: list[str] = []
    collecting = False
    for line in path.read_text().splitlines():
        if line.startswith("|") and line.rstrip().endswith("| Mark |"):
            collecting = True
            continue
        if not line.startswith("|"):
            collecting = False
            continue
        if collecting and not set(line) <= set("| -"):  # skip the rule row
            rows.append(line.strip())
    return rows


def spec_questions() -> list[str]:
    """`10`'s ten questions, read off the spec's own numbered list."""
    numbers = [
        match.group(1)
        for line in section(SPEC, "## Questions to answer")
        if (match := re.match(r"(\d+)\. ", line))
    ]
    return [f"Q{number}" for number in numbers]


# --------------------------------------------------------------------------- #
# The questions are all answered, once, in the right place
# --------------------------------------------------------------------------- #


def test_the_spec_still_asks_ten_questions() -> None:
    assert spec_questions() == [f"Q{number}" for number in range(1, 11)]


def test_every_question_has_exactly_one_answer() -> None:
    answered = [question for path in ANSWER_DOCS for question in answers(path)]
    assert sorted(answered) == sorted(spec_questions())


@pytest.mark.parametrize("path", ANSWER_DOCS, ids=lambda path: path.name)
def test_each_document_answers_the_questions_it_owns(path: Path) -> None:
    assert set(answers(path)) == OWNERS[path]


# --------------------------------------------------------------------------- #
# Nothing is claimed without a mark
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", ANSWER_DOCS, ids=lambda path: path.name)
def test_every_answer_is_marked(path: Path) -> None:
    unmarked = [
        question
        for question, bullet in answers(path).items()
        if not MARK.search(bullet)
    ]
    assert unmarked == []


@pytest.mark.parametrize("path", ANSWER_DOCS, ids=lambda path: path.name)
def test_every_table_row_is_marked(path: Path) -> None:
    assert [row for row in marked_rows(path) if not MARK.search(row)] == []


@pytest.mark.parametrize("path", (UI_MAP, SEED_LIMITS), ids=lambda path: path.name)
def test_the_tables_that_carry_observations_have_rows(path: Path) -> None:
    """`hermes-attach.md` is exempt: its one table is the fallback ladder, and a
    rung is a decision rather than something anybody watched the page do."""
    assert marked_rows(path)


@pytest.mark.parametrize("path", ANSWER_DOCS, ids=lambda path: path.name)
def test_a_document_that_observed_nothing_says_so(path: Path) -> None:
    """The gate for `11`: the status line and the marks cannot disagree.

    Either every mark in the document is `unknown` and it says no spike has run,
    or something was observed and the line has to be replaced by the date, the
    Hermes version and the Chrome version `10`'s method asks for.
    """
    text = path.read_text()
    claims = OBSERVED.search(text) is not None
    assert claims is not (NOT_RUN in text), (
        f"{path.name}: {NOT_RUN!r} and an `observed on` mark cannot both be true"
    )


# --------------------------------------------------------------------------- #
# LIMITATIONS.md
# --------------------------------------------------------------------------- #


def test_limitations_names_what_ten_expects_to_find() -> None:
    """`10` names three outright: timestamps, message ids, the model used."""
    text = LIMITATIONS.read_text().casefold()
    for expected in ("timestamp", "message identifier", "model"):
        assert expected in text, expected


def test_every_limitation_is_marked() -> None:
    entries = bullets(section(LIMITATIONS, "## Structural fidelity (§15)"), "- **")
    assert len(entries) > 5
    assert [entry for entry in entries if not LIMITATION_MARK.search(entry)] == []


# --------------------------------------------------------------------------- #
# The evidence directory
# --------------------------------------------------------------------------- #


def test_the_spike_directory_says_what_lands_in_it() -> None:
    assert (DOCS / "spike" / "README.md").is_file()
