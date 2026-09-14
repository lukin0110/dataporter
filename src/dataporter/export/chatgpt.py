"""Recognising and counting a ChatGPT export (`43`, brief `06` §64).

The tool recognises and counts a ChatGPT archive and does not model it. What
it reads is what `docs/chatgpt-export-format.md` says, every line of which is
*assumed*: `user.json`, an object; `conversations.json`, an array of
conversation objects each with a `mapping`, or the numbered
`conversations-NNN.json` members a large export is split into. The fourteen
content types, the branches and the hidden messages are an importer's to read,
in the brief that reads them. Reading less is the point: a reader that pinned
fourteen assumed payload shapes before anyone had opened a real export would
be fourteen guesses a snapshot depended on.

Three numbers come out of one pass over the archive (§38):

- **conversations**, the objects in the conversation members;
- **files**, the members the archive carries that are not JSON documents and
  not the rendering for a person — the attachment bytes a 2026 export is
  reported to ship, which Claude's does not;
- **missing files**, the attachments a message refers to whose bytes no member
  carries: the one gap kind a ChatGPT snapshot has (§31, §64).

The fingerprint is the SHA-256 over the conversation members in name order —
one member, one hash, which is Claude's rule (`02`); several, one hash over all
of them in the order their names sort, so that a split export has one identity
however its members were listed.

Nothing here imports the export reader: `sources` reads this module through a
hook, and `export/source.py` reads it to refuse an archive that is not its own,
so this module knows the archive's *shape* and not the tool's view of one.
"""

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from orval import deep_get
from pydantic import BaseModel, ConfigDict, ValidationError

from dataporter import log
from dataporter.errors import ExportError
from dataporter.sources.base import LOOKS_LIKE, Reading

if TYPE_CHECKING:
    from dataporter.export.source import ExportView

_logger = log.get_logger(__name__)

CONVERSATIONS_FILE = "conversations.json"
SPLIT_FILE = re.compile(r"^conversations-\d+\.json$")
"""One member, or several numbered ones: OpenAI's own transfer article says a
large export "may contain numbered conversation JSON files instead"
(`docs/chatgpt-export-format.md`, *assumed*)."""

USER_FILE = "user.json"
"""The account, an object. Singular, where Claude's `users.json` is a list —
which is what tells the two archives apart by their names alone."""

HTML_FILE = "chat.html"
"""A rendering for a person, and the one non-JSON member that is not a file."""

CONVERSATIONS_KEY = "conversations"
"""The rare shape: an object wrapping the array under this key (*assumed*)."""

ATTACHMENT_ID = re.compile(r"^file[-_](?P<key>[0-9A-Za-z]+)")
"""An attachment id, `file-<key>` or `file_<key>`; a member carries the file
when its name holds the key. Members are reported both as `file_<id>.dat` and
under media directories, so the key is looked for anywhere in the name."""

CLAUDE_MEMBER = "users.json"
CLAUDE_KEY = "chat_messages"
"""What a Claude archive has that a ChatGPT one never does: the plural account
member, and a flat message list on each conversation (`02`)."""

NO_CONVERSATIONS = "no conversations member in the archive ({expected}): {display}"
NOT_AN_ARRAY = "{member} is not a JSON array of conversations: {display}"
NOT_AN_OBJECT = "{member}[{position}] is not an object: {display}"
INVALID_CONVERSATION = "invalid conversation at {member}[{position}] ({reason}): {display}"
USER_NOT_AN_OBJECT = f"{USER_FILE} is not an object: {{display}}"


class Envelope(BaseModel):
    """What a conversation must have to be counted: a `mapping`. Nothing else is read."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    mapping: dict[str, Any]


def looks_like(names: Sequence[str]) -> bool:
    """Whether an archive with these members is ChatGPT's, by its names alone.

    `user.json` is the account member no other source spells that way, and a
    numbered conversation member exists in no other export.
    """
    return USER_FILE in names or any(SPLIT_FILE.match(name) for name in names)


def conversation_members(names: Sequence[str], display: str) -> list[str]:
    """Return the members that hold conversations, in the order their names sort."""
    if CONVERSATIONS_FILE in names:
        return [CONVERSATIONS_FILE]
    split = sorted(name for name in names if SPLIT_FILE.match(name))
    if not split:
        raise ExportError(
            detail=NO_CONVERSATIONS.format(expected=f"{CONVERSATIONS_FILE} or conversations-NNN.json", display=display)
        )
    return split


def is_file(name: str) -> bool:
    """Whether a member is one the archive carries as bytes rather than as a document."""
    base = name.rsplit("/", 1)[-1]
    return not base.endswith(".json") and base != HTML_FILE


def read(view: "ExportView") -> Reading:
    """Count the archive, or refuse it with the reason (§64)."""
    names = view.names()
    if CLAUDE_MEMBER in names:
        raise ExportError(detail=LOOKS_LIKE.format(looks="Claude", asked="ChatGPT", display=view.display))
    digest = hashlib.sha256()
    conversations = 0
    referenced: list[str] = []
    for member in conversation_members(names, view.display):
        raw = view.read(member)
        digest.update(raw)
        for position, item in enumerate(_items(view, member, raw)):
            envelope = _envelope(view, member, position, item)
            conversations += 1
            referenced.extend(_attachment_ids(envelope.mapping))
    _account(view)
    carried = [name for name in names if is_file(name)]
    missing = [key for key in _unique(referenced) if not any(key in name for name in carried)]
    _logger.info(
        "chatgpt export shape",
        extra={
            "conversations": conversations,
            "members": len(names),
            "files": len(carried),
            "referenced": len(_unique(referenced)),
            "missing": len(missing),
        },
    )
    return Reading(
        conversations=conversations,
        fingerprint=digest.hexdigest(),
        files=len(carried),
        missing_files=len(missing),
    )


def _items(view: "ExportView", member: str, raw: bytes) -> list[Any]:
    """Return the member's conversations: the array, or the object that wraps one."""
    decoded = view.parse(view.decode(raw, member), member)
    if isinstance(decoded, Mapping) and isinstance(decoded.get(CONVERSATIONS_KEY), list):
        decoded = decoded[CONVERSATIONS_KEY]
    if not isinstance(decoded, list):
        raise ExportError(detail=NOT_AN_ARRAY.format(member=member, display=view.display))
    return decoded


def _envelope(view: "ExportView", member: str, position: int, item: Any) -> Envelope:
    """Validate one conversation's envelope, naming the other source when it is its shape."""
    if not isinstance(item, Mapping):
        raise ExportError(detail=NOT_AN_OBJECT.format(member=member, position=position, display=view.display))
    if CLAUDE_KEY in item:
        raise ExportError(detail=LOOKS_LIKE.format(looks="Claude", asked="ChatGPT", display=view.display))
    try:
        return Envelope.model_validate(dict(item))
    except ValidationError as exc:
        reason = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or '(root)'}: {error['msg']}" for error in exc.errors()
        )
        raise ExportError(
            detail=INVALID_CONVERSATION.format(member=member, position=position, reason=reason, display=view.display)
        ) from exc


def _account(view: "ExportView") -> None:
    """Check the account member is an object. Its fields are not read."""
    if not view.exists(USER_FILE):
        return
    decoded = view.parse(view.decode(view.read(USER_FILE), USER_FILE), USER_FILE)
    if not isinstance(decoded, Mapping):
        raise ExportError(detail=USER_NOT_AN_OBJECT.format(display=view.display))


def _attachment_ids(mapping: Mapping[str, Any]) -> Iterable[str]:
    """Every attachment key a message in the mapping refers to, in mapping order."""
    for node in mapping.values():
        attachments = deep_get(node, "message.metadata.attachments") if isinstance(node, dict) else None
        if not isinstance(attachments, list):
            continue
        for attachment in attachments:
            identifier = attachment.get("id") if isinstance(attachment, Mapping) else None
            match = ATTACHMENT_ID.match(identifier) if isinstance(identifier, str) else None
            if match is not None:
                yield match.group("key")


def _unique(values: Iterable[str]) -> list[str]:
    """Order-preserving deduplication.

    Hand-rolled for the fourth time in this tool (`docs/orval-candidates.md`,
    C5): `set` loses the order, and the order is what makes two reads of one
    archive report the same missing files in the same order.
    """
    seen: set[str] = set()
    kept: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            kept.append(value)
    return kept
