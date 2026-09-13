"""What the mock chatgpt.com does, without a socket in the way."""

import pytest
from chatgptmock import IDENTITY
from chatgptmock.site import PASTE_THRESHOLD, Chat, Message, Site, Upload
from mockcore.ledger import Ledger
from mockcore.reply import CANNED

from conftest import WALL

SEED = "Part 1 of 1\n\nReply with exactly one line:\nMIGRATION-ACK aa000001 1/1\n"


def test_a_reply_grows_in_steps_and_only_then_holds_the_line() -> None:
    """§54: the reply appears after a delay and grows, as on every mock."""
    clock = [100.0]
    site = Site(email="a@example.invalid", password="p", reply_delay_s=10.0, reply_steps=2, clock=lambda: clock[0])
    chat = site.create_chat(SEED, session="s")

    assert chat.generating(clock[0])
    assert [message.role for message in chat.view(clock[0])] == ["user"]

    clock[0] += 10.0
    partial = chat.view(clock[0])
    assert [message.role for message in partial] == ["user", "assistant"]
    assert "MIGRATION-ACK aa000001 1/1" not in partial[-1].text
    assert chat.generating(clock[0])

    clock[0] += 10.0
    assert chat.view(clock[0])[-1].text == "MIGRATION-ACK aa000001 1/1"
    assert not chat.generating(clock[0])


def test_the_reply_reads_the_pasted_text_too(chatgpt_site: Site) -> None:
    """`paste over the threshold`: a seed arrives as an attachment, and the line it asks for is in it."""
    chat = chatgpt_site.create_chat("", pasted=[SEED], session="s")
    chat.reply.started -= 10  # ty: ignore[possibly-unbound-attribute]
    assert chat.view(chatgpt_site.now())[-1].text == "MIGRATION-ACK aa000001 1/1"
    assert chat.messages[0] == Message("user", "", pasted=(SEED,))
    assert chat.messages[0].content == SEED + "\n"


def test_a_follow_up_gets_one_canned_sentence(chatgpt_site: Site) -> None:
    chat = chatgpt_site.create_chat(SEED, session="s")
    chatgpt_site.receive(chat, "In one sentence, what did we discuss?", session="s")
    chat.reply.started -= 10  # ty: ignore[possibly-unbound-attribute]
    assert chat.view(chatgpt_site.now())[-1].text == CANNED


def test_every_turn_survives_the_next_message(chatgpt_site: Site) -> None:
    chat = chatgpt_site.create_chat(SEED, session="s")
    chat.reply.started -= 10  # ty: ignore[possibly-unbound-attribute]
    chatgpt_site.receive(chat, SEED.replace("1/1", "2/2"), session="s")
    chat.reply.started -= 10  # ty: ignore[possibly-unbound-attribute]
    assert [message.role for message in chat.view(chatgpt_site.now())] == ["user", "assistant", "user", "assistant"]


def test_stopping_keeps_what_the_page_showed_as_the_finished_turn() -> None:
    """`generating`: the one control stops the reply, and what was on the page stays."""
    clock = [0.0]
    site = Site(email="a@example.invalid", password="p", reply_delay_s=10.0, reply_steps=2, clock=lambda: clock[0])
    chat = site.create_chat(SEED, session="s")
    clock[0] += 10.0
    shown = chat.view(clock[0])[-1].text
    site.stop(chat)
    assert not chat.generating(clock[0])
    assert chat.messages[-1] == Message("assistant", shown)
    assert shown != "MIGRATION-ACK aa000001 1/1"


def test_stopping_before_anything_showed_leaves_the_question_alone(chatgpt_site: Site) -> None:
    chat = chatgpt_site.create_chat(SEED, session="s")
    chatgpt_site.stop(chat)
    assert [message.role for message in chat.messages] == ["user"]


def test_exactly_one_pair_signs_in(chatgpt_site: Site) -> None:
    assert chatgpt_site.credentials_match("rehearsal@example.invalid", "rehearsal-not-a-real-password")
    assert not chatgpt_site.credentials_match("rehearsal@example.invalid", "guess")
    assert not chatgpt_site.credentials_match("someone@example.invalid", "rehearsal-not-a-real-password")


def test_a_session_is_held_until_signed_out(chatgpt_site: Site) -> None:
    token = chatgpt_site.sign_in()
    assert chatgpt_site.signed_in(token)
    assert not chatgpt_site.signed_in("someone-else")
    assert not chatgpt_site.signed_in(None)
    chatgpt_site.sign_out(token)
    assert not chatgpt_site.signed_in(token)


def test_the_ledger_counts_what_the_mock_was_asked_to_do() -> None:
    """§54: the same six counts, under a heading that names the site."""
    ledger = Ledger(IDENTITY.heading)
    site = Site(email="a@example.invalid", password="p", ledger=ledger)
    site.sign_in()
    site.accept_file("notes.txt", 12, session="s")
    chat = site.create_chat(SEED, session="s")
    site.receive(chat, SEED, session="s")
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
    assert ledger.block().startswith("Mock chatgpt.com — ledger\n")
    assert chat.messages[0].files == (Upload("notes.txt", 12),)


def test_a_file_belongs_to_the_message_the_session_sends_next(chatgpt_site: Site) -> None:
    """The export names a file on the message that carried it, so the site keeps it there."""
    chatgpt_site.accept_file("q3-chart.png", 3, session="s")
    assert chatgpt_site.pending("s") == [Upload("q3-chart.png", 3)]
    chat = chatgpt_site.create_chat(SEED, session="s")
    assert chat.messages[0].files == (Upload("q3-chart.png", 3),)
    assert chatgpt_site.pending("s") == []
    chat.reply.started -= 10  # ty: ignore[possibly-unbound-attribute]
    chatgpt_site.accept_file("notes.txt", 5, session="s")
    chatgpt_site.receive(chat, "and this", session="s")
    assert chat.messages[2].files == (Upload("notes.txt", 5),)
    assert chat.messages[0].files == (Upload("q3-chart.png", 3),)


def test_a_file_waiting_in_another_session_stays_there(chatgpt_site: Site) -> None:
    chatgpt_site.accept_file("theirs.txt", 1, session="other")
    chat = chatgpt_site.create_chat(SEED, session="s")
    assert chat.messages[0].files == ()
    assert chatgpt_site.pending("other") == [Upload("theirs.txt", 1)]


def test_the_sidebar_lists_chats_newest_first_and_the_archive_oldest_first(chatgpt_site: Site) -> None:
    first = chatgpt_site.create_chat(SEED, session="s")
    second = chatgpt_site.create_chat(SEED, session="s")
    assert chatgpt_site.sidebar() == (second, first)
    assert chatgpt_site.all_chats() == (first, second)
    assert chatgpt_site.chat_ids() == (first.id, second.id)
    assert chatgpt_site.chat(first.id) is first
    assert chatgpt_site.chat("nope") is None


def test_a_rename_is_kept_and_counted(chatgpt_site: Site) -> None:
    chat = chatgpt_site.create_chat(SEED, session="s")
    assert chat.title == "New chat"
    chatgpt_site.rename(chat, "Notes on pooling")
    assert chatgpt_site.chat(chat.id).title == "Notes on pooling"  # ty: ignore[possibly-unbound-attribute]
    assert chatgpt_site.counters()["renames"] == 1


def test_an_export_ask_mints_a_link_and_is_counted(chatgpt_site: Site) -> None:
    """§54: one ask mints one link at once, and a second ask adds a second."""
    first = chatgpt_site.request_export()
    second = chatgpt_site.request_export()
    assert first.token != second.token
    assert [export.token for export in chatgpt_site.exports()] == [first.token, second.token]
    assert chatgpt_site.counters()["exports_requested"] == 2
    assert chatgpt_site.fetch_export("deadbeef") is None
    assert chatgpt_site.fetch_export(first.token) is first
    assert first.fetched == 1


def test_a_chat_is_dated_by_the_wall_clock(chatgpt_site: Site) -> None:
    chat = chatgpt_site.create_chat(SEED, session="s")
    assert chat.created_at == pytest.approx(WALL)
    assert isinstance(chat, Chat)


def test_the_threshold_is_the_documented_one() -> None:
    """*reported (OpenAI 6825453)*: more than 10,000 characters."""
    assert PASTE_THRESHOLD == 10_000
