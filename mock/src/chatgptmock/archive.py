"""The chats, as the archive a ChatGPT export link downloads.

§55: the archive is in ChatGPT's own shape (ADR 0005), rendered from the mock's
chats at the moment of the fetch, so that a run can migrate into the mock and
then extract what it migrated. OpenAI publishes no description of that shape;
`docs/chatgpt-export-format.md` is the one place it is written down, every claim
in it *assumed* until a real export has been read, and this module renders what
that document says. The day a real export is read, the document changes first
and this module follows.

The decisions are the document's, each marked *decided in brief `05`* there:

- **Two members and nothing else** — `conversations.json` and `user.json`. An
  empty member would claim a feature the mock does not have.
- **One root node with no message, then the turns chained one under the other**,
  `current_node` the last of them.
- **`text` only.** A message's typed text and its pasted texts are its `parts`,
  the pasted texts first, since that is the order a reply read them in.
- **A file is named, never carried.** An accepted file sits in
  `metadata.attachments` on the user message that carried it, with no bytes
  behind its id — the one gap this archive has (§55).
- **Time is the chat's.** A chat is dated by its creation and its messages one
  second apart, so the same chats render the same bytes.
- **Finished turns only.** Never the prefix of a reply the page is still
  revealing.
"""

import io
import json
import mimetypes
import uuid
import zipfile
from collections.abc import Iterable, Sequence
from typing import Any

from chatgptmock.site import Chat, Message, Upload

CONVERSATIONS_FILE = "conversations.json"
USER_FILE = "user.json"

ENTRY_DATE_TIME = (1980, 1, 1, 0, 0, 0)
"""What every zip entry is stamped with — the format's own epoch, so the archive's
bytes depend on the chats and on nothing else."""

MODEL_SLUG = "auto"
"""What `default_model_slug` says. The mock has no model; `auto` is what the
format document reports an ordinary chat carries."""

ROOT = "root"
FILE_OFFSET = 1000
"""Names under a chat's id: the root node's, and where file ids start counting
so that none collides with a message's."""


def user_id(email: str) -> str:
    """Return the account's id, `user-…`, derived from the configured email (`user.json`)."""
    return f"user-{uuid.uuid5(uuid.NAMESPACE_URL, f'mailto:{email}').hex[:24]}"


def node_id(chat_id: str, name: str | int) -> str:
    """Return a node's id: a real UUID, derived from the chat's, the same on every fetch."""
    return str(uuid.uuid5(uuid.UUID(chat_id), str(name)))


def messages_of(chat: Chat, now: float) -> list[Message]:
    """Return the messages an archive carries: the thread, plus a reply only once whole."""
    return list(chat.messages) if chat.generating(now) else chat.view(now)


def attachment(chat: Chat, position: int, upload: Upload) -> dict[str, Any]:
    """One file reference, as `metadata.attachments` lists it: an id, a name, a type, a size."""
    return {
        "id": f"file-{uuid.UUID(node_id(chat.id, FILE_OFFSET + position)).hex}",
        "name": upload.name,
        "mime_type": mimetypes.guess_type(upload.name)[0] or "application/octet-stream",
        "size": upload.size,
    }


def message(chat: Chat, index: int, entry: Message) -> dict[str, Any]:
    """One message, in the export's shape."""
    moment = chat.created_at + index
    parts = [*entry.pasted, entry.text] if entry.text else list(entry.pasted)
    metadata: dict[str, Any] = {}
    if entry.files:
        metadata["attachments"] = [attachment(chat, position, upload) for position, upload in enumerate(entry.files)]
    return {
        "id": node_id(chat.id, index),
        "author": {"role": entry.role, "name": None, "metadata": {}},
        "create_time": moment,
        "update_time": moment,
        "content": {"content_type": "text", "parts": parts},
        "status": "finished_successfully",
        "end_turn": True,
        "weight": 1.0,
        "metadata": metadata,
        "recipient": "all",
        "channel": None,
    }


def mapping(chat: Chat, messages: Sequence[Message]) -> dict[str, Any]:
    """Return the nodes: a root with no message, then the turns chained one under the other."""
    ids = [node_id(chat.id, index) for index in range(len(messages))]
    root = node_id(chat.id, ROOT)
    nodes: dict[str, Any] = {
        root: {"id": root, "message": None, "parent": None, "children": ids[:1]},
    }
    for index, entry in enumerate(messages):
        nodes[ids[index]] = {
            "id": ids[index],
            "message": message(chat, index, entry),
            "parent": ids[index - 1] if index else root,
            "children": ids[index + 1 : index + 2],
        }
    return nodes


def conversation(chat: Chat, *, now: float) -> dict[str, Any]:
    """One chat as one conversation."""
    messages = messages_of(chat, now)
    nodes = mapping(chat, messages)
    return {
        "title": chat.title,
        "create_time": chat.created_at,
        "update_time": chat.created_at + len(messages),
        "mapping": nodes,
        "current_node": node_id(chat.id, len(messages) - 1) if messages else node_id(chat.id, ROOT),
        "conversation_id": chat.id,
        "id": chat.id,
        "is_archived": False,
        "default_model_slug": MODEL_SLUG,
        "gizmo_id": None,
        "gizmo_type": None,
        "conversation_template_id": None,
        "moderation_results": [],
        "plugin_ids": None,
        "safe_urls": [],
        "blocked_urls": [],
        "disabled_tool_ids": [],
        "conversation_origin": None,
        "voice": None,
        "async_status": None,
    }


def conversations(chats: Iterable[Chat], *, now: float) -> list[dict[str, Any]]:
    """Return every chat as a conversation, in the order given — `conversations.json`."""
    return [conversation(chat, now=now) for chat in chats]


def user(email: str) -> dict[str, Any]:
    """Return the one account, as `user.json` holds it."""
    return {"id": user_id(email), "email": email}


def render(chats: Sequence[Chat], *, email: str, now: float) -> bytes:
    """Return the archive: a flat zip, deflated, the two members at its top level."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in (
            (CONVERSATIONS_FILE, conversations(chats, now=now)),
            (USER_FILE, user(email)),
        ):
            entry = zipfile.ZipInfo(name, date_time=ENTRY_DATE_TIME)
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, json.dumps(payload, indent=2) + "\n")
    return buffer.getvalue()
