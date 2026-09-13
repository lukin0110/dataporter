"""`docs/export-format.md`, which the spec requires to mark every claim.

This tests a document rather than a module, which is unusual, but the marking is
an acceptance criterion of `02` and a new bullet is exactly the kind of thing that
gets added without one.
"""

from pathlib import Path

DOC = Path(__file__).resolve().parents[1] / "docs" / "export-format.md"

MARKS = ("*observed*", "*assumed*", "*decided in `02`*")


def claims() -> list[str]:
    """Return the bullets and table rows under `## Claims`, up to the next `## `.

    A bullet is joined with its wrapped continuation lines: the mark is often on
    the last line of one, and a per-line check would read that as unmarked.
    """
    lines = DOC.read_text().splitlines()
    start = lines.index("## Claims")
    end = next(position for position, line in enumerate(lines[start + 1 :], start + 1) if line.startswith("## "))
    found: list[str] = []
    open_bullet = False
    for line in lines[start:end]:
        if line.lstrip().startswith("- "):
            found.append(line.strip())
            open_bullet = True
        elif line.startswith("| `") and not line.rstrip().endswith("| Mark |"):
            found.append(line.strip())  # a table row; the header carries no claim
            open_bullet = False
        elif open_bullet and line.strip():
            found[-1] += " " + line.strip()
        else:
            open_bullet = False
    return found


def test_the_document_exists() -> None:
    assert DOC.is_file()


def test_there_are_claims_to_check() -> None:
    assert len(claims()) > 10


def test_every_claim_is_marked() -> None:
    unmarked = [claim for claim in claims() if not any(m in claim for m in MARKS)]
    assert unmarked == []


def test_the_status_says_no_export_has_been_read() -> None:
    """Until a real export confirms it, the gap must be impossible to miss."""
    assert "**Export inspected:** none." in DOC.read_text()
