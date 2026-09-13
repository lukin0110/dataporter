"""`claude-mock`: start the mock, or ask it what it has been asked to do.

Two commands and no configuration file. `serve` starts the site and prints the
one thing an operator needs in order to reach it — nobody composes a resolver
rule by hand (§21, *Reachability*) — and `ledger` prints the count the rehearsal
record reconciles against (§25).

What the printed lines must *do* is the brief's (§21): send the `claude.ai` host
to the mock, and trust the mock's own key and never every certificate. The port,
the mechanism and the lines themselves are `26`'s to choose, and are chosen here:
`8443`, Chrome's host-resolver rule, and an SPKI pin. The tool is byte-identical
to the one that will meet claude.ai and has no setting that names the mock, so
the only way in is configuration an operator may already write — and what is
printed is that configuration, ready to paste.
"""

import argparse
import os
import signal
import ssl
import sys
import time
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from types import FrameType

from claudemock import HOST, PROGRAM_NAME, __version__, certificate, server, uimap
from claudemock.site import DEFAULT_REPLY_DELAY_S, DEFAULT_REPLY_STEPS, Site

DEFAULT_PORT = 8443
DEFAULT_HOST = "127.0.0.1"

PROXY_ENV = ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY")
"""Chrome reads these on Linux, and a proxy resolves the host name itself — so
`--host-resolver-rules` never fires and the mock looks unreachable. Not part of
the block, because it is a fact about the machine rather than about the mock."""

PROXY_NOTE = """\
This machine has a proxy in its environment ({names}), which Chrome reads and
which would resolve claude.ai itself. Add to the same list:

  "--no-proxy-server",

"""

DEFAULT_EMAIL = "rehearsal@example.invalid"
DEFAULT_PASSWORD = "rehearsal-not-a-real-password"
"""Invented, and invalid by construction: `.invalid` is reserved and can never
name a real mailbox (§23, *What it never touches*)."""


def reachability(*, host: str, port: int, material: certificate.Material) -> str:
    """Return the reachability block, byte for byte, ending in a blank line.

    `26`'s golden string, pinned by `mock/tests/test_cli.py`. §21 constrains what
    it does and leaves what it looks like to the slice; the shape here is the
    brief's own illustration, kept because an operator has nothing to gain from
    a different one.
    """
    return "\n".join([
        f"Mock claude.ai listening on https://{host}:{port}",
        "",
        "Add to <workspace>/config.toml before running the tool:",
        "",
        "[browser]",
        "extra_args = [",
        f'  "--host-resolver-rules=MAP {HOST} {host}:{port}",',
        f'  "{material.flag}",',
        "]",
        "",
        "",
    ])


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog=PROGRAM_NAME, description=__doc__)
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command")

    start = commands.add_parser("serve", help="start the mock")
    start.add_argument("--host", default=DEFAULT_HOST)
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--email", default=DEFAULT_EMAIL)
    start.add_argument("--password", default=DEFAULT_PASSWORD)
    start.add_argument(
        "--reply-delay-s",
        type=float,
        default=DEFAULT_REPLY_DELAY_S,
        help="how long each step of a reply takes; must be more than zero",
    )
    start.add_argument("--reply-steps", type=int, default=DEFAULT_REPLY_STEPS)
    start.add_argument(
        "--cert-dir",
        type=Path,
        default=None,
        help="where the TLS key lives; the default keeps one between runs",
    )

    count = commands.add_parser("ledger", help="print a running mock's ledger")
    count.add_argument("--host", default=DEFAULT_HOST)
    count.add_argument("--port", type=int, default=DEFAULT_PORT)

    commands.add_parser("rows", help="the UI map rows the mock is built out of")
    return root


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    if arguments.command == "ledger":
        return ledger(host=arguments.host, port=arguments.port)
    if arguments.command == "rows":
        return rows()
    return serve(arguments)


def serve(arguments: argparse.Namespace) -> int:
    if arguments.reply_delay_s <= 0:
        print(
            f"{PROGRAM_NAME}: a reply delay is more than zero — a rehearsal that "
            "never waits for a reply proves nothing",
            file=sys.stderr,
        )
        return 2
    if arguments.reply_steps < 2:
        print(
            f"{PROGRAM_NAME}: a reply grows in at least two steps",
            file=sys.stderr,
        )
        return 2
    material = certificate.ensure(arguments.cert_dir)
    site = Site(
        email=arguments.email,
        password=arguments.password,
        reply_delay_s=arguments.reply_delay_s,
        reply_steps=arguments.reply_steps,
    )
    running = server.serve(site, host=arguments.host, port=arguments.port, material=material)
    print(
        reachability(host=arguments.host, port=running.port, material=material),
        end="",
    )
    proxies = [name for name in PROXY_ENV if os.environ.get(name)]
    if proxies:
        print(PROXY_NOTE.format(names=", ".join(proxies)), end="")
    sys.stdout.flush()

    def stop(_signal: int, _frame: FrameType | None) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        # A sleep loop rather than `signal.pause`, which does not exist on
        # Windows: the mock is a developer's tool and runs wherever Chrome does.
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        running.close()
    # The ledger on the way out, so a rehearsal that forgot to ask still has it.
    print(site.ledger.block(), end="")
    return 0


def ledger(*, host: str, port: int) -> int:
    """Ask a running mock for its count. Its own certificate, and no other."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    url = f"https://{host}:{port}{server.LEDGER_PATH}"
    try:
        with urllib.request.urlopen(url, context=context, timeout=10) as answer:
            print(answer.read().decode("utf-8"), end="")
    except OSError as failure:
        print(f"{PROGRAM_NAME}: {url}: {failure}", file=sys.stderr)
        return 1
    return 0


def rows() -> int:
    """Every row of the UI map the mock stands on, and what it did about it."""
    print("Mock claude.ai — the UI map rows it is built out of\n")
    for row in uimap.cited():
        print(f"{row}\n  {uimap.WHAT_THE_MOCK_DOES[row]}\n")
    return 0
