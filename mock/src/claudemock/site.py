"""The mock's state: accounts, chats, replies, and the clock they grow on.

This module is the behaviour. It holds no HTML and no HTTP — `pages.py` renders
it and `server.py` serves it — so that what the mock *does* can be read, and
tested, without a socket.

The two behaviours a rehearsal's honesty rests on — **obedience**, the one line a
seed asks for answered with exactly it, and **growth**, the reply appearing after
a delay and in steps — are the core's (`mockcore.reply`), because every mock has
them. What is here is what a chat on claude.ai *is*: a title, a transcript, the
files it took, and the reply it is writing.

A third behaviour is `32`'s, and smaller: the site keeps the **exports** it was
asked for — a token each, minted when the export page's confirmation is pressed —
and renders nothing itself. `archive.py` turns the chats into the archive a token
is fetched as.

A fourth is `49`'s (brief 07 §79): the site **signs people in by link**. An
address submitted mints a sign-in link instead of mailing one, remembered as
pending against the browser that asked; redeeming that link in that browser
signs it in, once. There is no password anywhere, because claude.ai has none.

Nothing here is a claim about claude.ai. `uimap.py` says which row of the UI map
each of these behaviours stands on.
"""

import base64
import secrets
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from mockcore.exports import Export, Exports, Part
from mockcore.ledger import Ledger
from mockcore.reply import DEFAULT_REPLY_DELAY_S, DEFAULT_REPLY_STEPS, Reply, Turn, answer
from mockcore.sessions import Pending, Sessions

from claudemock import EXPORT_CATEGORIES, IDENTITY, ORIGIN

SIGN_IN_LINK_PATH = "/magic-link"
"""Where a sign-in link lands: the real site's path, re-typed (ADR 0003). The
token rides in the fragment, `#<token>:<base64url address>`, which is the shape
the tool's `sign-in link` row records the real page reading off itself — and
which never reaches this server: the page's own script posts it."""

EMAIL_STEP = "email"
LINK_SENT_STEP = "link_sent"
"""The two states of the sign-in page: the address not yet given, and the link on
its way (the tool's `link sent` row)."""


@dataclass
class SignInLink:
    """One sign-in link the site minted: whose, for which browser, and whether it was spent.

    `pending` is the token of the browser that asked (its `mock_login` cookie):
    the link finishes the sign-in that began there and no other, which is what
    brief 07 §73 means by *spent here rather than opened*.
    """

    token: str
    email: str
    pending: str
    minted_at: float
    spent: bool = False

    @property
    def fragment(self) -> str:
        """The part after `#`: the token, then the address, base64url without padding."""
        address = base64.urlsafe_b64encode(self.email.encode("utf-8")).decode("ascii").rstrip("=")
        return f"{self.token}:{address}"


NEW_CHAT_TITLE = "New chat"
"""What a chat is called before anything renames it. Not a title of anything —
the mock never sees a source conversation."""


@dataclass
class Chat:
    """One chat: what it is called, what is in it, and what it is writing.

    `created_at` is wall-clock seconds, the one moment the archive dates a chat
    by; everything else about time here is the monotonic clock replies grow on.
    """

    id: str
    created_at: float
    title: str = NEW_CHAT_TITLE
    turns: list[Turn] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    reply: Reply | None = None

    def view(self, now: float) -> list[Turn]:
        """Return the transcript as the page shows it at `now`."""
        turns = list(self.turns)
        if self.reply is not None:
            text = self.reply.visible(now)
            if text:
                turns.append(Turn("assistant", text))
        return turns

    def generating(self, now: float) -> bool:
        return self.reply is not None and not self.reply.finished(now)


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
        reply_delay_s: float = DEFAULT_REPLY_DELAY_S,
        reply_steps: int = DEFAULT_REPLY_STEPS,
        ledger: Ledger | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self.email = email
        self.reply_delay_s = reply_delay_s
        self.reply_steps = reply_steps
        self.ledger = ledger if ledger is not None else Ledger(IDENTITY.heading)
        self.origin = ORIGIN
        """Where this process really answers, which is what its links are spelled
        with. `ORIGIN` until `server.create_app` is told what the socket bound —
        the default port in every ordinary run, and an ephemeral one under the
        mock's own tests."""
        self.clock = clock
        self.wall = wall
        self.chats: dict[str, Chat] = {}
        self.sessions = Sessions()
        self.pending_sign_ins = Pending()
        """The half-finished sign-ins: the browser's token, and the address it gave."""
        self.pending_files: dict[str, list[str]] = {}
        self._links: dict[str, SignInLink] = {}
        self._strays: set[str] = set()
        """Browsers that opened a link whose sign-in was not theirs (`link opened elsewhere`)."""
        self._exports = Exports(wall=wall)
        self._lock = threading.Lock()

    # -- the clock ---------------------------------------------------------- #

    def now(self) -> float:
        """Return the mock's own clock. Injectable so the tests need no sleeps."""
        return float(self.clock())

    # -- sign-in by link (`49`) -------------------------------------------- #

    def address_known(self, email: str) -> bool:
        """Exactly one address gets a link. Any other is refused (§21)."""
        return email == self.email

    def request_sign_in(self, email: str, *, pending: str) -> SignInLink | None:
        """Take an address from a browser: remember the sign-in it began, and mint its link.

        `None` for an address that is not the account's, and the browser's
        earlier attempt forgotten with it. A second ask from the same browser
        — the page's *resend* — mints a second link for the same pending
        sign-in, which is what a person who did not get the email needs.
        """
        if not self.address_known(email):
            self.forget_pending(pending)
            return None
        self.pending_sign_ins.remember(pending, email)
        link = SignInLink(token=secrets.token_hex(16), email=email, pending=pending, minted_at=float(self.wall()))
        with self._lock:
            self._links[link.token] = link
            self._strays.discard(pending)
        self.ledger.count("links_minted")
        return link

    def resend(self, pending: str) -> SignInLink | None:
        """Mint another link for a sign-in this browser began; `None` if it began none."""
        email = self.pending_sign_ins.pending(pending)
        return self.request_sign_in(email, pending=pending) if email else None

    def forget_pending(self, pending: str) -> None:
        """Forget whatever this browser began: the page's *change address*."""
        self.pending_sign_ins.forget(pending)
        with self._lock:
            self._strays.discard(pending)

    def sign_in_step(self, pending: str) -> str:
        """Which of the sign-in page's two states this browser is at."""
        with self._lock:
            stray = pending in self._strays
        return LINK_SENT_STEP if stray or self.pending_sign_ins.pending(pending) else EMAIL_STEP

    def redeem(self, token: str, email: str, *, pending: str) -> str | None:
        """Spend a link in a browser: a session, or `None` and the browser left at the code page.

        The link signs in the browser whose sign-in it finishes — the one that
        gave the address, still holding the same pending token — and once. A
        link opened elsewhere, twice, or with the wrong address signs nobody in;
        what the real site shows then is unobserved (`link opened elsewhere`),
        and the mock leaves that browser at the one page the tool recognises,
        the code field, with no code behind it: the code door is deferred (§80).
        """
        with self._lock:
            link = self._links.get(token)
            good = (
                link is not None
                and not link.spent
                and link.email == email
                and link.pending == pending
                and self.pending_sign_ins.pending(pending) == email
            )
            if link is not None and good:
                link.spent = True
            else:
                self._strays.add(pending)
        if not good:
            return None
        self.pending_sign_ins.forget(pending)
        return self.sign_in()

    def sign_in_links(self) -> Sequence[SignInLink]:
        """Every sign-in link minted, in the order minted — the listing that stands in for the inbox."""
        with self._lock:
            return tuple(self._links.values())

    def link_of(self, link: SignInLink) -> str:
        """Return the address a person would find in the email: on the site's own host, token in the fragment."""
        return f"{self.origin}{SIGN_IN_LINK_PATH}#{link.fragment}"

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

    def create_chat(self, message: str, *, session: str) -> Chat:
        """Return a submit on `/new`: an id, a URL, a first turn, and an answer coming."""
        created = Chat(id=str(uuid.uuid4()), created_at=float(self.wall()))
        with self._lock:
            self.chats[created.id] = created
        self.ledger.count("chats_created")
        self.attach_pending(created, session=session)
        self.receive(created, message)
        return created

    def receive(self, chat: Chat, message: str) -> Chat:
        """One message into a chat, and the reply it will grow into."""
        with self._lock:
            chat.turns = [*chat.view(self.now()), Turn("human", message)]
            chat.reply = answer(message, started=self.now(), delay_s=self.reply_delay_s, steps=self.reply_steps)
        self.ledger.count("messages_received")
        return chat

    def rename(self, chat: Chat, title: str) -> None:
        with self._lock:
            chat.title = title
        self.ledger.count("renames")

    # -- files -------------------------------------------------------------- #

    def accept_file(self, name: str, *, session: str) -> None:
        """Take a file into the composer. It belongs to the next message sent."""
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

    # -- exports (`32`) ------------------------------------------------------ #

    def request_export(self) -> Export:
        """Mint the link an ask gets instead of an email, and count the ask.

        The link is an *index*: it names one part per category, each with a
        single-use address of its own. `archive.CATEGORIES` is what those are,
        and the order is the manifest's.
        """
        export = self._exports.request(EXPORT_CATEGORIES)
        self.ledger.count("exports_requested")
        return export

    def fetch_export(self, token: str) -> Export | None:
        """Return the export a token names and count the fetch; `None` for one nobody minted.

        The index, which may be read again. The parts it names may not — that is
        `spend_part`.
        """
        return self._exports.fetch(token)

    def spend_part(self, part_token: str) -> Part | None:
        """Return the part a token names, once. `None` for an unknown part or a spent one.

        The manifest says so in its own words: each export URL can only be used
        once. A second fetch of the same part is `404` on a real account, and this
        is where the mock says the same.
        """
        return self._exports.spend(part_token)

    def expire_sessions(self) -> int:
        """Forget every session, so the next request is one whose sign-in lapsed.

        Reached only through the witness (`wire.EXPIRE_PATH`). Nothing the tool
        drives can ask for this: an expiry is something that happens *to* a run.
        """
        return self.sessions.close_all()

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


def names(files: Iterable[str]) -> list[str]:
    """File names, in order, without repeats — what the chip row shows."""
    seen: list[str] = []
    for name in files:
        if name not in seen:
            seen.append(name)
    return seen
