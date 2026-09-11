"""`doctor`: ten checks in order, stopping at the first failure."""

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataporter import cli
from dataporter.browser import launcher
from dataporter.browser.cdp import CdpClient
from dataporter.config import BrowserSettings, HermesSettings, Settings, TimeoutSettings
from dataporter.errors import BrowserError
from dataporter.exit_codes import ExitCode
from dataporter.hermes import doctor as hermes_doctor
from dataporter.hermes import profile as profiling
from dataporter.hermes import version as versioning
from fake_chrome import BROKEN_TARGET, Call, FakeChrome, FakeTarget, page_state
from fake_hermes import FakeHermes

MODEL = "anthropic/claude-sonnet-5"
ANSWER = "__NONCE__\nhttps://claude.ai/new\ntrue\n"
"""What a working Hermes answers both `doctor` tasks with: the nonce, the URL of
the other tab in *our* browser, and the helper's `ok` field."""


@pytest.fixture
def chrome() -> Iterator[FakeChrome]:
    with FakeChrome(
        targets=[
            FakeTarget(id="page-1", url="https://claude.ai/new", evaluate=page_state())
        ]
    ) as fake:
        yield fake


@pytest.fixture
def fake(tmp_path: Path) -> FakeHermes:
    return FakeHermes(root=tmp_path / "bin").write(
        version="hermes 1.0.0",
        config_extra={"agent.model": MODEL},
        answer=ANSWER,
        append_probe=True,
    )


def make_settings(tmp_path: Path, fake: FakeHermes, chrome: FakeChrome) -> Settings:
    return Settings(
        workspace=tmp_path / "migration",
        browser=BrowserSettings(executable=Path(sys.executable), cdp_port=chrome.port),
        hermes=HermesSettings(
            executable=fake.executable, home=tmp_path / "hermes-home"
        ),
        timeouts=TimeoutSettings(cdp_call_s=2.0, hermes_check_s=30.0),
    )


def adopt_instead(
    monkeypatch: pytest.MonkeyPatch, chrome: FakeChrome, *, adopted: bool = True
) -> None:
    """`launch` returns a session over the fake browser instead of starting one."""

    def fake_launch(settings: Settings, url: str) -> launcher.BrowserSession:
        return launcher.BrowserSession(
            client=CdpClient(port=chrome.port, timeout=2.0),
            profile=settings.browser_profile_dir,
            adopted=adopted,
        )

    monkeypatch.setattr(launcher, "launch", fake_launch)


def run_checks(settings: Settings) -> list[hermes_doctor.Check]:
    return list(hermes_doctor.checks(settings))


def labels(results: list[hermes_doctor.Check]) -> list[str]:
    return [check.label for check in results]


# --------------------------------------------------------------------------- #
# Everything working
# --------------------------------------------------------------------------- #


def test_setup_then_doctor_is_ten_ok_lines(
    tmp_path: Path,
    fake: FakeHermes,
    chrome: FakeChrome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`09`'s acceptance criterion, as close as a test can get to it."""
    settings = make_settings(tmp_path, fake, chrome)
    profiling.run_setup(settings)
    adopt_instead(monkeypatch, chrome)

    results = run_checks(settings)
    assert labels(results) == list(hermes_doctor.LABELS)
    assert all(check.ok for check in results), [
        check.render() for check in results if not check.ok
    ]


def test_the_two_hermes_checks_really_ran_hermes(
    tmp_path: Path,
    fake: FakeHermes,
    chrome: FakeChrome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path, fake, chrome)
    profiling.run_setup(settings)
    adopt_instead(monkeypatch, chrome)
    run_checks(settings)

    one_shots = fake.one_shots
    assert len(one_shots) == 2
    # Each task carries its own nonce, and neither is a nonce we wrote down.
    nonces = {hermes_doctor.nonce() for _ in range(2)}
    for call in one_shots:
        assert "HCM-" in call.prompt
        assert call.prompt not in nonces
    # The helper task names our command, our workspace and nothing else to run.
    assert "browser probe" in one_shots[1].prompt
    assert str(settings.workspace) in one_shots[1].prompt


def test_the_throwaway_tab_is_closed_again(
    tmp_path: Path,
    fake: FakeHermes,
    chrome: FakeChrome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path, fake, chrome)
    profiling.run_setup(settings)
    adopt_instead(monkeypatch, chrome)
    run_checks(settings)
    assert [target.url for target in chrome.targets] == ["https://claude.ai/new"]


def test_a_browser_doctor_started_is_closed_again(
    tmp_path: Path,
    fake: FakeHermes,
    chrome: FakeChrome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path, fake, chrome)
    profiling.run_setup(settings)
    adopt_instead(monkeypatch, chrome, adopted=False)
    run_checks(settings)
    assert chrome.closed


def test_an_adopted_browser_is_left_running(
    tmp_path: Path,
    fake: FakeHermes,
    chrome: FakeChrome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It belongs to whoever started it, as `session status` already has it."""
    settings = make_settings(tmp_path, fake, chrome)
    profiling.run_setup(settings)
    adopt_instead(monkeypatch, chrome)
    run_checks(settings)
    assert not chrome.closed


# --------------------------------------------------------------------------- #
# Each failure, and where it stops
# --------------------------------------------------------------------------- #


def test_no_hermes_stops_at_the_first_line(
    tmp_path: Path, chrome: FakeChrome, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    settings = Settings(workspace=tmp_path / "migration")
    results = run_checks(settings)
    assert len(results) == 1
    assert results[0].label == hermes_doctor.HERMES_ON_PATH
    assert not results[0].ok
    assert "hermes not found" in results[0].detail


def test_a_version_below_the_floor_is_refused(
    tmp_path: Path, fake: FakeHermes, chrome: FakeChrome
) -> None:
    fake.write(version="hermes 0.0.1")
    results = run_checks(make_settings(tmp_path, fake, chrome))
    assert len(results) == 1
    assert not results[0].ok
    assert versioning.format_version(versioning.MINIMUM_VERSION) in results[0].detail


def test_an_unreadable_version_stops_there_too(
    tmp_path: Path, fake: FakeHermes, chrome: FakeChrome
) -> None:
    fake.write(version="hermes", version_exit=1)
    results = run_checks(make_settings(tmp_path, fake, chrome))
    assert labels(results) == [hermes_doctor.HERMES_ON_PATH]


def test_a_missing_profile_points_at_setup(
    tmp_path: Path, fake: FakeHermes, chrome: FakeChrome
) -> None:
    results = run_checks(make_settings(tmp_path, fake, chrome))
    assert labels(results) == [
        hermes_doctor.HERMES_ON_PATH,
        hermes_doctor.HERMES_PROFILE,
    ]
    assert "run: hermes-claude-migrate setup" in results[-1].detail


def test_a_profile_list_that_fails_is_reported_as_the_profile_check(
    tmp_path: Path, fake: FakeHermes, chrome: FakeChrome
) -> None:
    fake.write(version="hermes 1.0.0", list_exit=1)
    results = run_checks(make_settings(tmp_path, fake, chrome))
    assert labels(results)[-1] == hermes_doctor.HERMES_PROFILE


def test_no_model_stops_before_the_config_check(
    tmp_path: Path, fake: FakeHermes, chrome: FakeChrome
) -> None:
    settings = make_settings(tmp_path, fake, chrome)
    fake.write(version="hermes 1.0.0", answer=ANSWER)  # no model key
    profiling.run_setup(settings)
    results = run_checks(settings)
    assert labels(results)[-1] == hermes_doctor.HERMES_MODEL
    assert results[-1].detail == (
        "no model configured — run: hermes -p dataporter setup model"
    )


def test_a_config_show_that_fails_is_reported_as_the_model_check(
    tmp_path: Path, fake: FakeHermes, chrome: FakeChrome
) -> None:
    settings = make_settings(tmp_path, fake, chrome)
    profiling.run_setup(settings)
    fake.write(version="hermes 1.0.0", show_exit=1)
    results = run_checks(settings)
    assert labels(results)[-1] == hermes_doctor.HERMES_MODEL


def test_a_key_the_profile_lost_is_named(
    tmp_path: Path, fake: FakeHermes, chrome: FakeChrome
) -> None:
    settings = make_settings(tmp_path, fake, chrome)
    profiling.run_setup(settings)
    fake.write(
        version="hermes 1.0.0",
        config_extra={"agent.model": MODEL, "browser.backend": "browser-use"},
        config_drop=["browser.cdp_url"],
    )
    results = run_checks(settings)
    assert labels(results)[-1] == hermes_doctor.HERMES_CONFIG
    assert "browser.backend=browser-use, expected off" in results[-1].detail
    assert "browser.cdp_url unset" in results[-1].detail


def test_the_config_line_reports_the_two_keys_that_matter(
    tmp_path: Path,
    fake: FakeHermes,
    chrome: FakeChrome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path, fake, chrome)
    profiling.run_setup(settings)
    adopt_instead(monkeypatch, chrome)
    detail = next(
        check.detail
        for check in run_checks(settings)
        if check.label == hermes_doctor.HERMES_CONFIG
    )
    assert detail == (
        f"browser.backend=off, browser.cdp_url=http://127.0.0.1:{chrome.port}"
    )


def test_a_missing_skill_points_at_setup(
    tmp_path: Path, fake: FakeHermes, chrome: FakeChrome
) -> None:
    settings = make_settings(tmp_path, fake, chrome)
    profiling.run_setup(settings)
    (
        settings.hermes_home
        / "profiles"
        / "dataporter"
        / "skills"
        / "dataporter"
        / "claude-migrate"
        / "SKILL.md"
    ).unlink()
    results = run_checks(settings)
    assert labels(results)[-1] == hermes_doctor.SKILL_INSTALLED
    assert "run: hermes-claude-migrate setup" in results[-1].detail


def test_no_browser_stops_at_the_executable(
    tmp_path: Path,
    fake: FakeHermes,
    chrome: FakeChrome,
) -> None:
    settings = make_settings(tmp_path, fake, chrome)
    profiling.run_setup(settings)
    # A configured browser that is not there, rather than an empty `PATH` or a
    # stubbed `shutil.which`: the `hermes` lookup goes through the same module
    # and the same `PATH`, so either would fail line one instead of line six.
    settings = settings.model_copy(
        update={
            "browser": BrowserSettings(
                executable=Path("/opt/not-a-browser"), cdp_port=chrome.port
            )
        }
    )
    results = run_checks(settings)
    assert labels(results)[-1] == hermes_doctor.CHROME_EXECUTABLE
    assert "configured browser executable not found" in results[-1].detail


def test_a_browser_that_will_not_start_stops_at_the_launch(
    tmp_path: Path,
    fake: FakeHermes,
    chrome: FakeChrome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path, fake, chrome)
    profiling.run_setup(settings)

    def refuse(settings: Settings, url: str) -> launcher.BrowserSession:
        raise BrowserError(detail="browser exited immediately with code 1")

    monkeypatch.setattr(launcher, "launch", refuse)
    results = run_checks(settings)
    assert labels(results)[-1] == hermes_doctor.CHROME_LAUNCH
    assert "exited immediately" in results[-1].detail


def test_an_answer_without_the_nonce_fails_the_attach_check(
    tmp_path: Path,
    fake: FakeHermes,
    chrome: FakeChrome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path, fake, chrome)
    profiling.run_setup(settings)
    fake.write(
        version="hermes 1.0.0",
        config_extra={"agent.model": MODEL},
        answer="I snapshotted the tab.\n",
    )
    adopt_instead(monkeypatch, chrome)
    results = run_checks(settings)
    assert labels(results)[-1] == hermes_doctor.HERMES_ATTACHES
    assert "did not answer with the nonce" in results[-1].detail
    # The path, never the output: a transcript contains page snapshots.
    assert str(settings.hermes_dir) in results[-1].detail


def test_an_answer_without_our_tab_means_it_is_not_our_chrome(
    tmp_path: Path,
    fake: FakeHermes,
    chrome: FakeChrome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure `10`'s first open question is about: a Chromium of its own."""
    settings = make_settings(tmp_path, fake, chrome)
    profiling.run_setup(settings)
    fake.write(
        version="hermes 1.0.0",
        config_extra={"agent.model": MODEL},
        answer="__NONCE__\nabout:blank\n",
    )
    adopt_instead(monkeypatch, chrome)
    results = run_checks(settings)
    assert labels(results)[-1] == hermes_doctor.HERMES_ATTACHES
    assert "not attached to our Chrome" in results[-1].detail


def test_a_hermes_that_exits_non_zero_fails_the_check_it_was_running(
    tmp_path: Path,
    fake: FakeHermes,
    chrome: FakeChrome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path, fake, chrome)
    profiling.run_setup(settings)
    fake.write(
        version="hermes 1.0.0",
        config_extra={"agent.model": MODEL},
        answer=ANSWER,
        exit=1,
        stderr="the model refused\n",
    )
    adopt_instead(monkeypatch, chrome)
    results = run_checks(settings)
    assert labels(results)[-1] == hermes_doctor.HERMES_ATTACHES
    assert "hermes exited 1" in results[-1].detail


def test_a_hermes_that_never_finishes_fails_the_check(
    tmp_path: Path,
    fake: FakeHermes,
    chrome: FakeChrome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path, fake, chrome).model_copy(
        update={
            "timeouts": TimeoutSettings(cdp_call_s=2.0, hermes_check_s=1.0),
        }
    )
    profiling.run_setup(settings)
    fake.write(
        version="hermes 1.0.0",
        config_extra={"agent.model": MODEL},
        answer=ANSWER,
        sleep=30,
    )
    adopt_instead(monkeypatch, chrome)
    results = run_checks(settings)
    assert labels(results)[-1] == hermes_doctor.HERMES_ATTACHES
    assert "timeout after 1s" in results[-1].detail


def test_a_helper_that_never_ran_fails_even_with_the_nonce(
    tmp_path: Path,
    fake: FakeHermes,
    chrome: FakeChrome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The record in `logs/actions.jsonl` is ours; the nonce is only the agent's."""
    settings = make_settings(tmp_path, fake, chrome)
    profiling.run_setup(settings)
    fake.write(
        version="hermes 1.0.0",
        config_extra={"agent.model": MODEL},
        answer=ANSWER,
        append_probe=False,
    )
    adopt_instead(monkeypatch, chrome)
    results = run_checks(settings)
    assert labels(results)[-1] == hermes_doctor.HERMES_HELPER
    assert "no probe recorded" in results[-1].detail


def test_a_signed_out_session_is_the_last_failure(
    tmp_path: Path, fake: FakeHermes, monkeypatch: pytest.MonkeyPatch
) -> None:
    with FakeChrome(
        targets=[
            FakeTarget(
                id="page-1",
                url="https://claude.ai/login",
                evaluate=page_state(
                    url="https://claude.ai/login", composer_present=False
                ),
            )
        ]
    ) as chrome:
        settings = make_settings(tmp_path, fake, chrome)
        profiling.run_setup(settings)
        adopt_instead(monkeypatch, chrome)
        results = run_checks(settings)
        assert labels(results) == list(hermes_doctor.LABELS)
        assert not results[-1].ok
        assert results[-1].detail == "not logged in — run: hermes-claude-migrate login"


def test_a_browser_that_goes_away_fails_the_session_check(
    tmp_path: Path,
    fake: FakeHermes,
    chrome: FakeChrome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path, fake, chrome)
    profiling.run_setup(settings)
    adopt_instead(monkeypatch, chrome)

    def collapse(session: launcher.BrowserSession, url: str = "") -> bool:
        raise BrowserError(detail="cdp unreachable")

    monkeypatch.setattr(hermes_doctor.browser_session, "signed_in", collapse)
    results = run_checks(settings)
    assert labels(results)[-1] == hermes_doctor.SESSION
    assert results[-1].detail == "cdp unreachable"


# --------------------------------------------------------------------------- #
# How a line looks
# --------------------------------------------------------------------------- #


def test_an_ok_line_puts_its_detail_in_brackets() -> None:
    rendered = hermes_doctor.Check("hermes profile", True, "dataporter").render()
    assert rendered == "hermes profile            ok  (dataporter)"


def test_the_longest_label_still_leaves_a_space() -> None:
    """`hermes attaches to chrome` is the widest label `09` names."""
    rendered = hermes_doctor.Check(hermes_doctor.HERMES_ATTACHES, True, "x").render()
    assert rendered == "hermes attaches to chrome ok  (x)"
    assert all(
        len(label) <= hermes_doctor.LABEL_WIDTH for label in hermes_doctor.LABELS
    )


def test_every_ok_column_lines_up() -> None:
    columns = {
        hermes_doctor.Check(label, True, "x").render().index("ok")
        for label in hermes_doctor.LABELS
    }
    assert len(columns) == 1


def test_a_failure_line_has_no_brackets() -> None:
    rendered = hermes_doctor.Check("session", False, "not logged in").render()
    assert rendered == "session                   FAIL not logged in"
    assert hermes_doctor.Check("session", False).render().endswith("FAIL")


def test_an_ok_line_with_nothing_to_add_is_just_ok() -> None:
    assert hermes_doctor.Check("session", True).render().endswith(" ok")


# --------------------------------------------------------------------------- #
# Through the command
# --------------------------------------------------------------------------- #


def workspace_with_config(tmp_path: Path, fake: FakeHermes, chrome: FakeChrome) -> Path:
    workspace = tmp_path / "migration"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "config.toml").write_text(
        "[hermes]\n"
        f'executable = "{fake.executable}"\n'
        f'home = "{tmp_path / "hermes-home"}"\n'
        "[browser]\n"
        f'executable = "{sys.executable}"\n'
        f"cdp_port = {chrome.port}\n",
        encoding="utf-8",
    )
    return workspace


def test_doctor_prints_ten_lines_and_exits_zero(
    runner: CliRunner,
    tmp_path: Path,
    fake: FakeHermes,
    chrome: FakeChrome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = workspace_with_config(tmp_path, fake, chrome)
    profiling.run_setup(make_settings(tmp_path, fake, chrome))
    adopt_instead(monkeypatch, chrome)

    result = runner.invoke(
        cli.app, ["--workspace", str(workspace), "doctor"], catch_exceptions=False
    )
    lines = result.stdout.splitlines()
    assert result.exit_code == ExitCode.OK
    assert [line[: hermes_doctor.LABEL_WIDTH].strip() for line in lines] == list(
        hermes_doctor.LABELS
    )
    assert all(" ok" in line for line in lines)
    assert result.stderr == ""


def test_doctor_without_hermes_exits_6_at_the_first_line(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    result = runner.invoke(
        cli.app,
        ["--workspace", str(tmp_path / "migration"), "doctor"],
        catch_exceptions=False,
    )
    assert result.exit_code == ExitCode.ENVIRONMENT
    assert len(result.stdout.splitlines()) == 1
    assert result.stdout.startswith("hermes on PATH")
    assert "FAIL" in result.stdout


# --------------------------------------------------------------------------- #
# The two ways a `doctor` task can be answered badly, one per task
# --------------------------------------------------------------------------- #


def test_a_helper_answer_without_the_nonce_fails_that_check(
    tmp_path: Path,
    fake: FakeHermes,
    chrome: FakeChrome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The attach task answers properly; the helper task does not."""
    settings = make_settings(tmp_path, fake, chrome)
    profiling.run_setup(settings)
    fake.write(
        version="hermes 1.0.0",
        config_extra={"agent.model": MODEL},
        answers=[ANSWER, "I ran it, honestly.\n"],
        append_probe=True,
    )
    adopt_instead(monkeypatch, chrome)
    results = run_checks(settings)
    assert labels(results)[-1] == hermes_doctor.HERMES_HELPER
    assert "did not answer with the nonce" in results[-1].detail


def test_a_browser_that_will_not_open_a_tab_fails_the_attach_check(
    tmp_path: Path, fake: FakeHermes, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(inner: FakeChrome, call: Call) -> dict[str, object] | None:
        if call.method == "Target.createTarget":
            return {"error": {"code": -32000, "message": "cannot create target"}}
        return None

    with FakeChrome(
        targets=[
            FakeTarget(id="page-1", url="https://claude.ai/new", evaluate=page_state())
        ],
        responder=refuse,
    ) as chrome:
        settings = make_settings(tmp_path, fake, chrome)
        profiling.run_setup(settings)
        adopt_instead(monkeypatch, chrome)
        results = run_checks(settings)
        assert labels(results)[-1] == hermes_doctor.HERMES_ATTACHES
        assert "cannot create target" in results[-1].detail


def test_a_throwaway_tab_that_will_not_close_does_not_fail_the_check(
    tmp_path: Path, fake: FakeHermes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tidying up is best effort: the check is about Hermes, not about the tab."""

    def broken_id(inner: FakeChrome, call: Call) -> dict[str, object] | None:
        if call.method == "Target.createTarget":
            inner.targets.append(FakeTarget(id=BROKEN_TARGET, url="about:blank"))
            return {"result": {"targetId": BROKEN_TARGET}}
        return None

    with FakeChrome(
        targets=[
            FakeTarget(id="page-1", url="https://claude.ai/new", evaluate=page_state())
        ],
        responder=broken_id,
    ) as chrome:
        settings = make_settings(tmp_path, fake, chrome)
        profiling.run_setup(settings)
        adopt_instead(monkeypatch, chrome)
        results = run_checks(settings)
        assert labels(results) == list(hermes_doctor.LABELS)
        assert all(check.ok for check in results)


def test_a_failing_helper_task_is_reported_as_that_check(
    tmp_path: Path,
    fake: FakeHermes,
    chrome: FakeChrome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first task works and the second one dies: only the second line fails."""
    settings = make_settings(tmp_path, fake, chrome)
    profiling.run_setup(settings)
    fake.write(
        version="hermes 1.0.0",
        config_extra={"agent.model": MODEL},
        answer=ANSWER,
        append_probe=True,
        exits=[0, 1],
    )
    adopt_instead(monkeypatch, chrome)
    results = run_checks(settings)
    assert labels(results)[-1] == hermes_doctor.HERMES_HELPER
    assert "hermes exited 1" in results[-1].detail
    assert results[-2].ok
