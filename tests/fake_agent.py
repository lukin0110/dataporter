"""An agent that is not an agent.

`11`'s acceptance criterion is that a run following the skill reaches `identify`
and comes back with a valid result. Hermes itself cannot be installed in CI, and
a stub that simply prints a result object would prove nothing about the
procedure, so this is the third thing: a scripted reader of the task prompt that
performs `11`'s steps in `11`'s order, with `11`'s verifications, against a
browser the test supplies.

`13` gave the procedure a *Recovery* table, and this performs that too — the
half of it a script can perform. Every row whose signal is a field of a `probe`
object or the `error` string of a helper answer is here: the detection, the one
recovery the table allows, and the outcome when that recovery does not work.
`test_recovery.py` drives one fixture page per row through it.

What it is worth, and what it is not:

- it proves the **prompt** carries everything the procedure needs — nothing here
  is passed a seed, a part count or an ack line by the test, only the rendered
  string;
- it proves the **helpers** compose into a migration: every step goes through the
  real CLI and the real page model, so a helper that changed its error vocabulary
  or stopped clearing the composer fails here;
- it proves the **recovery table is performable** — that each signal it names can
  actually be read off a page, and that the outcome it prescribes is the outcome
  a run following it produces;
- it proves nothing about **Hermes**. A real agent has to decide when to act and
  can decide wrongly; this one cannot. Three rows of the table — rate limiting, a
  CAPTCHA and a security challenge — rest entirely on reading a snapshot, which
  is judgement and not a script, and they are out of reach here. `10`'s throwaway
  prompts and `20` are where all of that is measured.

Where the table says classify and stop, this stops: `Stopped` carries the result
object out, so each step reads as the step rather than as a chain of returns.
"""

import re
import shlex
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, NoReturn, Protocol

from dataporter.browser import helpers
from dataporter.steps import Step

NEW_CHAT_URL = "https://claude.ai/new"
CHAT_URL = "https://claude.ai/chat/{uuid}"
LOGIN_URL = "https://claude.ai/login"

SCALARS = (
    "short_id",
    "parts",
    "resume_from",
    "existing conversation_id",
    "parts already acknowledged",
    "title",
    "helper",
)
BLOCKS = ("seed files", "attachments", "expected acknowledgements")
NONE = "none"

KEY_LINE = re.compile(r"^[a-z][a-z_ ]*:( |$)")
"""What ends a block: the next field. A seed path starts with a separator and an
acknowledgement line starts with `MIGRATION-ACK`, so neither can look like one."""

ATTACHMENT_FAILED = "attachment upload failed: {file_name}"
NOTHING_TO_ATTACH_TO = "nothing_to_attach_to"
"""`16`: what a resume with every part already acknowledged answers with. There
is no message being composed, so there is nothing for a chip to belong to."""

UNREADABLE = (helpers.NO_CLAUDE_TAB, helpers.UNKNOWN_TARGET)
"""`13`'s network row, as the helpers spell it: the tab this run was driving is
not there to be read. A browser error page looks exactly like this, because the
page it went to is not on claude.ai any more."""


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
    title: str
    """What to rename the chat to (`17`), or `""` when the prompt said `none`."""
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
        title="" if fields.get("title", NONE) == NONE else fields["title"],
        helper=tuple(item for item in helper if item != "…"),
    )


class Stopped(Exception):
    """The procedure cannot go on. Carries the result object to print."""

    def __init__(self, printed: dict[str, Any]) -> None:
        super().__init__(printed.get("outcome", ""))
        self.printed = printed


class Browser(Protocol):
    """The three things the skill asks an agent, not a helper, to do."""

    def navigate(self, url: str) -> None: ...

    def submit(self, expected_ack: str) -> None:
        """Press Enter in the composer. `expected_ack` is what the chat will
        eventually answer with — the test's page needs it, the agent does not,
        and passing it here keeps the agent from ever holding a seed."""

    def rename(self, title: str) -> None:
        """Open the chat's menu and give it this name (`17`).

        The one thing an agent types that a helper does not, and the one piece
        of a conversation's metadata that reaches the page through the model —
        which is why the whole of it is one call a stub can perform."""


Helper = Callable[[Sequence[str]], tuple[int, dict[str, Any]]]
"""Run one helper call: argv in, exit code and the object it printed out."""


@dataclass
class ScriptedAgent:
    """`11`'s procedure and `13`'s recovery, performed without an agent."""

    helper: Helper
    browser: Browser
    actions: int = 0
    last: Step | None = None
    acked: int = 0
    conversation_id: str | None = None
    errors: list[str] = field(default_factory=list)
    """The helper `error` strings met on the way. Never content: the helpers
    print ids, counts and digests, and this keeps only their error names."""
    recoveries: list[str] = field(default_factory=list)
    """Which rows of `13`'s table fired, in order. A test asserts on the outcome;
    this is what says the outcome came from the row it was meant to come from."""
    uploaded_attachments: list[str] = field(default_factory=list)
    failed_attachments: list[dict[str, str]] = field(default_factory=list)
    """`16`'s two lists, by file name. The prompt gives paths; what the result
    reports is names, because a name is what the page shows on the chip."""

    # -- the two ways to look at the page ----------------------------------- #

    def call(self, task: Task, *args: str) -> dict[str, Any]:
        self.actions += 1
        _, printed = self.helper([*task.helper, *args])
        if printed.get("ok") is not True:
            self.errors.append(str(printed.get("error", "unknown")))
        return printed

    def probe(
        self,
        task: Task,
        *expect: str,
        messages: bool = False,
        expect_title: str | None = None,
    ) -> dict[str, Any]:
        arguments = ["probe"]
        if messages:
            arguments.append("--messages")
        if expect_title is not None:
            arguments += ["--expect-title", expect_title]
        for item in expect:
            arguments += ["--expect", item]
        return self.call(task, *arguments)

    def look(
        self,
        task: Task,
        *expect: str,
        messages: bool = False,
        expect_title: str | None = None,
    ) -> dict[str, Any]:
        """One probe, with the rows that can fire on any probe already applied.

        Four of `13`'s rows are about the page rather than about a step — the
        tab is unreadable, there are two of it, it is a sign-in page, something
        modal is over it — so they are checked wherever the procedure looks
        rather than repeated at each step that looks.
        """
        state = self.probe(task, *expect, messages=messages, expect_title=expect_title)
        if state.get("error") in UNREADABLE:
            # network: navigate back to the run's URL and look once more. The
            # skill's five-second wait is the agent's, and is not scripted here —
            # a real sleep per row would add half a minute to the suite to prove
            # nothing, and none of these pages changes with time.
            self.recoveries.append("network")
            self.browser.navigate(self.url(task))
            state = self.probe(
                task, *expect, messages=messages, expect_title=expect_title
            )
            if state.get("error") in UNREADABLE:
                self.give_up("network", "the page could not be read")
        if state.get("error") == helpers.AMBIGUOUS_TAB:
            self.recoveries.append("ambiguous_tab")
            self.call(task, "close-extra-tabs")
            state = self.probe(
                task, *expect, messages=messages, expect_title=expect_title
            )
        if self.signed_out(state):
            self.halt("needs_human", "auth", "a sign-in page", "auth_required")
        if state.get("error") == helpers.OUTSIDE_MIGRATION_SURFACE:
            self.give_up("safety", "the tab is somewhere this run may not touch")
        if state.get("dialogs"):
            self.halt("needs_human", "dialog", "a dialog is in the way", "ambiguous_ui")
        return state

    @staticmethod
    def signed_out(state: dict[str, Any]) -> bool:
        """`13`'s login-expiry signal, as a helper can see it.

        The login page is outside the migration surface, so no helper will drive
        it and none reports `kind: login`; what comes back is the wall's refusal
        with the URL it refused. `kind` is checked too, for the day a probe can
        answer from a page our own helpers are allowed to read.
        """
        if state.get("kind") == "login":
            return True
        return state.get("error") == helpers.OUTSIDE_MIGRATION_SURFACE and str(
            state.get("url", "")
        ).startswith(LOGIN_URL)

    def url(self, task: Task) -> str:
        """Where this run belongs: its chat, or `/new` while it has no id."""
        if self.conversation_id is None:
            return NEW_CHAT_URL
        return CHAT_URL.format(uuid=self.conversation_id)

    # -- the run ------------------------------------------------------------ #

    def run(self, prompt: str) -> dict[str, Any]:
        task = parse(prompt)
        try:
            return self.migrate(task)
        except Stopped as stopped:
            return stopped.printed

    def migrate(self, task: Task) -> dict[str, Any]:
        if len(task.seed_files) != task.parts:
            self.halt("failed", "hermes", "the prompt does not add up")
        self.conversation_id = task.conversation_id

        state = self.open(task)
        if task.conversation_id is None:
            self.new_chat(task, state)
        self.check_resumable(task)
        self.attach(task)

        self.acked = task.acknowledged
        for index in range(task.acknowledged, task.parts):
            self.part(task, index)
        self.identify(task)
        self.rename(task)
        self.verify(task)
        self.last = Step.DONE
        if self.failed_attachments:
            # `16`: the chat is there and holds every message, and one of its
            # files is not in it. That is what `partial` is for.
            return self.result(
                "partial",
                error={
                    "category": "unsupported",
                    "detail": ATTACHMENT_FAILED.format(
                        file_name=self.failed_attachments[0]["file_name"]
                    ),
                },
            )
        return self.result("completed")

    def attach(self, task: Task) -> None:
        """`attach`: every file into the composer, before the first paste (`16`).

        Not a step that can stop the run. A file that will not attach is recorded
        and the migration goes on without it, because the conversation is worth
        more than the attachment — and a run that stopped here would leave a chat
        with no messages at all.
        """
        if not task.attachments:
            return
        if task.acknowledged >= task.parts:
            # A resume with every part already sent: there is no message left for
            # a chip to belong to, and attaching to one that is never submitted
            # would look like an upload and be nothing.
            for path in task.attachments:
                self.refuse(path, NOTHING_TO_ATTACH_TO)
            return
        attached: list[str] = []
        for path in task.attachments:
            answer = self.call(task, "attach", "--file", path)
            if answer.get("ok") is not True:
                self.refuse(path, str(answer.get("error", "unknown")))
                continue
            attached.append(path)
            self.uploaded_attachments.append(name_of(path))
        if not attached:
            return
        found = self.call(task, "attachments", *_file_arguments(attached))
        if found.get("ok") is not True:
            # The chips are not all there at the moment that matters, and no
            # per-file answer says which: everything this step thought it had
            # uploaded is unaccounted for.
            self.uploaded_attachments.clear()
            for path in attached:
                self.refuse(path, str(found.get("error", "unknown")))
            return
        self.last = Step.ATTACH

    def refuse(self, path: str, error: str) -> None:
        self.failed_attachments.append({"file_name": name_of(path), "error": error})

    def open(self, task: Task) -> dict[str, Any]:
        """`open`: navigate, then prove there is a composer to type into."""
        self.browser.navigate(self.url(task))
        state = self.look(task)
        if not state.get("composer_present"):
            # missing composer: reload the run's URL and look once more.
            self.recoveries.append("missing_composer")
            self.browser.navigate(self.url(task))
            state = self.look(task)
            if not state.get("composer_present"):
                self.give_up("ui", "there is no composer on the page")
        self.last = Step.OPEN
        return state

    def new_chat(self, task: Task, state: dict[str, Any]) -> None:
        """`new_chat`: on `/new`, with nothing in the composer."""
        if state.get("kind") != "new_chat":
            self.browser.navigate(NEW_CHAT_URL)
            state = self.look(task)
        if state.get("kind") != "new_chat" or state.get("composer_chars") != 0:
            self.give_up("browser", "no empty composer on /new")
        self.last = Step.NEW_CHAT

    def check_resumable(self, task: Task) -> None:
        """The chat really does hold the acknowledgement it is said to hold.

        One probe, one `--expect`, no snapshot: the count in the prompt is
        `12`'s, and this is the cheapest evidence that it still describes the
        page.
        """
        if not task.acknowledged:
            return
        expected = task.acknowledgements[task.acknowledged - 1]
        state = self.look(task, expected)
        if expected not in state.get("last_message", {}).get("contains", []):
            self.halt("partial", "verification", "the chat is not where it was")

    # -- one part ----------------------------------------------------------- #

    def part(self, task: Task, index: int) -> None:
        """`paste` → `submit` → `await` → `ack`, for one seed part."""
        ack = task.acknowledgements[index]
        self.paste(task, index)
        self.submit(task, ack)
        self.answer(task, ack)

    def paste(self, task: Task, index: int) -> None:
        pasted = self.call(task, "paste", "--seed", task.seed_files[index])
        if pasted.get("error") == helpers.COMPOSER_NOT_EMPTY:
            # The page may still be settling after the previous submit; this is
            # the one helper error the skill lets a step re-run on.
            self.recoveries.append("composer_not_empty")
            pasted = self.call(task, "paste", "--seed", task.seed_files[index])
        if pasted.get("ok") is not True:
            self.give_up("browser", f"paste answered {pasted.get('error')}")
        self.last = Step.PASTE

    def submit(self, task: Task, ack: str) -> None:
        """`submit`, and the two rows that tell its failures apart.

        A composer that still holds the part is a click that did not land, and
        the table allows one more. A composer that cleared with no turn to show
        for it is the page having changed under us: the message went somewhere,
        and nowhere the procedure knows how to look.
        """
        state = self.press(task, ack)
        if state.get("composer_chars") != 0:
            self.recoveries.append("failed_click")
            state = self.press(task, ack)
            if state.get("composer_chars") != 0:
                self.give_up("ui", "the composer still holds the part")
        if state.get("last_message", {}).get("role") != "human":
            self.halt(
                "needs_human",
                "ui",
                "the message was sent and no turn appeared",
                "ambiguous_ui",
            )
        self.check_url(task, state)
        self.last = Step.SUBMIT

    def press(self, task: Task, ack: str) -> dict[str, Any]:
        self.browser.submit(ack)
        self.actions += 1
        return self.look(task)

    def check_url(self, task: Task, state: dict[str, Any]) -> None:
        """`13`'s page-navigation row: the tab is still where this run put it."""
        found = state.get("conversation_id")
        if self.conversation_id is None and found:
            self.conversation_id = str(found)
        if self.on_track(state):
            return
        self.recoveries.append("navigation")
        self.browser.navigate(self.url(task))
        if not self.on_track(self.look(task)):
            self.give_up("navigation", "the tab left this run's chat")

    def on_track(self, state: dict[str, Any]) -> bool:
        if state.get("kind") not in ("new_chat", "chat"):
            return False
        found = state.get("conversation_id")
        return not (self.conversation_id and found and found != self.conversation_id)

    def answer(self, task: Task, ack: str) -> None:
        """`await` and `ack`, with the generation-failure row between them."""
        answered = self.call(task, "await-response", "--expect", ack)
        if answered.get("ok") is not True:
            # A real agent clicks the retry control first if the page offers one;
            # a script has no way to find one, so this is the second half of the
            # row — wait for the answer once more.
            self.recoveries.append("generation")
            answered = self.call(task, "await-response", "--expect", ack)
            if answered.get("ok") is not True:
                self.give_up("generation", "no answer to this part")
        self.last = Step.AWAIT

        if ack not in answered.get("last_message", {}).get("contains", []):
            self.give_up("generation", "the acknowledgement did not appear")
        self.last = Step.ACK
        self.acked += 1
        self.conversation_id = answered.get("conversation_id") or self.conversation_id

    def identify(self, task: Task) -> None:
        """`identify`: the destination id, read off the URL."""
        state = self.look(task)
        found = state.get("conversation_id")
        if not found or (self.conversation_id and found != self.conversation_id):
            self.give_up("verification", "no conversation id")
        self.conversation_id = str(found)
        self.last = Step.IDENTIFY

    def rename(self, task: Task) -> None:
        """`rename`: the source title, through the chat's own menu (`17`).

        Best effort by design. A rename that does not take leaves `last_step` at
        `identify` and the run carries on: the conversation is worth more than
        its name, and the tool checks the title itself afterwards and records
        `title_not_set` when it is not there.
        """
        if not task.title:
            return
        self.browser.rename(task.title)
        self.actions += 1
        state = self.look(task, expect_title=task.title)
        if state.get("title", {}).get("matches") is True:
            self.last = Step.RENAME

    def verify(self, task: Task) -> None:
        """`verify`: every part's acknowledgement is on the page, in one probe."""
        state = self.look(task, *task.acknowledgements, messages=True)
        seen = {
            item
            for message in state.get("messages", [])
            for item in message.get("contains", [])
        }
        for index, ack in enumerate(task.acknowledgements, start=1):
            if ack not in seen:
                self.give_up("generation", f"part {index} is not in the chat")
        self.last = Step.VERIFY

    # -- what it prints ----------------------------------------------------- #

    def give_up(self, category: str, detail: str) -> NoReturn:
        """Stop, as `partial` when a chat exists and `failed` when none does."""
        self.halt("partial" if self.conversation_id else "failed", category, detail)

    def halt(
        self, outcome: str, category: str, detail: str, reason: str | None = None
    ) -> NoReturn:
        extra: dict[str, Any] = {"error": {"category": category, "detail": detail}}
        if reason is not None:
            extra["needs_human_reason"] = reason
        raise Stopped(self.result(outcome, **extra))

    def result(self, outcome: str, **extra: Any) -> dict[str, Any]:
        printed: dict[str, Any] = {
            "outcome": outcome,
            "conversation_id": self.conversation_id,
            # `open` when nothing passed at all: the field is required, and the
            # skill says so rather than leaving an agent to invent a name.
            "last_step": str(self.last or Step.OPEN),
            "chunks_acked": self.acked,
            "actions": self.actions,
            **extra,
        }
        if self.uploaded_attachments or self.failed_attachments:
            printed["attachments_uploaded"] = list(self.uploaded_attachments)
            printed["attachments_failed"] = list(self.failed_attachments)
        return printed


def name_of(path: str) -> str:
    """The file name in a path the prompt gave. The chip carries this, not the
    directory it came out of.

    `PurePath`, whose separators follow the host, rather than `PurePosixPath`:
    the prompt is rendered by `12` on the same machine that runs this, so a
    Windows path arrives with backslashes and posix semantics would read the
    whole of `C:\\…\\notes.txt` as the name. (Raised by Copilot in review on #25.)
    """
    return PurePath(path).name


def _file_arguments(paths: Sequence[str]) -> list[str]:
    return [item for path in paths for item in ("--file", path)]
