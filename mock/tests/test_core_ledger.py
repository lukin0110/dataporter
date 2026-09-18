"""The ledger block, byte for byte.

`26`'s golden string, with `32`'s row under it, `49`'s under that, `67`'s two
under those, and `38`'s heading over it — the site's own, since two mocks running at once keep two ledgers
(§54). Brief `02`'s block (§21) illustrates the shape and leaves it to the slice;
this is where the slice pins it. `rehearsal/run.py` rebuilds §21's five rows from
the numbers for the record — the sixth is always zero in a migration rehearsal —
so the first five must stay as they are.
"""

import threading

from mockcore.ledger import Ledger


def test_the_block_is_the_golden_string() -> None:
    ledger = Ledger(
        heading="Mock claude.ai — ledger",
        sign_ins=2,
        chats_created=8,
        messages_received=11,
        files_accepted=2,
        renames=8,
        exports_requested=1,
        links_minted=2,
        skills_listed=3,
        skills_served=9,
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
        "Sign-in links minted:          2\n"
        "Skill lists read:              3\n"
        "Skills served:                 9\n"
        "\n"
    )


def test_a_fresh_ledger_is_all_zeros() -> None:
    assert Ledger("Mock — ledger").counters() == {
        "sign_ins": 0,
        "chats_created": 0,
        "messages_received": 0,
        "files_accepted": 0,
        "renames": 0,
        "exports_requested": 0,
        "links_minted": 0,
        "skills_listed": 0,
        "skills_served": 0,
    }


def test_counting_is_safe_to_do_from_several_threads() -> None:
    """The server is threaded, and a witness that under-counts is worse than no witness at all."""
    ledger = Ledger("Mock — ledger")
    workers = [
        threading.Thread(target=lambda: [ledger.count("messages_received") for _ in range(500)]) for _ in range(8)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert ledger.counters()["messages_received"] == 4_000


def test_the_heading_names_the_site() -> None:
    """§54: two mocks at once keep two ledgers, and a reader can tell which is which."""
    assert Ledger("Mock chatgpt.com — ledger").block().startswith("Mock chatgpt.com — ledger\n\nSign-ins:")
