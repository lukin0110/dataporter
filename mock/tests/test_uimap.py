"""The citation is real: every row the mock stands on is a row of the map.

The mock invents nothing, and this is the checkable form of that claim. It is
also the thing that fails when somebody teaches the mock a behaviour without
first adding a row for it — which is the order §21 fixes, because a mock that
can do something the map does not describe is a mock inventing claude.ai.

`docs/claude-ui-map.md` belongs to the tool's repository, not to this project.
While the two live together the test reads it; after the mock moves out (ADR
0003) there is nothing to read and the test says so rather than failing.
"""

import re
from pathlib import Path

import pytest
from claudemock import uimap

MAP = Path(__file__).resolve().parents[2] / "docs" / "claude-ui-map.md"

ROW = re.compile(r"^\|\s*`(?P<label>[^`]+)`")
"""A table row's first cell, which the map always writes in backticks. Anything
after the closing backtick — the slice that added the row, usually — is
decoration and not part of the label."""


def labels() -> set[str]:
    found = set()
    for line in MAP.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if match is not None:
            found.add(match.group("label"))
    return found


@pytest.mark.skipif(not MAP.exists(), reason="the UI map lives in the tool's repository")
def test_every_row_the_mock_cites_is_in_the_map() -> None:
    missing = sorted(set(uimap.cited()) - labels())
    assert not missing, (
        f"the mock shows states the UI map has no row for: {missing}. Add the row first, marked *unknown*."
    )


def test_every_cited_row_says_what_the_mock_did_about_it() -> None:
    assert sorted(uimap.WHAT_THE_MOCK_DOES) == uimap.cited()
