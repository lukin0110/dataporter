"""An agent that is not an agent.

`11`'s acceptance criterion is that a run following the skill reaches `identify`
and comes back with a valid result. Hermes itself cannot be installed in CI, and
a stub that simply prints a result object would prove nothing about the
procedure, so this is the third thing: a scripted reader of the task prompt that
performs `11`'s steps in `11`'s order, with `11`'s verifications, against a
browser the test supplies.

What it is worth, and what it is not:

- it proves the **prompt** carries everything the procedure needs — nothing here
  is passed a seed, a part count or an ack line by the test, only the rendered
  string;
- it proves the **helpers** compose into a migration: every step goes through the
  real CLI and the real page model, so a helper that changed its error vocabulary
  or stopped clearing the composer fails here;
- it proves nothing about **Hermes**. A real agent has to decide when to act and
  can decide wrongly; this one cannot. `10`'s throwaway prompts and `20` are
  where that is measured.

The class deliberately has no judgement in it. Where the skill says "classify and
stop", this stops.
"""

import re
import shlex
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from dataporter.steps import Step

NEW_CHAT_URL = "https://claude.ai/new"
CHAT_URL = "https://claude.ai/chat/{uuid}"

SCALARS = (
    "short_id",
    "parts",
    "resume_from",
    "existing conversation_id",
    "parts already acknowledged",
    "helper",
)
BLOCKS = ("seed files", "attachments", "expected acknowledgements")
NONE = "none"

KEY_LINE = re.compile(r"^[a-z][a-z_ ]*:( |$)")
"""What ends a block: the next field. A seed path starts with a separator and an
acknowledgement line starts with `MIGRATION-ACK`, so neither can look like one."""


@dataclass(frozen=True)
class Task:
    """The task prompt, as the agent reads it."""

    short_id: str
    parts: int
    seed_files: tuple[str, ...]
    attachments: tuple[str, ...]
    acknowledgements: tuple[str, ...]
    resume_from: str
    conversation_id: str | None
    acknowledged: int
    helper: tuple[str, ...]
    """The helper command prefix, split into argv."""


def parse(prompt: str) -> Task:
    """Read the fields out of a rendered prompt.

    Written against the prompt's shape rather than against `prompt.py`'s
    constants on purpose: an agent gets a string, so if the string stops being
    readable this should be what says so.
    """
    fields: dict[str, Any] = {}
    lines = prompt.splitlines()
    position = 0
    while position < len(lines):
        line = lines[position]
        position += 1
        key, _, value = line.partition(": ")
        bare = line.rstrip(":")
        if key in SCALARS and value:
            fields[key] = value
            continue
        if bare in BLOCKS:
            collected: list[str] = []
            while position < len(lines):
                item = lines[position]
                if not item.strip() or KEY_LINE.match(item):
                    break
                collected.append(item)
                position += 1
            fields[bare] = collected
        elif key in BLOCKS and value == NONE:
            fields[key] = []
    helper = shlex.split(fields.get("helper", ""))
    conversation = fields.get("existing conversation_id", NONE)
    return Task(
        short_id=fields["short_id"],
        parts=int(fields["parts"]),
        seed_files=tuple(fields["seed files"]),
        attachments=tuple(fields["attachments"]),
        acknowledgements=tuple(fields["expected acknowledgements"]),
        resume_from=fields["resume_from"],
        conversation_id=None if conversation == NONE else conversation,
        acknowledged=int(fields["parts already acknowledged"]),
        helper=tuple(item for item in helper if item != "…"),
    )


class Browser(Protocol):
    """The two things the skill asks an agent, not a helper, to do."""

    def navigate(self, url: str) -> None: ...

    def submit(self, expected_ack: str) -> None:
        """Press Enter in the composer. `expected_ack` is what the chat will
        eventually answer with — the test's page needs it, the agent does not,
        and passing it here keeps the agent from ever holding a seed."""


Helper = Callable[[Sequence[str]], tuple[int, dict[str, Any]]]
"""Run one helper call: argv in, exit code and the object it printed out."""


@dataclass
class ScriptedAgent:
    """`11`'s procedure, performed without an agent."""

    helper: Helper
    browser: Browser
    actions: int = 0
    last: Step | None = None
    acked: int = 0
    conversation_id: str | None = None
    errors: list[str] = field(default_factory=list)
    """The helper `error` strings met on the way. Never content: the helpers
    print ids, counts and digests, and this keeps only their error names."""

    # -- the two ways to look at the page ----------------------------------- #

    def call(self, task: Task, *args: str) -> dict[str, Any]:
        self.actions += 1
        _, printed = self.helper([*task.helper, *args])
        if printed.get("ok") is not True:
            self.errors.append(str(printed.get("error", "unknown")))
        return printed

    def probe(self, task: Task, *expect: str) -> dict[str, Any]:
        arguments = ["probe"]
        for item in expect:
            arguments += ["--expect", item]
        return self.call(task, *arguments)

    # -- the run ------------------------------------------------------------ #

    def run(self, prompt: str) -> dict[str, Any]:
        task = parse(prompt)
        if len(task.seed_files) != task.parts:
            return self.stop("failed", "hermes", "the prompt does not add up")
        self.conversation_id = task.conversation_id

        state = self.open(task)
        if state is None:
            return self.result(
                "needs_human",
                needs_human_reason="auth_required",
                error={"category": "auth", "detail": "no composer to type into"},
            )
        if task.conversation_id is None and not self.new_chat(task, state):
            return self.stop("failed", "browser", "no empty composer on /new")
        if not self.resumable(task):
            return self.stop("partial", "verification", "the chat is not where it was")
        for path in task.attachments:
            if self.call(task, "attach", "--file", path).get("ok") is not True:
                return self.stop("failed", "browser", "attach refused")
            self.last = Step.ATTACH

        self.acked = task.acknowledged
        for index in range(task.acknowledged, task.parts):
            if not self.part(task, index):
                return self.stop(
                    "partial" if self.conversation_id else "failed",
                    "browser",
                    f"part {index + 1} stopped at {self.last}",
                )
        if not self.identify(task):
            return self.stop("partial", "verification", "no conversation id")
        self.last = Step.DONE
        return self.result("completed")

    def open(self, task: Task) -> dict[str, Any] | None:
        """`open`: navigate, then prove there is a composer to type into."""
        self.browser.navigate(
            NEW_CHAT_URL
            if task.conversation_id is None
            else CHAT_URL.format(uuid=task.conversation_id)
        )
        state = self.probe(task)
        if not state.get("logged_in") or not state.get("composer_present"):
            return None
        self.last = Step.OPEN
        return state

    def new_chat(self, task: Task, state: dict[str, Any]) -> bool:
        """`new_chat`: on `/new`, with nothing in the composer."""
        if state.get("kind") != "new_chat":
            self.browser.navigate(NEW_CHAT_URL)
            state = self.probe(task)
        if state.get("kind") != "new_chat" or state.get("composer_chars") != 0:
            return False
        self.last = Step.NEW_CHAT
        return True

    def resumable(self, task: Task) -> bool:
        """The chat really does hold the acknowledgement it is said to hold.

        One probe, one `--expect`, no snapshot: the count in the prompt is
        `12`'s, and this is the cheapest evidence that it still describes the
        page.
        """
        if not task.acknowledged:
            return True
        expected = task.acknowledgements[task.acknowledged - 1]
        state = self.probe(task, expected)
        return expected in state.get("last_message", {}).get("contains", [])

    def part(self, task: Task, index: int) -> bool:
        """`paste` → `submit` → `await` → `ack`, for one seed part."""
        ack = task.acknowledgements[index]
        pasted = self.call(task, "paste", "--seed", task.seed_files[index])
        if pasted.get("ok") is not True:
            return False
        self.last = Step.PASTE

        self.browser.submit(ack)
        self.actions += 1
        state = self.probe(task)
        if state.get("composer_chars") != 0:
            return False
        if state.get("last_message", {}).get("role") != "human":
            return False
        self.last = Step.SUBMIT

        answered = self.call(task, "await-response", "--expect", ack)
        if answered.get("ok") is not True:
            return False
        self.last = Step.AWAIT

        if ack not in answered.get("last_message", {}).get("contains", []):
            return False
        self.last = Step.ACK
        self.acked += 1
        self.conversation_id = answered.get("conversation_id") or self.conversation_id
        return True

    def identify(self, task: Task) -> bool:
        """`identify`: the destination id, read off the URL."""
        state = self.probe(task)
        found = state.get("conversation_id")
        if not found or (self.conversation_id and found != self.conversation_id):
            return False
        self.conversation_id = found
        self.last = Step.IDENTIFY
        return True

    # -- what it prints ----------------------------------------------------- #

    def stop(self, outcome: str, category: str, detail: str) -> dict[str, Any]:
        return self.result(outcome, error={"category": category, "detail": detail})

    def result(self, outcome: str, **extra: Any) -> dict[str, Any]:
        return {
            "outcome": outcome,
            "conversation_id": self.conversation_id,
            # `open` when nothing passed at all: the field is required, and the
            # skill says so rather than leaving an agent to invent a name.
            "last_step": str(self.last or Step.OPEN),
            "chunks_acked": self.acked,
            "actions": self.actions,
            **extra,
        }
