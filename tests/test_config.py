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
