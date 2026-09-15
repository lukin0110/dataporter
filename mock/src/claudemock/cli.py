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

What the printed lines must *do* is the brief's (§21): send the `claude.ai` host
to the mock, and trust the mock's own key and never every certificate. The port,
the mechanism and the lines themselves are `26`'s to choose: `8443`, Chrome's
host-resolver rule, and an SPKI pin — printed by the core (`mockcore.cli`) since
`38`, byte for byte as `26` pinned them. What is this site's alone is the tail
of the block: the tool fetches this site's export link with Python, and the
certificate it must trust for that is a fact about this mock.
"""

import argparse
import sys
from collections.abc import Sequence

from mockcore import certificate, wire
from mockcore import cli as core

from claudemock import DEFAULT_PORT, IDENTITY, server, uimap
from claudemock.site import Site

DEFAULT_HOST = core.DEFAULT_HOST

FETCH_PROXY_NOTE = """\
The tool's fetch of an export link reads the same proxy. Set beside SSL_CERT_FILE:

  no_proxy=127.0.0.1

"""
"""What this site adds to the core's proxy note (`32`): the tool downloads a
link with Python, which reads the same proxy Chrome does."""

HOST_NOTE = """\
The mock is listening on {host}, and the tool cannot fetch an export link from
there: its certificate names 127.0.0.1 alone. Chrome is unaffected — it trusts
the key, not the name — so a migration rehearses; an extraction needs the
default host.

"""
"""Printed when `--host` is not the loopback address. The links `serve` mints and
`exports` lists are spelled with the address the socket really bound, and the
tool's fetch verifies that address against the certificate (`32`)."""

DEFAULT_EMAIL = "rehearsal@example.invalid"
DEFAULT_PASSWORD = "rehearsal-not-a-real-password"
"""Invented, and invalid by construction: `.invalid` is reserved and can never
name a real mailbox (§23, *What it never touches*)."""


def reachability(*, host: str, port: int, material: certificate.Material) -> str:
    """Return the reachability block, byte for byte, ending in a blank line.

    `26`'s golden string, pinned by `mock/tests/test_claude_cli.py`. §21 constrains
    what it does and leaves what it looks like to the slice; the shape here is the
    brief's own illustration, kept because an operator has nothing to gain from
    a different one. The tail is `32`'s: the fetch of an export link is Python's,
    not Chrome's, so the two Chrome lines do not reach it.
    """
    return core.reachability(
        IDENTITY,
        host=host,
        port=port,
        flag=material.flag,
        tail=[
            "Set in the tool's environment before fetching an export link from it:",
            "",
            f"  SSL_CERT_FILE={material.cert_path}",
            "",
        ],
    )


def proxy_note(names: Sequence[str]) -> str:
    """Return the core's note, and then what the tool's own fetch needs."""
    return core.proxy_note(IDENTITY, names) + FETCH_PROXY_NOTE


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
    material = certificate.ensure(IDENTITY, arguments.cert_dir)
    site = Site(
        email=arguments.email,
        reply_delay_s=arguments.reply_delay_s,
        reply_steps=arguments.reply_steps,
    )
    running = server.serve(
        site,
        host=arguments.host,
        port=arguments.port,
        material=material,
        announce=core.announce,
        announce_sign_in=core.announce_sign_in,
    )
    print(reachability(host=arguments.host, port=running.port, material=material), end="")
    proxies = core.proxies()
    if proxies:
        print(proxy_note(proxies), end="")
    if arguments.host != DEFAULT_HOST:
        print(HOST_NOTE.format(host=arguments.host), end="")
    sys.stdout.flush()
    core.wait(running)
    # The ledger on the way out, so a rehearsal that forgot to ask still has it.
    print(site.ledger.block(), end="")
    return 0


def ledger(*, host: str, port: int = DEFAULT_PORT) -> int:
    """Ask a running mock for its count. Its own certificate, and no other."""
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
