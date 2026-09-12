"""The semantic probe: one question, asked in a chat this migration made.

§18's third question — does Claude understand the reconstructed history? — is the
only one of the six that cannot be answered by counting. So `20` asks: after a
pilot run, every `completed` conversation gets one follow-up message in its new
chat, `In one sentence, what did we discuss in this conversation?`, and the reply
is what a person grades. This module sends that message and writes the replies
down.

It is deliberately the smallest thing that can produce the evidence:

- **The question is a file, not a string in a prompt.** It reaches the composer
  through `browser paste --seed`, byte for byte, exactly as a seed does — so the
  skill's rule 3 holds unchanged and the same helper that proved a seed landed
  proves this did.
- **One extra message, in one chat, and nothing else.** §17's boundary is the
  chats this run created, and a follow-up in one of them is inside it. The skill
  says so in one sentence, which is the whole of what `20` added to it.
- **The reply is content, and is treated as content.** It is written to
  `<workspace>/pilot/probes.json` and goes nowhere else: not to stdout, not to a
  log record, not into the report. What this module prints is a short id, an
  outcome and a character count.

The reply does pass through Hermes's output tokens, which nothing else in this
tool does — a seed never does, and `11` forbids quoting a message. It is the one
exception `20` makes and it is made here, for a reason that does not generalise:
the reply is three dozen characters Claude wrote about a chat we created, in a
throwaway account, and the alternative — a helper that returns page text — would
put a way of reading any message on the page into the hands of every step of
every migration.

What this module does not do is judge the replies. A person grades them in
`docs/experiment-01.md`; `judge` is the optional second opinion, and it reads
this file rather than asking anything again.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from dataporter import log, render, state
from dataporter import verify as verifying
from dataporter.config import Settings
from dataporter.errors import HermesError
from dataporter.hermes import prompt as prompting
from dataporter.hermes import runner as hermes_running
from dataporter.state import ConversationState, Instant, MigrationState, Status

_logger = log.get_logger(__name__)

QUESTION = "In one sentence, what did we discuss in this conversation?"
"""§20's probe, exactly. One sentence asked of one chat, the same for every
conversation, so that a weak answer is a fact about the migration and not about
how the question was phrased this time."""

QUESTION_FILENAME = "question.txt"
PROBES_FILENAME = "probes.json"

RUN_PREFIX = "probe-"
"""What a probe's Hermes run is called in `<workspace>/hermes/`. Distinct from a
migration's run id so a transcript can be told apart from one `12` produced."""

ANSWERED = "answered"
"""The one outcome that produces evidence. The other three are why it did not."""

WRONG_CHAT = "answered in another chat: {reported}"
"""Why a reply that arrived is not recorded (`Prober.ask`)."""


# --------------------------------------------------------------------------- #
# What one probe run answers with
# --------------------------------------------------------------------------- #


class ProbeResult(BaseModel):
    """The last JSON object a probe run prints, validated.

    `extra="ignore"` for `HermesResult`'s reason: the producer is an agent, and a
    run that did the work and added a field of its own has still answered.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    outcome: Literal["answered", "failed", "needs_human", "rate_limited"]
    conversation_id: str | None = None
    reply: str = ""
    """What the chat replied. Content: never logged, never printed."""
    error: str = ""
    """Why there is no reply, in the agent's own words. Never content."""


class ProbeModel(BaseModel):
    """Base for `probes.json`: immutable, and closed. `plan.PlanModel`'s rule."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Verdict(ProbeModel):
    """What `judge` made of one reply (`20`, the `judge` extra).

    `score` is §20's three grades, which are also the ones a person uses, so the
    two columns of the write-up are comparable without a translation.
    """

    score: Literal["pass", "weak", "fail"]
    reason: str = ""
    """One line. May quote the reply, so it stays in this file."""
    model: str = ""
    """What graded it. A verdict with no model beside it is not reproducible."""


class Probe(ProbeModel):
    """One conversation, asked once."""

    conversation_uuid: str
    short_id: str
    conversation_id: str
    outcome: Literal["answered", "failed", "needs_human", "rate_limited"]
    reply: str = ""
    error: str = ""
    asked_at: Instant
    verdict: Verdict | None = None
    """`judge`'s, when it has been run. The hand grade lives in
    `docs/experiment-01.md`, where §20 puts it: a number in a write-up somebody
    signed is worth more than a field nobody can see."""

    @property
    def answered(self) -> bool:
        return self.outcome == ANSWERED and bool(self.reply.strip())

    def line(self) -> str:
        """One probe's line of output. A count, never the reply (§10)."""
        if self.answered:
            return f"{self.short_id}  {ANSWERED}  chars={len(self.reply)}"
        return f"{self.short_id}  FAILED  {self.error or self.outcome}"


class ProbeFile(ProbeModel):
    """`<workspace>/pilot/probes.json`: the question, and every answer to it."""

    question: str = QUESTION
    probes: list[Probe] = []

    def replace(self, probe: Probe) -> "ProbeFile":
        """This file with `probe`'s conversation answered afresh.

        A probe re-run overwrites its own record rather than appending a second
        one: the question is the same question, and two answers in the file would
        leave a write-up to choose between them. In place, where the
        conversation is already in the file, so that re-asking one of ten does
        not reorder the other nine.
        """
        probes = list(self.probes)
        for position, item in enumerate(probes):
            if item.conversation_uuid == probe.conversation_uuid:
                probes[position] = probe
                break
        else:
            probes.append(probe)
        return self.model_copy(update={"probes": probes})


# --------------------------------------------------------------------------- #
# The file
# --------------------------------------------------------------------------- #


def probes_path(settings: Settings) -> Path:
    return settings.pilot_dir / PROBES_FILENAME


def question_path(settings: Settings) -> Path:
    return settings.pilot_dir / QUESTION_FILENAME


def read(settings: Settings) -> ProbeFile:
    """`probes.json`, or an empty one. A missing file is not an error: the first
    probe run is what creates it, and `judge` reports nothing to grade."""
    try:
        text = probes_path(settings).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ProbeFile()
    try:
        return ProbeFile.model_validate_json(text)
    except ValidationError as exc:
        raise state.StateError(
            f"{probes_path(settings)} is not a probe file: {_describe(exc)}"
        ) from exc


def write(settings: Settings, file: ProbeFile) -> Path:
    """Write the whole file atomically, as every other workspace file is.

    Newline-terminated, because `state._dump` and `19`'s `report.json` are: one
    convention for the workspace's JSON keeps its diffs quiet and its files
    readable by the line-oriented tools an operator reaches for. (Raised by
    Copilot in review on #29.)
    """
    target = probes_path(settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    state.write_atomically(target, file.model_dump_json(indent=2) + "\n")
    return target


def write_question(settings: Settings, question: str = QUESTION) -> Path:
    """The question, as the file the helper pastes from.

    `newline=""` and UTF-8, exactly as `04` writes a seed part: what the composer
    ends up holding is compared against a hash of these bytes.
    """
    target = question_path(settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(question, encoding="utf-8", newline="")
    return target


def _describe(exc: ValidationError) -> str:
    """`loc: msg`, with the offending value left out — it may be a reply."""
    return "; ".join(
        f"{'.'.join(str(item) for item in error['loc']) or '(root)'}: {error['msg']}"
        for error in exc.errors()
    )


# --------------------------------------------------------------------------- #
# Who gets asked
# --------------------------------------------------------------------------- #


def in_the_right_chat(result: ProbeResult, conversation_id: str) -> ProbeResult:
    """`result`, or a failure when it says it answered somewhere else.

    The agent is told which chat to ask in and reports which chat it asked in,
    and those two disagreeing is the one way a probe can produce a reply that is
    evidence about the wrong conversation — which is worse than no evidence,
    because nothing downstream could tell. So the reply is dropped rather than
    filed: it belongs to a chat this record does not describe, and it is
    somebody else's conversation as far as this row is concerned.

    A result that names no chat at all is left alone. It is not evidence of a
    wrong chat, only of an agent that did not say — and the reply it carries is
    still the answer to a question asked in the chat the prompt named.
    (Raised by Copilot in review on #29.)
    """
    reported = result.conversation_id
    if not reported or reported == conversation_id:
        return result
    return ProbeResult(
        outcome="failed",
        conversation_id=reported,
        error=WRONG_CHAT.format(reported=log.safe_token(reported)),
    )


def probeable(migration: MigrationState) -> Iterator[tuple[str, ConversationState]]:
    """Every `completed` entry with a chat to ask in, in `state.json`'s order.

    `completed` only, which is §20's word: a `partial` chat is missing part of
    the conversation, so what Claude does or does not remember about it says
    nothing about whether a *migrated* conversation is understood.
    """
    for uuid, entry in migration.items():
        if entry.status is Status.COMPLETED and entry.destination.conversation_id:
            yield uuid, entry


# --------------------------------------------------------------------------- #
# The prompt
# --------------------------------------------------------------------------- #

HEAD = (
    "Use the skill `claude-migrate` (load it with skill_view before acting). This is\n"
    "a follow-up probe and not a migration: ask one question in one chat this\n"
    "migration created, and report the answer.\n"
)

TAIL = """\
Procedure, in this order, verifying each step as the skill says: navigate to the chat
url; `<helper> probe` must report composer_present true and this conversation_id. Insert
question with `<helper> paste --seed <question file>` — never type it yourself — submit
it, and wait with `<helper> await-response`. Take one browser_snapshot and copy the last
assistant message into `reply`, verbatim and whole; that message is the answer to this
question and is the one message this task may quote.

Ask once. Do not retry the question, do not ask anything else, do not rename, and do not
open another chat. If the page is not in the state a step needs, stop and report.

Print exactly one JSON object as the last thing you output, and nothing after it:
{"outcome": "answered", "conversation_id": "<the chat's uuid>", "reply": "<the reply>"}
`outcome` is `answered`, `failed`, `needs_human` or `rate_limited`; anything but
`answered` carries `error` saying what stopped it, in your own words and with no message
in it.
"""


def prompt(
    *, short_id: str, conversation_id: str, question_file: Path, workspace: Path
) -> str:
    """One probe's task prompt. Names files and ids, as `11`'s prompt does."""
    return "\n".join(
        [
            HEAD,
            f"short_id: {short_id}",
            f"conversation_id: {conversation_id}",
            f"chat url: {verifying.chat_url(conversation_id)}",
            f"question file: {question_file}",
            f"helper: {prompting.helper_command(workspace)}",
            "",
            TAIL,
        ]
    )


# --------------------------------------------------------------------------- #
# Asking
# --------------------------------------------------------------------------- #


class Prober:
    """Runs one probe per conversation, through Hermes, and records the answer.

    No browser of its own: the caller opens one and proves it is signed in, for
    the reason `verify` does — the probe is a question about the account, and the
    thing that opens the account is the thing that should have checked it.
    """

    def __init__(
        self, settings: Settings, *, runner: hermes_running.HermesRunner | None = None
    ) -> None:
        self.settings = settings
        self.runner = (
            runner if runner is not None else hermes_running.HermesRunner(settings)
        )
        self.question_file = write_question(settings)

    def ask(self, uuid: str, entry: ConversationState) -> Probe:
        """Ask one chat, and say what came back. Never raises for a probe that
        failed: a run that could not get an answer is a row of the write-up, and
        nine more conversations are waiting behind it."""
        short_id = render.short_id(uuid)
        conversation_id = entry.destination.conversation_id or ""
        text = prompt(
            short_id=short_id,
            conversation_id=conversation_id,
            question_file=self.question_file,
            workspace=self.settings.workspace,
        )
        try:
            result = self._run(text, short_id)
        except HermesError as exc:
            result = ProbeResult(outcome="failed", error=exc.detail or "hermes failed")
        result = in_the_right_chat(result, conversation_id)
        _logger.info(
            "probe",
            extra={
                "conversation_id": short_id,
                "outcome": result.outcome,
                # A length, never the reply itself.
                "reply_chars": len(result.reply),
            },
        )
        return Probe(
            conversation_uuid=uuid,
            short_id=short_id,
            conversation_id=conversation_id,
            outcome=result.outcome,
            reply=result.reply,
            error=result.error,
            asked_at=state.now(),
        )

    def _run(self, text: str, short_id: str) -> ProbeResult:
        """The subprocess, and the object it printed last.

        `run_raw` rather than `run`: the result contract here is this module's,
        not `09`'s, and a probe that answered `answered` is not a migration
        outcome. The scan for it is `09`'s, though — the last object carrying
        `outcome` — because a transcript holds our own helpers' objects too.
        """
        raw = self.runner.run_raw(
            text,
            run_id=f"{RUN_PREFIX}{short_id}",
            timeout_s=self.settings.timeouts.hermes_task_s,
        )
        payload = hermes_running.last_result_object(raw.stdout)
        if payload is None:
            raise HermesError(detail=f"no result json; stdout: {raw.stdout_path}")
        try:
            return ProbeResult.model_validate(payload)
        except ValidationError as exc:
            raise HermesError(
                detail=f"invalid probe json: {_describe(exc)}; "
                f"stdout: {raw.stdout_path}"
            ) from exc
