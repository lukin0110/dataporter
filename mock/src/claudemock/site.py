"""The mock's state: accounts, chats, replies, and the clock they grow on.

This module is the behaviour. It holds no HTML and no HTTP — `pages.py` renders
it and `server.py` serves it — so that what the mock *does* can be read, and
tested, without a socket.

Two behaviours are worth reading closely, because a rehearsal is only as honest
as they are:

- **Obedience.** A migration seed ends by asking Claude to reply with exactly one
  line. The mock finds that line in the message it was sent and replies with
  exactly it. It does not paraphrase and it does not summarise, because the tool
  verifies a migration by looking for that line and a stand-in that answered
  anything else would make every rehearsal a failed one. A message with no such
  line — the follow-up probe's question — gets one canned sentence.
- **Growth.** The reply does not appear at once. It appears after a non-zero
  delay and grows in at least two steps, so that "the reply stopped growing",
  which is what the tool's `await-response` waits for, is something a rehearsal
  really waits for rather than a condition that is true on the first poll.

Nothing here is a claim about claude.ai. `uimap.py` says which row of the UI map
each of these behaviours stands on.
"""

import re
import secrets
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from claudemock.ledger import Ledger

ASK = re.compile(
    r"Reply\s+with\s+exactly\s+one\s+line:[ \t]*\r?\n[ \t]*(?P<line>[^\r\n]+)"
)
"""What a seed asks for (`dataporter`'s `render.py` writes it at the end of every
part).

Two details, both of them found by a rehearsal rather than designed:

- the phrase itself may be **wrapped**, because the seed's footer is wrapped to
  a column and a multi-part seed's is longer — so the words are separated by
  `\s+` rather than by single spaces;
- the **last** match wins, because a transcript being migrated may quote the
  phrase in one of its own turns and the one that matters is the instruction at
  the foot of the message.
"""

CANNED = (
    "In one sentence: we went back over a conversation you asked me to treat as "
    "our shared history."
)
"""What a message that asks for no particular line gets. One sentence, the same
one every time, and about nothing: the follow-up probe grades a *reply*, and
against the mock that grade is `not applicable` (§27)."""

DEFAULT_REPLY_DELAY_S = 1.0
DEFAULT_REPLY_STEPS = 2
"""Non-zero, and at least two, because §21 says so."""

NEW_CHAT_TITLE = "New chat"
"""What a chat is called before anything renames it. Not a title of anything —
the mock never sees a source conversation."""


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
        """The part of the reply the page would show. `""` before the first step.

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


@dataclass
class Chat:
    """One chat: what it is called, what is in it, and what it is writing."""

    id: str
    title: str = NEW_CHAT_TITLE
    turns: list[Turn] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    reply: Reply | None = None

    def view(self, now: float) -> list[Turn]:
        """The transcript as the page shows it at `now`."""
        turns = list(self.turns)
        if self.reply is not None:
            text = self.reply.visible(now)
            if text:
                turns.append(Turn("assistant", text))
        return turns

    def generating(self, now: float) -> bool:
        return self.reply is not None and not self.reply.finished(now)


def asked_line(message: str) -> str | None:
    """The one line a message asked to be answered with, if it asked for one."""
    found = list(ASK.finditer(message))
    return found[-1].group("line").strip() if found else None


class Site:
    """Everything the mock knows, behind one lock.

    In memory and nowhere else: a rehearsal in several sessions sees the same
    chats throughout because the process keeps running, and restarting it resets
    it (§21, *Lifetime*).
    """

    def __init__(
        self,
        *,
        email: str,
        password: str,
        reply_delay_s: float = DEFAULT_REPLY_DELAY_S,
        reply_steps: int = DEFAULT_REPLY_STEPS,
        ledger: Ledger | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.email = email
        self.password = password
        self.reply_delay_s = reply_delay_s
        self.reply_steps = reply_steps
        self.ledger = ledger if ledger is not None else Ledger()
        self.clock = clock
        self.chats: dict[str, Chat] = {}
        self.sessions: set[str] = set()
        self.pending_files: dict[str, list[str]] = {}
        self._lock = threading.Lock()

    # -- the clock ---------------------------------------------------------- #

    def now(self) -> float:
        """The mock's own clock. Injectable so the tests need no sleeps."""
        return float(self.clock())

    # -- sign-in ------------------------------------------------------------ #

    def credentials_match(self, email: str, password: str) -> bool:
        """Exactly one pair signs in. Any other is refused (§21)."""
        return email == self.email and password == self.password

    def sign_in(self) -> str:
        """Mint a session, and count the sign-in."""
        token = secrets.token_hex(16)
        with self._lock:
            self.sessions.add(token)
        self.ledger.count("sign_ins")
        return token

    def signed_in(self, token: str | None) -> bool:
        if not token:
            return False
        with self._lock:
            return token in self.sessions

    def sign_out(self, token: str | None) -> None:
        with self._lock:
            self.sessions.discard(token or "")

    # -- chats -------------------------------------------------------------- #

    def chat(self, chat_id: str) -> Chat | None:
        with self._lock:
            return self.chats.get(chat_id)

    def create_chat(self, message: str, *, session: str) -> Chat:
        """A submit on `/new`: an id, a URL, a first turn, and an answer coming."""
        created = Chat(id=str(uuid.uuid4()))
        with self._lock:
            self.chats[created.id] = created
        self.ledger.count("chats_created")
        self.attach_pending(created, session=session)
        self.receive(created, message)
        return created

    def receive(self, chat: Chat, message: str) -> Chat:
        """One message into a chat, and the reply it will grow into."""
        line = asked_line(message)
        with self._lock:
            chat.turns = [*chat.view(self.now()), Turn("human", message)]
            chat.reply = Reply(
                text=line if line is not None else CANNED,
                started=self.now(),
                delay_s=self.reply_delay_s,
                steps=self.reply_steps,
            )
        self.ledger.count("messages_received")
        return chat

    def rename(self, chat: Chat, title: str) -> None:
        with self._lock:
            chat.title = title
        self.ledger.count("renames")

    # -- files -------------------------------------------------------------- #

    def accept_file(self, name: str, *, session: str) -> None:
        """A file into the composer. It belongs to the next message sent."""
        with self._lock:
            self.pending_files.setdefault(session, []).append(name)
        self.ledger.count("files_accepted")

    def pending(self, session: str) -> list[str]:
        with self._lock:
            return list(self.pending_files.get(session, ()))

    def attach_pending(self, chat: Chat, *, session: str) -> None:
        """Move whatever is in the composer's chip row into the chat."""
        with self._lock:
            names = self.pending_files.pop(session, [])
            chat.files.extend(names)

    # -- what a rehearsal reconciles against -------------------------------- #

    def counters(self) -> dict[str, int]:
        return self.ledger.counters()

    def chat_ids(self) -> Sequence[str]:
        with self._lock:
            return tuple(self.chats)


def names(files: Iterable[str]) -> list[str]:
    """File names, in order, without repeats — what the chip row shows."""
    seen: list[str] = []
    for name in files:
        if name not in seen:
            seen.append(name)
    return seen
