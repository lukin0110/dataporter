"""Finding `hermes`, running it in an environment we built, reading what it says."""

import os
import re
from pathlib import Path

import pytest

from dataporter import trace as tracing
from dataporter.browser.site import Site
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
    assert cli.config(["browser.cdp_url"])["browser.cdp_url"] == "http://127.0.0.1:9222"
    assert fake.calls[-1].argv[:2] == ["-p", "dataporter"]


# --------------------------------------------------------------------------- #
# Reading the output
# --------------------------------------------------------------------------- #


def test_profile_list_survives_decoration() -> None:
    text = "profiles:\n* dataporter (active)\n  - default\n\n(2 total)\n"
    assert hermes_client.parse_profile_list(text) == ["dataporter", "default"]


def test_the_profile_table_keeps_its_header_out_of_the_names() -> None:
    """The column table `59` observed: a header, a rule, a marked active row."""
    text = (
        "\n Profile          Model             Gateway\n"
        " ───────────────    ──────────────    ───────────\n"
        " ◆default         a/model           running\n"
        "  dataporter      b/model           stopped\n\n"
    )
    assert hermes_client.parse_profile_list(text) == ["default", "dataporter"]


def test_a_json_value_becomes_the_string_the_config_file_spells() -> None:
    """`config get --json` answers with types; `mismatches` compares strings."""
    assert hermes_client.parse_value('"off"\n') == "off"
    assert hermes_client.parse_value('"manual"') == "manual"
    assert hermes_client.parse_value("120\n") == "120"
    assert hermes_client.parse_value("true\n") == "true"
    assert hermes_client.parse_value("false\n") == "false"


def test_a_key_hermes_has_not_got_reads_as_none() -> None:
    """Hermes exits `0` for one and says so in prose, so not-JSON is the signal."""
    assert hermes_client.parse_value("Config key not set: nope.not_a_key\n") is None
    assert hermes_client.parse_value("") is None


def test_a_section_reads_as_none_rather_than_as_a_dict_repr() -> None:
    """`config get model` answers the whole section, and `59` is what that cost.

    Read as unset, so a caller that asked for the section is told it has no
    value, rather than an operator being shown `{'default': …}` as their model.
    """
    assert hermes_client.parse_value('{"default": "a/model", "provider": "custom"}') is None
    assert hermes_client.parse_value("[1, 2]") is None
    assert hermes_client.parse_value("null") is None


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


def test_the_environment_carries_the_trace_when_this_process_has_one(tmp_path: Path) -> None:
    """`33`: the run's trace travels to every Hermes the way the workspace does."""
    settings = make_settings(tmp_path)
    site = Site("claude", "claude.ai", {})
    trace = tracing.Trace.open(settings, command="import", flags=(), site=site, chrome=None, agent=None)
    tracing.set_current(trace)
    try:
        env = hermes_client.hermes_env(settings)
        assert env[tracing.TRACE_ENV_VAR] == str(trace.path)
        assert set(env) <= {*hermes_client.PASSED_THROUGH_ENV, "DATAPORTER_WORKSPACE", tracing.TRACE_ENV_VAR}
    finally:
        tracing.set_current(None)
        trace.close()
    assert tracing.TRACE_ENV_VAR not in hermes_client.hermes_env(settings)
