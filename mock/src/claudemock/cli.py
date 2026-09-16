"""`claude-mock`: start the mock, or ask it what it has been asked to do.

Five commands and no configuration file. `serve` starts the site and prints the
one thing an operator needs in order to reach it — nobody composes a resolver
rule by hand (§21, *Reachability*) — `ledger` prints the count the rehearsal
record reconciles against (§25), `exports` prints the links the site has
handed out instead of emails (`32`), `sign-in-links` the links it minted where
a sign-in email would have gone (`49`), both for the terminal that did not
start it, and `rows` prints the UI map rows the mock is built out of.

`--password` is still accepted by `serve`, because the parser is every mock's
(`38`), and ignored: claude.ai signs in with an address and a link, and so does
this (brief 07 §72).

What the printed lines must *do* was the brief's (§21): send the `claude.ai`
host to the mock, and trust its key. `65` answers both by not needing either —
the mock is at `http://127.0.0.1:8443` and the tool is told so by `--mock`, so
the block is the address and the flag (ADR 0010).
"""

import argparse
import sys
from collections.abc import Sequence

from mockcore import cli as core
from mockcore import wire

from claudemock import DEFAULT_PORT, IDENTITY, server, uimap
from claudemock.site import Site

DEFAULT_HOST = core.DEFAULT_HOST

DEFAULT_EMAIL = "rehearsal@example.invalid"
DEFAULT_PASSWORD = "rehearsal-not-a-real-password"
"""Invented, and invalid by construction: `.invalid` is reserved and can never
name a real mailbox (§23, *What it never touches*)."""


def reachability(*, host: str, port: int) -> str:
    """Return the reachability block, byte for byte, ending in a blank line.

    Two lines since `65`: the address, and the flag that reaches it. `26`'s block
    was a `config.toml` table an operator pasted, because the tool had no setting
    that could name a mock (ADR 0001); `--mock` is that setting now (ADR 0010),
    so there is nothing left to paste.
    """
    return core.reachability(IDENTITY, host=host, port=port)


LISTINGS = (("sign-in-links", "print the sign-in links a running mock has minted"),)
"""This site's own listing command (`49`), beside the core's `exports`."""


def parser() -> argparse.ArgumentParser:
    return core.parser(IDENTITY, description=__doc__, email=DEFAULT_EMAIL, password=DEFAULT_PASSWORD, listings=LISTINGS)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    if arguments.command == "ledger":
        return ledger(host=arguments.host, port=arguments.port)
    if arguments.command == "exports":
        return exports(host=arguments.host, port=arguments.port)
    if arguments.command == "sign-in-links":
        return sign_in_links(host=arguments.host, port=arguments.port)
    if arguments.command == "rows":
        return rows()
    return serve(arguments)


def serve(arguments: argparse.Namespace) -> int:
    refused = core.refused_reply(IDENTITY, arguments)
    if refused is not None:
        return refused
    site = Site(
        email=arguments.email,
        reply_delay_s=arguments.reply_delay_s,
        reply_steps=arguments.reply_steps,
    )
    running = server.serve(
        site,
        host=arguments.host,
        port=arguments.port,
        announce=core.announce,
        announce_sign_in=core.announce_sign_in,
    )
    print(reachability(host=arguments.host, port=running.port), end="")
    sys.stdout.flush()
    core.wait(running)
    # The ledger on the way out, so a rehearsal that forgot to ask still has it.
    print(site.ledger.block(), end="")
    return 0


def ledger(*, host: str, port: int = DEFAULT_PORT) -> int:
    """Ask a running mock for its count."""
    return core.ledger(IDENTITY, host=host, port=port)


def exports(*, host: str, port: int = DEFAULT_PORT) -> int:
    """Ask a running mock for the links it handed out, one per line, oldest first."""
    return core.exports(IDENTITY, host=host, port=port)


def sign_in_links(*, host: str, port: int = DEFAULT_PORT) -> int:
    """Ask a running mock for the sign-in links it minted, one per line, oldest first (`49`).

    `claude-mock sign-in-links | tail -n 1` is the newest: what a person hands
    to `dataporter login --link`, in the terminal the mock is not in.
    """
    return core.fetch_text(IDENTITY, host=host, port=port, path=wire.SIGN_IN_LINKS_PATH)


def rows() -> int:
    """Every row of the UI map the mock stands on, and what it did about it."""
    return core.rows(IDENTITY, uimap.cited(), uimap.WHAT_THE_MOCK_DOES)
