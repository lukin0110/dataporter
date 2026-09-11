"""The task prompt: what Hermes is told about one conversation.

Everything Hermes needs to know *how* to migrate a conversation is in the
`claude-migrate` skill, which is installed once and never varies. This module
writes the other half — *which* conversation, how many parts it has, where its
seed files are, what its acknowledgement lines say, and where a retry should pick
the procedure up — and that is all it writes.

The rule that shapes it: **the prompt names files, never their contents.** A
Hermes transcript is a workspace artefact an operator may read and a report may
quote from, and §10 keeps conversation text out of both. Seed text reaches the
page through `browser paste` and never through the prompt, an agent's context or
its output tokens (`specs/README.md`, division of labour). What is here is a
short id, a count, some paths and an ack line — and an ack line is ours, not the
conversation's.

`delay between parts` is `15`'s, and is the one field here that asks for an
absence rather than an action: the per-part loop happens inside one Hermes run,
so the only process that can put a gap between one part's acknowledgement and the
next part's paste is the agent making them. §13's pacing would otherwise stop at
the door of the one loop that sends messages.

`parts already acknowledged` is the one field `11` added to the template the spec
first sketched. Without it a resumed run has to work out which parts are already
in the chat by reading the transcript — which means snapshots, which means
conversation text in an agent's context, to recover a number `state.json` already
holds (`06`). Sending it is cheaper, exact, and keeps the resume rule ("never
re-paste an acknowledged part") checkable.

Nothing here decides anything. `12` chooses the conversation, writes the seed
files and reads the result; this renders a string.
"""

from collections.abc import Sequence
from pathlib import Path

from dataporter import PROGRAM_NAME, log
from dataporter.hermes.client import quoted
from dataporter.seed import Seed
from dataporter.steps import Step

NONE = "none"
"""What an empty field says. A literal rather than a blank, so a prompt with no
attachments and a prompt whose attachment list failed to render cannot look the
same to an agent."""

HEAD = (
    # Split across two string literals only because the line it produces is 91
    # characters and this file is formatted to 88. The prompt `11` specifies is
    # what reaches Hermes, wrapped where the spec wraps it.
    "Use the skill `claude-migrate` (load it with skill_view before acting). "
    "Migrate exactly one\n"
    "conversation into the claude.ai tab already open in the attached browser.\n"
)

TAIL = """\
Follow the skill's procedure. After every action verify it as the skill says. Never type
the seed yourself; only the helper inserts it. When finished, or when you cannot safely
continue, print the result JSON described in the skill as the last thing you output.
"""

HELPER_SUFFIX = "…"
"""How the helper line shows that a subcommand follows. The skill spells the
subcommands out; this line exists so that the workspace flag and the program name
reach the agent already joined and quoted."""


class PromptError(ValueError):
    """The prompt cannot be rendered from these arguments.

    A `ValueError` and not a `MigrationError`: every field comes from our own
    code — a seed `04` built, paths `12` has just written — so getting one wrong
    is a bug here, not something an operator can fix by typing something else.
    """


def _one_line(value: str) -> str:
    """A field value that cannot become two fields.

    `log.safe_token` is the same reduction everywhere else, but its length limit
    is wrong for this: a truncated path names a different file, or none, and the
    agent would be told to paste it. So the control characters go and the length
    stays.
    """
    return log.CONTROL_CHARACTERS.sub("?", value)


def _block(key: str, values: Sequence[str]) -> list[str]:
    """`key:` and then one value per line, or `key: none`.

    One shape for all three lists — seeds, attachments, acknowledgements — so an
    agent reading the prompt learns it once. The spec's `{N}/{N}` ellipsis is
    written out in full for the same reason `paste` hashes what it inserted:
    these strings are matched exactly, and a list an agent has to reconstruct is
    a list it can reconstruct wrongly.
    """
    if not values:
        return [f"{key}: {NONE}"]
    return [f"{key}:", *(_one_line(item) for item in values)]


def helper_command(workspace: Path) -> str:
    """The helper prefix, quoted, so a workspace path with a space survives."""
    return (
        quoted([PROGRAM_NAME, "--workspace", str(workspace), "browser"])
        + f" {HELPER_SUFFIX}"
    )


def render(
    *,
    short_id: str,
    parts: int,
    seed_files: Sequence[Path],
    acknowledgements: Sequence[str],
    workspace: Path,
    attachments: Sequence[Path] = (),
    resume_from: Step = Step.OPEN,
    conversation_id: str | None = None,
    acknowledged: int = 0,
    delay_between_parts_s: float = 0.0,
) -> str:
    """One conversation's task prompt.

    `parts` is passed rather than derived from `seed_files` so that the two can
    disagree and be caught: a prompt that says three parts and lists two seed
    files would have Hermes wait for an acknowledgement that is never coming.

    `delay_between_parts_s` defaults to no wait, because this function renders
    what it is given and a default of five seconds here would be a second place
    that decides the pacing. `12` passes `pacing.delay_between_parts_s`, which is
    the one.
    """
    if parts < 1:
        raise PromptError(f"a conversation has at least one part, not {parts}")
    if len(seed_files) != parts:
        raise PromptError(f"{parts} parts but {len(seed_files)} seed files")
    if len(acknowledgements) != parts:
        raise PromptError(f"{parts} parts but {len(acknowledgements)} ack lines")
    if not 0 <= acknowledged <= parts:
        raise PromptError(f"{acknowledged} acknowledged parts out of {parts}")
    if delay_between_parts_s < 0:
        raise PromptError(f"a delay is not negative: {delay_between_parts_s}")
    if acknowledged and conversation_id is None:
        raise PromptError("acknowledged parts with no chat to find them in")
    lines = [
        HEAD,
        f"short_id: {_one_line(short_id)}",
        f"parts: {parts}",
        *_block("seed files", [str(item) for item in seed_files]),
        *_block("attachments", [str(item) for item in attachments]),
        *_block("expected acknowledgements", acknowledgements),
        f"resume_from: {resume_from}",
        f"existing conversation_id: {_one_line(conversation_id or NONE)}",
        f"parts already acknowledged: {acknowledged}",
        f"delay between parts: {delay_between_parts_s:g}",
        f"helper: {helper_command(workspace)}",
        "",
        TAIL,
    ]
    return "\n".join(lines)


def for_seed(
    seed: Seed,
    *,
    seed_files: Sequence[Path],
    workspace: Path,
    attachments: Sequence[Path] = (),
    resume_from: Step = Step.OPEN,
    conversation_id: str | None = None,
    acknowledged: int = 0,
    delay_between_parts_s: float = 0.0,
) -> str:
    """The prompt for a seed `04` generated and `12` has just written out.

    The acknowledgement lines come off the seed itself rather than being rebuilt
    from the short id, so the line the chat is asked to reply with and the line
    Hermes is told to expect are the same string by construction — `render.py`
    builds it once, and a footer and a matcher that disagreed would fail every
    conversation for a reason nobody could see.
    """
    return render(
        short_id=seed.short_id,
        parts=len(seed.chunks),
        seed_files=seed_files,
        acknowledgements=[chunk.ack for chunk in seed.chunks],
        workspace=workspace,
        attachments=attachments,
        resume_from=resume_from,
        conversation_id=conversation_id,
        acknowledged=acknowledged,
        delay_between_parts_s=delay_between_parts_s,
    )
