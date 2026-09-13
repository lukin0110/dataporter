"""The mock's state: the account, the chats, the replies, and the clock they grow on.

This module is the behaviour. It holds no HTML and no HTTP — `pages.py` renders
it and `server.py` serves it — so that what the mock *does* can be read, and
tested, without a socket. Obedience and growth are the core's
(`mockcore.reply`): a seed written for a ChatGPT destination asks the same way
(§54, *Obedient*).

What a chat on chatgpt.com *is*, as the map reports it: a title in the sidebar,
a thread of messages each carrying its author's role, and the reply being
written. Two things about a message are this site's own:

- **A long paste is an attachment.** OpenAI documents that more than 10,000
  characters pasted into the composer become an attachment (6825453). The page
  applies the rule; what reaches the site is a message with its typed text and
  its pasted texts apart, and the reply reads both — the line a seed asks for
  is in the pasted text, not in the composer.
- **A file belongs to the message that carried it.** The export names an
  accepted file on the user message it was attached to
  (`docs/chatgpt-export-format.md`), so the site keeps it there rather than on
  the chat.

Nothing here is a claim about chatgpt.com. `uimap.py` says which row of the UI
map each of these behaviours stands on.
"""

import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from mockcore.exports import Export, Exports
from mockcore.ledger import Ledger
from mockcore.reply import DEFAULT_REPLY_DELAY_S, DEFAULT_REPLY_STEPS, Reply, answer
from mockcore.sessions import Sessions

from chatgptmock import IDENTITY

PASTE_THRESHOLD = 10_000
"""Characters. Past this, an insertion into the composer becomes an attachment
(`paste over the threshold`, *reported (OpenAI 6825453)*). The page applies it;
the site only knows what arrived as pasted text."""

NEW_CHAT_TITLE = "New chat"
"""What a chat is called before anything renames it. Not a title of anything —
the mock never sees a source conversation."""


@dataclass(frozen=True)
class Upload:
    """One file the composer took: its name, and how many bytes the mock read and dropped."""

    name: str
    size: int


@dataclass(frozen=True)
class Message:
    """One message in a thread: who said it, what was typed, what was pasted, what was attached."""

    role: str
    text: str
    pasted: tuple[str, ...] = ()
    files: tuple[Upload, ...] = ()

    @property
    def content(self) -> str:
        """Everything the message says, the pasted texts first — what a reply reads."""
        return "\n".join([*self.pasted, self.text])


@dataclass
class Chat:
    """One chat: what it is called, what is in it, and what it is writing.

    `created_at` is wall-clock seconds, the one moment the archive dates a chat
    by; everything else about time here is the monotonic clock replies grow on.
    """

    id: str
    created_at: float
    title: str = NEW_CHAT_TITLE
    messages: list[Message] = field(default_factory=list)
    reply: Reply | None = None

    def view(self, now: float) -> list[Message]:
        """Return the thread as the page shows it at `now`."""
        messages = list(self.messages)
        if self.reply is not None:
            text = self.reply.visible(now)
            if text:
                messages.append(Message("assistant", text))
        return messages

    def generating(self, now: float) -> bool:
        return self.reply is not None and not self.reply.finished(now)


class Site:
    """Everything the mock knows, behind one lock.

    In memory and nowhere else: a walk in several sessions sees the same chats
    throughout because the process keeps running, and restarting it resets it
    (§54, *Lifetime*).
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
        wall: Callable[[], float] = time.time,
    ) -> None:
        self.email = email
        self.password = password
        self.reply_delay_s = reply_delay_s
        self.reply_steps = reply_steps
        self.ledger = ledger if ledger is not None else Ledger(IDENTITY.heading)
        self.clock = clock
        self.wall = wall
        self.chats: dict[str, Chat] = {}
        self.sessions = Sessions()
        self.pending_files: dict[str, list[Upload]] = {}
        self._exports = Exports(wall=wall)
        self._lock = threading.Lock()

    # -- the clock ---------------------------------------------------------- #

    def now(self) -> float:
        """Return the mock's own clock. Injectable so the tests need no sleeps."""
        return float(self.clock())

    # -- sign-in ------------------------------------------------------------ #

    def credentials_match(self, email: str, password: str) -> bool:
        """Exactly one pair signs in. Any other is refused (§54)."""
        return email == self.email and password == self.password

    def sign_in(self) -> str:
        """Mint a session, and count the sign-in."""
        token = self.sessions.open()
        self.ledger.count("sign_ins")
        return token

    def signed_in(self, token: str | None) -> bool:
        return self.sessions.holds(token)

    def sign_out(self, token: str | None) -> None:
        self.sessions.close(token)

    # -- chats -------------------------------------------------------------- #

    def chat(self, chat_id: str) -> Chat | None:
        with self._lock:
            return self.chats.get(chat_id)

    def create_chat(self, text: str, *, pasted: Sequence[str] = (), session: str) -> Chat:
        """Return a submit at the root: an id, a URL, a first message, and an answer coming."""
        created = Chat(id=str(uuid.uuid4()), created_at=float(self.wall()))
        with self._lock:
            self.chats[created.id] = created
        self.ledger.count("chats_created")
        self.receive(created, text, pasted=pasted, session=session)
        return created

    def receive(self, chat: Chat, text: str, *, pasted: Sequence[str] = (), session: str) -> Chat:
        """One message into a chat, with the files waiting in the composer, and the reply it grows into."""
        with self._lock:
            files = tuple(self.pending_files.pop(session, []))
            message = Message("user", text, pasted=tuple(pasted), files=files)
            chat.messages = [*chat.view(self.now()), message]
            chat.reply = answer(message.content, started=self.now(), delay_s=self.reply_delay_s, steps=self.reply_steps)
        self.ledger.count("messages_received")
        return chat

    def stop(self, chat: Chat) -> Chat:
        """Stop the reply where it is: what is on the page becomes the finished turn.

        `generating`: one control sends and, while the reply is being written,
        stops it. Not counted — stopping asks nothing new of the site.
        """
        with self._lock:
            chat.messages = chat.view(self.now())
            chat.reply = None
        return chat

    def rename(self, chat: Chat, title: str) -> None:
        with self._lock:
            chat.title = title
        self.ledger.count("renames")

    def sidebar(self) -> Sequence[Chat]:
        """Every chat as the sidebar lists them, newest first."""
        with self._lock:
            return tuple(reversed(self.chats.values()))

    # -- files -------------------------------------------------------------- #

    def accept_file(self, name: str, size: int, *, session: str) -> None:
        """Take a file into the composer. It belongs to the next message sent."""
        with self._lock:
            self.pending_files.setdefault(session, []).append(Upload(name, size))
        self.ledger.count("files_accepted")

    def pending(self, session: str) -> list[Upload]:
        with self._lock:
            return list(self.pending_files.get(session, ()))

    # -- exports ------------------------------------------------------------ #

    def request_export(self) -> Export:
        """Mint the link an ask gets instead of an email, and count the ask (§54)."""
        export = self._exports.request()
        self.ledger.count("exports_requested")
        return export

    def fetch_export(self, token: str) -> Export | None:
        """Return the export a token names and count the fetch; `None` for one nobody minted."""
        return self._exports.fetch(token)

    def exports(self) -> Sequence[Export]:
        """Every export asked for, in the order asked."""
        return self._exports.all()

    def all_chats(self) -> Sequence[Chat]:
        """Every chat, in the order created — what an archive holds."""
        with self._lock:
            return tuple(self.chats.values())

    # -- what a rehearsal reconciles against -------------------------------- #

    def counters(self) -> dict[str, int]:
        return self.ledger.counters()

    def chat_ids(self) -> Sequence[str]:
        with self._lock:
            return tuple(self.chats)
