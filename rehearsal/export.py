"""The rehearsal export: a purpose-built export with no real conversation in it.

§24 says what it has to cover — the five kinds §18 names, and as many of `20`'s
selection categories as can be built — and this builds exactly that, the same
way every time:

| short id   | what it is                        | why it is here                   |
| ---------- | --------------------------------- | -------------------------------- |
| `a1000001` | a short conversation              | the common case                  |
| `b2000002` | a long one, over the seed budget  | more than one part, pasted twice |
| `c3000003` | one with code                     | fenced blocks through a composer |
| `d4000004` | one with attachments              | all three classes of §14         |
| `e5000005` | one with many turns               | a long transcript to render      |
| `f6000006` | one with nothing representable    | the unsupported branch           |
| four spares| short conversations               | work left after the pilot (§23)  |

Every character of it is generated here. No real export is read, ever (§23), and
nothing in it is anybody's conversation: the turns are about the rehearsal
itself, which is the one subject that cannot leak anything.

It is sized so that a complete run in one mode takes minutes at rehearsal
pacing: one seed is deliberately over the 50,000-character default so that the
two-part path is exercised, and everything else is small.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ACCOUNT = "acct-0000-0000-0000-00000000000r"

SHORT = "a1000001-1111-4111-8111-111111111111"
LONG = "b2000002-2222-4222-8222-222222222222"
CODE = "c3000003-3333-4333-8333-333333333333"
ATTACHED = "d4000004-4444-4444-8444-444444444444"
MANY_TURNS = "e5000005-5555-4555-8555-555555555555"
UNSUPPORTED = "f6000006-6666-4666-8666-666666666666"

SPARES: tuple[str, ...] = (
    "07000007-7777-4777-8777-777777777777",
    "08000008-8888-4888-8888-888888888888",
    "09000009-9999-4999-8999-999999999999",
    "10000010-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
)
"""Four more short conversations, and they are here for the protocol rather than
for the export.

§23 runs `import --pilot` and then an `import --all` that the interruption drill
kills. `20`'s selection takes one conversation per category, up to eight distinct
ones — so against the six above it would take every conversation there was and
leave the drill nothing to interrupt. These are what is left over.
"""

MIGRATABLE: tuple[str, ...] = (SHORT, LONG, CODE, ATTACHED, MANY_TURNS, *SPARES)
"""What a rehearsal expects to end `completed`. §25's 100 % is over these."""

INLINE_FILE = "rehearsal-notes.txt"
UPLOAD_FILE = "rehearsal-chart.png"
UNSUPPORTED_FILE = "rehearsal-archive.zip"
"""§14's three classes, in one conversation: text the export inlined, bytes that
are on disk beside the export, and a type claude.ai does not take."""

UPLOAD_BYTES = b"\x89PNG\r\n\x1a\n" + b"rehearsal" * 64
"""Not a real image, and nothing reads it as one: the mock takes the bytes and
counts them, and what the tool checks is that a chip carrying the name appeared.
The PNG signature is there so that a person looking at the directory can tell
what it is standing in for."""

LONG_TURNS = 22
LONG_ANSWER_CHARS = 3_000
"""Enough rendered text to cross the tool's default 50,000-character seed
budget, which is what makes this conversation two parts. Deliberately expressed
as "how much text", not "how many parts": the budget is `10`'s to change, and a
rehearsal export that silently stopped being two parts would still pass."""


def _message(
    uuid: str,
    sender: str,
    text: str,
    *,
    index: int,
    parent: str | None,
    minute: int,
    day: int,
    attachments: Sequence[dict[str, object]] = (),
    files: Sequence[dict[str, object]] = (),
) -> dict[str, object]:
    stamp = f"2026-03-{day:02d}T09:{minute:02d}:00.000000Z"
    return {
        "uuid": uuid,
        "text": text,
        "content": [{"type": "text", "text": text}],
        "sender": sender,
        "created_at": stamp,
        "updated_at": stamp,
        "attachments": list(attachments),
        "files": list(files),
        "files_v2": list(files),
        "index": index,
        "parent_message_uuid": parent,
    }


@dataclass
class Builder:
    """One conversation's messages, in order, each the child of the last."""

    uuid: str
    day: int
    messages: list[dict[str, object]]

    @classmethod
    def start(cls, uuid: str, day: int) -> "Builder":
        return cls(uuid=uuid, day=day, messages=[])

    def say(
        self,
        sender: str,
        text: str,
        *,
        attachments: Sequence[dict[str, object]] = (),
        files: Sequence[dict[str, object]] = (),
    ) -> "Builder":
        index = len(self.messages)
        parent = str(self.messages[-1]["uuid"]) if self.messages else None
        self.messages.append(
            _message(
                f"{self.uuid[:8]}-0000-4000-8000-{index:012d}",
                sender,
                text,
                index=index,
                parent=parent,
                minute=index % 60,
                day=self.day,
                attachments=attachments,
                files=files,
            )
        )
        return self

    def done(self, name: str) -> dict[str, object]:
        leaf = str(self.messages[-1]["uuid"]) if self.messages else None
        return {
            "uuid": self.uuid,
            "name": name,
            "summary": "",
            "created_at": f"2026-03-{self.day:02d}T09:00:00.000000Z",
            "updated_at": f"2026-03-{self.day:02d}T10:00:00.000000Z",
            "account": {"uuid": ACCOUNT},
            "chat_messages": self.messages,
            "current_leaf_message_uuid": leaf,
        }


def _short() -> dict[str, object]:
    return (
        Builder.start(SHORT, 1)
        .say("human", "What is a rehearsal for?")
        .say(
            "assistant",
            "It proves the deterministic half of the tool against a real browser "
            "showing a real, stateful site, and nothing about claude.ai.",
        )
        .done("A short exchange")
    )


def _long() -> dict[str, object]:
    """Enough text to need two parts at the tool's default seed budget."""
    builder = Builder.start(LONG, 2)
    for turn in range(1, LONG_TURNS + 1):
        builder.say("human", f"Question {turn}: what does the rehearsal prove here?")
        sentence = (
            f"Answer {turn}: the seed reaches the composer byte for byte, the "
            "submit lands, the reply is waited for rather than assumed, and the "
            "acknowledgement is read back off the page. "
        )
        repeats = LONG_ANSWER_CHARS // len(sentence) + 1
        builder.say("assistant", (sentence * repeats)[:LONG_ANSWER_CHARS])
    return builder.done("A long exchange, over the seed budget")


def _code() -> dict[str, object]:
    body = "\n".join(
        [
            "```python",
            "def parts(text: str, budget: int) -> list[str]:",
            '    """Split a seed the way the tool does, more or less."""',
            "    return [text[at : at + budget] for at in range(0, len(text), budget)]",
            "```",
        ]
    )
    return (
        Builder.start(CODE, 3)
        .say("human", f"Does a fenced block survive the composer?\n\n{body}")
        .say(
            "assistant",
            "It should: the helper inserts the seed as text and hashes what the "
            f"composer holds.\n\n{body}",
        )
        .done("A conversation with code in it")
    )


def _attached() -> dict[str, object]:
    inline = {
        "file_name": INLINE_FILE,
        "file_size": 74,
        "file_type": "text/plain",
        "extracted_content": (
            "Rehearsal note one: the mock counts what it was asked to do.\n"
            "Rehearsal note two: the tool cannot tell the difference.\n"
        ),
    }
    unsupported = {
        "file_name": UNSUPPORTED_FILE,
        "file_size": 2048,
        "file_type": "application/zip",
        "extracted_content": "",
    }
    upload = {"file_name": UPLOAD_FILE, "file_uuid": f"{ATTACHED[:8]}-file-0001"}
    return (
        Builder.start(ATTACHED, 4)
        .say(
            "human",
            "Here are three files: one the export inlined, one whose bytes are "
            "beside the export, and one of a type that is not accepted.",
            attachments=[inline, unsupported],
            files=[upload],
        )
        .say(
            "assistant",
            "Two of them can reach a chat: the inlined one as text in the seed, "
            "and the one with bytes through the file input. The third is recorded "
            "and not sent.",
        )
        .done("A conversation with attachments")
    )


def _many_turns() -> dict[str, object]:
    builder = Builder.start(MANY_TURNS, 5)
    for turn in range(1, 21):
        builder.say("human", f"Turn {turn}: is the transcript still in order?")
        builder.say("assistant", f"Turn {turn}: it is, and every turn is rendered.")
    return builder.done("A conversation with many turns")


def _unsupported() -> dict[str, object]:
    """Nothing a seed could be made of: the branch that must not be migrated."""
    return Builder.start(UNSUPPORTED, 6).done("")


def _spare(uuid: str, index: int) -> dict[str, object]:
    return (
        Builder.start(uuid, 7 + index)
        .say("human", f"Spare {index}: is there still work after the pilot?")
        .say(
            "assistant",
            f"Spare {index}: there is, which is what the interruption drill needs.",
        )
        .done(f"A short exchange, number {index}")
    )


def conversations() -> list[dict[str, object]]:
    return [
        _short(),
        _long(),
        _code(),
        _attached(),
        _many_turns(),
        _unsupported(),
        *(_spare(uuid, index) for index, uuid in enumerate(SPARES, start=1)),
    ]


def build(root: Path) -> tuple[Path, Path]:
    """Write the export and the attachment bytes. Returns both directories.

    The bytes live *beside* the export rather than in it, because that is where
    a real export leaves them: §24 asks for class 2, and class 2 is exactly the
    case where the export names a file it does not contain.
    """
    export = root / "export"
    attachments = root / "attachments"
    (export / ".").mkdir(parents=True, exist_ok=True)
    (attachments / ATTACHED).mkdir(parents=True, exist_ok=True)
    _write(export / "conversations.json", conversations())
    _write(
        export / "users.json",
        [
            {
                "uuid": ACCOUNT,
                "full_name": "Rehearsal Operator",
                "email_address": "rehearsal@example.invalid",
            }
        ],
    )
    _write(export / "projects.json", [])
    (attachments / ATTACHED / UPLOAD_FILE).write_bytes(UPLOAD_BYTES)
    return export, attachments


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root", type=Path, help="where to write export/ and attachments/"
    )
    arguments = parser.parse_args(argv)
    export, attachments = build(arguments.root)
    print(f"export:      {export}")
    print(f"attachments: {attachments}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
