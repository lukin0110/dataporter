"""What the mock claude.ai does, without a socket in the way.

Obedience — the line a seed asks for, wrapped or quoted — is the core's and is
tested in `test_core_reply.py`; what is here is what a chat on this site is.
"""

import pytest
from claudemock import IDENTITY
from claudemock.site import Site
from mockcore.ledger import Ledger
from mockcore.reply import CANNED

from conftest import WALL

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


def test_a_reply_grows_in_steps_and_only_then_holds_the_line() -> None:
    """§21: the reply appears after a delay and grows.

    That "it stopped growing" is something a rehearsal really waits for.
    """
    clock = [100.0]
    site = Site(
        email="a@example.invalid",
        password="p",
        reply_delay_s=10.0,
        reply_steps=2,
        clock=lambda: clock[0],
    )
    chat = site.create_chat(SEED, session="s")

    assert chat.generating(clock[0])
    assert [turn.role for turn in chat.view(clock[0])] == ["human"]

    clock[0] += 10.0
    partial = chat.view(clock[0])
    assert [turn.role for turn in partial] == ["human", "assistant"]
    assert "MIGRATION-ACK aa000001 1/1" not in partial[-1].text
    assert partial[-1].text
    assert chat.generating(clock[0])

    clock[0] += 10.0
    whole = chat.view(clock[0])
    assert whole[-1].text == "MIGRATION-ACK aa000001 1/1"
    assert not chat.generating(clock[0])


def test_a_follow_up_gets_one_canned_sentence(site: Site) -> None:
    chat = site.create_chat(SEED, session="s")
    site.receive(chat, "In one sentence, what did we discuss in this conversation?")
    chat.reply.started -= 10  # ty: ignore[possibly-unbound-attribute]
    assert chat.view(site.now())[-1].text == CANNED


def test_every_turn_survives_the_next_message(site: Site) -> None:
    """A chat is a transcript, not a last message: what a reload shows is this."""
    chat = site.create_chat(SEED, session="s")
    chat.reply.started -= 10  # ty: ignore[possibly-unbound-attribute]
    site.receive(chat, SEED.replace("1/1", "2/2"))
    chat.reply.started -= 10  # ty: ignore[possibly-unbound-attribute]
    assert [turn.role for turn in chat.view(site.now())] == [
        "human",
        "assistant",
        "human",
        "assistant",
    ]


def test_exactly_one_pair_signs_in(site: Site) -> None:
    assert site.credentials_match("rehearsal@example.invalid", "rehearsal-not-a-real-password")
    assert not site.credentials_match("rehearsal@example.invalid", "guess")
    assert not site.credentials_match("someone@example.invalid", "guess")


def test_the_ledger_counts_what_the_mock_was_asked_to_do() -> None:
    ledger = Ledger(IDENTITY.heading)
    site = Site(email="a@example.invalid", password="p", ledger=ledger)
    site.sign_in()
    site.accept_file("notes.txt", session="s")
    chat = site.create_chat(SEED, session="s")
    site.receive(chat, SEED)
    site.rename(chat, "A name")
    site.request_export()

    assert ledger.counters() == {
        "sign_ins": 1,
        "chats_created": 1,
        "messages_received": 2,
        "files_accepted": 1,
        "renames": 1,
        "exports_requested": 1,
    }
    assert chat.files == ["notes.txt"]


def test_an_export_ask_mints_a_link_and_is_counted(site: Site) -> None:
    """`32`: two asks are two links, in order, and never the same token."""
    first = site.request_export()
    second = site.request_export()
    assert first.token != second.token
    assert all(len(export.token) == 32 for export in (first, second))
    assert [export.token for export in site.exports()] == [first.token, second.token]
    assert site.counters()["exports_requested"] == 2


def test_a_token_nobody_minted_is_nothing_and_a_minted_one_counts_its_fetches(site: Site) -> None:
    assert site.fetch_export("deadbeef") is None
    minted = site.request_export()
    assert site.fetch_export(minted.token) is minted
    site.fetch_export(minted.token)
    assert minted.fetched == 2


def test_a_chat_is_dated_by_the_wall_clock(site: Site) -> None:
    chat = site.create_chat(SEED, session="s")
    assert chat.created_at == pytest.approx(WALL)
    assert site.all_chats() == (chat,)


def test_a_file_belongs_to_the_chat_the_next_message_creates(site: Site) -> None:
    site.accept_file("q3-chart.png", session="s")
    assert site.pending("s") == ["q3-chart.png"]
    chat = site.create_chat(SEED, session="s")
    assert chat.files == ["q3-chart.png"]
    assert site.pending("s") == []


@pytest.mark.parametrize("steps", [2, 4])
def test_the_reply_is_whole_at_the_last_step(steps: int) -> None:
    clock = [0.0]
    site = Site(
        email="a@example.invalid",
        password="p",
        reply_delay_s=1.0,
        reply_steps=steps,
        clock=lambda: clock[0],
    )
    chat = site.create_chat(SEED, session="s")
    clock[0] += steps
    assert chat.view(clock[0])[-1].text == "MIGRATION-ACK aa000001 1/1"
