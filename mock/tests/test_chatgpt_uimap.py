"""The citation is real: every row the mock chatgpt.com stands on is a row of its map.

The mock invents nothing, and this is the checkable form of that claim. It is
also the thing that fails when somebody teaches the mock a behaviour without
first adding a row for it — which is the order §54 fixes: a behaviour the mock
needs and the map has no row for is added to the map first, marked *reported* if
a source says so and *unknown* if none does.

`docs/chatgpt-ui-map.md` belongs to the tool's repository, not to this project.
While the two live together the test reads it; after the mocks move out (ADR
0003) there is nothing to read and the test says so rather than failing.
"""

import re
from pathlib import Path

import pytest
from chatgptmock import uimap

MAP = Path(__file__).resolve().parents[2] / "docs" / "chatgpt-ui-map.md"

ROW = re.compile(r"^\|\s*`(?P<label>[^`]+)`")
"""A table row's first cell, which the map always writes in backticks."""

MARK = re.compile(r"\*(unknown|observed on \d{4}-\d{2}-\d{2}|reported \([^)]*\))\*")


def rows() -> dict[str, str]:
    found: dict[str, str] = {}
    for line in MAP.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if match is not None:
            found[match.group("label")] = line
    return found


@pytest.mark.skipif(not MAP.exists(), reason="the UI map lives in the tool's repository")
def test_every_row_the_mock_cites_is_in_the_map() -> None:
    missing = sorted(set(uimap.cited()) - set(rows()))
    assert not missing, (
        f"the mock shows states the UI map has no row for: {missing}. Add the row first, "
        "marked *reported* if a source says so and *unknown* if none does."
    )


@pytest.mark.skipif(not MAP.exists(), reason="the UI map lives in the tool's repository")
def test_no_row_the_mock_cites_is_observed() -> None:
    """A mock run never turns a row *observed*, and nobody has looked at chatgpt.com yet."""
    for label, line in rows().items():
        if label in uimap.cited():
            marks = MARK.findall(line)
            assert marks, f"the row `{label}` carries no mark"
            assert not any(mark.startswith("observed") for mark in marks), (
                f"the row `{label}` is marked observed; the mock's citation must say what was observed"
            )


def test_every_cited_row_says_what_the_mock_did_about_it() -> None:
    assert sorted(uimap.WHAT_THE_MOCK_DOES) == uimap.cited()
