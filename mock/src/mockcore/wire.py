"""The wire every mock shares: cookies, redirects, the witness routes, and the server.

Every decision about what a site *does* is in its `site.py`, and everything
about what it *looks* like is in its `pages.py`; its `server.py` holds its
routes. What is here is the part of the wire that is the same for every site:

- **It is plain HTTP on loopback** since `65`. It used to be HTTPS always,
  because the tool refused every URL that was not `https://` on the site's own
  host and a mock had to be reachable without being told it was one — the door
  ADR 0001 refused. ADR 0010 gives that up: the tool is told, by `--mock`, and
  once it is there is nothing left for a certificate to do. Chrome treats
  `http://127.0.0.1` as a trustworthy origin, so no page behaves differently for
  the loss.
- **The session cookie has a lifetime**, so a session survives Chrome being
  closed and started again — which is what `login` storing a session in the
  workspace profile means.
- **The witness lives at `/__mock/`.** Not a path on any site, so nothing a
  helper drives can reach it, which is what keeps the witness independent of
  the thing it is a witness to. The ledger and the list of links are served
  here for every site, on its own host and port (§54, *Reachability*); the
  archive a link names is each site's own route, because whether it wants a
  session is a fact about the site.

The routes are plain `def`s rather than `async def`s on purpose: a `Site` is
synchronous and guards its state with a lock, so FastAPI runs each route on a
worker thread and the lock keeps doing its job.
"""

import socket
import threading
import time
from collections.abc import Callable
from http import HTTPStatus
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from fastapi.responses import RedirectResponse as _RedirectResponse

from mockcore.exports import Export, Exports
from mockcore.ledger import Ledger

ORIGIN_SCHEME = "http"
"""Plain, on loopback, since `65`. One place spells it, so a mock that ever
served TLS again is one edit and not a search."""


def origin_of(host: str, port: int) -> str:
    """Return where a mock bound: what its links are spelled with, and what `--mock` names."""
    return f"{ORIGIN_SCHEME}://{host}:{port}"


SESSION_COOKIE = "mock_session"
LOGIN_COOKIE = "mock_login"

LEDGER_PATH = "/__mock/ledger"
LEDGER_JSON_PATH = "/__mock/ledger.json"
EXPORTS_PATH = "/__mock/exports"
EXPORTS_JSON_PATH = "/__mock/exports.json"
ARCHIVE_PATH = EXPORTS_PATH + "/{token}.zip"
MANIFEST_PATH = EXPORTS_PATH + "/{token}"
PART_PATH = "/__mock/export/{export_id}/download/{part_token}.zip"
"""The three shapes a link can have, all under `/__mock/` and none of them a path
on any site: no helper will drive one, because no surface admits it.

A site serves *either* `ARCHIVE_PATH` — the link is the archive, which is the
mock chatgpt.com — *or* `MANIFEST_PATH` and `PART_PATH`, where the link is an
index naming a file per category and each file has a single-use address of its
own. `PART_PATH` is shaped after the real one — `/export/<account>/download/<token>` —
and that shape matters for more than a trace's sake: it carries **no part of the
index's own token**. A real one does not either, and the snapshot is why. The tool
files the vendor's manifest verbatim, so anything in a part's URL is kept on disk
next to the archive; the part tokens there are spent by then, and the index's is
not. A mock that hung the parts under the index's token would have put a live
credential in every snapshot and called it fidelity.

Registering them is the site's, not the core's, because whether the download
wants a session is the site's fact — and today both sites say it does."""

EXPIRE_PATH = "/__mock/expire-session"
"""Where a run asks for its session to be thrown away, so that what the site does
next is what it does to a person whose sign-in has lapsed. Behind no session, like
every witness route: it is the operator speaking to the mock, not the tool."""

SESSION_MAX_AGE_S = 7 * 24 * 60 * 60
"""How long a signed-in session lasts. Long enough to survive the browser being
closed and started again: a cookie with no lifetime is discarded when Chrome
exits, and every later command would sign in again."""

LOGIN_MAX_AGE_S = 60 * 60
"""How long a half-finished sign-in lasts (`49`). The mock claude.ai's pending
sign-in has to outlive the window it began in — the tool's `login --link` may
open the profile again after that window closed (brief 07 §73) — and whether
the real site's does is unobserved; the mock says an hour and says so here."""

SIGN_IN_LINKS_PATH = "/__mock/sign-in-links"
SIGN_IN_LINKS_JSON_PATH = "/__mock/sign-in-links.json"
"""Where a site that signs people in by link lists the links it minted (`49`),
beside the exports: the listing that stands in for the inbox."""

MAX_BODY_BYTES = 32 * 1024 * 1024
"""A seed is tens of kilobytes and a rehearsal attachment is smaller still. A
cap because a mock reads whatever `Content-Length` promises into memory."""

STARTUP_TIMEOUT_S = 10.0
"""How long `serve` waits for uvicorn to report that it is accepting
connections before giving up. Starting takes milliseconds; the timeout exists
so a failure to start is an error rather than a hang."""


class SignedOutError(Exception):
    """Raised by a route that needs a session and was not given one.

    The site's handler turns it into the redirect to wherever its signed-out
    state lives, so that `signed out` is one line in every route that needs it.
    """


# -- responses ---------------------------------------------------------------- #


LIFETIMES = {SESSION_COOKIE: SESSION_MAX_AGE_S, LOGIN_COOKIE: LOGIN_MAX_AGE_S}
"""The two cookies that outlive the browser; every other one is the tab's."""


def set_cookie(response: Response, name: str, value: str) -> None:
    """Set a cookie for the whole site. The session and the pending sign-in have a lifetime."""
    response.set_cookie(
        name,
        value,
        path="/",
        max_age=LIFETIMES.get(name),
    )


def redirect(location: str, **cookies: str) -> Response:
    response = _RedirectResponse(location, status_code=HTTPStatus.SEE_OTHER)
    for name, value in cookies.items():
        set_cookie(response, name, value)
    return response


def not_found() -> Response:
    return PlainTextResponse("not found", status_code=HTTPStatus.NOT_FOUND)


def session_of(signed_in: Callable[[str | None], bool]) -> Callable[[Request], str]:
    """Return the dependency a route with a session behind it declares."""

    def session(request: Request) -> str:
        token = request.cookies.get(SESSION_COOKIE)
        if not signed_in(token):
            raise SignedOutError
        return str(token)

    return session


def quiet(_link: str) -> None:
    """Announce a link to nobody: what a server does when no caller asked."""


def export_json(export: Export, link: str) -> dict[str, Any]:
    return {
        "token": export.token,
        "link": link,
        "requested_at": export.requested_at,
        "fetched": export.fetched,
        "parts": [
            {
                "category": part.category,
                "part": part.part,
                "filename": part.filename,
                "spent": part.token in export.spent,
            }
            for part in export.parts
        ],
    }


def witness(
    app: FastAPI,
    *,
    ledger: Ledger,
    exports: Exports,
    link_of: Callable[[Export], str],
    expire: Callable[[], int] | None = None,
) -> None:
    """Register the witness routes: the ledger, the links, and the expiry.

    The listing of links is open because it stands in for the inbox, and the
    inbox is not the account (§54, *The export page*).

    `expire` is offered only by a site that can show what a lapsed session looks
    like. It is a witness route rather than a site one for the same reason the
    ledger is: it is the operator reaching past the site, and nothing the tool
    drives can reach it.
    """

    @app.get(LEDGER_PATH)
    def ledger_block() -> Response:
        return PlainTextResponse(ledger.block())

    @app.get(LEDGER_JSON_PATH)
    def ledger_json() -> dict[str, int]:
        return ledger.counters()

    @app.get(EXPORTS_PATH)
    def exports_text() -> Response:
        """Return the links minted so far, one per line, oldest first. Nothing when none."""
        return PlainTextResponse("".join(f"{link_of(export)}\n" for export in exports.all()))

    @app.get(EXPORTS_JSON_PATH)
    def exports_json() -> list[dict[str, Any]]:
        return [export_json(export, link_of(export)) for export in exports.all()]

    if expire is None:
        return

    @app.post(EXPIRE_PATH)
    def expire_sessions() -> dict[str, int]:
        """Throw every session away and say how many there were.

        What the browser holds is unchanged — it still carries the cookie — so the
        next page it asks for is a request with a token the site no longer knows,
        which is exactly the shape of a sign-in that lapsed while a run was
        under way.
        """
        return {"expired": expire()}


# -- serving it --------------------------------------------------------------- #


class MockServer:
    """The server, running on its own thread until it is closed."""

    def __init__(self, app: FastAPI, sock: socket.socket) -> None:
        self.app = app
        self._socket = sock
        self._server = uvicorn.Server(
            uvicorn.Config(
                app,
                # Quiet: a rehearsal's terminal belongs to the tool. No access
                # log and no logging configuration of uvicorn's own, so nothing
                # below a warning is printed and a warning still is.
                log_config=None,
                log_level="warning",
                access_log=False,
                lifespan="off",
            )
        )
        self._failure: BaseException | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        """Run the thread's body.

        Uvicorn, and whatever stopped it, kept for `start` to report rather than printed
        by the thread on its way out.
        """
        try:
            self._server.run(sockets=[self._socket])
        except BaseException as failure:  # ruff: ignore[blind-except] — whatever stopped it is the report
            self._failure = failure

    @property
    def port(self) -> int:
        return int(self._socket.getsockname()[1])

    @property
    def host(self) -> str:
        return str(self._socket.getsockname()[0])

    def start(self, timeout_s: float = STARTUP_TIMEOUT_S) -> None:
        """Start the thread and wait until uvicorn is accepting connections.

        A start that fails closes what it opened: the port is released rather than held
        by a thread nobody will join.
        """
        self._thread.start()
        try:
            self._await_started(time.monotonic() + timeout_s)
        except BaseException:
            self.close()
            raise

    def _await_started(self, deadline: float) -> None:
        """Block until uvicorn reports itself started, or say why it never will."""
        while not self._server.started:
            if not self._thread.is_alive():
                raise RuntimeError("the mock's server stopped before it started") from self._failure
            if time.monotonic() > deadline:
                raise RuntimeError("the mock's server did not start in time")
            time.sleep(0.005)

    def close(self) -> None:
        """Stop accepting, finish what is in flight, and release the port."""
        self._server.should_exit = True
        if self._thread.is_alive():
            self._thread.join()
        self._socket.close()


def listen(host: str, port: int) -> socket.socket:
    """Return a bound socket, before the server exists.

    Binding here rather than in uvicorn is what makes `port=0` answerable — the tests
    ask for any free port and need to know which one they got — and what makes a port
    already in use an error in the caller's thread rather than in the server's.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError:
        sock.close()
        raise
    return sock


def serve(
    build: Callable[[str, int], FastAPI],
    *,
    port: int,
    host: str = "127.0.0.1",
) -> MockServer:
    """Return a started server, listening. The caller closes it.

    `build` is told the address and port the socket really got — `0` asks for
    any port — so that a site whose links point at its own address can spell
    them for this process and no other.
    """
    sock = listen(host, port)
    try:
        bound_host, bound_port = sock.getsockname()[:2]
        server = MockServer(build(str(bound_host), int(bound_port)), sock)
    except BaseException:
        sock.close()
        raise
    server.start()
    return server
