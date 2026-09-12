"""The pilot selection: which ten conversations, and why each one.

`20`'s first acceptance criterion is this module's subject — `--pilot` on the
fixture chooses the expected short ids for categories 1–5 and 7–9, the fixture
having neither a class 2 attachment nor a tenth distinct conversation — and it is
a unit test because the selection is a pure function of an export and a plan.

Two settings are exercised rather than one. At the default `seed.max_chars`
nothing in the fixture needs a second part, so category 3 chooses nothing and
category 2 takes the longest conversation there is; at 4 000 characters — the
same number `04`'s two-part golden files use — the long conversation splits and
the two categories separate. Both are properties of the selection rule, and a
test at one setting alone would pin only half of it.
"""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dataporter import cli, pilot, state
from dataporter.config import SeedSettings, Settings
from dataporter.exit_codes import ExitCode
from dataporter.export import load_export
from dataporter.plan import build_plan
from dataporter.state import PilotChoice, Status
from world import World, cli_env

FIRST = "aa000001-1111-4111-8111-111111111111"
LONG = "bb000002-2222-4222-8222-222222222222"
CODE = "cc000003-3333-4333-8333-333333333333"
ATTACHED = "dd000004-4444-4444-8444-444444444444"
BRANCHED = "ee000005-5555-4555-8555-555555555555"
EMPTY = "ff000006-6666-4666-8666-666666666666"


def choices(export_dir: Path, *, max_chars: int = 50_000) -> dict[int, str | None]:
    """`{category number: the uuid it chose}` for the fixture export."""
    export = load_export(export_dir)
    settings = Settings(
        workspace=Path("/nowhere"), seed=SeedSettings(max_chars=max_chars)
    )
    return {
        record.category: record.uuid
        for record in pilot.choose(export, build_plan(export, settings))
    }


# --------------------------------------------------------------------------- #
# Acceptance: the categories, on the fixture
# --------------------------------------------------------------------------- #


def test_every_category_chooses_what_20_says_it_should(export_dir: Path) -> None:
    """The acceptance criterion, at the seed size that separates 2 from 3.

    Category 6 chooses nothing because the fixture's one class 1 conversation is
    already category 5's and it has no class 2 at all, and category 10 chooses
    nothing because the five migratable conversations are all spoken for — which
    is what `20` means by "the fixture lacks class 2 and a tenth distinct
    conversation".
    """
    assert choices(export_dir, max_chars=4_000) == {
        1: FIRST,
        2: ATTACHED,
        3: LONG,
        4: CODE,
        5: ATTACHED,
        6: None,
        7: LONG,
        8: BRANCHED,
        9: CODE,
        10: None,
    }


def test_at_the_default_seed_size_nothing_needs_two_parts(export_dir: Path) -> None:
    """So category 3 has nothing to choose and category 2 takes the longest
    conversation in the export rather than the longest short one."""
    found = choices(export_dir)
    assert found[2] == LONG
    assert found[3] is None


def test_the_unmigratable_conversation_is_never_chosen(export_dir: Path) -> None:
    """`ff000006` has no messages. A pilot measures what the tool does to
    conversations it can do something with."""
    assert EMPTY not in set(choices(export_dir).values())


# --------------------------------------------------------------------------- #
# The rules each category follows
# --------------------------------------------------------------------------- #


PLAIN = pilot.Candidate(
    uuid="",
    position=0,
    messages=2,
    off_path=0,
    seed_chars=100,
    parts=1,
    inline_attachments=0,
    upload_attachments=0,
    code_in_both_roles=False,
    has_artifact=False,
    recency=(0.0, 0.0),
)
"""A conversation no category is looking for: two messages, one part, no files,
no code, no artifact, no branch. Every candidate below is this one with the one
property its category asks about turned on."""


def candidate(uuid: str, **fields: Any) -> pilot.Candidate:
    return replace(PLAIN, uuid=uuid, **fields)


def picks(found: list[pilot.Candidate]) -> dict[int, str | None]:
    chosen: list[str] = []
    out: dict[int, str | None] = {}
    for category in pilot.CATEGORIES:
        picked = category.choose(found, chosen)
        out[category.number] = picked.uuid if picked is not None else None
        if picked is not None and picked.uuid not in chosen:
            chosen.append(picked.uuid)
    return out


def test_a_one_message_conversation_is_too_short_to_be_the_shortest() -> None:
    """§20 writes "fewest active-path messages, ≥ 2": a question nobody answered
    says nothing about whether a history was understood."""
    found = [
        candidate("one", position=0, messages=1),
        candidate("two", position=1, messages=3),
    ]
    assert picks(found)[1] == "two"


def test_ties_are_broken_by_export_order() -> None:
    """Two equally short conversations choose the same way on every run."""
    found = [
        candidate("first", position=0, messages=2),
        candidate("second", position=1, messages=2),
    ]
    assert picks(found)[1] == "first"


def test_the_second_attachment_category_wants_a_class_2_first() -> None:
    found = [
        candidate("inline", position=0, inline_attachments=1),
        candidate("upload", position=1, upload_attachments=1),
    ]
    picked = picks(found)
    assert picked[5] == "inline"
    assert picked[6] == "upload"


def test_with_no_class_2_it_falls_back_to_another_class_1() -> None:
    """ "Another": the point of the category is a second attachment
    conversation, and naming category 5's again would put nothing in the pilot."""
    found = [
        candidate("inline", position=0, inline_attachments=1),
        candidate("also-inline", position=1, inline_attachments=2),
    ]
    assert picks(found)[6] == "also-inline"


def test_a_category_names_a_conversation_an_earlier_one_already_took() -> None:
    """Eight of the ten answer for themselves. One conversation that is both the
    longest and the one with ten turns is a fact a write-up needs."""
    found = [candidate("both", messages=12, seed_chars=5_000)]
    picked = picks(found)
    assert picked[2] == "both"
    assert picked[7] == "both"


def test_the_newest_category_skips_what_is_already_chosen() -> None:
    """It exists to fill the tenth slot, and a duplicate fills nothing."""
    found = [
        candidate("old", position=0, messages=12, recency=(1.0, 1.0)),
        candidate("new", position=1, messages=1, recency=(9.0, 9.0)),
    ]
    assert picks(found)[10] == "new"


def test_the_newest_category_is_empty_when_everything_is_taken() -> None:
    assert picks([candidate("only")])[10] is None


def test_the_run_set_is_each_conversation_once_in_category_order() -> None:
    records = [
        PilotChoice(category=1, name="shortest", uuid="b"),
        PilotChoice(category=2, name="longest-one-part", uuid="a"),
        PilotChoice(category=3, name="longest-multi-part", uuid=None),
        PilotChoice(category=4, name="code-both-roles", uuid="b"),
    ]
    assert pilot.uuids(records) == ["b", "a"]


def test_an_export_with_nothing_migratable_chooses_nothing(export_dir: Path) -> None:
    export = load_export(export_dir)
    empty = export.model_copy(update={"conversations": []})
    settings = Settings(workspace=Path("/nowhere"))
    records = pilot.choose(empty, build_plan(empty, settings))
    assert [record.uuid for record in records] == [None] * len(pilot.CATEGORIES)
    assert pilot.uuids(records) == []


# --------------------------------------------------------------------------- #
# What it prints
# --------------------------------------------------------------------------- #


def test_the_block_is_a_line_per_category_aligned_on_the_widest_name() -> None:
    records = [
        PilotChoice(category=1, name="shortest", uuid=FIRST),
        PilotChoice(category=10, name="newest", uuid=None),
    ]
    assert pilot.block(records) == (
        "Pilot selection:\n 1  shortest  aa000001\n10  newest    -\n"
    )


def test_the_block_carries_no_title(export_dir: Path, workspace: Path) -> None:
    """§10: a short id identifies a conversation on stdout; a name never does."""
    export = load_export(export_dir)
    settings = Settings(workspace=workspace)
    text = pilot.block(pilot.choose(export, build_plan(export, settings)))
    for title in ("Listing files", "Postgres questions", "Q3 report"):
        assert title not in text


# --------------------------------------------------------------------------- #
# Through the command
# --------------------------------------------------------------------------- #


def test_a_dry_run_prints_the_selection_and_then_the_block(
    runner: CliRunner, workspace: Path, export_dir: Path
) -> None:
    """The whole pilot selection, with no account touched and no workspace
    written: §9's promise holds under `--pilot` like any other dry run."""
    result = runner.invoke(
        cli.app,
        ["import", str(export_dir), "--dry-run", "--pilot"],
        catch_exceptions=False,
    )

    assert result.exit_code == ExitCode.OK
    assert result.stdout.startswith("Pilot selection:\n 1  shortest")
    assert "Conversations found:      5" in result.stdout
    assert not (workspace / "migration").exists()


@pytest.mark.parametrize("flag", [["--only", FIRST], ["--limit", "2"], ["--all"]])
def test_a_selection_flag_beside_pilot_is_a_usage_error(
    runner: CliRunner, workspace: Path, export_dir: Path, flag: list[str]
) -> None:
    """A flag that chooses cannot lose silently to another flag that chooses."""
    result = runner.invoke(
        cli.app,
        ["import", str(export_dir), "--dry-run", "--pilot", *flag],
        catch_exceptions=False,
    )

    assert result.exit_code == ExitCode.USAGE
    assert result.stderr == f"error: {pilot.PILOT_CHOOSES}\n"


def test_a_pilot_of_an_export_with_nothing_migratable_exits_4(
    runner: CliRunner, workspace: Path, tmp_path: Path
) -> None:
    empty = tmp_path / "export-empty"
    empty.mkdir()
    (empty / "conversations.json").write_text("[]", encoding="utf-8")

    result = runner.invoke(
        cli.app,
        ["import", str(empty), "--dry-run", "--pilot"],
        catch_exceptions=False,
    )

    assert result.exit_code == ExitCode.NOTHING_TO_DO
    assert result.stdout.startswith("Pilot selection:\n")


def test_the_choices_round_trip_through_run_json(workspace: Path) -> None:
    """`run.json.selection.pilot` is where the reasons outlive the run."""
    store = state.StateStore(workspace)
    store.bind_export("fingerprint", workspace)
    selection = state.Selection(
        only=[FIRST],
        pilot=[PilotChoice(category=1, name="shortest", uuid=FIRST)],
    )

    store.start_run(selection)

    recorded = state.StateStore(workspace).run().runs[0].selection
    assert recorded.pilot == [PilotChoice(category=1, name="shortest", uuid=FIRST)]


# --------------------------------------------------------------------------- #
# The whole run, once
# --------------------------------------------------------------------------- #


def test_a_pilot_run_migrates_its_selection_and_records_why(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--pilot` end to end: the block, the five fixture conversations, and the
    categories that chose them, kept in `run.json` for the write-up to cite."""
    cli_env(world, monkeypatch)

    outcome = runner.invoke(
        cli.app, ["import", str(world.export), "--pilot"], catch_exceptions=False
    )

    assert outcome.exit_code == ExitCode.OK
    assert outcome.stdout.startswith("Pilot selection:\n")
    recorded = world.store().run().runs[0].selection
    assert recorded.limit == pilot.PILOT_LIMIT
    assert {record.category: record.uuid for record in recorded.pilot}[1] == FIRST
    # In export order by the time it is a selection, whatever order the
    # categories chose in: `state.select` is what puts it back.
    assert recorded.uuids == [FIRST, LONG, CODE, ATTACHED, BRANCHED]
    assert world.entry(FIRST).status is Status.COMPLETED
