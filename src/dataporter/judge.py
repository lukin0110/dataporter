"""The optional second opinion on §18's third question.

A person grades every probe reply `pass`, `weak` or `fail` in
`docs/experiment-01.md`; that is the grade the experiment reports. This module
grades the same replies again with a model, records its verdicts beside the hand
ones, and exists mostly so that a *disagreement* between the two is visible —
which is itself a finding, and the reason §20 asks for both.

Three things keep it honest, and they are the reason it is one small module
behind an extra rather than a second agent loop in the middle of the tool:

- **It judges nothing that is counted.** Every §19 metric — chats created, parts
  acknowledged, retries, interventions — is a tally of things that happened.
  This grades one sentence about one conversation, and nothing downstream reads
  its answer.
- **It asks nothing of the account.** The replies are already in
  `<workspace>/pilot/probes.json` and the sources are already in
  `<workspace>/seeds/`; a `judge` run touches neither a browser nor Hermes.
- **`pydantic-ai` is not a runtime dependency.** It is imported inside the one
  function that needs it, so a build without the `judge` extra runs everything
  else and says exactly what to install when somebody asks for this.

Both halves of what it reads are content — a seed is the conversation and a reply
is a message — so the verdicts go back into `probes.json` and what reaches an
operator's terminal is a short id and one of three words.
"""

import importlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from dataporter import log
from dataporter import seed as seeding
from dataporter.config import Settings
from dataporter.followup import Probe, Verdict

_logger = log.get_logger(__name__)

API_KEY_ENV = "ANTHROPIC_API_KEY"
"""The key `pydantic-ai` authenticates with — the same variable Hermes's own
`.env` uses. Checked for presence and never read, printed or recorded (§17)."""

NO_EXTRA = (
    "the judge extra is not installed: uv sync --extra judge, "
    "or pip install 'dataporter[judge]'"
)
NO_KEY = f"{API_KEY_ENV} is not set; the judge grades with the key Hermes uses"
NO_SOURCE = "no seed on disk"
"""Why a probe cannot be graded: nothing to compare the reply against. Seeds are
rewritten by every run, so a workspace whose seeds were cleared can still hold
replies — and a verdict on a reply with no source would be a judgement of how
plausible a sentence sounds."""

INSTRUCTIONS = """\
You are grading one step of a chat-history migration experiment. A conversation was
moved into a new Claude chat by pasting a transcript of it, and the new chat was then
asked, in one sentence, what the conversation was about. You are given the transcript
that was pasted and the answer that came back.

Grade whether the answer shows that the history was understood:

- pass: the answer is about this conversation and gets its subject right.
- weak: the answer is about this conversation but is vague, partly wrong, or describes
  the transcript rather than the conversation in it.
- fail: the answer is about something else, says it cannot tell, or is empty.

Answer with the grade and one sentence of reason. Judge the answer only; do not comment
on the migration, the transcript's formatting, or how the question was phrased.
"""


class JudgeError(Exception):
    """The judge cannot run as asked. The CLI reports this as exit `6`.

    The environment row of `01`'s table, not the usage one: a missing extra and a
    missing key are both "this machine is not set up for that yet", which is what
    `doctor` is for everywhere else.
    """


class FidelityVerdict(BaseModel):
    """§20's `output_type`, exactly: a grade and a reason.

    Its own model rather than `followup.Verdict` because this one is a schema
    handed to a model and that one is a record with provenance on it: the model
    is not asked which model it is.
    """

    model_config = ConfigDict(frozen=True)

    score: Literal["pass", "weak", "fail"]
    reason: str = ""


Grader = Callable[[str], FidelityVerdict]
"""What grades one rendered comparison. Injected rather than constructed at the
call site so the loop can be tested without a network, a key or the extra."""


# --------------------------------------------------------------------------- #
# What the judge is shown
# --------------------------------------------------------------------------- #


def source_text(settings: Settings, conversation_uuid: str) -> str:
    """The seed this conversation was migrated from, capped, or `""`.

    The parts in order, joined the way they were sent. Capped at
    `judge.max_seed_chars` because the question is whether a one-sentence summary
    is about *this* conversation, which the opening of it settles.
    """
    directory = settings.seeds_dir / conversation_uuid
    try:
        parts = sorted(directory.glob(seeding.PART_GLOB))
    except OSError:  # pragma: no cover - a workspace we just wrote
        return ""
    text = "\n\n".join(_read(part) for part in parts)
    return text[: settings.judge.max_seed_chars]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:  # pragma: no cover - it was listed a moment ago
        return ""


def comparison(source: str, reply: str) -> str:
    """The two halves, labelled. What a person grading by hand reads, too."""
    return f"<transcript>\n{source}\n</transcript>\n\n<answer>\n{reply}\n</answer>"


# --------------------------------------------------------------------------- #
# Grading
# --------------------------------------------------------------------------- #


def grader(settings: Settings) -> Grader:
    """A grader backed by `pydantic-ai`, or a `JudgeError` saying what is missing.

    The import is here and nowhere else, and it is dynamic: `pydantic-ai` is an
    extra, so a module that imported it at the top would make `import
    dataporter.cli` fail on every machine that did not install it — and a static
    import of a package the dev environment does not have is an unresolved import
    to `ty`, which `make check` treats as an error. `importlib` asks the question
    at the only moment it can be answered.

    What comes back is validated through `FidelityVerdict` rather than trusted:
    the agent's `output` is typed `Any` from here, and the one value this module
    produces should not be.
    """
    try:
        module = importlib.import_module("pydantic_ai")
    except ImportError as exc:
        raise JudgeError(NO_EXTRA) from exc
    if not os.environ.get(API_KEY_ENV):
        raise JudgeError(NO_KEY)
    agent = module.Agent(
        settings.judge.model,
        output_type=FidelityVerdict,
        instructions=INSTRUCTIONS,
    )

    def grade(text: str) -> FidelityVerdict:
        return FidelityVerdict.model_validate(
            agent.run_sync(text).output, from_attributes=True
        )

    return grade


def verdict_for(settings: Settings, probe: Probe, *, grade: Grader) -> Verdict | None:
    """Grade one probe, or `None` when there is nothing to grade it against.

    `None` for a probe that never got an answer and for one whose seed is gone:
    both are rows of the write-up that say why there is no verdict, and a
    verdict invented for either would be the one number in `20` that nobody
    could check.
    """
    if not probe.answered:
        return None
    source = source_text(settings, probe.conversation_uuid)
    if not source.strip():
        return None
    found = grade(comparison(source, probe.reply))
    _logger.info(
        "judged",
        extra={"conversation_id": probe.short_id, "score": found.score},
    )
    return Verdict(score=found.score, reason=found.reason, model=settings.judge.model)


def line(probe: Probe, verdict: Verdict | None) -> str:
    """One conversation's line of `judge` output.

    The score and never the reason: a reason is one sentence about a
    conversation, which is content, and it is in `probes.json` where the other
    half of this experiment's evidence already lives.
    """
    if verdict is not None:
        return f"{probe.short_id}  {verdict.score}"
    reason = NO_SOURCE if probe.answered else (probe.error or probe.outcome)
    return f"{probe.short_id}  not graded  {reason}"
