"""The packaged skill: what it says, and installing it into the profile.

`09` built the installing half against a placeholder body. `11` wrote the body,
so the first section now also checks the document itself — that it has the
sections the spec names, the five §17 rules, the error words `08` actually
prints, and result examples our own runner would accept.

The procedure's *steps* are checked in `test_steps.py`, against the spec's table,
and the procedure's *behaviour* in `test_skill_dry_run.py`, by performing it.
"""

import json
import re
from pathlib import Path

import pytest

from dataporter import PROGRAM_NAME
from dataporter.browser import helpers
from dataporter.config import HermesSettings, Settings
from dataporter.errors import Category, HermesUsageError
from dataporter.hermes import runner
from dataporter.hermes import skill as skilling
from dataporter.hermes.runner import HermesResult

FRONTMATTER_KEYS = ("name", "description", "version", "platforms", "metadata")
"""Every top-level key `11` fixes in the skill's frontmatter."""

SKILL_TEXT = (skilling.packaged_dir() / skilling.SKILL_FILENAME).read_text(encoding="utf-8")

SECTIONS = (
    "When to use",
    "Inputs",
    "Procedure",
    "Verification",
    "Rules",
    "Recovery",
    "Result",
)
"""The body sections `11` specifies, in the order it lists them."""

SAFETY_CLAUSES = (
    "No other page, no settings, no billing, no other chats.",
    "Never delete, archive, star, share or rename anything except",
    "Never enter text into the composer except through the helper.",
    "`needs_human` with reason `confirmation_required`",
    "password, a code, a CAPTCHA or a security challenge",
)
"""One clause per §17 rule. Clauses rather than whole rules: the skill wraps its
prose and the spec wraps it differently, and a line break is not a rule."""

HELPER_ERRORS = (
    helpers.NO_CLAUDE_TAB,
    helpers.AMBIGUOUS_TAB,
    helpers.UNKNOWN_TARGET,
    helpers.OUTSIDE_MIGRATION_SURFACE,
    helpers.COMPOSER_MISSING,
    helpers.COMPOSER_NOT_EMPTY,
    helpers.TEXT_MISMATCH,
    helpers.SEED_NOT_FOUND,
    helpers.SEED_UNREADABLE,
    helpers.FILE_NOT_FOUND,
    helpers.INPUT_NOT_FOUND,
    helpers.UPLOAD_REJECTED,
    helpers.CHIP_NOT_FOUND,
    helpers.RESPONSE_TIMEOUT,
)
"""Every `error` string `08` can print. Read from the module, so renaming one
there fails here until the skill is corrected."""

OUTCOMES = ("completed", "partial", "failed", "needs_human", "rate_limited")

JSON_BLOCK = re.compile(r"```json\n(.*?)\n```", re.DOTALL)

CATEGORY_LINE = re.compile(r"`error\.category` is one of (.*?)\. Pick", re.DOTALL)
"""The sentence that lists the taxonomy, so the test reads what the skill offers
rather than searching the whole document for words like `ui`."""


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        workspace=tmp_path / "migration",
        hermes=HermesSettings(home=tmp_path / "hermes-home"),
    )


# --------------------------------------------------------------------------- #
# The file we ship
# --------------------------------------------------------------------------- #


def test_the_packaged_skill_is_in_the_install() -> None:
    """It has to be inside the package, or a wheel would not carry it."""
    path = skilling.packaged_dir() / skilling.SKILL_FILENAME
    assert path.is_file()
    assert skilling.packaged_dir().name == skilling.SKILL_NAME


def test_the_packaged_skill_identifies_itself_as_11_specifies() -> None:
    text = (skilling.packaged_dir() / skilling.SKILL_FILENAME).read_text(encoding="utf-8")
    fields = skilling.frontmatter(text)
    assert fields["name"] == skilling.SKILL_NAME
    assert fields["version"] == "0.1.0"
    for key in FRONTMATTER_KEYS:
        assert key in fields, f"{key} is missing from the skill frontmatter"


def test_the_helper_prefix_is_the_program_name() -> None:
    """The `helper` row is a literal the agent is told to use verbatim.

    It is the one copy of the command name that `PROGRAM_NAME` does not produce. ADR
    0004's rename is what made that worth a test: a skill still spelling the old command
    fails at run time, in the agent, and nowhere in the suite.
    """
    assert f"`{PROGRAM_NAME} --workspace <workspace> browser …`. Use it verbatim" in SKILL_TEXT
    assert "hermes-claude-migrate" not in SKILL_TEXT


def test_the_body_is_a_procedure_and_no_longer_a_placeholder() -> None:
    """`09` shipped a file that refused to act. `11` is what replaced it."""
    assert "not finished" not in SKILL_TEXT
    assert "placeholder" not in SKILL_TEXT
    assert "Filled in by" not in SKILL_TEXT


def test_it_has_every_section_11_names() -> None:
    for heading in SECTIONS:
        assert f"\n## {heading}\n" in SKILL_TEXT, f"no {heading} section"


def test_the_safety_rules_are_all_there() -> None:
    """§17, as five rules an agent can check itself against."""
    for clause in SAFETY_CLAUSES:
        assert clause in SKILL_TEXT, f"missing safety rule: {clause}"


def test_it_names_every_error_a_helper_can_answer_with() -> None:
    """`08` decides this vocabulary; the skill branches on it.

    One list, or the skill teaches Hermes to recognise a word no helper prints.
    """
    for error in HELPER_ERRORS:
        assert error in SKILL_TEXT, f"the skill does not mention {error}"


def test_it_never_tells_an_agent_to_read_a_seed() -> None:
    """The one instruction that would put conversation text in a transcript."""
    assert "A seed must never pass through your output tokens." in SKILL_TEXT
    assert "Read only by the helper, never by you." in SKILL_TEXT


def test_every_result_example_validates_against_09s_contract() -> None:
    """The examples are what an agent copies.

    One that our own runner would reject is worse than no example at all.
    """
    examples = [HermesResult.model_validate(json.loads(block)) for block in JSON_BLOCK.findall(SKILL_TEXT)]
    assert {item.outcome for item in examples} == set(OUTCOMES)
    for item in examples:
        assert item.step is not None, f"{item.last_step} is not a step name"


def test_the_needs_human_reasons_are_the_ones_14_will_branch_on() -> None:
    for reason in runner.NEEDS_HUMAN_REASONS:
        assert reason in SKILL_TEXT, f"the skill does not mention {reason}"


def test_it_offers_every_error_category_and_invents_none() -> None:
    """`01` fixed the taxonomy.

    A category the skill made up would reach `state.json` through `09`'s contract and
    fail validation there.
    """
    offered = CATEGORY_LINE.search(SKILL_TEXT)
    assert offered is not None
    assert set(re.findall(r"`([a-z_]+)`", offered.group(1))) == {str(item) for item in Category}


# --------------------------------------------------------------------------- #
# Reading frontmatter
# --------------------------------------------------------------------------- #


def test_nested_keys_are_skipped_not_flattened() -> None:
    text = "---\nname: x\nmetadata:\n  hermes:\n    category: dataporter\n---\nbody\n"
    assert skilling.frontmatter(text) == {"name": "x", "metadata": ""}


def test_quotes_are_stripped() -> None:
    assert skilling.frontmatter('---\nname: "x"\n---\n')["name"] == "x"


def test_a_file_with_no_frontmatter_has_none() -> None:
    assert skilling.frontmatter("# just a document\n") == {}
    assert skilling.frontmatter("") == {}


# --------------------------------------------------------------------------- #
# Installing
# --------------------------------------------------------------------------- #


def test_install_puts_it_where_09_says(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    meta = skilling.install(settings)
    target = skilling.install_dir(settings)

    assert target == (tmp_path / "hermes-home" / "profiles" / "dataporter" / "skills" / "dataporter" / "claude-migrate")
    assert (target / skilling.SKILL_FILENAME).is_file()
    assert str(meta) == "claude-migrate 0.1.0"
    assert skilling.installed(settings) == meta


def test_install_is_idempotent_and_overwrites(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    skilling.install(settings)
    installed = skilling.install_dir(settings) / skilling.SKILL_FILENAME
    installed.write_text("---\nname: stale\nversion: 0.0.1\n---\n", encoding="utf-8")

    assert skilling.install(settings) == skilling.SkillMeta("claude-migrate", "0.1.0")
    assert "stale" not in installed.read_text(encoding="utf-8")


def test_a_sibling_file_in_the_profile_is_left_alone(tmp_path: Path) -> None:
    """The directory is inside the operator's home; `setup` does not clear it."""
    settings = make_settings(tmp_path)
    skilling.install(settings)
    theirs = skilling.install_dir(settings) / "notes.md"
    theirs.write_text("mine", encoding="utf-8")
    skilling.install(settings)
    assert theirs.read_text(encoding="utf-8") == "mine"


def test_nothing_installed_reads_as_nothing(tmp_path: Path) -> None:
    assert skilling.installed(make_settings(tmp_path)) is None


def test_a_skill_with_no_version_does_not_count_as_installed(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    target = skilling.install_dir(settings)
    target.mkdir(parents=True)
    (target / skilling.SKILL_FILENAME).write_text("---\nname: x\n---\n", encoding="utf-8")
    assert skilling.installed(settings) is None


def test_an_install_that_cannot_be_written_says_where(tmp_path: Path) -> None:
    blocker = tmp_path / "hermes-home"
    blocker.write_text("not a directory", encoding="utf-8")
    with pytest.raises(HermesUsageError, match="cannot install the skill"):
        skilling.install(make_settings(tmp_path))


def test_the_profile_directory_is_where_transcripts_live(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    assert skilling.profile_dir(settings) == (tmp_path / "hermes-home" / "profiles" / "dataporter")


def test_the_sign_in_task_is_scoped_and_rule_5_is_intact() -> None:
    """`24`: one paragraph admits `/login` for one task; the blanket rule stays."""
    assert "a **sign-in** task asks you to bring the tab to" in SKILL_TEXT
    assert "rule 1 admits `/login`" in SKILL_TEXT
    assert "you hold no credentials and must not ask for any" in SKILL_TEXT
    assert (
        "If a page asks for a password, a code, a CAPTCHA or a security challenge, do\n"
        "   not attempt it; return `needs_human` with the matching reason."
    ) in SKILL_TEXT
    assert '"outcome": "form_ready"' in SKILL_TEXT
