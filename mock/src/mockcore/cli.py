"""What every mock's command has in common: the blocks it prints and the loop it runs.

A site's `cli.py` is thin: it names its identity, its defaults and its UI map,
and hands the rest to this module — the parser with its four commands, the
reachability block, the notes, the wait for a signal, and the two commands that
ask a running mock what it has been asked to do.

What the printed lines must *do* is the brief's (§21, §54): send every host
the mock answers as to the mock, and trust the mock's own key and never every
certificate. The mechanism and the lines themselves are the slices' (`26`, `38`),
and are chosen here: Chrome's host-resolver rule and an SPKI pin. The tool is
byte-identical to the one that will meet the real site and has no setting that
names a mock, so the only way in is configuration an operator may already write
— and what is printed is that configuration, ready to paste.
"""

import argparse
import os
import signal
import ssl
import sys
import time
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import FrameType

from mockcore import Identity, __version__
from mockcore.reply import DEFAULT_REPLY_DELAY_S, DEFAULT_REPLY_STEPS
from mockcore.wire import EXPORTS_PATH, LEDGER_PATH, MockServer

DEFAULT_HOST = "127.0.0.1"

PROXY_ENV = ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY")
"""Chrome reads these on Linux, and a proxy resolves the host name itself — so
`--host-resolver-rules` never fires and the mock looks unreachable. Not part of
the block, because it is a fact about the machine rather than about the mock."""

PROXY_NOTE = """\
This machine has a proxy in its environment ({names}), which Chrome reads and
which would resolve {hosts} itself. Add to the same list:

  "--no-proxy-server",

"""

LINK_NOTE = """\
Export requested — the link, instead of an email:

  {link}

"""
"""What `serve` prints when the export page's confirmation is pressed: a mock
has no inbox to send to, so the terminal it runs in is where the link arrives.
`<program> exports` says the same to any other terminal."""


def resolver_rule(identity: Identity, *, host: str, port: int) -> str:
    """Return the one `--host-resolver-rules` value that sends every host to the mock.

    Chrome keeps one value per argument, so a mock with two names prints one
    rule with two maps in it, comma-separated — and two mocks at once are merged
    into one the same way (§54, *Two mocks at once*; the README says how).
    """
    return ", ".join(f"MAP {name} {host}:{port}" for name in identity.hosts)


def reachability(
    identity: Identity,
    *,
    host: str,
    port: int,
    flag: str,
    tail: Sequence[str] = (),
) -> str:
    """Return the reachability block, byte for byte, ending in a blank line.

    `26`'s golden string, kept byte for byte for the mock claude.ai and pinned
    by its tests; `38` made the site's name and its hosts the identity's, and the
    lines after the Chrome table the site's (`tail`: the mock claude.ai's
    `SSL_CERT_FILE` line for the tool's fetch; nothing for a site whose archive
    the tool cannot fetch).
    """
    return "\n".join([
        f"{identity.title} listening on https://{host}:{port}",
        "",
        "Add to <workspace>/config.toml before running the tool:",
        "",
        "[browser]",
        "extra_args = [",
        f'  "--host-resolver-rules={resolver_rule(identity, host=host, port=port)}",',
        f'  "{flag}",',
        "]",
        "",
        *tail,
        "",
    ])


def proxy_note(identity: Identity, names: Sequence[str]) -> str:
    return PROXY_NOTE.format(names=", ".join(names), hosts=identity.spelled_hosts)


def proxies() -> list[str]:
    """Return the proxy variables this machine's environment names, in `PROXY_ENV`'s order."""
    return [name for name in PROXY_ENV if os.environ.get(name)]


def link_note(link: str) -> str:
    """Return what `serve` prints for one export asked for, byte for byte."""
    return LINK_NOTE.format(link=link)


def parser(identity: Identity, *, description: str | None, email: str, password: str) -> argparse.ArgumentParser:
    """Return the four commands every mock has: `serve`, `ledger`, `exports`, `rows`."""
    root = argparse.ArgumentParser(prog=identity.program, description=description)
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command")

    start = commands.add_parser("serve", help="start the mock")
    start.add_argument("--host", default=DEFAULT_HOST)
    start.add_argument("--port", type=int, default=identity.port)
    start.add_argument("--email", default=email)
    start.add_argument("--password", default=password)
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
    count.add_argument("--port", type=int, default=identity.port)

    links = commands.add_parser("exports", help="print the export links a running mock has handed out")
    links.add_argument("--host", default=DEFAULT_HOST)
    links.add_argument("--port", type=int, default=identity.port)

    commands.add_parser("rows", help="the UI map rows the mock is built out of")
    return root


def refused_reply(identity: Identity, arguments: argparse.Namespace) -> int | None:
    """Return exit `2` for a reply nobody would wait for, and `None` for one they would.

    A reply delay of zero or fewer than two steps is refused, because §21 and
    §54 say a reply appears after a non-zero delay and grows in at least two
    steps — a rehearsal that never waits for a reply proves nothing.
    """
    if arguments.reply_delay_s <= 0:
        print(
            f"{identity.program}: a reply delay is more than zero — a rehearsal that "
            "never waits for a reply proves nothing",
            file=sys.stderr,
        )
        return 2
    if arguments.reply_steps < 2:
        print(f"{identity.program}: a reply grows in at least two steps", file=sys.stderr)
        return 2
    return None


def announce(link: str) -> None:
    """Print the link note where an email would have arrived.

    Printed from the server's thread; the main thread only sleeps, so nothing
    interleaves.
    """
    print(link_note(link), end="", flush=True)


def wait(running: MockServer) -> None:
    """Block until interrupted or told to terminate, then close the server."""

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


def ledger(identity: Identity, *, host: str, port: int) -> int:
    """Ask a running mock for its count. Its own certificate, and no other."""
    return fetch_text(identity, host=host, port=port, path=LEDGER_PATH)


def exports(identity: Identity, *, host: str, port: int) -> int:
    """Ask a running mock for the links it handed out, one per line, oldest first.

    `<program> exports | tail -n 1` is the newest, which is what an operator
    hands to whatever fetches it, in the terminal the mock is not in.
    """
    return fetch_text(identity, host=host, port=port, path=EXPORTS_PATH)


def fetch_text(identity: Identity, *, host: str, port: int, path: str) -> int:
    """Print what a running mock serves at `path`, verifying nothing: it is ours."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    url = f"https://{host}:{port}{path}"
    try:
        with urllib.request.urlopen(url, context=context, timeout=10) as answer:
            print(answer.read().decode("utf-8"), end="")
    except OSError as failure:
        print(f"{identity.program}: {url}: {failure}", file=sys.stderr)
        return 1
    return 0


def rows(identity: Identity, cited: Sequence[str], what: Mapping[str, str]) -> int:
    """Every row of the UI map the mock stands on, and what it did about it."""
    print(f"{identity.title} — the UI map rows it is built out of\n")
    for row in cited:
        print(f"{row}\n  {what[row]}\n")
    return 0
