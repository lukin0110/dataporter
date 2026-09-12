"""`10`'s paste ladder: the instrument that answers Q3.

The ladder is the one scripted step of the spike, and the only one that can be
exercised without a claude.ai account — it drives our own CLI, not Hermes. So it
is tested twice, the way `07` and `08` are: once against a scripted `helper` that
returns the refusals `08` can answer with, and once against a real headless
browser pasting tens of kilobytes into the checked-in composer fixture.

What is deliberately *not* here: any observation about claude.ai. `10`'s four
documents all say `**Spike run:** none.`, and nothing in this file writes to
`docs/`. Every test redirects `spike.NOTES` into `tmp_path`; the ladder writes
`paste-ladder.json` beside it and appends a Q3 note, both inside the repository
by default.
"""

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import ladder_cli
from dataporter.browser import launcher
from fake_pages import PageServer
from live_browser import live_browser, requires_a_browser, visit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "spikes"))

import paste_ladder  # noqa: E402
import spike  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

SPIKE_DIR = REPO / "docs" / "spike"
LADDER_WRITES = ("notes.jsonl", "paste-ladder.json")
"""The two files a ladder run creates, named so the test below can say which
absence it is asserting. `docs/spike/README.md` documents both as written by the
spike, not committed with it."""


@pytest.fixture
def notes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`spike.NOTES`, moved out of the repository."""
    path = tmp_path / "docs" / "spike" / "notes.jsonl"
    monkeypatch.setattr(spike, "NOTES", path)
    return path


# --------------------------------------------------------------------------- #
# The sample text
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("size", [500, 5_000, 20_000, 50_000])
def test_a_sample_never_exceeds_the_size_asked_for(size: int) -> None:
    assert len(paste_ladder.sample(size)) <= size


def test_a_sample_ends_on_a_real_character(size: int = 5_000) -> None:
    """`normalise` strips trailing whitespace, so a sample ending in a
    half-written blank line would measure the comparison, not the composer."""
    text = paste_ladder.sample(size)
    assert text.endswith("\n")
    assert text[:-1] == text[:-1].rstrip()


def test_a_sample_is_deterministic() -> None:
    assert paste_ladder.sample(9_000) == paste_ladder.sample(9_000)


def test_a_sample_is_our_own_text() -> None:
    """Nothing reaching `docs/spike/` should be something a person wrote."""
    text = paste_ladder.sample(3_000)
    assert "filler" in text
    assert "Block 1." in text


def test_a_sample_carries_the_shapes_the_ladder_is_about() -> None:
    """A leading space and a blank line between turns are the two things
    `normalise` and `blockText` disagree about."""
    text = paste_ladder.sample(3_000)
    assert "\n " in text
    assert "\n\n" in text


# --------------------------------------------------------------------------- #
# Reading a helper's answer
# --------------------------------------------------------------------------- #


def fake_command(tmp_path: Path, body: str) -> str:
    """An executable printing `body` on stdout, for `helper` to read."""
    script = tmp_path / "fake-helper"
    script.write_text(
        f'#!/bin/sh\ncat <<"EOF"\n{body}\nEOF\nexit ${{FAKE_RC:-0}}\n', encoding="utf-8"
    )
    script.chmod(0o755)
    return str(script)


def test_a_helper_answer_is_read_from_the_last_stdout_line(tmp_path: Path) -> None:
    """Hermes quotes chatter around the object; the object is the last line."""
    command = fake_command(tmp_path, 'noise\n{"ok": true, "composer_chars": 0}')
    assert paste_ladder.helper(command, tmp_path, "probe") == {
        "ok": True,
        "composer_chars": 0,
    }


def test_a_non_zero_exit_is_read_rather_than_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal is data the ladder wants to record."""
    command = fake_command(tmp_path, '{"ok": false, "error": "composer_not_empty"}')
    monkeypatch.setenv("FAKE_RC", "1")
    answer = paste_ladder.helper(command, tmp_path, "probe")
    assert answer["ok"] is False
    assert answer["error"] == "composer_not_empty"


def test_unparsable_output_becomes_an_empty_answer(tmp_path: Path) -> None:
    command = fake_command(tmp_path, "not json at all")
    assert paste_ladder.helper(command, tmp_path, "probe") == {"ok": True}


def test_a_json_scalar_is_not_mistaken_for_an_answer(tmp_path: Path) -> None:
    command = fake_command(tmp_path, "42")
    assert paste_ladder.helper(command, tmp_path, "probe") == {"ok": True}


# --------------------------------------------------------------------------- #
# One rung
# --------------------------------------------------------------------------- #


def scripted(
    monkeypatch: pytest.MonkeyPatch, probe: dict[str, Any], paste: dict[str, Any]
) -> list[str]:
    """Replace `helper` with canned answers; return the questions asked."""
    asked: list[str] = []

    def fake_helper(command: str, workspace: Path, *args: str) -> dict[str, Any]:  # noqa: ANN401
        return dict(probe) if args[0] == "probe" else dict(paste)

    monkeypatch.setattr(paste_ladder, "helper", fake_helper)
    monkeypatch.setattr(
        paste_ladder,
        "ask",
        lambda question, *, prompt: asked.append(question) or "unknown",
    )
    monkeypatch.setattr(paste_ladder, "pause", lambda message, *, prompt: None)
    return asked


EMPTY_COMPOSER = {"ok": True, "composer_present": True, "composer_chars": 0}


def test_a_round_with_no_composer_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = scripted(monkeypatch, {"ok": True, "composer_present": False}, {})
    row = paste_ladder.round_trip(
        "cli", tmp_path, write_seed(tmp_path), "insert_text", prompt=True
    )
    assert "skipped" in row
    assert "inserted" not in row
    assert asked == []


def test_a_verbatim_round_is_measured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = scripted(
        monkeypatch, EMPTY_COMPOSER, {"ok": True, "chars": 4_000, "elapsed_ms": 12}
    )
    row = paste_ladder.round_trip(
        "cli", tmp_path, write_seed(tmp_path), "insert_text", prompt=True
    )
    assert row["inserted"] is True
    assert row["verbatim"] is True
    assert row["paste_chars"] == 4_000
    assert len(asked) == 1


def test_a_text_mismatch_still_counts_as_an_insert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`paste` answering `text_mismatch` is the more interesting Q3 finding: the
    text reached the composer and came back changed."""
    asked = scripted(
        monkeypatch,
        EMPTY_COMPOSER,
        {"ok": False, "error": paste_ladder.TEXT_MISMATCH, "observed_chars": 3_999},
    )
    row = paste_ladder.round_trip(
        "cli", tmp_path, write_seed(tmp_path), "insert_text", prompt=True
    )
    assert row["inserted"] is True
    assert row["verbatim"] is False
    assert len(asked) == 1


@pytest.mark.parametrize(
    "error", ["composer_not_empty", "composer_missing", "no_claude_tab"]
)
def test_a_refused_round_is_not_an_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: str
) -> None:
    """`c7f8194`: asking a human whether a chip appeared for a round that never
    inserted anything files their guess as an observation."""
    asked = scripted(monkeypatch, EMPTY_COMPOSER, {"ok": False, "error": error})
    row = paste_ladder.round_trip(
        "cli", tmp_path, write_seed(tmp_path), "insert_text", prompt=True
    )
    assert row["inserted"] is False
    assert "chip" not in row
    assert asked == [], "a refused round must not be asked about"
    assert "*unknown*" in paste_ladder.table([row], "2026-09-11")
    assert "observed on" not in paste_ladder.table([row], "2026-09-11")


def write_seed(directory: Path, chars: int = 4_000) -> Path:
    seed = directory / "sample.txt"
    seed.write_text(paste_ladder.sample(chars), encoding="utf-8")
    return seed


# --------------------------------------------------------------------------- #
# The table
# --------------------------------------------------------------------------- #


def test_a_skipped_round_says_so_rather_than_no() -> None:
    """A bare `no` would read as "the composer mangled the seed"."""
    assert paste_ladder.verdict({"skipped": "no composer"}) == "skipped"


def test_a_refused_round_names_its_refusal() -> None:
    row = {"inserted": False, "error": "composer_not_empty"}
    assert paste_ladder.verdict(row) == "refused (composer_not_empty)"


def test_a_refusal_with_no_code_still_reads_as_a_refusal() -> None:
    assert paste_ladder.verdict({"inserted": False}) == "refused (unknown)"


@pytest.mark.parametrize(("verbatim", "expected"), [(True, "yes"), (False, "no")])
def test_an_inserted_round_reports_whether_it_survived(
    verbatim: bool, expected: str
) -> None:
    row = {"inserted": True, "verbatim": verbatim}
    assert paste_ladder.verdict(row) == expected


def test_only_an_inserted_row_is_marked_observed() -> None:
    """`tests/test_spike_docs.py` reads these marks: a row marked `observed` for
    a round that inserted nothing would tell it the spike had run."""
    rows = [
        {"chars": 5_000, "method": "insert_text", "inserted": True, "verbatim": True},
        {"chars": 5_000, "method": "exec_command", "inserted": False, "error": "x"},
    ]
    lines = paste_ladder.table(rows, "2026-09-11").splitlines()
    assert "*observed on 2026-09-11*" in lines[2]
    assert "*unknown*" in lines[3]


def test_an_empty_cell_is_a_dash() -> None:
    row = {"chars": 1_000, "method": "insert_text", "inserted": True, "verbatim": True}
    assert "| — |" in paste_ladder.table([row], "2026-09-11")


def test_the_rule_row_matches_the_column_count() -> None:
    rows = [{"chars": 1, "method": "insert_text", "inserted": True, "verbatim": True}]
    header, rule, body = paste_ladder.table(rows, "2026-09-11").splitlines()
    assert header.count("|") == rule.count("|") == body.count("|")


# --------------------------------------------------------------------------- #
# Against a real browser
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def live() -> Iterator[tuple[launcher.BrowserSession, PageServer]]:
    """One real browser and one fixture server for the whole module."""
    with live_browser() as pair:
        yield pair


def ladder_on_path(
    live: tuple[launcher.BrowserSession, PageServer],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One empty composer, and a `dataporter` that can reach it."""
    session, server = live
    visit(session, server.url("/new"))
    directory = tmp_path / "bin"
    ladder_cli.write_shim(
        directory, cdp_port=session.client.port, server_port=server.port
    )
    monkeypatch.setenv("PATH", ladder_cli.on_path(directory))


@requires_a_browser
@pytest.mark.parametrize("method", ["insert_text", "exec_command"])
def test_the_ladder_measures_a_real_composer(
    live: tuple[launcher.BrowserSession, PageServer],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    notes: Path,
    method: str,
) -> None:
    """The whole instrument, end to end: seed file, subprocess, CDP, composer,
    read-back, table. Only the host is not claude.ai."""
    ladder_on_path(live, tmp_path, monkeypatch)

    assert (
        paste_ladder.main(
            [
                "--workspace",
                str(tmp_path / "ws"),
                "--sizes",
                "5000",
                "--methods",
                method,
                "--no-prompt",
            ]
        )
        == 0
    )

    payload = json.loads((notes.parent / "paste-ladder.json").read_text("utf-8"))
    (row,) = payload["rows"]
    assert row["inserted"] is True
    assert row["verbatim"] is True, row.get("error")
    assert row["composer_chars_after"] == row["chars"]
    assert row["method"] == method
    assert "*observed on " in payload["table"]


@requires_a_browser
def test_without_a_human_only_the_first_round_is_measured(
    live: tuple[launcher.BrowserSession, PageServer],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    notes: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Nothing in `08` clears a composer, so unattended the second round meets
    the first round's text. The rows stay honest and the warning says so."""
    ladder_on_path(live, tmp_path, monkeypatch)

    assert (
        paste_ladder.main(
            [
                "--workspace",
                str(tmp_path / "ws"),
                "--sizes",
                "5000,20000",
                "--methods",
                "insert_text",
                "--no-prompt",
            ]
        )
        == 0
    )

    assert "--no-prompt measures only the first round" in capsys.readouterr().err
    first, second = json.loads((notes.parent / "paste-ladder.json").read_text("utf-8"))[
        "rows"
    ]
    assert first["inserted"] is True
    assert second["inserted"] is False
    assert second["error"] == "composer_not_empty"
    # Honest rather than useful: a refused round is never filed as an observation.
    assert paste_ladder.verdict(second) == "refused (composer_not_empty)"


@requires_a_browser
def test_the_ladder_writes_nothing_into_the_repository(
    live: tuple[launcher.BrowserSession, PageServer],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    notes: Path,
) -> None:
    """`spike.NOTES` points inside the repository. A run that forgot to redirect
    would commit a fabricated observation into `docs/spike/`."""
    ladder_on_path(live, tmp_path, monkeypatch)
    # Named rather than a whole-directory listing: an observation committed by an
    # earlier run would sit in `before` and the equality below would still pass.
    for name in LADDER_WRITES:
        assert not (SPIKE_DIR / name).exists(), f"{name} is committed"
    before = sorted(path.name for path in SPIKE_DIR.iterdir())

    paste_ladder.main(
        [
            "--workspace",
            str(tmp_path / "ws"),
            "--sizes",
            "5000",
            "--methods",
            "insert_text",
            "--no-prompt",
        ]
    )

    assert sorted(path.name for path in SPIKE_DIR.iterdir()) == before
    assert notes.is_file(), "the note went to the redirected file instead"
