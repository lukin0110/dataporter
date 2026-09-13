"""`10`'s note file: the thing every observation in the spike goes through.

`spikes/` is lint-checked and type-checked by `make check` because "a script
nobody can run after the next refactor cannot repeat the spike". Neither proves
it runs. These tests do, for the half that needs no browser: question
validation, the stamped context, and the one-JSON-object-per-line file.

Every test redirects `spike.NOTES` into `tmp_path`. The module points it at
`docs/spike/notes.jsonl` inside the repository, so a test that forgot would
write a fabricated observation into the working tree.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "spikes"))

import spike

from dataporter.browser import launcher
from dataporter.errors import BrowserError


@pytest.fixture
def notes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`spike.NOTES`, moved somewhere a test may write."""
    path = tmp_path / "docs" / "spike" / "notes.jsonl"
    monkeypatch.setattr(spike, "NOTES", path)
    return path


# --------------------------------------------------------------------------- #
# Questions
# --------------------------------------------------------------------------- #


def test_the_spike_asks_exactly_ten_questions() -> None:
    assert tuple(f"Q{number}" for number in range(1, 11)) == spike.QUESTIONS


@pytest.mark.parametrize("question", ["Q0", "Q11", "q1", "", "Q1 "])
def test_a_question_outside_the_ten_is_refused(notes: Path, question: str) -> None:
    """A typo is how an observation ends up in no document."""
    with pytest.raises(SystemExit):
        spike.record(question, "something was seen")
    assert not notes.exists()


# --------------------------------------------------------------------------- #
# Recording
# --------------------------------------------------------------------------- #


def test_a_note_is_one_json_line_carrying_the_context(notes: Path) -> None:
    entry = spike.record("Q4", "the stop control is a button")

    line = notes.read_text(encoding="utf-8").splitlines()
    assert len(line) == 1
    written = json.loads(line[0])
    assert written == entry
    assert written["question"] == "Q4"
    assert written["note"] == "the stop control is a button"
    for stamp in ("recorded_at", "hermes_version", "chrome_version"):
        assert stamp in written, stamp


def test_the_notes_directory_is_created(notes: Path) -> None:
    assert not notes.parent.exists()
    spike.record("Q1", "a note")
    assert notes.is_file()


def test_notes_accumulate_rather_than_replace(notes: Path) -> None:
    spike.record("Q1", "first")
    spike.record("Q2", "second")
    lines = notes.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["note"] for line in lines] == ["first", "second"]


def test_extra_fields_are_carried_into_the_line(notes: Path) -> None:
    """The ladder records counts beside its note; they must survive."""
    spike.record("Q3", "paste ladder", rounds=10, measured=4)
    written = json.loads(notes.read_text(encoding="utf-8"))
    assert written["rounds"] == 10
    assert written["measured"] == 4


def test_a_line_is_sorted_so_two_runs_diff_cleanly(notes: Path) -> None:
    spike.record("Q5", "a note", zebra=1, alpha=2)
    keys = list(json.loads(notes.read_text(encoding="utf-8")).keys())
    assert keys == sorted(keys)


# --------------------------------------------------------------------------- #
# Versions
# --------------------------------------------------------------------------- #


def test_a_binary_that_is_not_installed_reads_unknown() -> None:
    assert spike._version_of("definitely-not-a-real-binary-xyzzy") == spike.UNKNOWN


def test_a_binary_that_answers_is_reduced_to_its_number() -> None:
    """`python --version` prints `Python 3.12.3`; the number is the version."""
    found = spike._version_of(sys.executable)
    assert found != spike.UNKNOWN
    assert found.split(".")[0].isdigit()


def test_chrome_that_cannot_be_found_reads_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def absent() -> Path:
        raise BrowserError(detail="no browser", transient=False)

    monkeypatch.setattr(launcher, "find_executable", absent)
    assert spike.chrome_executable() == spike.UNKNOWN


def test_a_context_with_no_chrome_does_not_probe_for_its_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_version_of(unknown)` would shell out to a binary named `unknown`."""
    monkeypatch.setattr(spike, "chrome_executable", lambda: spike.UNKNOWN)
    called: list[str] = []

    def watched(executable: Path | str) -> str:
        called.append(str(executable))
        return spike.UNKNOWN

    monkeypatch.setattr(spike, "_version_of", watched)
    context = spike.Context.read()
    assert context.chrome_version == spike.UNKNOWN
    assert called == ["hermes"]


def test_a_context_is_stamped_with_a_utc_timestamp() -> None:
    assert spike.Context.read().recorded_at.startswith("20")


# --------------------------------------------------------------------------- #
# The command line
# --------------------------------------------------------------------------- #


def test_the_context_command_prints_json(notes: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert spike.main(["context"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert set(printed) == {
        "recorded_at",
        "hermes_version",
        "chrome_version",
        "chrome_executable",
    }
    assert not notes.exists(), "`context` must record nothing"


def test_the_note_command_records_and_prints(notes: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert spike.main(["note", "Q7", "rename is a menu item"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["question"] == "Q7"
    assert json.loads(notes.read_text(encoding="utf-8")) == printed


def test_the_note_command_rejects_an_unknown_question(notes: Path) -> None:
    """Argparse `choices` refuses before `record` is reached."""
    with pytest.raises(SystemExit):
        spike.main(["note", "Q99", "a note"])


def test_a_command_is_required(notes: Path) -> None:
    with pytest.raises(SystemExit):
        spike.main([])
