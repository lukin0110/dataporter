"""`chatgpt-mock`: start the mock, or ask it what it has been asked to do.

Four commands and no configuration file, the same four as `claude-mock`'s and
all of them the core's (`mockcore.cli`): `serve` starts the site and prints the
one thing an operator needs in order to reach it — nobody composes a resolver
rule for two host names by hand (§54, *Reachability*) — `ledger` prints the
count a record reconciles against, `exports` prints the links the site has
handed out instead of emails, for the terminal that did not start it, and `rows`
prints the UI map rows the mock is built out of.

What is this site's alone is what the block does *not* say: the mock claude.ai's
block names a certificate for the tool's own fetch of an export link, and this
site's archive wants a session the tool's fetch does not carry (§54), so there is
nothing to tell the tool. The README says how a person fetches one.
"""

import argparse
import sys
from collections.abc import Sequence

from mockcore import certificate
from mockcore import cli as core

from chatgptmock import DEFAULT_PORT, IDENTITY, server, uimap
from chatgptmock.site import Site

DEFAULT_HOST = core.DEFAULT_HOST

DEFAULT_EMAIL = "rehearsal@example.invalid"
DEFAULT_PASSWORD = "rehearsal-not-a-real-password"
"""Invented, and invalid by construction: `.invalid` is reserved and can never
name a real mailbox (§56). The same pair as the mock claude.ai's, so that an
operator with both mocks up has one thing to remember."""


def reachability(*, host: str, port: int, material: certificate.Material) -> str:
    """Return the reachability block, byte for byte, ending in a blank line.

    `39`'s golden string, pinned by `mock/tests/test_chatgpt_cli.py`: the core's
    block with both host names in one resolver rule, and no tail.
    """
    return core.reachability(IDENTITY, host=host, port=port, flag=material.flag)


def proxy_note(names: Sequence[str]) -> str:
    return core.proxy_note(IDENTITY, names)


def parser() -> argparse.ArgumentParser:
    return core.parser(IDENTITY, description=__doc__, email=DEFAULT_EMAIL, password=DEFAULT_PASSWORD)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    if arguments.command == "ledger":
        return ledger(host=arguments.host, port=arguments.port)
    if arguments.command == "exports":
        return exports(host=arguments.host, port=arguments.port)
    if arguments.command == "rows":
        return rows()
    return serve(arguments)


def serve(arguments: argparse.Namespace) -> int:
    refused = core.refused_reply(IDENTITY, arguments)
    if refused is not None:
        return refused
    material = certificate.ensure(IDENTITY, arguments.cert_dir)
    site = Site(
        email=arguments.email,
        password=arguments.password,
        reply_delay_s=arguments.reply_delay_s,
        reply_steps=arguments.reply_steps,
    )
    running = server.serve(
        site,
        host=arguments.host,
        port=arguments.port,
        material=material,
        announce=core.announce,
    )
    print(reachability(host=arguments.host, port=running.port, material=material), end="")
    proxies = core.proxies()
    if proxies:
        print(proxy_note(proxies), end="")
    sys.stdout.flush()
    core.wait(running)
    # The ledger on the way out, so a walk that forgot to ask still has it.
    print(site.ledger.block(), end="")
    return 0


def ledger(*, host: str, port: int = DEFAULT_PORT) -> int:
    """Ask a running mock for its count. Its own certificate, and no other."""
    return core.ledger(IDENTITY, host=host, port=port)


def exports(*, host: str, port: int = DEFAULT_PORT) -> int:
    """Ask a running mock for the links it handed out, one per line, oldest first."""
    return core.exports(IDENTITY, host=host, port=port)


def rows() -> int:
    """Every row of the UI map the mock stands on, and what it did about it."""
    return core.rows(IDENTITY, uimap.cited(), uimap.WHAT_THE_MOCK_DOES)
