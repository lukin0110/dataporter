"""The chats, as the archive a Claude export link downloads.

`32`'s other half: the export page (`pages.py`) mints a link, and this is what the
link is fetched as — a zip holding `conversations.json` and `users.json`, rendered
from the site's chats at the moment of the fetch. No state and no HTTP, like
`pages.py`: `site.py` holds the chats and `server.py` serves the bytes.

The shape is the vendor's, spelled here by hand. The tool reads it with its own
models and `rehearsal/export.py` writes the same shape for a rehearsal, and this
module imports neither: the mock knows nothing about the tool (ADR 0003), so a
key the tool validates is a literal below, and a change to the export format is a
change in two places on purpose. What the tool requires is small — a
conversation's `uuid`, `name`, `created_at`, `updated_at` and `chat_messages`,
each message's `uuid`, `sender`, `text` and `created_at` — and everything else is
what a real archive carries beside them.

Three decisions, each the simplest thing the tool accepts:

- **Finished turns only.** A chat still generating contributes what is in its
  transcript, never the prefix of a reply the page is still revealing: a half
  line is text that will never exist in the account.
- **Time is the chat's.** A chat is dated by `Chat.created_at`, and its messages
  one second apart from there. Monotone within a conversation, and nothing the
  page shows has to remember when it was said.
- **The same chats give the same bytes.** Entries carry a fixed timestamp and the
  JSON is rendered the same way every time, so a link fetched twice — once by the
  tool and once by hand — downloads one archive (§39, 2).
"""

import io
import json
import uuid
import zipfile
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from claudemock.site import Chat, Turn

CONVERSATIONS_FILE = "conversations.json"
USERS_FILE = "users.json"
"""The two files. `projects.json` and `memories.json` are optional to the tool and
the mock has neither, and an empty file would claim a feature the site lacks."""

ENTRY_DATE_TIME = (1980, 1, 1, 0, 0, 0)
"""What every zip entry is stamped with — the format's own epoch, so the archive's
bytes depend on the chats and on nothing else."""

FILE_UUID_OFFSET = 1000
"""Where the file references' uuids start counting, so none collides with a
message's."""

STAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def stamp(seconds: float) -> str:
    """Wall-clock seconds as the export writes a timestamp: UTC, microseconds, `Z`."""
    return datetime.fromtimestamp(seconds, UTC).strftime(STAMP_FORMAT)


def account_uuid(email: str) -> str:
    """Return the one account's id, the same across restarts."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"mailto:{email}"))


def message_uuid(chat_id: str, index: int) -> str:
    """Return a message's id: a real UUID, derived from the chat's, the same on every fetch."""
    return str(uuid.uuid5(uuid.UUID(chat_id), str(index)))


def turns_of(chat: Chat, now: float) -> list[Turn]:
    """Return the turns an archive carries: the transcript, plus a reply only once whole."""
    return list(chat.turns) if chat.generating(now) else chat.view(now)


def message(chat: Chat, index: int, turn: Turn, *, files: Sequence[str] = ()) -> dict[str, object]:
    """One message, in the export's shape."""
    when = stamp(chat.created_at + index)
    refs = [
        {"file_name": name, "file_uuid": message_uuid(chat.id, FILE_UUID_OFFSET + position)}
        for position, name in enumerate(files)
    ]
    return {
        "uuid": message_uuid(chat.id, index),
        "text": turn.text,
        "content": [{"type": "text", "text": turn.text}],
        "sender": turn.role,
        "created_at": when,
        "updated_at": when,
        "attachments": [],
        "files": refs,
        "files_v2": list(refs),
        "index": index,
        "parent_message_uuid": message_uuid(chat.id, index - 1) if index else None,
    }


def conversation(chat: Chat, *, email: str, now: float) -> dict[str, object]:
    """One chat as one conversation.

    The files the chat accepted are named on its first message — the human turn
    that created it, which is where they were attached — as references and never
    as bytes, which is the one gap a Claude export has (§31).
    """
    turns = turns_of(chat, now)
    messages = [message(chat, index, turn, files=chat.files if index == 0 else ()) for index, turn in enumerate(turns)]
    return {
        "uuid": chat.id,
        "name": chat.title,
        "summary": "",
        "created_at": stamp(chat.created_at),
        "updated_at": stamp(chat.created_at + len(messages)),
        "account": {"uuid": account_uuid(email)},
        "chat_messages": messages,
        "current_leaf_message_uuid": str(messages[-1]["uuid"]) if messages else None,
    }


def conversations(chats: Iterable[Chat], *, email: str, now: float) -> list[dict[str, object]]:
    return [conversation(chat, email=email, now=now) for chat in chats]


def users(email: str) -> list[dict[str, object]]:
    """Return the one account, as `users.json` lists it."""
    return [{"uuid": account_uuid(email), "full_name": "Rehearsal Operator", "email_address": email}]


def render(chats: Sequence[Chat], *, email: str, now: float) -> bytes:
    """Return the archive: a flat zip, deflated, the two files at its top level."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in (
            (CONVERSATIONS_FILE, conversations(chats, email=email, now=now)),
            (USERS_FILE, users(email)),
        ):
            entry = zipfile.ZipInfo(name, date_time=ENTRY_DATE_TIME)
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, json.dumps(payload, indent=2) + "\n")
    return buffer.getvalue()
