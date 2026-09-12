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
    monkeypatch.setenv("DATAPORTER_WORKSPACE", "/tmp/x")
    assert load_settings().workspace == Path("/tmp/x")


def test_flag_beats_the_environment(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATAPORTER_WORKSPACE", "/tmp/x")
    assert load_settings(workspace=Path("/tmp/y")).workspace == Path("/tmp/y")


def test_config_file_loses_to_both(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(workspace / DEFAULT_WORKSPACE, 'workspace = "/tmp/z"\n')

    # ...to the environment,
    monkeypatch.setenv("DATAPORTER_WORKSPACE", "/tmp/x")
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
    monkeypatch.setenv("DATAPORTER_WORKSPACE", str(elsewhere))

    assert config_file_for() == elsewhere / "config.toml"
    # The environment wins over the file's own workspace key.
    assert load_settings().workspace == elsewhere


def test_empty_environment_value_is_ignored(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`DATAPORTER_WORKSPACE=` in a shell script means unset, not the current
    directory."""
    monkeypatch.setenv("DATAPORTER_WORKSPACE", "")
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
        monkeypatch.setenv("DATAPORTER_PACING__DELAY_BETWEEN_CONVERSATIONS_S", "7")
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
    monkeypatch.setenv("DATAPORTER_SEED__MAX_CHARS", "1234")
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
    monkeypatch.setenv("DATAPORTER_ATTACHMENTS__DIR", "elsewhere")
    assert load_settings().attachments_dir == workspace / "elsewhere"


def test_accepted_types_are_normalised(workspace: Path) -> None:
    """`03` matches a casefolded suffix, so `.PDF` in a config must still match."""
    write_config(
        workspace / DEFAULT_WORKSPACE,
        '[attachments]\naccepted_types = [".PDF", "Png"]\n',
    )
    assert load_settings().attachments.accepted_types == ("pdf", "png")


def test_the_browser_profile_lives_in_the_workspace(workspace: Path) -> None:
    """Not configurable: the point of the dedicated profile is that it is ours,
    and that `session logout` knows where to find it (§17)."""
    settings = load_settings()
    assert settings.browser_profile_dir == settings.workspace / "browser-profile"


def test_the_browser_section_comes_from_the_config_file(workspace: Path) -> None:
    write_config(
        workspace / DEFAULT_WORKSPACE,
        '[browser]\ncdp_port = 9333\nexecutable = "/opt/chromium"\n',
    )
    settings = load_settings()
    assert settings.browser.cdp_port == 9333
    assert settings.browser.executable == Path("/opt/chromium")
    assert settings.browser.extra_args == ()


def test_timeouts_have_defaults_and_can_be_overridden(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert load_settings().timeouts.login_s == 600.0
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__LOGIN_S", "30")
    settings = load_settings()
    assert settings.timeouts.login_s == 30.0
    assert settings.timeouts.browser_start_s == 30.0
    assert settings.timeouts.cdp_call_s == 20.0


# --------------------------------------------------------------------------- #
# The section `13` added
# --------------------------------------------------------------------------- #


def test_the_retry_budget_has_the_spec_defaults(workspace: Path) -> None:
    settings = load_settings()
    assert settings.retries.max_attempts == 3
    assert settings.retries.backoff_s == (30.0, 120.0, 300.0)
    assert settings.run.stop_after_consecutive_failures == 3


def test_the_retry_budget_follows_the_ladder(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`15` owns these numbers; `13` only has to make them reachable."""
    write_config(
        workspace / DEFAULT_WORKSPACE,
        "[retries]\nmax_attempts = 5\nbackoff_s = [1, 2]\n"
        "[run]\nstop_after_consecutive_failures = 9\n",
    )
    settings = load_settings()
    assert settings.retries.max_attempts == 5
    assert settings.retries.backoff_s == (1.0, 2.0)
    assert settings.run.stop_after_consecutive_failures == 9

    monkeypatch.setenv("DATAPORTER_RETRIES__MAX_ATTEMPTS", "2")
    monkeypatch.setenv("DATAPORTER_RUN__STOP_AFTER_CONSECUTIVE_FAILURES", "0")
    overridden = load_settings()
    assert overridden.retries.max_attempts == 2
    assert overridden.run.stop_after_consecutive_failures == 0


# --------------------------------------------------------------------------- #
# `24`: the mode, the credentials, and where they may not come from
# --------------------------------------------------------------------------- #


def test_the_mode_is_off_and_the_browser_headed_by_default(workspace: Path) -> None:
    settings = load_settings()
    assert settings.non_interactive is False
    assert settings.headless is False
    assert settings.credentials is None


def test_the_flag_and_the_environment_both_switch_the_mode_on(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert load_settings(non_interactive=True).non_interactive is True
    monkeypatch.setenv("DATAPORTER_NON_INTERACTIVE", "1")
    assert load_settings().non_interactive is True
    assert load_settings().headless is True


def test_headless_follows_the_mode_unless_configured(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATAPORTER_NON_INTERACTIVE", "1")
    monkeypatch.setenv("DATAPORTER_BROWSER__HEADLESS", "false")
    assert load_settings().headless is False
    monkeypatch.delenv("DATAPORTER_NON_INTERACTIVE")
    monkeypatch.setenv("DATAPORTER_BROWSER__HEADLESS", "true")
    assert load_settings().headless is True


def test_credentials_come_from_the_environment(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATAPORTER_AUTH__EMAIL", "someone@example.test")
    monkeypatch.setenv("DATAPORTER_AUTH__PASSWORD", "hunter2")
    found = load_settings().credentials
    assert found is not None
    assert found.email == "someone@example.test"
    assert found.password.get_secret_value() == "hunter2"


def test_half_a_credential_is_no_credential(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATAPORTER_AUTH__EMAIL", "someone@example.test")
    assert load_settings().credentials is None


def test_the_flags_set_the_half_they_name_and_keep_the_other(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATAPORTER_AUTH__EMAIL", "env@example.test")
    monkeypatch.setenv("DATAPORTER_AUTH__PASSWORD", "from-env")
    secret = tmp_path / "secret.txt"
    secret.write_text("from-file\nsecond line ignored\n", encoding="utf-8")

    found = load_settings(password_file=secret).credentials
    assert found is not None
    assert (found.email, found.password.get_secret_value()) == (
        "env@example.test",
        "from-file",
    )

    found = load_settings(email="flag@example.test").credentials
    assert found is not None
    assert (found.email, found.password.get_secret_value()) == (
        "flag@example.test",
        "from-env",
    )


def test_an_unreadable_secret_file_is_a_configuration_error(
    workspace: Path, tmp_path: Path
) -> None:
    with pytest.raises(ConfigError, match="cannot read"):
        load_settings(password_file=tmp_path / "missing.txt")


def test_the_secret_never_appears_in_a_dump(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATAPORTER_AUTH__EMAIL", "someone@example.test")
    monkeypatch.setenv("DATAPORTER_AUTH__PASSWORD", "hunter2")
    settings = load_settings()
    for rendering in (repr(settings), str(settings), settings.model_dump_json()):
        assert "hunter2" not in rendering
    assert "hunter2" not in repr(settings.model_dump())
    assert "hunter2" not in repr(settings.credentials)


@pytest.mark.parametrize("table", ["[auth]\nemail = 'x'\n", "non_interactive = true\n"])
def test_the_config_file_may_not_carry_the_mode_or_a_credential(
    workspace: Path, table: str
) -> None:
    write_config(workspace / "migration", table)
    with pytest.raises(ConfigError, match="not in config.toml"):
        load_settings()


@pytest.mark.parametrize(
    ("email", "secret"),
    [("someone@example.test", "   "), ("   ", "hunter2"), ("someone@example.test", "")],
)
def test_a_blank_half_is_no_credential(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, email: str, secret: str
) -> None:
    """Whitespace arrives as a string where an empty variable would not; a run
    must not start a browser on it. (Raised by Copilot in review on #33.)"""
    monkeypatch.setenv("DATAPORTER_AUTH__EMAIL", email)
    monkeypatch.setenv("DATAPORTER_AUTH__PASSWORD", secret)
    assert load_settings().credentials is None


def test_a_blank_first_line_in_the_secret_file_is_no_credential(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATAPORTER_AUTH__EMAIL", "someone@example.test")
    secret = tmp_path / "secret.txt"
    secret.write_text("\nhunter2\n", encoding="utf-8")
    assert load_settings(password_file=secret).credentials is None
