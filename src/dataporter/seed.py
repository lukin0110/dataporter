"""Migration seeds: the files a new chat is fed, and the hashes that prove it.

`03` landed the renderer in `render.py`, because it could not compute
`chunk_count` or `estimated_seed_chars` without one. What is left to this slice is
everything built on top of it: `Seed` and `SeedChunk`, each part's sha256, the
`part-NN.txt` files, and the `seeds` command that writes them. The seed *format*
lives in `render.py` and is not restated here.

Determinism is the property to protect: the same conversation and the same
settings produce byte-identical files. Nothing here reads a clock, a random number
or an environment variable, and every part is written UTF-8 with `\\n` endings, so
the sha256 recorded in memory is the sha256 of the bytes on disk on every
platform.

No conversation content may reach a log record from here. A chunk is content and
`Conversation.name` is a title; what the records below carry is ids, counts and
paths, and an id that came out of the export goes through `log.safe_token` first.
"""

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from orval import hashify
from pydantic import BaseModel, ConfigDict

from dataporter import log, render, store
from dataporter import plan as planning
from dataporter.config import Settings
from dataporter.console import DISCARD, Sink
from dataporter.errors import UnsupportedError
from dataporter.exit_codes import ExitCode
from dataporter.export.model import Conversation

_logger = log.get_logger(__name__)

PART_PREFIX = "part-"
PART_SUFFIX = ".txt"
PART_GLOB = f"{PART_PREFIX}*{PART_SUFFIX}"

UNSAFE_CONVERSATION_ID = "unsafe_conversation_id"
"""Skip reason for a uuid that cannot be a directory name. See `write_seed`."""


def part_filename(index: int) -> str:
    """`part-01.txt`. Zero-padded to two digits so parts sort as they read."""
    return f"{PART_PREFIX}{index:02d}{PART_SUFFIX}"


def sha256_of(text: str) -> str:
    """The hash `08`'s paste helper compares against, over UTF-8 bytes.

    `orval.hashify` of a `str` is sha256 over `str.encode()`, which is UTF-8: the
    same digest this has always produced. Pinned by a test rather than trusted,
    because `08` compares this value against what a browser composer holds, and a
    change upstream would fail every paste for a reason nobody could see.
    """
    return hashify(text)


# --------------------------------------------------------------------------- #
# The models
# --------------------------------------------------------------------------- #


class SeedModel(BaseModel):
    """Base for the seed models: immutable, and closed.

    Same reasoning as `plan.PlanModel`: this shape is ours, so an unexpected key
    is a bug in us rather than drift in someone else's file.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class SeedChunk(SeedModel):
    """One part of one conversation — one message into the destination chat."""

    index: int
    """1-based, and the number in the file name."""
    total: int
    text: str
    sha256: str
    """Of `text`, UTF-8. `08` pastes the seed and compares what the composer holds
    against this, which is how "the paste worked" stops being a judgement call."""
    message_uuids: list[str]
    """The messages *fully* contained in this part. A message split across two
    parts belongs to neither, so `12` cannot count it as delivered until both
    halves are acknowledged."""
    ack: str
    """The exact line Claude is asked to reply with, without its newline."""

    @property
    def file_name(self) -> str:
        return part_filename(self.index)


class Seed(SeedModel):
    """Everything one conversation needs to become a chat."""

    conversation_uuid: str
    short_id: str
    """First 8 hex characters of the uuid: what the acknowledgement line carries."""
    chunks: list[SeedChunk]
    messages_represented: int
    limitations: list[str]
    """`thinking_omitted:n`, `tool_calls_summarised:n`, … — `03`'s slugs, so the
    dry run, the seed and the report describe one conversation the same way."""

    @property
    def total_chars(self) -> int:
        """The characters that reach the chat, envelopes included."""
        return sum(len(chunk.text) for chunk in self.chunks)


def from_rendered(rendered: render.RenderedConversation) -> Seed:
    """Turn `03`'s rendering into the artefact `12` delivers."""
    total = len(rendered.chunks)
    chunks = [
        SeedChunk(
            index=index,
            total=total,
            text=text,
            sha256=sha256_of(text),
            message_uuids=list(uuids),
            ack=render.ack_line(rendered.short_id, index, total),
        )
        for index, (text, uuids) in enumerate(
            zip(rendered.chunks, rendered.chunk_message_uuids, strict=True), start=1
        )
    ]
    return Seed(
        conversation_uuid=rendered.conversation_uuid,
        short_id=rendered.short_id,
        chunks=chunks,
        messages_represented=rendered.messages_represented,
        limitations=rendered.limitations.slugs(),
    )


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SeedOutcome:
    """One conversation's seed, or the reason it does not have one."""

    conversation_uuid: str
    short_id: str
    seed: Seed | None = None
    reason: str | None = None
    """Set exactly when `seed` is `None`: `03`'s blocking reason, or
    `unsafe_conversation_id`."""


class SeedGenerator:
    """Seeds for the conversations that can have them.

    The migratability rules are not restated here: `plan.blocking_reason` decides,
    so a conversation the dry run calls unmigratable can never acquire a seed file
    that says otherwise.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._planner = planning.Planner(settings)

    def seed(self, conversation: Conversation) -> SeedOutcome:
        token = render.short_id(conversation.uuid)
        rendered = self._planner.render_conversation(conversation)
        reason = planning.blocking_reason(rendered, self._settings)
        if rendered is None or reason is not None:
            return SeedOutcome(conversation.uuid, token, reason=reason)
        if not planning.safe_component(conversation.uuid):
            # `write_seed` refuses it too; catching it here turns an exception
            # that would end the run into one skipped conversation.
            _logger.warning(
                "conversation id rejected as a directory name",
                extra={"conversation_id": log.safe_token(token)},
            )
            return SeedOutcome(conversation.uuid, token, reason=UNSAFE_CONVERSATION_ID)
        return SeedOutcome(conversation.uuid, token, seed=from_rendered(rendered))

    def seeds(self, conversations: Iterable[Conversation]) -> Iterator[SeedOutcome]:
        """One outcome per conversation, in the order given."""
        for conversation in conversations:
            yield self.seed(conversation)


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #


def write_seed(seed: Seed, root: Path) -> list[Path]:
    """Write `<root>/<uuid>/part-NN.txt` and return the paths, in order.

    Stale parts are removed first. A conversation that used to need three parts
    and now needs two would otherwise leave a `part-03.txt` behind for `11`'s
    prompt to list and `12` to paste — a fragment of a seed nobody generated.

    The uuid is export data being used as a path component, so it is checked
    before it is joined, exactly as `03` checks an attachment's `file_name`. A
    name that fails is not sanitised into something else: two conversations must
    never share a directory.
    """
    if not planning.safe_component(seed.conversation_uuid):
        raise UnsupportedError(
            detail=f"conversation id is not a usable directory name: {seed.short_id}"
        )
    directory = root / seed.conversation_uuid
    directory.mkdir(parents=True, exist_ok=True)
    for stale in sorted(directory.glob(PART_GLOB)):
        stale.unlink()

    written: list[Path] = []
    for chunk in seed.chunks:
        target = directory / chunk.file_name
        # `newline=""` writes `\n` through untranslated: on Windows the default
        # would emit `\r\n` and every sha256 in the seed would describe bytes
        # that are not the ones in the file.
        target.write_text(chunk.text, encoding="utf-8", newline="")
        written.append(target)
    _logger.info(
        "seed written",
        extra={
            "conversation_id": seed.short_id,
            "parts": len(seed.chunks),
            "chars": seed.total_chars,
        },
    )
    return written


# --------------------------------------------------------------------------- #
# The `seeds` command (`23`)
# --------------------------------------------------------------------------- #

SKIPPED = "skipped {short_id}: {reason}"
WRITTEN = "{short_id}  parts={parts}  chars={chars}"


@dataclass(frozen=True)
class SeedsOutcome:
    """What `seeds` wrote, what it skipped and why, and exit `4` for nothing."""

    written: int
    skipped: tuple[tuple[str, str], ...]
    """`(short_id, reason)` per conversation that got no seed."""
    exit_code: ExitCode


def write_seeds(
    settings: Settings,
    export: str,
    *,
    only: Sequence[str] = (),
    out: Path | None = None,
    quiet: bool = False,
    sink: Sink = DISCARD,
) -> SeedsOutcome:
    """Generate migration seeds without touching a browser (`04`).

    Stdout is one line per *written* seed, and stderr is where an operator who
    asked for one conversation by uuid is owed the reason nothing appeared — one
    note per skipped conversation, whatever it contains, with the short id
    passed through `log.safe_token` because a skipped conversation is the one
    case where the export's uuid may be malformed. `05` is where the full
    accounting lives. `quiet` suppresses the written lines and nothing else: they
    are progress, and the notes are results.
    """
    from dataporter.export import load_export
    from dataporter.selection import export_path, selected_conversations

    path = export_path(export)
    store.refuse_workspace_inside(path, settings.workspace)
    root = out if out is not None else settings.seeds_dir
    log.enable_run_log(settings.workspace)

    conversations = selected_conversations(load_export(path), only)
    generator = SeedGenerator(settings)
    written = 0
    skipped: list[tuple[str, str]] = []
    for outcome in generator.seeds(conversations):
        if outcome.seed is None:
            reason = outcome.reason or ""
            skipped.append((outcome.short_id, reason))
            sink.note(
                SKIPPED.format(short_id=log.safe_token(outcome.short_id), reason=reason)
            )
            continue
        write_seed(outcome.seed, root)
        written += 1
        if not quiet:
            sink.line(
                WRITTEN.format(
                    short_id=outcome.short_id,
                    parts=len(outcome.seed.chunks),
                    chars=outcome.seed.total_chars,
                )
            )
    return SeedsOutcome(
        written=written,
        skipped=tuple(skipped),
        exit_code=ExitCode.OK if written else ExitCode.NOTHING_TO_DO,
    )
