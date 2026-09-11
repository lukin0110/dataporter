"""The handshake a run makes with the person sitting in front of it.

§12 asks for one thing: when Hermes cannot safely proceed, the run stops, says
what it needs, lets the human act in the browser window it already opened, and
then *resumes rather than restarts*. This module is the half of that which faces
the terminal — the block that is printed, the phrases that name the six reasons,
and the wait for Enter. `importer` owns the other half: the pause record, the
budget, and the re-run of the same conversation from its last successful step.

Three decisions worth naming:

- **The block is a golden string.** `14` writes it out in full, so the labels,
  the padding and the two blank lines are the rule here and `tests/
  test_intervention.py` compares bytes. `LABEL_WIDTH` is the whole of the
  alignment.
- **Waiting is a seam, not a `input()` call.** `Intervention` is a protocol the
  way `Progress` is in `12`, so a test drives a run through six interventions
  without a terminal, and `18` can later draw the same ask differently without
  touching the loop.
- **Not a TTY is not an error.** A run in a cron job or a CI step cannot be asked
  anything, so `Console` answers "no human" and the run pauses to disk for
  `resume` to pick up. That is the difference between exit `5` and a process
  blocked forever on a pipe nobody is holding.

Nothing here prints a title or a message: the ask carries a short id, a reason
phrase this module owns, a step name and two counts.
"""

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import IO, Protocol

from dataporter import PROGRAM_NAME
from dataporter.steps import Step

AUTH_REQUIRED = "auth_required"
"""The one reason the tool can check for itself, by probing the page again."""

DEFAULT_REASON = "ambiguous_ui"
"""What a `needs_human` that names no reason is treated as.

The same fallback `12` uses for the category, and for the same reason: a result
that stopped without saying which of the six it was is an unexplained UI state,
which is exactly what `ambiguous_ui` means.
"""

CONFIRMATION_REQUIRED = "confirmation_required"
"""The reason `15` escalates a rate limit under.

Not one of its own: §12's list has six reasons and a wait that is too long to
make is not a seventh kind of blocked page. It is the one row whose phrase
carries a detail, which is what lets the ask say *which* wait it is asking about.
"""

REASON_PHRASES: dict[str, str] = {
    AUTH_REQUIRED: "authentication required",
    "captcha": "CAPTCHA",
    "security_challenge": "security challenge",
    "ambiguous_ui": "ambiguous UI state",
    "browser_error": "unrecoverable browser error",
    CONFIRMATION_REQUIRED: "confirmation required",
}
"""`09`'s six `needs_human` reasons as the words `14` prints.

`confirmation_required` is the one that continues: the printed phrase is
`confirmation required: <detail>`, where the detail is Hermes's description of
the action it wanted to take. Resuming does not grant it permission to take that
action — the skill rule (`11`) still applies, and it is the human's own click
that changes the page.
"""

HEADER = "Human intervention required"
PROMPT = "Press Enter to resume, or Ctrl-C to stop."
BROWSER_HELP = "the Chrome window is open — complete the step there"

LABEL_WIDTH = 14
"""What the four labels are padded to. `Conversation:` is the longest at 13."""

STILL_NOT_LOGGED_IN = "still not logged in"
"""Printed when Enter came back and the page is still showing a sign-in form.

Only for `auth_required`: it is the one reason whose resolution the tool can
observe. A solved CAPTCHA and a dismissed dialog look, from a probe, exactly like
a page that was never blocked, so for those five the human's word is what the run
has and taking it is not a weakness of the check but the absence of one.
"""

TOO_MANY_INTERVENTIONS = "too many interventions — see report"
"""The run gave up asking. `run.max_interventions` is the budget."""

RATE_LIMIT_UNTIL = "rate limit until {until}"
"""The detail of an escalated rate limit, so the block reads
`confirmation required: rate limit until 15:00 UTC`. The wait is longer than
`pacing.max_rate_limit_wait_s`, and a person decides whether to sit it out."""

RATE_LIMIT_NO_TIME = "rate limited {waits} times with no time given"
"""The second escalation: the account keeps refusing and never says until when,
so there is no wait to make and `15` stops guessing at one."""

RATE_LIMIT_AGAIN = "rate limited {waits} times, now until {until}"
"""The third: the page keeps saying when and the answer keeps being later. Each
wait was short enough to make; three in a row is an account that is not going to
let this run finish, and the operator can see what the tool cannot."""

LOGIN_TIMED_OUT = "still not logged in after {seconds:g}s — stopping"
"""An `auth_required` ask that outlived `timeouts.login_s` (`15`, exit `3`).

The only intervention with a clock on it, because it is the only one whose
resolution the tool can check: five of the six are cleared by a person's word,
and a run cannot tell a human who is taking their time from one who has left.
"""


def offer(short_id: str) -> str:
    """What an `import` says when it finds a pause somebody left behind."""
    return f"paused at {short_id} — run: {PROGRAM_NAME} resume"


# --------------------------------------------------------------------------- #
# The ask
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Request:
    """One ask, as everything the printed block needs and nothing more."""

    short_id: str
    reason: str = DEFAULT_REASON
    """One of `REASON_PHRASES`, as `09` spells it on the wire. The default is the
    same fallback the phrase lookup makes: an ask with no reason behind it is an
    unexplained page, which is what `ambiguous_ui` means."""
    detail: str = ""
    """Hermes's own words. Printed only for `confirmation_required`, which is the
    only reason whose phrase is incomplete without them — the other five say all
    there is to say, and the detail is in the log and in `run.json`."""
    last_step: Step = Step.OPEN
    """Where a resume starts. `open` when Hermes reported no step we know."""
    position: int = 1
    """1-based, within the selection this run was given."""
    total: int = 1

    @property
    def phrase(self) -> str:
        """The reason, in the words §12 uses for it."""
        phrase = REASON_PHRASES.get(self.reason, REASON_PHRASES[DEFAULT_REASON])
        if self.reason == CONFIRMATION_REQUIRED and self.detail:
            return f"{phrase}: {self.detail}"
        return phrase

    @property
    def rows(self) -> Sequence[tuple[str, str]]:
        return (
            ("Reason:", self.phrase),
            ("Conversation:", f"{self.short_id} ({self.position} of {self.total})"),
            ("Last step:", str(self.last_step)),
            ("Browser:", BROWSER_HELP),
        )


def block(request: Request) -> str:
    """The §12 ask, newline-terminated, exactly as `14` writes it."""
    lines = [
        HEADER,
        "",
        *(f"{label:<{LABEL_WIDTH}}{value}" for label, value in request.rows),
        "",
        PROMPT,
    ]
    return "".join(f"{line}\n" for line in lines)


# --------------------------------------------------------------------------- #
# Who answers it
# --------------------------------------------------------------------------- #


class Intervention(Protocol):
    """Where a run's asks go, and where the answer comes back from.

    `True` means a human says they have acted and the run may look again; `False`
    means there is nobody to ask — not a terminal, or a terminal whose operator
    pressed Ctrl-C — and the run should pause to disk for `resume`.
    """

    def ask(self, request: Request) -> bool:
        """Print the block and wait."""
        ...

    def retry(self, message: str) -> bool:
        """Say why the last answer was not enough, and wait again."""
        ...

    def note(self, message: str) -> None:
        """Say something that is not a question."""
        ...


@dataclass
class Console:
    """The terminal: block on stdout, Enter on stdin, advisories on stderr.

    Both streams are fields rather than `sys.stdin` and `sys.stderr` read at the
    call site, so a test can hand this a pseudo-terminal and prove the real path
    — `isatty`, a blocking read, EOF — rather than a stub of it.
    """

    stdin: IO[str] | None = None
    stderr: IO[str] | None = None

    def ask(self, request: Request) -> bool:
        # Printed even under `--quiet`: `-q` suppresses progress, and a question
        # the run cannot continue without is not progress.
        print(block(request), end="")
        return self._wait()

    def retry(self, message: str) -> bool:
        print(message)
        return self._wait()

    def note(self, message: str) -> None:
        print(message, file=self.stderr if self.stderr is not None else sys.stderr)

    def _wait(self) -> bool:
        """Block until Enter. `False` for no terminal, EOF, or Ctrl-C.

        `readline` rather than `input()` because the stream is injected: `input()`
        reads the process's own stdin whatever this object was handed, which would
        make the pseudo-terminal test pass for the wrong reason.
        """
        stream = self.stdin if self.stdin is not None else sys.stdin
        try:
            if not stream.isatty():
                return False
            return stream.readline() != ""
        except KeyboardInterrupt:
            # Ctrl-C at the prompt ends the run the same way a pipe does: the
            # pause is already on disk, so this is "stop", not "crash". A blank
            # line keeps the next thing printed off the ^C.
            print()
            return False
        except (OSError, ValueError):
            # A closed or detached stdin. Indistinguishable from EOF as far as
            # the run is concerned: there is nobody to ask.
            return False
