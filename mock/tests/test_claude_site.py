"""What the mock claude.ai does, without a socket in the way.

Obedience — the line a seed asks for, wrapped or quoted — is the core's and is
tested in `test_core_reply.py`; what is here is what a chat on this site is.
"""

import pytest
from claudemock import IDENTITY, ORIGIN
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


# -- the sign-in by link (`49`) ------------------------------------------------ #


def test_exactly_one_address_gets_a_link(site: Site) -> None:
    """§21: one address is the account's; any other is refused, and refused *before* a link exists."""
    assert site.request_sign_in("someone@example.invalid", pending="browser-1") is None
    assert site.sign_in_links() == ()
    assert site.sign_in_step("browser-1") == "email"
    link = site.request_sign_in("rehearsal@example.invalid", pending="browser-1")
    assert link is not None
    assert site.sign_in_step("browser-1") == "link_sent"
    assert site.counters()["links_minted"] == 1


def test_the_link_is_the_real_shape_and_lands_on_the_site(site: Site) -> None:
    """`sign-in link`: on claude.ai, at /magic-link, the token and the base64url address in the fragment."""
    link = site.request_sign_in("rehearsal@example.invalid", pending="browser-1")
    assert link is not None
    assert site.link_of(link) == f"{ORIGIN}/magic-link#{link.token}:cmVoZWFyc2FsQGV4YW1wbGUuaW52YWxpZA"
    assert len(link.token) == 32
    assert "=" not in link.fragment


def test_the_link_signs_in_the_browser_that_asked_and_only_once(site: Site) -> None:
    link = site.request_sign_in("rehearsal@example.invalid", pending="browser-1")
    assert link is not None
    session = site.redeem(link.token, "rehearsal@example.invalid", pending="browser-1")
    assert session is not None
    assert site.signed_in(session)
    assert site.counters()["sign_ins"] == 1
    assert site.sign_in_step("browser-1") == "email"  # the pending sign-in is over
    # Spent: a second redemption signs nobody in.
    assert site.redeem(link.token, "rehearsal@example.invalid", pending="browser-1") is None
    assert site.counters()["sign_ins"] == 1


def test_a_link_opened_elsewhere_signs_nobody_in_and_leaves_that_browser_at_the_code_page(site: Site) -> None:
    """`link opened elsewhere`: another browser, a wrong address, a token nobody minted."""
    link = site.request_sign_in("rehearsal@example.invalid", pending="browser-1")
    assert link is not None
    assert site.redeem(link.token, "rehearsal@example.invalid", pending="browser-2") is None
    assert site.sign_in_step("browser-2") == "link_sent"
    assert site.redeem(link.token, "someone@example.invalid", pending="browser-1") is None
    assert site.redeem("deadbeef", "rehearsal@example.invalid", pending="browser-1") is None
    assert not link.spent
    assert site.counters()["sign_ins"] == 0
    # The one that asked can still spend it.
    assert site.redeem(link.token, "rehearsal@example.invalid", pending="browser-1") is not None


def test_resend_mints_another_link_for_the_same_sign_in_and_change_forgets_it(site: Site) -> None:
    assert site.resend("browser-1") is None
    first = site.request_sign_in("rehearsal@example.invalid", pending="browser-1")
    second = site.resend("browser-1")
    assert first is not None
    assert second is not None
    assert first.token != second.token
    assert [item.token for item in site.sign_in_links()] == [first.token, second.token]
    assert site.counters()["links_minted"] == 2
    site.forget_pending("browser-1")
    assert site.sign_in_step("browser-1") == "email"
    assert site.redeem(second.token, "rehearsal@example.invalid", pending="browser-1") is None


def test_the_ledger_counts_what_the_mock_was_asked_to_do() -> None:
    ledger = Ledger(IDENTITY.heading)
    site = Site(email="a@example.invalid", ledger=ledger)
    link = site.request_sign_in("a@example.invalid", pending="b")
    assert link is not None
    site.redeem(link.token, "a@example.invalid", pending="b")
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
        "links_minted": 1,
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
        reply_delay_s=1.0,
        reply_steps=steps,
        clock=lambda: clock[0],
    )
    chat = site.create_chat(SEED, session="s")
    clock[0] += steps
    assert chat.view(clock[0])[-1].text == "MIGRATION-ACK aa000001 1/1"
