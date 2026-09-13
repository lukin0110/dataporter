"""The obedient reply: the one line a seed asks for, answered in steps.

Two behaviours, and every mock has both because a rehearsal is only as honest as
they are (§21, §54):

- **Obedience.** A migration seed ends by asking the model to reply with exactly
  one line. The mock finds that line in the message it was sent and replies with
  exactly it. It does not paraphrase and it does not summarise, because the tool
  verifies a migration by looking for that line and a stand-in that answered
  anything else would make every rehearsal a failed one. A message with no such
  line — the follow-up probe's question — gets one canned sentence.
- **Growth.** The reply does not appear at once. It appears after a non-zero
  delay and grows in at least two steps, so that "the reply stopped growing",
  which is what the tool's `await-response` waits for, is something a rehearsal
  really waits for rather than a condition that is true on the first poll.

The seed is the tool's own, and a seed written for a ChatGPT destination asks
the same way, which is why this is the core's and not a site's (§54, *Obedient*).
"""

import re
from dataclasses import dataclass

ASK = re.compile(r"Reply\s+with\s+exactly\s+one\s+line:[ \t]*\r?\n[ \t]*(?P<line>[^\r\n]+)")
r"""What a seed asks for (`dataporter`'s `render.py` writes it at the end of every
part).

Two details, both of them found by a rehearsal rather than designed:

- the phrase itself may be **wrapped**, because the seed's footer is wrapped to
  a column and a multi-part seed's is longer — so the words are separated by
  `\s+` rather than by single spaces;
- the **last** match wins, because a transcript being migrated may quote the
  phrase in one of its own turns and the one that matters is the instruction at
  the foot of the message.
"""

CANNED = "In one sentence: we went back over a conversation you asked me to treat as our shared history."
"""What a message that asks for no particular line gets. One sentence, the same
one every time, and about nothing: the follow-up probe grades a *reply*, and
against a mock that grade is `not applicable` (§27)."""

DEFAULT_REPLY_DELAY_S = 1.0
DEFAULT_REPLY_STEPS = 2
"""Non-zero, and at least two, because §21 says so."""


@dataclass(frozen=True)
class Turn:
    """One message on the page, and which side said it."""

    role: str
    text: str


@dataclass
class Reply:
    """An answer being written, and how much of it is on the page by now."""

    text: str
    started: float
    delay_s: float
    steps: int

    def revealed(self, now: float) -> int:
        """How many of the steps have elapsed. Never more than there are."""
        if self.delay_s <= 0:  # pragma: no cover - the CLI refuses zero
            return self.steps
        return min(self.steps, int((now - self.started) // self.delay_s))

    def visible(self, now: float) -> str:
        """Return the part of the reply the page would show. `""` before the first step.

        A prefix, so that a reader watching the message grow sees it grow; and
        never the whole of it before the last step, so that the line the tool is
        waiting for cannot appear early.
        """
        done = self.revealed(now)
        if done <= 0:
            return ""
        if done >= self.steps:
            return self.text
        return self.text[: max(1, len(self.text) * done // self.steps)]

    def finished(self, now: float) -> bool:
        return self.revealed(now) >= self.steps


def asked_line(message: str) -> str | None:
    """Return the one line a message asked to be answered with, if it asked for one."""
    found = list(ASK.finditer(message))
    return found[-1].group("line").strip() if found else None


def answer(message: str, *, started: float, delay_s: float, steps: int) -> Reply:
    """Return the reply a message gets: the line it asked for, or the canned sentence."""
    line = asked_line(message)
    return Reply(text=line if line is not None else CANNED, started=started, delay_s=delay_s, steps=steps)
