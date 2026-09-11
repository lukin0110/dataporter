"""The names of the steps one migration is made of.

`11` fixes a sequence: every step acts, then verifies what it did, then records
its own name. The name is what `state.last_step` holds, what a `HermesResult`
reports when a run stops early, and what `19` prints as "last successful step" —
so it is one vocabulary in one place rather than a string typed out in a skill, a
prompt, a state file and a report, four times, slightly differently.

The list mirrors §5's diagram one to one on purpose: a reader who sees
`last_step: paste` in `state.json` can find `paste` in the brief without a
translation table.

Two things the enum deliberately does not carry:

- **Order as a number.** `ORDER` is the declaration order and nothing reads it as
  arithmetic. A migration is not monotonic — the four `PER_PART` steps repeat
  once per seed part — so "further along" is `chunks_acked` plus a step name, not
  a comparison.
- **What to do at each step.** That is the skill's, and `13`'s. This module is
  the vocabulary; putting the procedure here would give us two of them.
"""

from enum import StrEnum


class Step(StrEnum):
    """One step of `11`'s procedure. The value is the recorded name."""

    OPEN = "open"
    """Navigate to a new chat and prove the composer is there."""
    NEW_CHAT = "new_chat"
    """Make sure the tab is on `/new` with an empty composer before the first
    paste — a run that resumes into a chat someone left open would append this
    conversation to that one."""
    ATTACH = "attach"
    """Upload one file (`16`). Repeats per file, before the first paste."""
    PASTE = "paste"
    """Insert one seed part into the composer, through the helper only."""
    SUBMIT = "submit"
    """Send what the composer holds. The one adaptive action of the sequence."""
    AWAIT = "await"
    """Wait until the answer to that part has finished generating."""
    ACK = "ack"
    """Read the acknowledgement line for that part, or classify what came
    instead (`13`)."""
    IDENTIFY = "identify"
    """Read `/chat/<uuid>` off the URL: the destination id §7 records."""
    RENAME = "rename"
    """Give the chat the source conversation's title (`17`)."""
    VERIFY = "verify"
    """Reload the chat and check the parts and acknowledgements are all there
    (`17`)."""
    DONE = "done"
    """Nothing left to do; the result is emitted."""


ORDER: tuple[Step, ...] = tuple(Step)
"""The steps in the order `11`'s table lists them.

Named so that a test can compare the table in the spec against this module, and
so that nothing has to rely on `Enum` iteration order to say "the sequence"."""

PER_PART: tuple[Step, ...] = (Step.PASTE, Step.SUBMIT, Step.AWAIT, Step.ACK)
"""The four steps that repeat, once per seed part.

Why it matters that they are named: `last_step: paste` on a three-part
conversation does not say which part, so every consumer of `last_step` needs
`chunks_acked` beside it to know where a run got to. `12` records both, `13`
resumes from both, and `19` reports both.
"""
