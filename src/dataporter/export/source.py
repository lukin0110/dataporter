"""Reading an export, without ever writing to it.

`ExportSource` accepts a `.zip` or an extracted directory. Zips are opened in mode
`r` and members are read from the archive stream — nothing is extracted, so a
member name is never joined to a filesystem path and cannot escape anywhere.

This module is the only place a library exception becomes an `ExportError`: a
`zipfile.BadZipFile`, a `json.JSONDecodeError` or a pydantic `ValidationError`
never reaches a caller. Two things that are easy to get wrong and are handled
here on purpose:

- `JSONDecodeError.pos` is a *character* offset. The spec asks for a byte offset,
  and the two diverge as soon as the file contains anything non-ASCII — which a
  conversation export certainly does. The bytes are decoded explicitly first so
  the offset can be converted.
- `str(ValidationError)` appends `input_value='…'`, which is message text going
  straight into an operator-facing string and into `19`'s report. Only `loc` and
  `msg` are used.

`ExportError.default_transient` is `False`, so `ExportError(transient=…)` raises
`TypeError`. Pass `detail=` and nothing else.

Tolerance is asymmetric by design. An unrecognised *value* — an unknown sender, an
unknown block type, an unexpected top-level file — becomes an `UnsupportedItem`
and parsing continues. A structurally broken archive stops the run. A conversation
that fails validation counts as structural: the models are already maximally
tolerant, so what is left is a missing required field, and skipping it silently
would make `05`'s "Conversations found" undercount an export the operator is about
to migrate.
"""

import hashlib
import json
import re
import zipfile
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import TracebackType
from typing import Any

from pydantic import ValidationError

from dataporter import log
from dataporter.errors import ExportError
from dataporter.export.model import (
    KNOWN_BLOCK_TYPES,
    Conversation,
    Export,
    UnknownBlock,
    UnsupportedItem,
)

_logger = log.get_logger(__name__)

CONVERSATIONS_FILE = "conversations.json"
OPTIONAL_FILES = ("users.json", "projects.json", "memories.json")
KNOWN_FILES = frozenset({CONVERSATIONS_FILE, *OPTIONAL_FILES})

SENDERS = frozenset({"human", "assistant"})

_TOKEN = re.compile(r"[^A-Za-z0-9_.:/-]")


def _token(value: object, limit: int = 40) -> str:
    """A reason fragment safe to put in a report.

    The sender and the block `type` come from the export and end up in
    `report.json`, so they are reduced to a bounded, punctuation-free token.
    """
    raw = value if isinstance(value, str) else type(value).__name__
    return _TOKEN.sub("_", raw)[:limit] or "(empty)"


def _describe(exc: ValidationError) -> str:
    """A pydantic error as `loc: msg`, with the offending value left out.

    Same shape as `config._describe`, deliberately re-written rather than
    imported: a private name is not a cross-module contract.
    """
    parts = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"]) or "(root)"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)


# --------------------------------------------------------------------------- #
# Unsupported item collection
# --------------------------------------------------------------------------- #


class _Unsupported:
    """Aggregates by `(path, reason)` so `count` means what it says."""

    def __init__(self) -> None:
        self._counts: dict[tuple[str, str], int] = {}

    def add(self, path: str, reason: str, count: int = 1) -> None:
        key = (path, reason)
        self._counts[key] = self._counts.get(key, 0) + count

    def items(self) -> list[UnsupportedItem]:
        """Sorted, because `03` requires two plans of one export to be identical."""
        return [
            UnsupportedItem(path=path, reason=reason, count=count)
            for (path, reason), count in sorted(self._counts.items())
        ]


# --------------------------------------------------------------------------- #
# The source
# --------------------------------------------------------------------------- #


class ExportSource:
    """A read-only view of an export. Use as a context manager."""

    def __init__(self, path: Path, display: str) -> None:
        self.path = path
        self.display = display
        """The path exactly as the operator typed it.

        `str(Path("./nowhere"))` is `"nowhere"`, which would make every message
        below name something the operator never wrote. `01` makes the same note.
        """

    @classmethod
    def open(cls, path: Path | str) -> "ExportSource":
        """Open a `.zip` or an extracted directory."""
        display = str(path)
        resolved = Path(path)
        if not resolved.exists():
            raise ExportError(detail=f"export not found: {display}")
        if resolved.is_dir():
            return _DirectorySource(resolved, display)
        # The suffix counts as well as the magic bytes: `is_zipfile` reads the
        # end-of-central-directory record, which is exactly what a truncated
        # archive has lost. Something the operator called a `.zip` deserves
        # "corrupt zip archive", not "that is not a zip".
        if zipfile.is_zipfile(resolved) or resolved.suffix.lower() == ".zip":
            return _ZipSource(resolved, display)
        raise ExportError(
            detail=f"export is not a directory or a .zip archive: {display}"
        )

    @property
    def is_archive(self) -> bool:
        raise NotImplementedError  # pragma: no cover - abstract

    def names(self) -> list[str]:
        """Top-level member names, with any wrapping directory stripped."""
        raise NotImplementedError  # pragma: no cover - abstract

    def read(self, member: str) -> bytes:
        raise NotImplementedError  # pragma: no cover - abstract

    def exists(self, member: str) -> bool:
        return member in self.names()

    def close(self) -> None:
        return None

    def __enter__(self) -> "ExportSource":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    # -- shared decoding ---------------------------------------------------- #

    def decode(self, data: bytes, member: str) -> str:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ExportError(
                detail=(
                    f"{member} is not valid UTF-8 at byte {exc.start}: {self.display}"
                )
            ) from exc

    def parse(self, body: str, member: str) -> Any:
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            offset = len(body[: exc.pos].encode("utf-8"))
            raise ExportError(
                detail=(
                    f"{member} is not valid JSON at byte {offset} "
                    f"({exc.msg}): {self.display}"
                )
            ) from exc


class _DirectorySource(ExportSource):
    """An extracted export on disk."""

    def __init__(self, path: Path, display: str) -> None:
        super().__init__(path, display)
        self._root = _directory_root(path)

    @property
    def is_archive(self) -> bool:
        return False

    def names(self) -> list[str]:
        return sorted(item.name for item in self._root.iterdir() if item.is_file())

    def read(self, member: str) -> bytes:
        target = self._root / member
        try:
            return target.read_bytes()
        except OSError as exc:
            raise ExportError(
                detail=f"cannot read {member} ({exc.strerror}): {self.display}"
            ) from exc


class _ZipSource(ExportSource):
    """A `.zip` export, read from the archive stream."""

    def __init__(self, path: Path, display: str) -> None:
        super().__init__(path, display)
        try:
            self._archive = zipfile.ZipFile(path, "r")
            members = [
                info.filename for info in self._archive.infolist() if not info.is_dir()
            ]
        except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError) as exc:
            raise ExportError(
                detail=f"corrupt zip archive ({exc}): {self.display}"
            ) from exc
        self._prefix = _archive_prefix(members)
        self._members = {
            name[len(self._prefix) :]: name
            for name in members
            if name.startswith(self._prefix)
        }

    @property
    def is_archive(self) -> bool:
        return True

    def names(self) -> list[str]:
        return sorted(self._members)

    def read(self, member: str) -> bytes:
        name = self._members.get(member)
        if name is None:
            raise ExportError(detail=f"{member} missing from export: {self.display}")
        try:
            with self._archive.open(name) as stream:
                # A full read is CRC-checked; nothing is written to disk.
                return stream.read()
        except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError) as exc:
            raise ExportError(
                detail=(
                    f"cannot read {member} from the archive ({exc}): {self.display}"
                )
            ) from exc

    def close(self) -> None:
        self._archive.close()


def _archive_prefix(members: list[str]) -> str:
    """`""`, or the single wrapping directory an export was zipped inside.

    Handing the tool an archive whose members sit under one folder is the most
    likely operator mistake, and detecting it is read-only and cheap.
    """
    if any("/" not in name for name in members):
        return ""
    roots = {name.split("/", 1)[0] for name in members}
    if len(roots) != 1:
        return ""
    return f"{roots.pop()}/"


def _directory_root(path: Path) -> Path:
    """The directory holding `conversations.json`: `path`, or one level down."""
    if (path / CONVERSATIONS_FILE).exists():
        return path
    children = [item for item in path.iterdir() if item.is_dir()]
    if len(children) == 1 and (children[0] / CONVERSATIONS_FILE).exists():
        return children[0]
    return path


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def load_export(path: Path | str) -> Export:
    """Parse an export. The export is never written to."""
    with ExportSource.open(path) as source:
        return read_export(source)


def read_export(source: ExportSource) -> Export:
    """Parse an already-open source."""
    unsupported = _Unsupported()
    names = source.names()
    _logger.info(
        "export opened",
        extra={
            "export_path": source.display,
            "archive": source.is_archive,
            "files": names,
        },
    )

    for name in names:
        if name not in KNOWN_FILES:
            _logger.warning("export unknown file", extra={"member": name})
            unsupported.add(name, "unknown_file")

    if CONVERSATIONS_FILE not in names:
        raise ExportError(
            detail=f"{CONVERSATIONS_FILE} missing from export: {source.display}"
        )

    raw = source.read(CONVERSATIONS_FILE)
    fingerprint = hashlib.sha256(raw).hexdigest()
    decoded = source.parse(source.decode(raw, CONVERSATIONS_FILE), CONVERSATIONS_FILE)
    if not isinstance(decoded, list):
        raise ExportError(
            detail=f"{CONVERSATIONS_FILE} is not a JSON array: {source.display}"
        )

    conversations = [
        _conversation(item, position, source, unsupported)
        for position, item in enumerate(decoded)
    ]
    users = _optional_list("users.json", source, unsupported)
    projects = _optional_list("projects.json", source, unsupported)
    memories = _optional_list("memories.json", source, unsupported)

    export = Export(
        conversations=conversations,
        users=users,
        unsupported=unsupported.items(),
        fingerprint=fingerprint,
    )
    _log_shape(export, projects=len(projects), memories=len(memories))
    return export


def _conversation(
    item: Any, position: int, source: ExportSource, unsupported: _Unsupported
) -> Conversation:
    """Validate one conversation, dropping what cannot be represented."""
    if not isinstance(item, Mapping):
        raise ExportError(
            detail=(
                f"{CONVERSATIONS_FILE}[{position}] is not an object: {source.display}"
            )
        )
    data: dict[str, Any] = {str(key): value for key, value in item.items()}
    uuid = data.get("uuid") if isinstance(data.get("uuid"), str) else f"[{position}]"
    path = f"{CONVERSATIONS_FILE}:{uuid}"

    # `sender` is a Literal, so an unknown one cannot be represented at all. It has
    # to go before validation, from the raw dicts.
    messages = data.get("chat_messages")
    if isinstance(messages, list):
        kept: list[Any] = []
        dropped = 0
        for message in messages:
            sender = message.get("sender") if isinstance(message, Mapping) else None
            if isinstance(sender, str) and sender in SENDERS:
                kept.append(message)
                continue
            dropped += 1
            unsupported.add(path, f"unknown_sender:{_token(sender)}")
        if dropped:
            _logger.warning(
                "export sender unknown",
                extra={"conversation_id": uuid, "count": dropped},
            )
        data["chat_messages"] = kept

    try:
        conversation = Conversation.model_validate(data)
    except ValidationError as exc:
        raise ExportError(
            detail=(
                f"invalid conversation at {CONVERSATIONS_FILE}[{position}] "
                f"({_describe(exc)}): {source.display}"
            )
        ) from exc

    _collect_blocks(conversation, path, unsupported)
    _collect_duplicates(conversation, path, unsupported)
    return conversation


def _collect_blocks(
    conversation: Conversation, path: str, unsupported: _Unsupported
) -> None:
    """Record every block the models could not represent."""
    for block in _blocks(conversation):
        if not isinstance(block, UnknownBlock):
            continue
        if not block.type:
            unsupported.add(path, "untyped_block")
        elif block.type in KNOWN_BLOCK_TYPES:
            unsupported.add(path, f"malformed_block:{_token(block.type)}")
        else:
            unsupported.add(path, f"unknown_block_type:{_token(block.type)}")


def _collect_duplicates(
    conversation: Conversation, path: str, unsupported: _Unsupported
) -> None:
    seen: set[str] = set()
    for message in conversation.chat_messages:
        if message.uuid in seen:
            unsupported.add(path, "duplicate_message_uuid")
        seen.add(message.uuid)


def _blocks(conversation: Conversation) -> Iterator[Any]:
    for message in conversation.chat_messages:
        yield from message.content


def _optional_list(
    member: str, source: ExportSource, unsupported: _Unsupported
) -> list[dict[str, Any]]:
    """Read an optional top-level file for counts. Absence is not an error.

    A malformed optional file is not fatal either: only `conversations.json` can
    stop a run, because only it decides what gets migrated.
    """
    if not source.exists(member):
        return []
    try:
        decoded = source.parse(source.decode(source.read(member), member), member)
    except ExportError:
        _logger.warning("export file unparsable", extra={"member": member})
        unsupported.add(member, "unparsable_file")
        return []
    if not isinstance(decoded, list):
        _logger.warning("export file unparsable", extra={"member": member})
        unsupported.add(member, "unparsable_file")
        return []
    return [
        {str(key): value for key, value in entry.items()}
        for entry in decoded
        if isinstance(entry, Mapping)
    ]


def _log_shape(export: Export, *, projects: int, memories: int) -> None:
    """One record per export, so a shape drift is visible on the run that hits it.

    Counts, uuid-free tokens and file names only: `ToolResultBlock` has a field
    named `content` and `Conversation.name` is the title, so no model or dump of
    one may ever appear in an `extra` mapping.
    """
    messages = 0
    blocks = 0
    with_index = 0
    with_files = 0
    with_files_v2 = 0
    attachments = 0
    block_types: set[str] = set()
    for conversation in export.conversations:
        for message in conversation.chat_messages:
            messages += 1
            blocks += len(message.content)
            with_index += message.index is not None
            with_files += bool(message.files)
            with_files_v2 += bool(message.files_v2)
            attachments += (
                len(message.attachments) + len(message.files) + len(message.files_v2)
            )
            block_types.update(_block_type(block) for block in message.content)
    _logger.info(
        "export shape",
        extra={
            "conversations": len(export.conversations),
            "messages": messages,
            "blocks": blocks,
            "with_index": with_index,
            "with_leaf": sum(
                conversation.current_leaf_message_uuid is not None
                for conversation in export.conversations
            ),
            "with_files": with_files,
            "with_files_v2": with_files_v2,
            "attachments": attachments,
            "block_types": sorted(block_types),
            "users": len(export.users),
            "projects": projects,
            "memories": memories,
            "unsupported": len(export.unsupported),
            "fingerprint": export.fingerprint,
        },
    )


def _block_type(block: Any) -> str:
    tag = getattr(block, "type", "")
    return _token(tag) if tag else "(untyped)"
