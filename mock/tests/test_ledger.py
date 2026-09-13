"""The ledger block, byte for byte.

`26`'s golden string, with `32`'s row under it. Brief `02`'s block (§21)
illustrates the shape and leaves it to the slice; this is where the slice pins it.
`rehearsal/run.py` rebuilds §21's five rows from the numbers for the record — the
sixth is always zero in a migration rehearsal — so the first five must stay as
they are.
"""

import threading

from claudemock.ledger import Ledger


def test_the_block_is_the_golden_string() -> None:
    ledger = Ledger(
        sign_ins=2,
        chats_created=8,
        messages_received=11,
        files_accepted=2,
        renames=8,
        exports_requested=1,
    )
    assert ledger.block() == (
        "Mock claude.ai — ledger\n"
        "\n"
        "Sign-ins:                      2\n"
        "Chats created:                 8\n"
        "Messages received:            11\n"
        "Files accepted:                2\n"
        "Renames:                       8\n"
        "Exports requested:             1\n"
        "\n"
    )


def test_a_fresh_ledger_is_all_zeros() -> None:
    assert Ledger().counters() == {
        "sign_ins": 0,
        "chats_created": 0,
        "messages_received": 0,
        "files_accepted": 0,
        "renames": 0,
        "exports_requested": 0,
    }


def test_counting_is_safe_to_do_from_several_threads() -> None:
    """The server is threaded, and a witness that under-counts is worse than no witness at all."""
    ledger = Ledger()
    workers = [
        threading.Thread(target=lambda: [ledger.count("messages_received") for _ in range(500)]) for _ in range(8)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert ledger.counters()["messages_received"] == 4_000
