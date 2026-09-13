"""What the mock was asked to do, counted.

Nothing in the tool can tell a rehearsal from a real run (§22), which is the
whole point of it — so the mock is the only party that can say what really
happened on the other side of the wire. A rehearsal record reconciles the tool's
own report against these five numbers (§25), and a record whose numbers do not
reconcile is not a rehearsal.

The counters are deliberately about *requests the mock served*, not about what
the tool believes: a chat created is a chat this process minted an id for, a
message received is a message this process parsed, a file accepted is bytes this
process read to the end.
"""

import threading
from dataclasses import dataclass, field

HEADING = "Mock claude.ai — ledger"

WIDTH = 32
"""Where the numbers end.

`26` pins the block's columns. The brief's own block (§21) illustrates the shape
and leaves it to the slice; this constant and `block` are the rule that prints
it, and `mock/tests/test_ledger.py` is where the bytes are held."""

LABELS: tuple[tuple[str, str], ...] = (
    ("sign_ins", "Sign-ins:"),
    ("chats_created", "Chats created:"),
    ("messages_received", "Messages received:"),
    ("files_accepted", "Files accepted:"),
    ("renames", "Renames:"),
)
"""Field name to printed label, in the order §21 lists them. One tuple rather
than two dicts, because the order is part of the block and a second list would be
a second thing to keep in step."""


@dataclass
class Ledger:
    """Five counters, and the block they print as.

    Thread-safe because the server is threaded: two uploads finishing at once
    would otherwise lose one, and a witness that under-counts is worse than no
    witness at all.
    """

    sign_ins: int = 0
    chats_created: int = 0
    messages_received: int = 0
    files_accepted: int = 0
    renames: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def count(self, name: str, amount: int = 1) -> None:
        with self._lock:
            setattr(self, name, getattr(self, name) + amount)

    def counters(self) -> dict[str, int]:
        """Return the five numbers as a mapping, in the block's order."""
        with self._lock:
            return {name: int(getattr(self, name)) for name, _ in LABELS}

    def block(self) -> str:
        """Return the ledger block, byte for byte, ending in a blank line.

        `26`'s golden string, in the shape §21 illustrates: the heading, a blank
        line, five labelled counts with the numbers right-aligned, a blank line.
        """
        counters = self.counters()
        lines = [HEADING, ""]
        for name, label in LABELS:
            lines.append(f"{label}{counters[name]:>{WIDTH - len(label)}}")
        return "\n".join([*lines, "", ""])
