"""The step names, and the three places they have to agree.

`11` names eleven steps. They are written down three times — in the spec's table,
in `dataporter/steps.py`, and in the skill Hermes reads — and a migration is only
describable if all three say the same thing: `state.json` records a name the
report prints and the agent claims to have reached.

So the spec is read as the source and the other two are compared against it. A
step renamed in one place fails here rather than in a report six slices later
that says `last_step: submit` about a procedure with no `submit` in it.
"""

import re
from pathlib import Path

from dataporter.hermes import skill as skilling
from dataporter.steps import ORDER, PER_PART, Step

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "specs" / "impl" / "11-skill.md"
SKILL = skilling.packaged_dir() / skilling.SKILL_FILENAME

FIRST_CELL = re.compile(r"^\|\s*`([a-z_]+)`")
"""The step name in the first column of a table row, ignoring whatever the cell
says after it — the spec's table qualifies some steps with the slice that owns
them (`` `attach` (per file, `16`) ``)."""


def table_steps(path: Path) -> list[str]:
    """Return the step names of the `| Step |` table in a Markdown document.

    Lines are stripped first: the spec's copy of the table is indented inside a
    bullet and the skill's is not, and that is a difference in Markdown, not in
    the procedure.
    """
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    start = next(position for position, line in enumerate(lines) if line.startswith("| Step |"))
    names = []
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        found = FIRST_CELL.match(line)
        if found is not None:
            names.append(found.group(1))
    return names


def test_the_enum_is_the_spec_table_in_order() -> None:
    assert [step.value for step in ORDER] == table_steps(SPEC)


def test_the_skill_runs_the_same_steps_in_the_same_order() -> None:
    """The procedure Hermes reads, against the vocabulary we record."""
    assert table_steps(SKILL) == [step.value for step in ORDER]


def test_the_repeated_steps_are_the_per_part_loop() -> None:
    """The four that repeat, and the seven that happen once."""
    assert PER_PART == (Step.PASTE, Step.SUBMIT, Step.AWAIT, Step.ACK)
    assert all(step in ORDER for step in PER_PART)


def test_a_step_is_its_name() -> None:
    """`StrEnum`, so a step reaches a prompt, a JSON file and a log as itself."""
    assert f"{Step.NEW_CHAT}" == "new_chat"
    assert Step("done") is Step.DONE
