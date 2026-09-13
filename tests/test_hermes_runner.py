"""One Hermes run: its command line, its files, its deadline and its answer."""

import json
import time
from pathlib import Path

import pytest

from dataporter.config import HermesSettings, Settings
from dataporter.errors import Category, HermesError, HermesUsageError
from dataporter.hermes import runner as hermes_runner
from dataporter.hermes.runner import HermesResult, HermesRunner
from dataporter.steps import Step
from fake_hermes import FakeHermes

pytestmark = pytest.mark.slow
"""Slow all the way through: the subject is a subprocess — its deadline, its
output, its process group.
"""

RESULT = {
    "outcome": "completed",
    "conversation_id": "2f1c5a6e-0b0c-4f26-9a1e-8a7d3f0c1b22",
    "last_step": "done",
    "chunks_acked": 2,
    "actions": 17,
}


def make_settings(tmp_path: Path, executable: Path) -> Settings:
    return Settings(
        workspace=tmp_path / "migration",
        hermes=HermesSettings(executable=executable),
    )


def runner_for(tmp_path: Path, fake: FakeHermes) -> HermesRunner:
    return HermesRunner(make_settings(tmp_path, fake.executable))


@pytest.fixture
def fake(tmp_path: Path) -> FakeHermes:
    return FakeHermes(root=tmp_path / "bin")


# --------------------------------------------------------------------------- #
# The command line `09` specifies
# --------------------------------------------------------------------------- #


def test_the_command_line_is_the_one_the_spec_names(tmp_path: Path, fake: FakeHermes) -> None:
    fake.write(answer=json.dumps(RESULT))
    runner = runner_for(tmp_path, fake)
    runner.run("do the thing", run_id="c0ffee01", timeout_s=30)

    call = fake.one_shots[0]
    assert call.argv[:4] == ["-p", "dataporter", "-z", "do the thing"]
    assert call.flag("--toolsets") == "browser,terminal"
    assert call.flag("--usage-file") == str(runner.usage_path("c0ffee01"))
    # cwd=<workspace>, which is also why DATAPORTER_WORKSPACE has to be set:
    # `./migration` resolved from here would be a second workspace one level down.
    assert call.cwd == str(tmp_path / "migration")
    assert call.env["DATAPORTER_WORKSPACE"] == str(tmp_path / "migration")


def test_stdout_and_stderr_land_in_the_workspace(tmp_path: Path, fake: FakeHermes) -> None:
    fake.write(answer=f"chatter\n{json.dumps(RESULT)}\n", stderr="a warning\n")
    runner = runner_for(tmp_path, fake)
    raw = runner.run_raw("go", run_id="run-1", timeout_s=30)

    assert raw.stdout_path == tmp_path / "migration" / "hermes" / "run-1.stdout.txt"
    assert "chatter" in raw.stdout_path.read_text(encoding="utf-8")
    assert raw.stderr_path.read_text(encoding="utf-8") == "a warning\n"
    assert raw.returncode == 0


def test_a_run_id_that_is_not_a_filename_is_refused(tmp_path: Path, fake: FakeHermes) -> None:
    """It becomes three file names, and `12` derives it from an export."""
    fake.write(answer=json.dumps(RESULT))
    runner = runner_for(tmp_path, fake)
    for bad in ("../escape", "a/b", "", "with space", "." * 3):
        with pytest.raises(ValueError, match="not a usable run id"):
            runner.run(".", run_id=bad, timeout_s=5)


def test_the_toolsets_come_from_configuration(tmp_path: Path, fake: FakeHermes) -> None:
    fake.write(answer=json.dumps(RESULT))
    settings = Settings(
        workspace=tmp_path / "migration",
        hermes=HermesSettings(executable=fake.executable, toolsets=("browser",)),
    )
    HermesRunner(settings).run_raw("go", run_id="r", timeout_s=30)
    assert fake.one_shots[0].flag("--toolsets") == "browser"


# --------------------------------------------------------------------------- #
# The result contract
# --------------------------------------------------------------------------- #


def test_a_fenced_object_after_chatter_validates(tmp_path: Path, fake: FakeHermes) -> None:
    """`09`'s acceptance criterion, almost verbatim."""
    fake.write(
        answer=(
            "I will migrate the conversation now.\n"
            "Calling browser_snapshot...\n"
            "```json\n" + json.dumps(RESULT, indent=2) + "\n```\n"
            "Done.\n"
        )
    )
    result = runner_for(tmp_path, fake).run("go", run_id="r", timeout_s=30)
    assert isinstance(result, HermesResult)
    assert result.outcome == "completed"
    assert result.chunks_acked == 2
    assert result.actions == 17


def test_a_bare_object_validates_too(tmp_path: Path, fake: FakeHermes) -> None:
    fake.write(answer=json.dumps(RESULT))
    assert runner_for(tmp_path, fake).run("go", run_id="r", timeout_s=30).last_step == ("done")


def test_a_helper_object_in_the_transcript_is_not_the_result(tmp_path: Path, fake: FakeHermes) -> None:
    """Our own helpers print JSON and Hermes quotes it.

    "the last object" is not a safe rule. The last object carrying `outcome` is.
    """
    fake.write(
        answer=(
            json.dumps(RESULT) + "\nThe helper said: " + json.dumps({"ok": True, "chars": 120, "sha256": "ab"}) + "\n"
        )
    )
    result = runner_for(tmp_path, fake).run("go", run_id="r", timeout_s=30)
    assert result.outcome == "completed"


def test_the_last_result_wins_when_there_are_two(tmp_path: Path, fake: FakeHermes) -> None:
    first = {**RESULT, "outcome": "partial", "chunks_acked": 1}
    fake.write(answer=f"{json.dumps(first)}\nthen I finished\n{json.dumps(RESULT)}\n")
    assert runner_for(tmp_path, fake).run("go", run_id="r", timeout_s=30).outcome == ("completed")


def test_no_object_at_all_is_transient_and_names_the_file(tmp_path: Path, fake: FakeHermes) -> None:
    fake.write(answer="I could not work out what to do.\n")
    runner = runner_for(tmp_path, fake)
    with pytest.raises(HermesError, match="no result json") as caught:
        runner.run("go", run_id="r", timeout_s=30)
    assert caught.value.transient is True
    assert str(runner.stdout_path("r")) in caught.value.detail


def test_an_object_that_is_not_a_result_is_still_no_result(tmp_path: Path, fake: FakeHermes) -> None:
    fake.write(answer=json.dumps({"ok": True}) + "\n")
    with pytest.raises(HermesError, match="no result json"):
        runner_for(tmp_path, fake).run("go", run_id="r", timeout_s=30)


def test_a_result_with_a_bad_field_is_not_silently_replaced(tmp_path: Path, fake: FakeHermes) -> None:
    """An earlier, valid result must not stand in for a malformed final answer."""
    good = json.dumps(RESULT)
    bad = json.dumps({**RESULT, "outcome": "nearly"})
    fake.write(answer=f"{good}\n{bad}\n")
    with pytest.raises(HermesError, match="invalid result json: outcome"):
        runner_for(tmp_path, fake).run("go", run_id="r", timeout_s=30)


def test_a_missing_required_field_is_reported_by_name(tmp_path: Path, fake: FakeHermes) -> None:
    fake.write(answer=json.dumps({"outcome": "completed"}))
    with pytest.raises(HermesError, match="invalid result json: last_step"):
        runner_for(tmp_path, fake).run("go", run_id="r", timeout_s=30)


def test_unknown_fields_do_not_fail_a_good_run(tmp_path: Path, fake: FakeHermes) -> None:
    fake.write(answer=json.dumps({**RESULT, "notes": "I also tidied up"}))
    assert runner_for(tmp_path, fake).run("go", run_id="r", timeout_s=30).outcome == ("completed")


def test_a_step_name_is_read_as_one_of_11s_steps(tmp_path: Path, fake: FakeHermes) -> None:
    fake.write(answer=json.dumps(RESULT))
    assert runner_for(tmp_path, fake).run("go", run_id="r", timeout_s=30).step is (Step.DONE)


def test_a_step_name_that_is_not_one_costs_nothing_else(tmp_path: Path, fake: FakeHermes) -> None:
    """An agent that reported where it got to in its own words still reported the outcome, the id and the count.

    `12` records `step`, which is `None`.
    """
    invented = {**RESULT, "outcome": "partial", "last_step": "await_response_part_2"}
    fake.write(answer=json.dumps(invented))
    result = runner_for(tmp_path, fake).run("go", run_id="r", timeout_s=30)
    assert result.outcome == "partial"
    assert result.last_step == "await_response_part_2"
    assert result.step is None


def test_a_needs_human_result_carries_its_reason(tmp_path: Path, fake: FakeHermes) -> None:
    fake.write(
        answer=json.dumps({
            "outcome": "needs_human",
            "conversation_id": None,
            "last_step": "open",
            "needs_human_reason": "auth_required",
            "error": {"category": "auth", "detail": "login page"},
        })
    )
    result = runner_for(tmp_path, fake).run("go", run_id="r", timeout_s=30)
    assert result.needs_human_reason == "auth_required"
    assert result.error is not None
    assert result.error.category is Category.AUTH


def test_every_needs_human_reason_the_spec_names_validates(tmp_path: Path, fake: FakeHermes) -> None:
    for reason in hermes_runner.NEEDS_HUMAN_REASONS:
        payload = {**RESULT, "outcome": "needs_human", "needs_human_reason": reason}
        assert HermesResult.model_validate(payload).needs_human_reason == reason


def test_a_rate_limited_result_carries_its_wait(tmp_path: Path, fake: FakeHermes) -> None:
    fake.write(answer=json.dumps({**RESULT, "outcome": "rate_limited", "retry_after_s": 900}))
    assert runner_for(tmp_path, fake).run("go", run_id="r", timeout_s=30).retry_after_s == (900)


def test_objects_are_found_inside_prose_and_nesting() -> None:
    text = 'before { not json } then {"outcome": "failed", "a": {"b": 1}} after'
    found = hermes_runner.json_objects(text)
    assert found == [{"outcome": "failed", "a": {"b": 1}}]
    assert hermes_runner.last_result_object(text) == found[0]


# --------------------------------------------------------------------------- #
# Exit codes and deadlines
# --------------------------------------------------------------------------- #


def test_exit_two_is_never_worth_retrying(tmp_path: Path, fake: FakeHermes) -> None:
    fake.write(answer=json.dumps(RESULT), exit=2, stderr="unknown flag --toolsets\n")
    runner = runner_for(tmp_path, fake)
    with pytest.raises(HermesUsageError, match="rejected the invocation") as caught:
        runner.run("go", run_id="r", timeout_s=30)
    assert caught.value.transient is False
    assert caught.value.category is Category.HERMES
    assert str(runner.stderr_path("r")) in caught.value.detail


def test_another_non_zero_exit_with_a_valid_result_is_the_result(tmp_path: Path, fake: FakeHermes) -> None:
    """An agent that said `failed` and then exited 1 has already told us."""
    fake.write(answer=json.dumps({**RESULT, "outcome": "failed"}), exit=1)
    assert runner_for(tmp_path, fake).run("go", run_id="r", timeout_s=30).outcome == ("failed")


def test_a_non_zero_exit_with_no_result_says_so(tmp_path: Path, fake: FakeHermes) -> None:
    fake.write(answer="crashed\n", exit=1)
    with pytest.raises(HermesError, match=r"no result json.*hermes exited 1"):
        runner_for(tmp_path, fake).run("go", run_id="r", timeout_s=30)


def test_a_run_past_its_deadline_is_killed(tmp_path: Path, fake: FakeHermes) -> None:
    fake.write(answer=json.dumps(RESULT), sleep=60)
    runner = runner_for(tmp_path, fake)
    started = time.monotonic()
    with pytest.raises(HermesError, match="timeout after 1s") as caught:
        runner.run("go", run_id="r", timeout_s=1)
    assert time.monotonic() - started < 30
    assert caught.value.transient is True
    assert str(runner.stdout_path("r")) in caught.value.detail


CHILD_DELAY_S = 3.0
"""How long the fake's grandchild waits before writing its marker."""

SURVIVAL_MARGIN = 1.2
"""How far past that delay the test waits before calling the marker absent.

A margin, because the grandchild starts a moment after the run does and the
machine may be busy; 1.2 rather than the 2.0 this was written with, because the
whole of it is wall-clock the suite pays on every run and a fifth of the delay is
already longer than the one-second deadline that kills it.
"""


def test_the_whole_process_group_goes_not_just_the_leader(tmp_path: Path, fake: FakeHermes) -> None:
    """Hermes starts children — its own environment, our helpers, a browser.

    Judged by a file that must *not* appear: the grandchild writes it three
    seconds in, and the run is timed out after one. Absence rather than a pid
    probe, because a killed process whose parent is already gone is a zombie
    until somebody reaps it, and who that is depends on the container.
    """
    marker = tmp_path / "survivor"
    fake.write(answer="", sleep=60, child=str(marker), child_delay=CHILD_DELAY_S)
    with pytest.raises(HermesError, match="timeout"):
        runner_for(tmp_path, fake).run("go", run_id="r", timeout_s=1)

    time.sleep(CHILD_DELAY_S * SURVIVAL_MARGIN)
    assert not marker.exists(), "a process the run started outlived the kill"


# --------------------------------------------------------------------------- #
# The usage file
# --------------------------------------------------------------------------- #


def test_usage_is_read_from_the_file_hermes_was_given(tmp_path: Path, fake: FakeHermes) -> None:
    fake.write(
        answer=json.dumps(RESULT),
        usage={"usage": {"input_tokens": 1200, "output_tokens": 340}, "cost": 0.0412},
    )
    runner = runner_for(tmp_path, fake)
    raw = runner.run_raw("go", run_id="r", timeout_s=30)
    usage = raw.usage
    assert usage.input_tokens == 1200
    assert usage.output_tokens == 340
    assert usage.cost_usd == pytest.approx(0.0412)
    assert not usage.empty


def test_other_spellings_are_read_too(tmp_path: Path) -> None:
    path = tmp_path / "usage.json"
    path.write_text(
        json.dumps({"prompt_tokens": 10, "completion_tokens": 2, "total_cost_usd": 1.5}),
        encoding="utf-8",
    )
    usage = hermes_runner.read_usage(path)
    assert (usage.input_tokens, usage.output_tokens, usage.cost_usd) == (10, 2, 1.5)


def test_an_absent_usage_file_is_not_an_error(tmp_path: Path) -> None:
    assert hermes_runner.read_usage(tmp_path / "nope.json").empty


def test_a_usage_file_that_is_not_json_is_not_an_error(tmp_path: Path) -> None:
    path = tmp_path / "usage.json"
    path.write_text("<html>503</html>", encoding="utf-8")
    assert hermes_runner.read_usage(path).empty


def test_a_usage_file_that_is_not_an_object_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "usage.json"
    path.write_text(json.dumps([{"input_tokens": 5}]), encoding="utf-8")
    assert hermes_runner.read_usage(path).empty


def test_a_number_buried_too_deep_is_not_hunted_for(tmp_path: Path) -> None:
    """The search is bounded: a usage file is a report, not a tree to walk."""
    payload: dict[str, object] = {"input_tokens": 7}
    for _ in range(8):
        payload = {"wrapped": payload}
    path = tmp_path / "usage.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert hermes_runner.read_usage(path).empty


def test_a_boolean_is_not_a_token_count(tmp_path: Path) -> None:
    path = tmp_path / "usage.json"
    path.write_text(json.dumps({"input_tokens": True}), encoding="utf-8")
    assert hermes_runner.read_usage(path).input_tokens == 0


def test_a_run_that_cannot_start_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeHermes
) -> None:
    fake.write(answer="")
    runner = runner_for(tmp_path, fake)

    def refuse(*args: object, **kwargs: object) -> None:
        raise OSError("Exec format error")

    monkeypatch.setattr(hermes_runner.subprocess, "Popen", refuse)
    with pytest.raises(HermesUsageError, match="cannot run"):
        runner.run_raw("go", run_id="r", timeout_s=5)
