"""The optional second opinion, and what it is allowed to say.

`20` grades every probe reply by hand and, optionally, again with a model. This
module covers the second half: what the judge is shown, what a verdict becomes,
and what happens on a machine that never installed the extra — which is most of
them, including the one this suite runs on. `pydantic-ai` is therefore never
imported here; `grader` is the one function that would import it, and what is
tested is that it says so rather than that it works.

The grading itself is a function passed in, which is why the loop can be tested
at all: a judge that could only be exercised with a key and a network would be a
judge nobody ran twice.
"""

from pathlib import Path
from types import ModuleType
from typing import Literal

import pytest
from typer.testing import CliRunner

from dataporter import cli, state
from dataporter import followup as following
from dataporter import judge as judging
from dataporter.config import JudgeSettings, Settings
from dataporter.exit_codes import ExitCode
from dataporter.followup import Probe, ProbeFile, Verdict
from dataporter.state import now

FIRST = "aa000001-1111-4111-8111-111111111111"
CHAT = "b6f0a2d4-1c88-4e3a-9a1f-2f0e5d7c8b91"
OTHER = "bb000002-2222-4222-8222-222222222222"
REPLY = "We talked about listing files in a directory from Python."

Score = Literal["pass", "weak", "fail"]


def settings_for(tmp_path: Path, **fields: object) -> Settings:
    return Settings(workspace=tmp_path / "migration", **fields)


def probe(**fields: object) -> Probe:
    payload: dict[str, object] = {
        "conversation_uuid": FIRST,
        "short_id": "aa000001",
        "conversation_id": CHAT,
        "outcome": "answered",
        "reply": REPLY,
        "asked_at": now(),
    }
    payload.update(fields)
    return Probe.model_validate(payload)


def seeded(settings: Settings, *parts: str) -> None:
    """A conversation's seed on disk, as `04` writes it."""
    directory = settings.seeds_dir / FIRST
    directory.mkdir(parents=True, exist_ok=True)
    for index, text in enumerate(parts, start=1):
        (directory / f"part-{index:02d}.txt").write_text(text, encoding="utf-8")


def grading(
    score: Score = "pass", reason: str = "about the right conversation"
) -> tuple[judging.Grader, list[str]]:
    """A grader that answers the same way every time, and remembers what it saw."""
    seen: list[str] = []

    def grade(text: str) -> judging.FidelityVerdict:
        seen.append(text)
        return judging.FidelityVerdict(score=score, reason=reason)

    return grade, seen


# --------------------------------------------------------------------------- #
# What the judge is shown
# --------------------------------------------------------------------------- #


def test_the_source_is_the_seed_parts_in_order(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    seeded(settings, "part one", "part two")

    assert judging.source_text(settings, FIRST) == "part one\n\npart two"


def test_the_source_is_capped(tmp_path: Path) -> None:
    """A judge handed forty kilobytes is being asked to read the conversation
    rather than to recognise it."""
    settings = settings_for(tmp_path, judge=JudgeSettings(max_seed_chars=4))
    seeded(settings, "part one")

    assert judging.source_text(settings, FIRST) == "part"


def test_a_conversation_with_no_seed_on_disk_has_no_source(tmp_path: Path) -> None:
    assert judging.source_text(settings_for(tmp_path), FIRST) == ""


def test_the_comparison_labels_both_halves() -> None:
    assert judging.comparison("source", "reply") == (
        "<transcript>\nsource\n</transcript>\n\n<answer>\nreply\n</answer>"
    )


# --------------------------------------------------------------------------- #
# One verdict
# --------------------------------------------------------------------------- #


def test_a_reply_is_graded_against_its_own_seed(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    seeded(settings, "User: how do I list files?")
    grade, seen = grading("weak", "vague")

    found = judging.verdict_for(settings, probe(), grade=grade)

    assert found == Verdict(score="weak", reason="vague", model=settings.judge.model)
    assert "how do I list files?" in seen[0]
    assert REPLY in seen[0]


def test_a_probe_that_never_got_an_answer_is_not_graded(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    seeded(settings, "User: how do I list files?")
    grade, seen = grading()

    assert (
        judging.verdict_for(settings, probe(outcome="failed", reply=""), grade=grade)
        is None
    )
    assert seen == []


def test_a_reply_with_no_seed_to_check_it_against_is_not_graded(
    tmp_path: Path,
) -> None:
    """A verdict on a reply with no source would be a judgement of how plausible
    a sentence sounds, which is the one number nobody could check."""
    grade, seen = grading()

    assert judging.verdict_for(settings_for(tmp_path), probe(), grade=grade) is None
    assert seen == []


def test_a_line_carries_the_score_and_never_the_reason() -> None:
    verdict = Verdict(score="fail", reason="it summarised a different chat")

    assert judging.line(probe(), verdict) == "aa000001  fail"


def test_an_ungraded_probe_says_why() -> None:
    assert judging.line(probe(), None) == f"aa000001  not graded  {judging.NO_SOURCE}"
    assert (
        judging.line(probe(outcome="failed", reply="", error="response_timeout"), None)
        == "aa000001  not graded  response_timeout"
    )


# --------------------------------------------------------------------------- #
# The extra, and the key
# --------------------------------------------------------------------------- #


def test_without_the_extra_the_judge_says_what_to_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(name: str) -> ModuleType:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(judging.importlib, "import_module", missing)

    with pytest.raises(judging.JudgeError) as raised:
        judging.grader(settings_for(tmp_path))

    assert str(raised.value) == judging.NO_EXTRA


def test_with_the_extra_and_no_key_it_says_which_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The key is Hermes's own, and this tool reads neither of them (§17): the
    one thing it does is notice that there is not one."""
    monkeypatch.setattr(
        judging.importlib, "import_module", lambda name: ModuleType(name)
    )
    monkeypatch.delenv(judging.API_KEY_ENV, raising=False)

    with pytest.raises(judging.JudgeError) as raised:
        judging.grader(settings_for(tmp_path))

    assert str(raised.value) == judging.NO_KEY


def test_the_agent_is_built_from_the_configured_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What `20` specifies: an `Agent` with `output_type=FidelityVerdict`. The
    package is stood in for, because it is an extra and this suite has not got
    it — what is checked is the call, which is the part that is ours."""
    built: dict[str, object] = {}

    class Agent:
        def __init__(self, model: str, **kwargs: object) -> None:
            built["model"] = model
            built.update(kwargs)

        def run_sync(self, text: str) -> object:
            built["text"] = text
            return type("Run", (), {"output": {"score": "pass", "reason": "yes"}})()

    module = ModuleType("pydantic_ai")
    module.Agent = Agent  # type: ignore[attr-defined]
    monkeypatch.setattr(judging.importlib, "import_module", lambda name: module)
    monkeypatch.setenv(judging.API_KEY_ENV, "not-a-real-key")

    grade = judging.grader(settings_for(tmp_path))
    found = grade("the comparison")

    assert built["model"] == "anthropic:claude-sonnet-5"
    assert built["output_type"] is judging.FidelityVerdict
    assert built["text"] == "the comparison"
    assert found == judging.FidelityVerdict(score="pass", reason="yes")


# --------------------------------------------------------------------------- #
# Through the command
# --------------------------------------------------------------------------- #


def test_judge_with_no_probes_exits_4(runner: CliRunner, workspace: Path) -> None:
    """`followup` is what produces the replies; grading none is not a graded
    experiment, and it is not the extra's fault either — so this comes first."""
    result = runner.invoke(cli.app, ["judge"], catch_exceptions=False)

    assert result.exit_code == ExitCode.NOTHING_TO_DO


def test_judge_does_not_report_nothing_to_grade_while_the_workspace_is_locked(
    runner: CliRunner, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lock is taken before `probes.json` is read, not only around the
    writes: a `followup` filling the file in the middle of this would have the
    judge report "nothing to grade" about replies that were arriving as it
    looked. A busy workspace is exit `2`. (Raised by Copilot in review on
    #29.)"""
    settings = Settings(workspace=workspace / "migration")
    monkeypatch.setenv("HCM_WORKSPACE", str(settings.workspace))
    lock = state.WorkspaceLock(settings.workspace)
    lock.acquire()
    try:
        result = runner.invoke(cli.app, ["judge"], catch_exceptions=False)
    finally:
        lock.release()

    assert result.exit_code == ExitCode.USAGE
    assert "locked" in result.stderr


def test_judge_without_the_extra_exits_6(
    runner: CliRunner, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(workspace=workspace / "migration")
    following.write(settings, ProbeFile(probes=[probe()]))

    def missing(name: str) -> ModuleType:
        raise ImportError(name)

    monkeypatch.setattr(judging.importlib, "import_module", missing)
    monkeypatch.setenv("HCM_WORKSPACE", str(settings.workspace))

    result = runner.invoke(cli.app, ["judge"], catch_exceptions=False)

    assert result.exit_code == ExitCode.ENVIRONMENT
    assert result.stderr == f"error: {judging.NO_EXTRA}\n"


def test_judge_only_grades_the_conversation_it_names(
    runner: CliRunner, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(workspace=workspace / "migration")
    seeded(settings, "User: how do I list files?")
    other = probe(conversation_uuid=OTHER, short_id="bb000002")
    following.write(settings, ProbeFile(probes=[probe(), other]))
    grade, _ = grading()
    monkeypatch.setattr(judging, "grader", lambda settings: grade)
    monkeypatch.setenv("HCM_WORKSPACE", str(settings.workspace))

    result = runner.invoke(
        cli.app, ["judge", "--only", "aa000001"], catch_exceptions=False
    )

    assert result.stdout == "aa000001  pass\n"
    graded = following.read(settings).probes
    assert graded[0].verdict is not None
    # The one it was not asked about is left exactly as it was.
    assert graded[1] == other


def test_judge_writes_a_verdict_beside_every_reply(
    runner: CliRunner, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(workspace=workspace / "migration")
    seeded(settings, "User: how do I list files?")
    following.write(settings, ProbeFile(probes=[probe()]))
    grade, _ = grading("pass", "names the subject")
    monkeypatch.setattr(judging, "grader", lambda settings: grade)
    monkeypatch.setenv("HCM_WORKSPACE", str(settings.workspace))

    result = runner.invoke(cli.app, ["judge"], catch_exceptions=False)

    assert result.exit_code == ExitCode.OK
    assert result.stdout == "aa000001  pass\n"
    graded = following.read(settings).probes[0].verdict
    assert graded is not None
    assert graded.score == "pass"
    assert graded.model == settings.judge.model
    # The reason is in the file and not on the terminal: it is one sentence
    # about somebody's conversation (§10).
    assert "names the subject" not in result.stdout
