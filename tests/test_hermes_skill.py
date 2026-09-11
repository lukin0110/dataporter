"""The packaged skill, and installing it into the profile."""

from pathlib import Path

import pytest

from dataporter.config import HermesSettings, Settings
from dataporter.errors import HermesUsageError
from dataporter.hermes import skill as skilling

FRONTMATTER_KEYS = ("name", "description", "version", "platforms", "metadata")
"""Every top-level key `11` fixes in the skill's frontmatter."""


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
    text = (skilling.packaged_dir() / skilling.SKILL_FILENAME).read_text(
        encoding="utf-8"
    )
    fields = skilling.frontmatter(text)
    assert fields["name"] == skilling.SKILL_NAME
    assert fields["version"] == "0.1.0"
    for key in FRONTMATTER_KEYS:
        assert key in fields, f"{key} is missing from the skill frontmatter"


def test_the_placeholder_body_says_it_is_one() -> None:
    """`11` writes the procedure. Until then the file must not look finished."""
    text = (skilling.packaged_dir() / skilling.SKILL_FILENAME).read_text(
        encoding="utf-8"
    )
    assert "not finished" in text
    assert "11" in text


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

    assert target == (
        tmp_path
        / "hermes-home"
        / "profiles"
        / "dataporter"
        / "skills"
        / "dataporter"
        / "claude-migrate"
    )
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
    (target / skilling.SKILL_FILENAME).write_text(
        "---\nname: x\n---\n", encoding="utf-8"
    )
    assert skilling.installed(settings) is None


def test_an_install_that_cannot_be_written_says_where(tmp_path: Path) -> None:
    blocker = tmp_path / "hermes-home"
    blocker.write_text("not a directory", encoding="utf-8")
    with pytest.raises(HermesUsageError, match="cannot install the skill"):
        skilling.install(make_settings(tmp_path))


def test_the_profile_directory_is_where_transcripts_live(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    assert skilling.profile_dir(settings) == (
        tmp_path / "hermes-home" / "profiles" / "dataporter"
    )
