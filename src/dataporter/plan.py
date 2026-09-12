"""Classification: what can be migrated, and what happens to every attachment.

The plan is computed once, offline, and then executed. `05` prints it, `12` runs
it, `19` reports it — none of them recompute, which is what makes the dry run's
numbers, the progress block's numbers and the report's numbers the same numbers.

Determinism is the property to protect: the same export and the same settings must
produce byte-identical `plan.json`. Everything here iterates in export order, and
the only observation of the outside world is whether a named file exists under the
attachments directory, how large it is, and — since `16` uploads one file once
however many messages named it — what its bytes hash to.

Nothing in this module may log content. `file_name` is safe; a title, a message or
a rendered seed is not (`log.FORBIDDEN_FIELDS`).
"""

import hashlib
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Literal

from orval import strip_control
from pydantic import BaseModel, ConfigDict

from dataporter import log, render
from dataporter.config import Settings
from dataporter.export.model import (
    Attachment,
    ChatMessage,
    Conversation,
    Export,
    FileRef,
)

_logger = log.get_logger(__name__)

AttachmentClass = render.AttachmentClass

PLAN_FILENAME = "plan.json"
"""Where `12` writes the plan, and where `19` reads it back.

Here rather than beside the loop that writes it: the file is a contract between
three slices, and the module that defines its shape is where its name belongs —
`19` reads it without importing the importer.
"""

EMPTY_CONVERSATION = "empty_conversation"
NO_REPRESENTABLE_TEXT = "no_representable_text"
SEED_OVER_HARD_CAP = "seed_over_hard_cap"

TYPE_NOT_ACCEPTED = "type_not_accepted"
BYTES_NOT_IN_EXPORT = "bytes_not_in_export"
TOO_LARGE = "too_large"
TOO_MANY_FOR_CHAT = "too_many_for_chat"
SKIPPED_BY_FLAG = "skipped_by_flag"
"""`16`'s `--skip-attachments`: a class 2 entry nobody is going to upload.

A reason of its own rather than one of the four above, because §14's question
about an attachment the report has to answer is "why is it not in the new chat",
and "the operator asked for that" is a different answer from "we do not have the
bytes". `19` is what tells the two apart in the report.
"""

DIGEST_CHUNK = 1 << 20
"""How much of a file is hashed at a time. `attachments.max_bytes` is thirty
megabytes by default and the digest is taken during planning, so the file is read
a megabyte at a time rather than into memory whole."""

_MIME_EXTENSIONS = {
    "application/json": "json",
    "application/pdf": "pdf",
    "application/xml": "xml",
    "image/gif": "gif",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "text/csv": "csv",
    "text/html": "html",
    "text/markdown": "md",
    "text/plain": "txt",
    "text/xml": "xml",
    "text/yaml": "yaml",
}
"""Enough MIME types to type a file whose name has no suffix.

The spec lists *extensions* while the export carries a MIME type on
`attachments[]` and nothing at all on `files[]`, so the name is authoritative and
this is the fallback, not the other way round.
"""

_UNSAFE_IN_NAME = ("/", "\\")
"""The separators. `:`, `*` and `?` are *not* rejected: they are legal on the
systems these exports come from, and refusing them would report a file that is
really there as bytes we do not have.

Control characters are refused as well, through `orval.strip_control` rather
than a pattern of our own — an export is trusted or distrusted once, and
`log.safe_token` reduces the same set for the other reason. The predicate is
spelled as a comparison because orval offers no `has_control`; see candidate C8.
NUL alone was the original rule; a newline or a carriage return is the same kind
of thing and reaches further, since such a name is joined into a path here and
printed by `04` when the conversation is skipped.
"""


# --------------------------------------------------------------------------- #
# The plan
# --------------------------------------------------------------------------- #


class PlanModel(BaseModel):
    """Base for the plan: immutable, and closed.

    Unlike the export models this shape is ours. `plan.json` is a contract `05`,
    `12` and `19` read, so an unexpected key is a bug in us, not drift in someone
    else's file, and `extra="forbid"` says so at the boundary.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class AttachmentPlan(PlanModel):
    """One file, and what will become of it."""

    message_uuid: str
    file_name: str
    file_type: str | None = None
    file_size: int | None = None
    klass: Literal["inline", "upload", "unsupported"]
    reason: str | None = None
    """Why it is unsupported. Always set when `klass == "unsupported"`."""
    source_path: Path | None = None
    """Where the bytes are. Set only when `klass == "upload"`."""
    sha256: str | None = None
    """Of the bytes at `source_path`. Set only when `klass == "upload"`.

    What `16` deduplicates on: one chat uploads one file once, however many
    messages of the conversation referred to it.
    """
    duplicate_of: str | None = None
    """The file name this entry's bytes were already planned under, earlier in
    the same conversation. `None` for the entry that is actually uploaded.

    An entry with this set is still `upload`: the file *is* in the chat, as one
    chip, and the message this entry belongs to refers to that chip. It is what
    keeps the upload list one file long while the report still accounts for both
    references (`19`).
    """


class ConversationPlan(PlanModel):
    """One conversation, and whether it can be migrated."""

    uuid: str
    migratable: bool
    reasons: list[str] = []
    """The blocking reason first, when there is one, then limitation slugs."""
    message_count: int
    off_path_count: int
    attachments: list[AttachmentPlan] = []
    estimated_seed_chars: int
    chunk_count: int


class PlanTotals(PlanModel):
    """The numbers `05` prints."""

    conversations: int
    messages: int
    attachments: int
    migratable: int
    unsupported: int


class MigrationPlan(PlanModel):
    """What a run would do, before it does any of it."""

    export_fingerprint: str
    conversations: list[ConversationPlan] = []
    totals: PlanTotals


# --------------------------------------------------------------------------- #
# The planner
# --------------------------------------------------------------------------- #


class Planner:
    """Turns a parsed export into a `MigrationPlan`.

    Settings are held rather than passed to `plan()` (the spec writes
    `Planner.plan(export, settings)`): every private step needs them, and one
    planner replanning under different settings has no caller. `build_plan` keeps
    the spec's call shape for anyone who wants it.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._attachments_dir = settings.attachments_dir

    def plan(self, export: Export) -> MigrationPlan:
        conversations = [
            self._conversation(conversation) for conversation in export.conversations
        ]
        totals = PlanTotals(
            conversations=len(conversations),
            messages=sum(item.message_count for item in conversations),
            attachments=sum(len(item.attachments) for item in conversations),
            migratable=sum(1 for item in conversations if item.migratable),
            unsupported=sum(1 for item in conversations if not item.migratable),
        )
        _logger.info(
            "plan built",
            extra={
                "conversations": totals.conversations,
                "messages": totals.messages,
                "attachments": totals.attachments,
                "migratable": totals.migratable,
                "unsupported": totals.unsupported,
            },
        )
        return MigrationPlan(
            export_fingerprint=export.fingerprint,
            conversations=conversations,
            totals=totals,
        )

    # -- one conversation --------------------------------------------------- #

    def render_conversation(
        self, conversation: Conversation
    ) -> render.RenderedConversation | None:
        """The seed rendering for one conversation, or `None` when it has no
        messages on its active path.

        Named for what it wraps rather than plain `render`: a method of that name
        would shadow the `render` module inside this class body, where several
        signatures below name `render.AttachmentRender`.

        Public because `04` builds its `Seed` from exactly this: a seed written
        from a different rendering than the one the plan measured would carry a
        `chunk_count` that no file on disk agrees with. It classifies the
        attachments again rather than taking them from a `ConversationPlan`,
        because an inline attachment's text is deliberately not in the plan
        (`19` reads `plan.json`, and a report is not the place for the contents
        of someone's spreadsheet).
        """
        active = conversation.active_path()
        if not active:
            return None
        _, by_message = self._attachments(conversation, active)
        return self._render(
            conversation, active, by_message, len(conversation.off_path())
        )

    def _render(
        self,
        conversation: Conversation,
        active: Sequence[ChatMessage],
        by_message: dict[str, list[render.AttachmentRender]],
        off_path: int,
    ) -> render.RenderedConversation:
        return render.render_conversation(
            conversation,
            active,
            by_message,
            max_chars=self._settings.seed.max_chars,
            branches_dropped=off_path,
        )

    def _conversation(self, conversation: Conversation) -> ConversationPlan:
        # `active_path()` and `off_path()` each recompute the split; `02` leaves
        # the caching to this slice, so both are taken once here.
        active = conversation.active_path()
        off_path = len(conversation.off_path())
        attachments, by_message = self._attachments(conversation, active)

        if not active:
            # Nothing to render: an envelope around no messages is not a seed,
            # and reporting its length as `estimated_seed_chars` would be a
            # number that means nothing.
            return ConversationPlan(
                uuid=conversation.uuid,
                migratable=False,
                reasons=[EMPTY_CONVERSATION],
                message_count=0,
                off_path_count=off_path,
                attachments=attachments,
                estimated_seed_chars=0,
                chunk_count=0,
            )

        rendered = self._render(conversation, active, by_message, off_path)

        blocking = blocking_reason(rendered, self._settings)
        reasons: list[str] = [] if blocking is None else [blocking]
        migratable = not reasons
        reasons.extend(rendered.limitations.slugs())

        return ConversationPlan(
            uuid=conversation.uuid,
            migratable=migratable,
            reasons=reasons,
            message_count=len(active),
            off_path_count=off_path,
            attachments=attachments,
            estimated_seed_chars=rendered.total_chars,
            chunk_count=len(rendered.chunks),
        )

    # -- attachments -------------------------------------------------------- #

    def _attachments(
        self, conversation: Conversation, messages: Sequence[ChatMessage]
    ) -> tuple[list[AttachmentPlan], dict[str, list[render.AttachmentRender]]]:
        """Every distinct file on the active path, classified.

        Returns the plan entries and the same verdicts keyed by message, since
        rendering needs an inline attachment's text and `AttachmentPlan` does not
        carry content — `plan.json` reaches `19` and a report is not the place for
        the contents of someone's spreadsheet.

        Three conversation-wide rules are applied here rather than in
        `_classify`, because each is about the chat and not about the file:

        - `--skip-attachments` (`16`) turns every class 2 entry into class 3 with
          the reason `skipped_by_flag`, before either rule below sees it: a file
          nobody will upload consumes no cap and deduplicates against nothing.
        - **Identical bytes are uploaded once.** The second entry whose sha256 has
          already been planned keeps `upload` and points at the first one's name,
          so the seed refers to the chip that will exist rather than to a second
          one that will not.
        - The `max_per_chat` cap is applied last: it is a limit on one chat's
          uploads, not on one message's, and only `upload` entries that are
          really uploaded consume it — an inline attachment is text in the seed
          and never touches the file picker, and a duplicate is a file already
          counted.
        """
        out: list[AttachmentPlan] = []
        by_message: dict[str, list[render.AttachmentRender]] = {}
        planned: dict[str, str] = {}
        """sha256 → the file name it was first planned under."""
        uploads = 0
        limit = self._settings.attachments.max_per_chat
        for message in messages:
            for entry in _distinct(message):
                item = self._classify(conversation, message, entry)
                if item.klass == "upload":
                    if self._settings.attachments.skip:
                        item = _refused(item, SKIPPED_BY_FLAG)
                    elif item.sha256 in planned:
                        item = item.model_copy(
                            update={"duplicate_of": planned[item.sha256 or ""]}
                        )
                    elif uploads >= limit:
                        item = _refused(item, TOO_MANY_FOR_CHAT)
                    else:
                        uploads += 1
                        planned[item.sha256 or ""] = item.file_name
                out.append(item)
                by_message.setdefault(message.uuid, []).append(
                    render.AttachmentRender(
                        # The name the chat will show: for a duplicate that is
                        # the name its bytes were uploaded under, which may not
                        # be the name this message called them.
                        file_name=item.duplicate_of or item.file_name,
                        file_type=item.file_type,
                        file_size=item.file_size,
                        klass=item.klass,
                        reason=item.reason,
                        extracted_content=(
                            entry.extracted_content
                            if isinstance(entry, Attachment)
                            else None
                        ),
                    )
                )
        return out, by_message

    def _classify(
        self,
        conversation: Conversation,
        message: ChatMessage,
        entry: Attachment | FileRef,
    ) -> AttachmentPlan:
        """§14's three classes for one entry.

        The class-3 reasons are decided in a fixed order — type, then bytes, then
        size — which runs from what is knowable without touching a disk to what is
        knowable only after finding the file. It also puts the one reason an
        operator can act on (`bytes_not_in_export`, fixed by supplying an
        attachments directory) *after* the one that no directory can fix, so
        nobody goes hunting for a file that would be refused on arrival.
        """
        file_name = entry.file_name
        declared = entry if isinstance(entry, Attachment) else None

        def verdict(
            klass: AttachmentClass,
            *,
            reason: str | None = None,
            source_path: Path | None = None,
            file_size: int | None = None,
            sha256: str | None = None,
        ) -> AttachmentPlan:
            return AttachmentPlan(
                message_uuid=message.uuid,
                file_name=file_name,
                file_type=declared.file_type if declared else None,
                file_size=(
                    file_size
                    if file_size is not None
                    else (declared.file_size if declared else None)
                ),
                klass=klass,
                reason=reason,
                source_path=source_path,
                sha256=sha256,
            )

        if declared is not None and (declared.extracted_content or "").strip():
            return verdict("inline")

        accepted = self._settings.attachments.accepted_types
        file_type = declared.file_type if declared else None
        if _extension(file_name, file_type) not in accepted:
            return verdict("unsupported", reason=TYPE_NOT_ACCEPTED)

        source = self._locate(conversation.uuid, file_name)
        if source is None:
            return verdict("unsupported", reason=BYTES_NOT_IN_EXPORT)

        size = source.stat().st_size
        if size > self._settings.attachments.max_bytes:
            return verdict("unsupported", reason=TOO_LARGE, file_size=size)
        digest = _digest(source)
        if digest is None:
            # It was there a moment ago and cannot be read now: a permission,
            # a race with whoever is filling the directory, a disk. Bytes we
            # cannot read are bytes we do not have, which is the reason the
            # operator can act on.
            return verdict("unsupported", reason=BYTES_NOT_IN_EXPORT, file_size=size)
        return verdict("upload", source_path=source, file_size=size, sha256=digest)

    def _locate(self, conversation_uuid: str, file_name: str) -> Path | None:
        """`<dir>/<uuid>/<name>`, then `<dir>/<name>`, or nothing.

        Both components come from the export, so both are checked before they are
        joined: a `file_name` of `../../etc/passwd` must not resolve outside the
        attachments directory, which is the finding `02`'s review raised against
        `ExportSource.read`. A rejected name is reported as bytes we do not have,
        because that is what it is — we will not go and fetch it.
        """
        root = self._attachments_dir
        if not safe_component(file_name):
            _logger.warning(
                "attachment name rejected",
                extra={
                    "conversation_id": log.safe_token(conversation_uuid),
                    # The name is being logged *because* it is malformed, so it is
                    # exactly the value that must not reach a record as it stands.
                    "file_name": log.safe_token(file_name),
                },
            )
            return None

        candidates = []
        if safe_component(conversation_uuid):
            candidates.append(root / conversation_uuid / file_name)
        candidates.append(root / file_name)

        for candidate in candidates:
            if candidate.is_file() and _within(root, candidate):
                # The *resolved* path, not the name that led to it: `_within`
                # validates where a symlink points, and recording the link
                # instead would let the target be swapped between planning and
                # `16`'s upload — the check would have been of one file and the
                # read of another.
                return candidate.resolve()
        return None


def blocking_reason(
    rendered: render.RenderedConversation | None, settings: Settings
) -> str | None:
    """The first migratability rule that fails, or `None` when none does.

    `None` for `rendered` is the empty conversation: there is no rendering to
    judge. Shared with `04` rather than reimplemented there, so that a
    conversation the plan calls unmigratable can never end up with a seed file on
    disk — the two would then disagree about what a run is going to do.
    """
    if rendered is None:
        return EMPTY_CONVERSATION
    if not rendered.has_original_content:
        return NO_REPRESENTABLE_TEXT
    if rendered.total_chars > settings.seed.hard_max_chars:
        return SEED_OVER_HARD_CAP
    return None


def build_plan(export: Export, settings: Settings) -> MigrationPlan:
    """The spec's call shape: `plan(export, settings)`."""
    return Planner(settings).plan(export)


def upload_paths(item: ConversationPlan) -> list[Path]:
    """The files `16` hands the prompt, in message order, each one once.

    The duplicates are already marked (`Planner._attachments`), so this is a
    filter and not a second deduplication: two places deciding which file is the
    one to upload is two places that can disagree about which name the seed
    should refer to.
    """
    return [
        attachment.source_path
        for attachment in item.attachments
        if attachment.klass == "upload"
        and attachment.duplicate_of is None
        and attachment.source_path is not None
    ]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _distinct(message: ChatMessage) -> Iterator[Attachment | FileRef]:
    """One entry per file on a message, in document order.

    `attachments[]` first because those are class 1 candidates and an inlined file
    beats the same file named again with no bytes. `files_v2[]` is the successor
    of `files[]` and a real export carries the same file in both, so an entry
    whose uuid *or* whose name has already been seen on this message is dropped —
    counting one file twice would show the operator two attachments where the UI
    showed one, and, once bytes exist, upload it twice.
    """
    entries: list[Attachment | FileRef] = [
        *message.attachments,
        *message.files,
        *message.files_v2,
    ]
    seen: set[str] = set()
    for entry in entries:
        keys = {entry.file_name.casefold()}
        if isinstance(entry, FileRef) and entry.file_uuid:
            keys.add(entry.file_uuid)
        if keys & seen:
            continue
        seen |= keys
        yield entry


def _refused(item: AttachmentPlan, reason: str) -> AttachmentPlan:
    """A class 2 entry the chat will not take, as the class 3 entry it becomes.

    The source path and the digest go with it: they describe a file that is going
    to be uploaded, and this one is not.
    """
    return item.model_copy(
        update={
            "klass": "unsupported",
            "reason": reason,
            "source_path": None,
            "sha256": None,
        }
    )


def _digest(path: Path) -> str | None:
    """sha256 of a file's bytes, or `None` when it cannot be read.

    Deduplication is on content and not on the name or the path, because one
    conversation can name the same bytes twice — `files[]` and `files_v2[]` on
    different messages, an export that renamed a file between them — and two
    chips for one file is a chat that does not look like the one it came from.
    """
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while chunk := handle.read(DIGEST_CHUNK):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _extension(file_name: str, file_type: str | None) -> str:
    """The file's type as an extension, lowercase, without the dot."""
    suffix = Path(file_name).suffix.lstrip(".").casefold()
    if suffix:
        return suffix
    mime = (file_type or "").split(";")[0].strip().casefold()
    return _MIME_EXTENSIONS.get(mime, "")


def safe_component(value: str) -> bool:
    """True when `value` is a single, ordinary path component.

    Public because `04` joins a conversation uuid to a directory as well, and one
    export can only be trusted or distrusted once.
    """
    if not value or value in (".", ".."):
        return False
    if strip_control(value) != value:
        return False
    return not any(character in value for character in _UNSAFE_IN_NAME)


def _within(root: Path, candidate: Path) -> bool:
    """True when `candidate` really sits under `root` once symlinks resolve."""
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True
