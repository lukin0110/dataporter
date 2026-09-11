"""`setup`: the profile, its configuration, the skill, and the model it prints."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataporter import cli
from dataporter.config import BrowserSettings, HermesSettings, Settings
from dataporter.errors import HermesUsageError
from dataporter.exit_codes import ExitCode
from dataporter.hermes import profile as profiling
from fake_hermes import FakeHermes

MODEL = "anthropic/claude-sonnet-5"


def make_settings(tmp_path: Path, fake: FakeHermes, port: int = 9222) -> Settings:
    return Settings(
        workspace=tmp_path / "migration",
        browser=BrowserSettings(cdp_port=port),
        hermes=HermesSettings(
            executable=fake.executable, home=tmp_path / "hermes-home"
        ),
    )


@pytest.fixture
def fake(tmp_path: Path) -> FakeHermes:
    """A Hermes with a model already chosen, which `hermes setup model` does."""
    return FakeHermes(root=tmp_path / "bin").write(
        version="hermes 1.0.0", config_extra={"agent.model": MODEL}
    )


# --------------------------------------------------------------------------- #
# What gets set
# --------------------------------------------------------------------------- #


def test_the_profile_is_created_when_it_is_missing(
    tmp_path: Path, fake: FakeHermes
) -> None:
    report = profiling.run_setup(make_settings(tmp_path, fake))
    assert report.created
    assert fake.profiles == ["dataporter"]
    assert report.model == MODEL


def test_an_existing_profile_is_not_recreated(tmp_path: Path, fake: FakeHermes) -> None:
    fake.with_profile("dataporter")
    report = profiling.run_setup(make_settings(tmp_path, fake))
    assert not report.created
    assert ["profile", "create"] not in [call.argv[:2] for call in fake.calls]


def test_every_key_09_names_is_set(tmp_path: Path, fake: FakeHermes) -> None:
    settings = make_settings(tmp_path, fake)
    profiling.run_setup(settings)
    expected = profiling.profile_config(settings)
    assert fake.config == expected
    assert expected["browser.backend"] == "off"
    assert expected["approvals.single_query_mode"] == "deny"
    assert expected["memory.memory_enabled"] == "false"
    assert expected["browser.record_sessions"] == "false"


def test_the_cdp_url_follows_the_configured_port(
    tmp_path: Path, fake: FakeHermes
) -> None:
    settings = make_settings(tmp_path, fake, port=9333)
    profiling.run_setup(settings)
    assert fake.config["browser.cdp_url"] == "http://127.0.0.1:9333"


def test_max_turns_follows_configuration(tmp_path: Path, fake: FakeHermes) -> None:
    settings = Settings(
        workspace=tmp_path / "migration",
        hermes=HermesSettings(
            executable=fake.executable, home=tmp_path / "h", max_turns=120
        ),
    )
    profiling.run_setup(settings)
    assert fake.config["agent.max_turns"] == "120"


def test_the_skill_is_installed_into_the_profile(
    tmp_path: Path, fake: FakeHermes
) -> None:
    settings = make_settings(tmp_path, fake)
    report = profiling.run_setup(settings)
    assert str(report.skill) == "claude-migrate 0.1.0"
    assert Path(report.skill_dir, "SKILL.md").is_file()


def test_setup_twice_leaves_the_config_identical(
    tmp_path: Path, fake: FakeHermes
) -> None:
    """`09`'s acceptance criterion: compared as `config show` prints it."""
    settings = make_settings(tmp_path, fake)
    profiling.run_setup(settings)
    first = profiling.HermesCli(settings).config_show_text()
    profiling.run_setup(settings)
    second = profiling.HermesCli(settings).config_show_text()
    assert first == second


def test_a_failing_config_set_stops_setup(tmp_path: Path, fake: FakeHermes) -> None:
    """Half a configuration is not a profile `doctor` may vouch for."""
    fake.write(version="hermes 1.0.0", set_exit=1)
    with pytest.raises(HermesUsageError, match="config set"):
        profiling.run_setup(make_settings(tmp_path, fake))


# --------------------------------------------------------------------------- #
# The model
# --------------------------------------------------------------------------- #


def test_the_model_is_read_from_whichever_key_holds_it() -> None:
    for key in profiling.MODEL_KEYS:
        assert profiling.configured_model({key: MODEL}) == MODEL


def test_no_model_reads_as_none() -> None:
    assert profiling.configured_model({"browser.backend": "off"}) == ""
    assert profiling.configured_model({"agent.model": "  "}) == ""


# --------------------------------------------------------------------------- #
# Through the command
# --------------------------------------------------------------------------- #


def config_toml(tmp_path: Path, fake: FakeHermes) -> Path:
    """A workspace whose `config.toml` points at the fake. `setup` takes no flags."""
    workspace = tmp_path / "migration"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "config.toml").write_text(
        "[hermes]\n"
        f'executable = "{fake.executable}"\n'
        f'home = "{tmp_path / "hermes-home"}"\n',
        encoding="utf-8",
    )
    return workspace


def test_setup_prints_what_it_did(
    runner: CliRunner, tmp_path: Path, fake: FakeHermes
) -> None:
    workspace = config_toml(tmp_path, fake)
    result = runner.invoke(
        cli.app, ["--workspace", str(workspace), "setup"], catch_exceptions=False
    )
    assert result.exit_code == ExitCode.OK
    lines = result.stdout.splitlines()
    assert lines[0] == "hermes profile   dataporter (created)"
    assert lines[1] == "hermes config    12 keys set"
    assert lines[2].startswith("skill            claude-migrate 0.1.0 -> ")
    assert lines[3] == f"hermes model     {MODEL}"
    # The transcripts are content, and `setup` is where an operator is told so.
    assert "session transcripts" in result.stdout
    assert "hermes-claude-migrate doctor" in result.stdout


def test_setup_with_no_model_exits_6_with_09s_words(
    runner: CliRunner, tmp_path: Path, fake: FakeHermes
) -> None:
    fake.write(version="hermes 1.0.0")  # no agent.model anywhere
    workspace = config_toml(tmp_path, fake)
    result = runner.invoke(
        cli.app, ["--workspace", str(workspace), "setup"], catch_exceptions=False
    )
    assert result.exit_code == ExitCode.ENVIRONMENT
    assert result.stderr == (
        "error: no model configured — run: hermes -p dataporter setup model\n"
    )
    # Everything it did before that still happened, and is still reported.
    assert "12 keys set" in result.stdout


def test_setup_without_hermes_exits_6_not_70(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    result = runner.invoke(
        cli.app,
        ["--workspace", str(tmp_path / "migration"), "setup"],
        catch_exceptions=False,
    )
    assert result.exit_code == ExitCode.ENVIRONMENT
    assert result.stderr.startswith("error: hermes not found")


def test_the_purge_hint_names_the_profile_directory(
    tmp_path: Path, fake: FakeHermes
) -> None:
    settings = make_settings(tmp_path, fake)
    hint = profiling.purge_hint(settings)
    assert str(tmp_path / "hermes-home" / "profiles" / "dataporter") in hint
