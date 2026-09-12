"""The pilot selection: ten conversations chosen because of what they are.

§18 asks six questions about a tool nobody has run on a real account yet, and the
answers are only worth having if the conversations that produced them were chosen
before the run rather than after it. So `--pilot` picks by category — the
shortest, the longest that still fits in one part, the one with a dropped branch,
the one with an artifact — and writes down which category chose which
conversation, so the write-up can say *why* a number came out the way it did and
somebody with a different export can reproduce the same experiment.

Three properties hold the whole module up:

- **It is a pure function of the export and the plan.** No clock, no filesystem,
  no state. The same export and the same settings choose the same ten
  conversations, which is what makes `20`'s acceptance criterion a unit test and
  a re-run on another machine the same experiment.
- **Every category answers independently.** A category names the conversation it
  would choose whether or not an earlier category has already chosen it, and only
  the run set is deduplicated. A record that said `-` for the fourth category
  because the third got there first would hide the fact that one conversation is
  both, which is exactly what a write-up needs to know.
  Two categories are deliberately not independent, and both say so in their own
  chooser: `6` asks for a *second* attachment conversation and `10` exists to
  fill the tenth slot, so each skips what is already chosen.
- **Nothing here is content.** A category is a slug, a conversation is a uuid,
  and what reaches an operator's terminal is `render.short_id` of it (§10).

What this module does not do is decide *how many*: `--pilot` runs as `import
--limit 10` does, and `PILOT_LIMIT` is that number, named here because the
categories are ten and the two must not drift apart.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dataporter import render
from dataporter.export.model import ChatMessage, Export, TextBlock
from dataporter.plan import ConversationPlan, MigrationPlan
from dataporter.state import PilotChoice

if TYPE_CHECKING:  # pragma: no cover - the name `max`'s own stub is typed with
    from _typeshed import SupportsRichComparison

PILOT_LIMIT = 10
"""How many conversations a pilot run migrates. §18's "five to ten", and the
number of categories below: one conversation each, at most."""

FENCE = "```"
"""What a fenced code block opens with, in both roles (category 4)."""

MANY_TURNS = 10
"""What category 7 counts as "≥ 10 turns".

Turns, not exchanges: the export calls each message a turn and so does the page
`17` reads back, so a conversation with ten messages on its active path is the
one this category is looking for — five questions and five answers.
"""

MIN_MESSAGES = 2
"""§20's "fewest active-path messages, ≥ 2" for category 1.

A one-message conversation is a question nobody answered; migrating it proves
nothing about whether Claude understood a reconstructed history.
"""

NOTHING = "-"
"""What a category with no conversation prints. Not a blank: a column that is
sometimes empty reads as a column that failed to render."""

HEADER = "Pilot selection:"


# --------------------------------------------------------------------------- #
# What a category knows about one conversation
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Candidate:
    """One migratable conversation, as the categories need to see it.

    The plan and the export each hold half of what a category asks about — the
    plan knows the seed's size and the attachment classes, the export knows what
    a message contains — so they are joined once, here, rather than in nine
    choosers.
    """

    uuid: str
    position: int
    """Where it sits in the export. Every tie below is broken by it, so that two
    conversations that are equally short choose the same way every time."""
    messages: int
    off_path: int
    seed_chars: int
    parts: int
    inline_attachments: int
    upload_attachments: int
    code_in_both_roles: bool
    has_artifact: bool
    recency: tuple[float, float]
    """`updated_at` and then `created_at`, as timestamps. Two of them because an
    export whose conversations were all updated in the same import would
    otherwise leave "newest" to the tie-break."""


def candidates(export: Export, plan: MigrationPlan) -> list[Candidate]:
    """Every migratable conversation of `plan`, in export order.

    Migratable only: a pilot exists to measure what the tool does to
    conversations it can do something with, and `05`'s block already counts the
    ones it cannot.
    """
    planned: Mapping[str, ConversationPlan] = {
        item.uuid: item for item in plan.conversations if item.migratable
    }
    found: list[Candidate] = []
    for position, conversation in enumerate(export.conversations):
        item = planned.get(conversation.uuid)
        if item is None:
            continue
        active = conversation.active_path()
        found.append(
            Candidate(
                uuid=conversation.uuid,
                position=position,
                messages=item.message_count,
                off_path=item.off_path_count,
                seed_chars=item.estimated_seed_chars,
                parts=item.chunk_count,
                inline_attachments=sum(
                    1 for entry in item.attachments if entry.klass == "inline"
                ),
                upload_attachments=sum(
                    1
                    for entry in item.attachments
                    if entry.klass == "upload" and entry.duplicate_of is None
                ),
                code_in_both_roles=_code_in_both_roles(active),
                has_artifact=_has_artifact(active),
                recency=(
                    conversation.updated_at.timestamp(),
                    conversation.created_at.timestamp(),
                ),
            )
        )
    return found


def _code_in_both_roles(messages: Sequence[ChatMessage]) -> bool:
    """A fenced code block in a human message *and* in an assistant one.

    Both roles, because the question this category is for is whether a
    reconstructed transcript keeps the shape of a conversation about code: a
    fence the user wrote and a fence Claude wrote come through the same seed and
    are reproduced by the same paste, and one without the other does not say
    whether the pair survived.

    Read off the blocks rather than off `ChatMessage.text`: the text field is the
    export's own flattening, and the seed is rendered from the blocks (`03`).
    """
    roles = {
        message.sender
        for message in messages
        if any(
            isinstance(block, TextBlock) and FENCE in block.text
            for block in message.content
        )
    }
    return {"human", "assistant"} <= roles


def _has_artifact(messages: Sequence[ChatMessage]) -> bool:
    """An `artifacts` tool call on the active path (`render.ARTIFACT_TOOL`).

    The same test `03` renders on, so a conversation this category chooses is one
    whose seed really carries an `[Artifact: …]` block.
    """
    return any(
        getattr(block, "name", "") == render.ARTIFACT_TOOL
        for message in messages
        for block in message.content
    )


# --------------------------------------------------------------------------- #
# The ten categories
# --------------------------------------------------------------------------- #

Chooser = Callable[[Sequence[Candidate], Sequence[str]], Candidate | None]
"""A category, as a function of the candidates and what is already chosen.

The second argument is only read by the two categories that are allowed to care
— `6` asks for *another* attachment conversation and `10` fills whatever slot is
left — and is ignored by the other eight, which answer for themselves.
"""


@dataclass(frozen=True)
class Category:
    """One row of §20's list: its number, its slug, and how it chooses."""

    number: int
    name: str
    choose: Chooser


Ranking = Callable[[Candidate], "SupportsRichComparison"]
"""How a category ranks its candidates. Every one of them sorts *down*: the key
is written so that the best candidate is the greatest, because `max` keeps the
first of equal keys and export order is every category's tie-break."""


def _first(found: Iterable[Candidate], key: Ranking | None = None) -> Candidate | None:
    """The best of `found` by `key`, the first of them when there is no key, or
    `None` when there are none at all."""
    items = list(found)
    if not items:
        return None
    return items[0] if key is None else max(items, key=key)


def _shortest(found: Sequence[Candidate], chosen: Sequence[str]) -> Candidate | None:
    eligible = [item for item in found if item.messages >= MIN_MESSAGES]
    return _first(eligible, key=lambda item: (-item.messages, -item.position))


def _longest_one_part(
    found: Sequence[Candidate], chosen: Sequence[str]
) -> Candidate | None:
    return _first(
        [item for item in found if item.parts == 1],
        key=lambda item: (item.seed_chars, -item.position),
    )


def _longest_multi_part(
    found: Sequence[Candidate], chosen: Sequence[str]
) -> Candidate | None:
    return _first(
        [item for item in found if item.parts >= 2],
        key=lambda item: (item.seed_chars, -item.position),
    )


def _code_both_roles(
    found: Sequence[Candidate], chosen: Sequence[str]
) -> Candidate | None:
    return _first(item for item in found if item.code_in_both_roles)


def _inline_attachment(
    found: Sequence[Candidate], chosen: Sequence[str]
) -> Candidate | None:
    return _first(item for item in found if item.inline_attachments)


def _upload_attachment(
    found: Sequence[Candidate], chosen: Sequence[str]
) -> Candidate | None:
    """A class 2 attachment, or *another* class 1 — §20's one written-down
    fallback, and the reason this chooser reads `chosen` at all.

    "Another" is the whole of it: the category exists to put a second attachment
    conversation in the pilot, and naming the one category 5 already named would
    put nothing there. A class 2 candidate is taken whether or not it is already
    chosen, because an uploaded file is a different thing to measure from an
    inlined one and the write-up needs to know that the same conversation is
    both.
    """
    taken = set(chosen)
    return _first(item for item in found if item.upload_attachments) or _first(
        item for item in found if item.inline_attachments and item.uuid not in taken
    )


def _many_turns(found: Sequence[Candidate], chosen: Sequence[str]) -> Candidate | None:
    return _first(item for item in found if item.messages >= MANY_TURNS)


def _dropped_branch(
    found: Sequence[Candidate], chosen: Sequence[str]
) -> Candidate | None:
    return _first(item for item in found if item.off_path)


def _artifact(found: Sequence[Candidate], chosen: Sequence[str]) -> Candidate | None:
    return _first(item for item in found if item.has_artifact)


def _newest(found: Sequence[Candidate], chosen: Sequence[str]) -> Candidate | None:
    """The newest conversation nothing has chosen yet.

    The one category with no property of its own to look for: it is here to fill
    the tenth slot, so a conversation an earlier category already named would
    leave the pilot nine long. An export with fewer than ten migratable
    conversations therefore reports no choice at all here, which is a fact about
    the export and is what `20`'s acceptance criterion expects of the fixture.
    """
    taken = set(chosen)
    return _first(
        (item for item in found if item.uuid not in taken),
        key=lambda item: (item.recency, -item.position),
    )


CATEGORIES: tuple[Category, ...] = (
    Category(1, "shortest", _shortest),
    Category(2, "longest-one-part", _longest_one_part),
    Category(3, "longest-multi-part", _longest_multi_part),
    Category(4, "code-both-roles", _code_both_roles),
    Category(5, "inline-attachment", _inline_attachment),
    Category(6, "second-attachment", _upload_attachment),
    Category(7, "many-turns", _many_turns),
    Category(8, "dropped-branch", _dropped_branch),
    Category(9, "artifact", _artifact),
    Category(10, "newest", _newest),
)
"""§20's ten, in §20's order. The order is the selection: a category chooses
against what the ones above it have already taken."""


# --------------------------------------------------------------------------- #
# Choosing, and writing it down
# --------------------------------------------------------------------------- #


def choose(export: Export, plan: MigrationPlan) -> list[PilotChoice]:
    """One record per category, in category order. The whole of the selection."""
    found = candidates(export, plan)
    chosen: list[str] = []
    records: list[PilotChoice] = []
    for category in CATEGORIES:
        picked = category.choose(found, chosen)
        records.append(
            PilotChoice(
                category=category.number,
                name=category.name,
                uuid=picked.uuid if picked is not None else None,
            )
        )
        if picked is not None and picked.uuid not in chosen:
            if len(chosen) >= PILOT_LIMIT:  # pragma: no cover - ten categories
                continue
            chosen.append(picked.uuid)
    return records


def uuids(records: Sequence[PilotChoice]) -> list[str]:
    """What the selection runs, each conversation once, in category order.

    Category order and not export order, because that is the order in which the
    pilot's reasons were decided; `state.select` puts them back into export order
    before anything is migrated, so nothing downstream depends on this.
    """
    found: list[str] = []
    for record in records:
        if record.uuid is not None and record.uuid not in found:
            found.append(record.uuid)
    return found


def lines(records: Sequence[PilotChoice]) -> list[str]:
    """The block `--pilot` prints: a category per line, widest name padded.

    Two spaces between columns, as `seeds`, `verify` and `18`'s event lines space
    them. The conversation is its short id and never its title (§10), and a
    category that chose nothing prints `-` rather than nothing at all.
    """
    width = max((len(record.name) for record in records), default=0)
    number = max((len(str(record.category)) for record in records), default=1)
    return [HEADER] + [
        f"{record.category:>{number}}  {record.name:<{width}}  "
        + (render.short_id(record.uuid) if record.uuid is not None else NOTHING)
        for record in records
    ]


def block(records: Sequence[PilotChoice]) -> str:
    """`lines`, as the text a command prints. Trailing newline, like §9's block."""
    return "".join(f"{line}\n" for line in lines(records))


PILOT_CHOOSES = (
    "--pilot chooses the conversations itself: drop --only, --limit and --all"
)
"""`20`'s usage error. The pilot selection is the experiment's design — ten
categories, in order — so a flag that would narrow, widen or reorder it is
refused rather than silently losing to it, whichever way round that went."""
