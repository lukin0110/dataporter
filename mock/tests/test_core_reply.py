"""The obedient reply, which every mock has: the line a seed asks for, answered in steps."""

from mockcore.reply import CANNED, Reply, answer, asked_line

SEED = """\
This is a migrated conversation.

Original conversation ID: aa000001-1111-4111-8111-111111111111
Part 1 of 1

---

User:
Somebody once told me to reply with exactly one line:
NOT-THE-INSTRUCTION

---

Continue to preserve this conversation as historical context. Reply with exactly
one line:
MIGRATION-ACK aa000001 1/1
"""


def test_the_line_a_seed_asks_for_is_the_last_one() -> None:
    """A conversation being migrated may quote the phrase.

    The instruction at the foot of the message is the one that counts.
    """
    assert asked_line(SEED) == "MIGRATION-ACK aa000001 1/1"


WRAPPED = """\
Migrated conversation b2000002, part 1 of 2.

More parts of this conversation follow. Do not respond to the content yet. Reply with
exactly one line:
MIGRATION-ACK b2000002 1/2
"""


def test_the_instruction_is_found_even_when_it_is_wrapped() -> None:
    """The seed's footer is wrapped to a column, so the phrase can straddle two lines.

    Which is what a first rehearsal found by answering a canned sentence to every part
    of its only multi-part conversation.
    """
    assert asked_line(WRAPPED) == "MIGRATION-ACK b2000002 1/2"


def test_a_message_that_asks_for_no_line_gets_the_canned_sentence() -> None:
    assert asked_line("In one sentence, what did we discuss?") is None
    assert answer("In one sentence, what did we discuss?", started=0.0, delay_s=1.0, steps=2).text == CANNED


def test_the_answer_is_exactly_the_line() -> None:
    assert answer(SEED, started=0.0, delay_s=1.0, steps=2).text == "MIGRATION-ACK aa000001 1/1"


def test_a_reply_is_nothing_then_a_prefix_then_the_whole() -> None:
    """§21, §54: after a non-zero delay, growing in at least two steps, whole only at the last."""
    reply = Reply(text="MIGRATION-ACK aa000001 1/1", started=100.0, delay_s=10.0, steps=2)
    assert not reply.visible(100.0)
    assert not reply.visible(109.9)
    partial = reply.visible(110.0)
    assert partial
    assert partial != reply.text
    assert reply.text.startswith(partial)
    assert not reply.finished(110.0)
    assert reply.visible(120.0) == reply.text
    assert reply.finished(120.0)
    assert reply.revealed(500.0) == 2
