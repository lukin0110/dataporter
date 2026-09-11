"""The task prompt: what it says, and what it must never say.

Two things are being tested. That a prompt carries everything the skill's
procedure asks for — the ack lines exactly as the seed ends with them, one path
per part, where to resume — and that it carries no conversation text, which is
the §10 rule the whole design of "the prompt names files" exists to keep.

The second is checked by grepping the rendered prompt for a phrase that appears
only in the fixture export. It is a cheap test and it would catch the expensive
mistake: a future convenience that inlines "just the first part" into the prompt
puts conversation text into a Hermes transcript and into an agent's context.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from conftest import LONG_CONVERSATION as LONG
from dataporter import PROGRAM_NAME
from dataporter import seed as seeding
from dataporter.hermes import prompt as prompting
from dataporter.steps import Step

FIXTURE_PHRASE = "materialised views"
"""A phrase that occurs in the fixture's messages and nowhere else."""

CHAT_ID = "b6f0a2d4-1c88-4e3a-9a1f-2f0e5d7c8b91"


@pytest.fixture
def rendered(two_part_seed: seeding.Seed, tmp_path: Path) -> str:
    """`12`'s call: a seed, written out, and the prompt that points at it."""
    files = seeding.write_seed(two_part_seed, tmp_path / "seeds")
    return prompting.for_seed(two_part_seed, seed_files=files, workspace=tmp_path)


# --------------------------------------------------------------------------- #
# Acceptance: what a two-part prompt contains
# --------------------------------------------------------------------------- #


def test_it_names_both_acknowledgements_and_both_seed_files(
    rendered: str, two_part_seed: seeding.Seed, tmp_path: Path
) -> None:
    assert len(two_part_seed.chunks) == 2
    for index, chunk in enumerate(two_part_seed.chunks, start=1):
        assert chunk.ack in rendered
        assert str(tmp_path / "seeds" / LONG / f"part-{index:02d}.txt") in rendered
    assert "parts: 2" in rendered


def test_it_contains_no_seed_text(rendered: str, two_part_seed: seeding.Seed) -> None:
    """The §10 rule, checked against a phrase only the fixture has."""
    assert FIXTURE_PHRASE in two_part_seed.chunks[0].text
    assert FIXTURE_PHRASE not in rendered
    assert "Postgres" not in rendered  # the fixture's title


def test_it_names_the_skill_and_the_helper(rendered: str, tmp_path: Path) -> None:
    assert "claude-migrate" in rendered
    assert f"helper: {PROGRAM_NAME} --workspace {tmp_path} browser" in rendered


def test_a_first_attempt_starts_at_open_with_no_chat(rendered: str) -> None:
    assert "resume_from: open" in rendered
    assert "existing conversation_id: none" in rendered
    assert "parts already acknowledged: 0" in rendered
    assert "attachments: none" in rendered


# --------------------------------------------------------------------------- #
# The fields, one at a time
# --------------------------------------------------------------------------- #


def render_one(
    *,
    short_id: str = "ab12cd34",
    parts: int = 1,
    seed_files: Sequence[Path] = (Path("/w/seeds/one/part-01.txt"),),
    acknowledgements: Sequence[str] = ("MIGRATION-ACK ab12cd34 1/1",),
    **rest: Any,
) -> str:
    """A one-part prompt, with whatever field the test is about replaced."""
    return prompting.render(
        short_id=short_id,
        parts=parts,
        seed_files=seed_files,
        acknowledgements=acknowledgements,
        workspace=rest.pop("workspace", Path("/w")),
        **rest,
    )


def test_a_retry_names_the_step_and_the_chat_to_continue() -> None:
    text = render_one(
        parts=2,
        seed_files=(Path("/w/a"), Path("/w/b")),
        acknowledgements=("ACK 1/2", "ACK 2/2"),
        resume_from=Step.PASTE,
        conversation_id=CHAT_ID,
        acknowledged=1,
    )
    assert "resume_from: paste" in text
    assert f"existing conversation_id: {CHAT_ID}" in text
    assert "parts already acknowledged: 1" in text


def test_acknowledged_parts_need_a_chat_to_have_been_acknowledged_in() -> None:
    """`12` would be telling Hermes to skip parts of a chat that does not exist."""
    with pytest.raises(prompting.PromptError):
        render_one(acknowledged=1)


def test_more_acknowledged_parts_than_parts_is_refused() -> None:
    with pytest.raises(prompting.PromptError):
        render_one(acknowledged=2, conversation_id=CHAT_ID)


def test_attachments_are_listed_one_per_line() -> None:
    text = render_one(attachments=[Path("/w/attachments/a.pdf"), Path("/w/b.png")])
    assert "attachments:\n/w/attachments/a.pdf\n/w/b.png\n" in text


def test_a_workspace_with_a_space_survives_as_one_argument() -> None:
    text = render_one(workspace=Path("/tmp/my workspace"))
    assert "--workspace '/tmp/my workspace' browser" in text


def test_a_field_cannot_forge_a_line() -> None:
    """Ids are export-derived. One with a newline in it would add a field."""
    text = render_one(short_id="ab12cd34\nparts: 99")
    assert "parts: 99" not in text.splitlines()
    assert "short_id: ab12cd34?parts: 99" in text.splitlines()


@pytest.mark.parametrize(
    "overrides",
    [
        {"parts": 0, "seed_files": (), "acknowledgements": ()},
        {"parts": 2},
        {"acknowledgements": ("one", "two")},
    ],
    ids=["no parts", "fewer seed files than parts", "more acks than parts"],
)
def test_a_prompt_that_does_not_add_up_is_refused(overrides: dict[str, Any]) -> None:
    """`12` would otherwise have Hermes wait for an ack that is never coming."""
    with pytest.raises(prompting.PromptError):
        render_one(**overrides)


def test_the_helper_prefix_is_the_one_doctor_proved(tmp_path: Path) -> None:
    """`09`'s `doctor` runs `<program> --workspace <ws> browser probe`; a prompt
    that spelled the prefix differently would be sending Hermes at a command
    nothing has ever checked."""
    assert prompting.helper_command(tmp_path).startswith(
        f"{PROGRAM_NAME} --workspace {tmp_path} browser"
    )
