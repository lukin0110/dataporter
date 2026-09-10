"""Configuration precedence: CLI flag > environment > config.toml > defaults."""

from pathlib import Path

import pytest
from pydantic import BaseModel

from dataporter.config import (
    DEFAULT_WORKSPACE,
    ConfigError,
    Settings,
    config_file_for,
    load_settings,
)


def write_config(directory: Path, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "config.toml"
    path.write_text(body)
    return path


def test_default_is_migration_beside_the_cwd(workspace: Path) -> None:
    settings = load_settings()
    assert settings.workspace == workspace / DEFAULT_WORKSPACE


def test_environment_sets_the_workspace(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HCM_WORKSPACE", "/tmp/x")
    assert load_settings().workspace == Path("/tmp/x")


def test_flag_beats_the_environment(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HCM_WORKSPACE", "/tmp/x")
    assert load_settings(workspace=Path("/tmp/y")).workspace == Path("/tmp/y")


def test_config_file_loses_to_both(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(workspace / DEFAULT_WORKSPACE, 'workspace = "/tmp/z"\n')

    # ...to the environment,
    monkeypatch.setenv("HCM_WORKSPACE", "/tmp/x")
    assert load_settings().workspace == Path("/tmp/x")

    # ...and to the flag.
    assert load_settings(workspace=Path("/tmp/y")).workspace == Path("/tmp/y")


def test_config_file_beats_the_default(workspace: Path) -> None:
    write_config(workspace / DEFAULT_WORKSPACE, 'workspace = "/tmp/z"\n')
    assert load_settings().workspace == Path("/tmp/z")


def test_config_is_read_from_the_bootstrap_workspace(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `workspace` key in config.toml sets the workspace but does not relocate
    config discovery — otherwise resolution would be a fixed-point iteration."""
    elsewhere = workspace / "elsewhere"
    write_config(elsewhere, 'workspace = "/tmp/z"\n')
    monkeypatch.setenv("HCM_WORKSPACE", str(elsewhere))

    assert config_file_for() == elsewhere / "config.toml"
    # The environment wins over the file's own workspace key.
    assert load_settings().workspace == elsewhere


def test_empty_environment_value_is_ignored(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`HCM_WORKSPACE=` in a shell script means unset, not "the current directory"."""
    monkeypatch.setenv("HCM_WORKSPACE", "")
    assert load_settings().workspace == workspace / DEFAULT_WORKSPACE


def test_workspace_is_absolute(workspace: Path) -> None:
    """`09` runs Hermes with cwd=<workspace>, so this cannot stay relative."""
    assert load_settings(workspace=Path("relative")).workspace.is_absolute()


def test_malformed_config_is_a_configuration_error(workspace: Path) -> None:
    write_config(workspace / DEFAULT_WORKSPACE, "workspace = [unclosed\n")
    with pytest.raises(ConfigError) as excinfo:
        load_settings()
    assert "invalid config file" in str(excinfo.value)


def test_unknown_key_is_a_configuration_error(workspace: Path) -> None:
    write_config(workspace / DEFAULT_WORKSPACE, 'wrokspace = "/tmp/z"\n')
    with pytest.raises(ConfigError) as excinfo:
        load_settings()
    assert "invalid configuration" in str(excinfo.value)


def test_missing_config_file_is_not_an_error(workspace: Path) -> None:
    assert not config_file_for().exists()
    assert load_settings().workspace == workspace / DEFAULT_WORKSPACE


class Pacing(BaseModel):
    delay_between_conversations_s: int = 20


class NestedSettings(Settings):
    """Later slices add nested sections; the mechanism has to carry them already."""

    pacing: Pacing = Pacing()


def test_nested_sections_follow_the_same_ladder(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(
        workspace / DEFAULT_WORKSPACE,
        "[pacing]\ndelay_between_conversations_s = 5\n",
    )
    from dataporter import config

    token = config._config_file.set(config.config_file_for())
    try:
        assert NestedSettings().pacing.delay_between_conversations_s == 5
        monkeypatch.setenv("HCM_PACING__DELAY_BETWEEN_CONVERSATIONS_S", "7")
        assert NestedSettings().pacing.delay_between_conversations_s == 7
        override = NestedSettings(pacing={"delay_between_conversations_s": 9})
        assert override.pacing.delay_between_conversations_s == 9
    finally:
        config._config_file.reset(token)


# --------------------------------------------------------------------------- #
# The sections `03` added
# --------------------------------------------------------------------------- #


def test_seed_and_attachment_defaults_are_the_spec_values(workspace: Path) -> None:
    settings = load_settings()
    assert settings.seed.max_chars == 50_000
    assert settings.seed.hard_max_chars == 400_000
    assert settings.attachments.max_bytes == 30_000_000
    assert settings.attachments.max_per_chat == 20
    assert "pdf" in settings.attachments.accepted_types
    assert "exe" not in settings.attachments.accepted_types


def test_a_real_section_takes_an_environment_override(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mechanism `01` built, on the first sections to actually use it."""
    monkeypatch.setenv("HCM_SEED__MAX_CHARS", "1234")
    assert load_settings().seed.max_chars == 1234


def test_a_real_section_is_read_from_the_config_file(workspace: Path) -> None:
    write_config(
        workspace / DEFAULT_WORKSPACE,
        "[attachments]\nmax_per_chat = 3\n",
    )
    assert load_settings().attachments.max_per_chat == 3


def test_the_attachments_directory_defaults_to_the_workspace(workspace: Path) -> None:
    settings = load_settings()
    assert settings.attachments_dir == settings.workspace / "attachments"


def test_an_explicit_attachments_directory_wins_and_is_absolute(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HCM_ATTACHMENTS__DIR", "elsewhere")
    assert load_settings().attachments_dir == workspace / "elsewhere"


def test_accepted_types_are_normalised(workspace: Path) -> None:
    """`03` matches a casefolded suffix, so `.PDF` in a config must still match."""
    write_config(
        workspace / DEFAULT_WORKSPACE,
        '[attachments]\naccepted_types = [".PDF", "Png"]\n',
    )
    assert load_settings().attachments.accepted_types == ("pdf", "png")
