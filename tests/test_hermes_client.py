"""Finding `hermes`, running it in an environment we built, reading what it says."""

import os
import re
from pathlib import Path

import pytest

from dataporter.config import HermesSettings, Settings, TimeoutSettings
from dataporter.errors import HermesError, HermesUsageError
from dataporter.hermes import client as hermes_client
from fake_hermes import FakeHermes


def make_settings(tmp_path: Path, executable: Path | None = None) -> Settings:
    return Settings(
        workspace=tmp_path / "migration",
        hermes=HermesSettings(executable=executable),
        timeouts=TimeoutSettings(hermes_cli_s=20.0),
    )


@pytest.fixture
def fake(tmp_path: Path) -> FakeHermes:
    return FakeHermes(root=tmp_path / "bin").write(version="hermes 1.2.3")


# --------------------------------------------------------------------------- #
# Finding the executable
# --------------------------------------------------------------------------- #


@pytest.mark.slow
def test_the_configured_executable_wins(tmp_path: Path, fake: FakeHermes) -> None:
    cli = hermes_client.HermesCli(make_settings(tmp_path, fake.executable))
    assert cli.path == fake.executable


@pytest.mark.slow
def test_a_bare_name_is_looked_up_on_path(tmp_path: Path, fake: FakeHermes, monkeypatch: pytest.MonkeyPatch) -> None:
    fake.on_path(monkeypatch)
    cli = hermes_client.HermesCli(make_settings(tmp_path))
    assert cli.path == fake.executable


def test_a_missing_hermes_names_the_remedy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hermes_client.shutil, "which", lambda name: None)
    cli = hermes_client.HermesCli(make_settings(tmp_path))
    with pytest.raises(HermesUsageError, match="hermes not found") as caught:
        _ = cli.path
    # Not transient: no number of retries installs Hermes.
    assert caught.value.transient is False


def test_a_configured_executable_that_is_not_there_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hermes_client.shutil, "which", lambda name: None)
    cli = hermes_client.HermesCli(make_settings(tmp_path, Path("/opt/nope/hermes")))
    with pytest.raises(HermesUsageError, match="configured hermes executable"):
        _ = cli.path


@pytest.mark.slow
def test_the_path_is_resolved_once(tmp_path: Path, fake: FakeHermes) -> None:
    """A `PATH` that changes under `doctor`'s five calls is a stranger problem."""
    cli = hermes_client.HermesCli(make_settings(tmp_path, fake.executable))
    assert cli.path is cli.path


# --------------------------------------------------------------------------- #
# The environment
# --------------------------------------------------------------------------- #


def test_the_environment_is_the_allowlist_and_nothing_else(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_YOLO_MODE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-ours")
    settings = make_settings(tmp_path)
    env = hermes_client.hermes_env(settings)
    assert set(env) <= {*hermes_client.PASSED_THROUGH_ENV, "DATAPORTER_WORKSPACE"}
    assert "HERMES_YOLO_MODE" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert env["DATAPORTER_WORKSPACE"] == str(settings.workspace)


def test_an_unset_variable_is_not_invented(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANG", raising=False)
    assert "LANG" not in hermes_client.hermes_env(make_settings(tmp_path))


#: PEP 538 locale coercion: CPython sets this in its own environment *after*
#: exec, so it is in the child's view of itself without ever being in what we
#: passed. The allowlist is about what crosses the boundary, so it is excluded
#: here and asserted exactly in `test_the_environment_is_the_allowlist_…`.
COERCED = {"LC_CTYPE", "LC_ALL"}


@pytest.mark.slow
def test_the_child_really_sees_only_that(tmp_path: Path, fake: FakeHermes) -> None:
    """Asserted against the process's own view, not against our call record."""
    cli = hermes_client.HermesCli(make_settings(tmp_path, fake.executable))
    cli.version()
    seen = set(fake.calls[0].env) - COERCED
    assert seen <= {*hermes_client.PASSED_THROUGH_ENV, "DATAPORTER_WORKSPACE"}
    assert "HERMES_YOLO_MODE" not in seen


# --------------------------------------------------------------------------- #
# The calls
# --------------------------------------------------------------------------- #


@pytest.mark.slow
def test_version_is_parsed(tmp_path: Path, fake: FakeHermes) -> None:
    cli = hermes_client.HermesCli(make_settings(tmp_path, fake.executable))
    assert cli.version() == (1, 2, 3)


@pytest.mark.slow
def test_an_unreadable_version_is_an_error(tmp_path: Path, fake: FakeHermes) -> None:
    fake.write(version="not a version at all")
    cli = hermes_client.HermesCli(make_settings(tmp_path, fake.executable))
    with pytest.raises(HermesUsageError, match="cannot read a version"):
        cli.version()


@pytest.mark.slow
def test_a_non_zero_exit_becomes_a_usage_error(tmp_path: Path, fake: FakeHermes) -> None:
    fake.write(version="hermes 1.0.0", version_exit=3)
    cli = hermes_client.HermesCli(make_settings(tmp_path, fake.executable))
    with pytest.raises(HermesUsageError, match="hermes --version"):
        cli.version()


def test_an_unrunnable_executable_is_a_usage_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Something that resolves and then will not exec: a broken install."""
    directory = tmp_path / "bin"
    directory.mkdir()
    monkeypatch.setattr(hermes_client.shutil, "which", lambda name: str(directory))
    cli = hermes_client.HermesCli(make_settings(tmp_path))
    with pytest.raises(HermesUsageError, match="cannot run"):
        cli.run("--version")


@pytest.mark.slow
def test_a_call_that_never_returns_is_cut_off(tmp_path: Path, fake: FakeHermes) -> None:
    fake.write(version="hermes 1.0.0", sleep=30)
    settings = Settings(
        workspace=tmp_path / "migration",
        hermes=HermesSettings(executable=fake.executable),
        timeouts=TimeoutSettings(hermes_cli_s=0.5),
    )
    cli = hermes_client.HermesCli(settings)
    with pytest.raises(HermesError, match=re.escape("timed out after 0.5s")):
        # `-z` is the one branch of the fake that sleeps.
        cli.run("-z", "anything")


@pytest.mark.slow
def test_profiles_and_creation_round_trip(tmp_path: Path, fake: FakeHermes) -> None:
    cli = hermes_client.HermesCli(make_settings(tmp_path, fake.executable))
    assert cli.profiles() == []
    cli.create_profile()
    assert cli.profiles() == ["dataporter"]
    assert fake.profiles == ["dataporter"]


@pytest.mark.slow
def test_config_set_is_passed_through_verbatim(tmp_path: Path, fake: FakeHermes) -> None:
    cli = hermes_client.HermesCli(make_settings(tmp_path, fake.executable))
    cli.config_set("browser.cdp_url", "http://127.0.0.1:9222")
    assert fake.config == {"browser.cdp_url": "http://127.0.0.1:9222"}
    assert cli.config()["browser.cdp_url"] == "http://127.0.0.1:9222"
    assert fake.calls[-1].argv[:2] == ["-p", "dataporter"]


# --------------------------------------------------------------------------- #
# Reading the output
# --------------------------------------------------------------------------- #


def test_profile_list_survives_decoration() -> None:
    text = "profiles:\n* dataporter (active)\n  - default\n\n(2 total)\n"
    assert hermes_client.parse_profile_list(text) == ["dataporter", "default"]


def test_nested_yaml_is_flattened_to_dotted_keys() -> None:
    text = """
# the profile
browser:
  backend: "off"
  cdp_url: http://127.0.0.1:9222
  nested:
    deep: 1
approvals:
  mode: manual
"""
    assert hermes_client.parse_config(text) == {
        "browser.backend": "off",
        "browser.cdp_url": "http://127.0.0.1:9222",
        "browser.nested.deep": "1",
        "approvals.mode": "manual",
    }


def test_flat_dotted_and_equals_forms_are_read_too() -> None:
    text = "browser.backend = off\nagent.max_turns: 80\n- ignored\n"
    assert hermes_client.parse_config(text) == {
        "browser.backend": "off",
        "agent.max_turns": "80",
    }


def test_a_line_that_is_not_a_setting_is_skipped() -> None:
    """`config show` may print a banner, a heading or a blank separator."""
    text = "hermes configuration\n\nbrowser.backend: off\n"
    assert hermes_client.parse_config(text) == {"browser.backend": "off"}


def test_a_sibling_key_after_a_block_leaves_the_block() -> None:
    """Dedenting closes the prefix, or every later key would be under it."""
    text = "browser:\n  backend: off\nmemory:\n  memory_enabled: false\n"
    assert hermes_client.parse_config(text) == {
        "browser.backend": "off",
        "memory.memory_enabled": "false",
    }


def test_mismatches_name_the_key_what_is_there_and_what_was_wanted() -> None:
    found = hermes_client.mismatches({"browser.backend": "browser-use"}, {"browser.backend": "off", "a.b": "1"})
    assert found == [
        "browser.backend=browser-use, expected off",
        "a.b unset, expected 1",
    ]


def test_a_value_that_only_differs_in_case_is_not_a_mismatch() -> None:
    """A YAML round trip may hand back `Off` for the `off` we set."""
    assert hermes_client.mismatches({"browser.backend": "Off"}, {"browser.backend": "off"}) == []


def test_a_path_under_home_is_abbreviated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hermes_client.Path, "home", lambda: Path("/home/someone"))
    assert hermes_client.home_relative(Path("/home/someone/.local/bin/hermes")) == ("~/.local/bin/hermes")
    assert hermes_client.home_relative(Path("/opt/hermes")) == "/opt/hermes"


def test_a_command_with_a_space_in_it_is_quoted() -> None:
    quoted = hermes_client.quoted(["dataporter", "--workspace", "/a b/c"])
    assert quoted == "dataporter --workspace '/a b/c'"


def test_the_failure_line_is_the_last_thing_said(tmp_path: Path) -> None:
    completed = hermes_client.Completed(command=("hermes",), returncode=1, stdout="starting\n", stderr="\nboom\n")
    assert completed.failure == "boom"
    assert not completed.ok


def test_a_silent_failure_falls_back_to_the_exit_code() -> None:
    completed = hermes_client.Completed(command=("hermes",), returncode=9, stdout="", stderr="")
    assert completed.failure == "exited 9"


def test_the_failure_line_cannot_forge_a_second_line() -> None:
    completed = hermes_client.Completed(command=("hermes",), returncode=1, stdout="", stderr="boom\r\nok  (fake)")
    assert "\n" not in completed.failure
    assert os.linesep not in completed.failure


@pytest.mark.slow
def test_a_credential_in_the_parent_never_reaches_hermes(
    tmp_path: Path, fake: FakeHermes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`24`: the environment is built, not filtered, and `DATAPORTER_AUTH__*` is not on it.

    So the agent cannot `printenv` its way to a password.
    """
    monkeypatch.setenv("DATAPORTER_AUTH__EMAIL", "someone@example.test")
    monkeypatch.setenv("DATAPORTER_AUTH__PASSWORD", "hunter2")
    settings = make_settings(tmp_path, fake.executable)
    env = hermes_client.hermes_env(settings)
    assert not any(key.startswith("DATAPORTER_AUTH") for key in env)
    hermes_client.HermesCli(settings).version()
    seen = fake.calls[-1].env
    assert not any(key.startswith("DATAPORTER_AUTH") for key in seen)
    assert "hunter2" not in " ".join(seen.values())
