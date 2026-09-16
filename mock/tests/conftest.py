"""A mock on a port of its own, for the tests that need the wire.

A site itself is tested without one — its `site.py` holds the behaviour and knows
nothing about HTTP — so these fixtures exist for the half that is about cookies,
status codes and redirects. One set per site,
because each mock keeps its own (§54).
"""

import json
import urllib.request
from collections.abc import Iterator
from typing import Any
from urllib.error import HTTPError

import pytest
from chatgptmock import server as chatgpt_server
from chatgptmock.site import Site as ChatGPTSite
from claudemock import server as claude_server
from claudemock.site import Site as ClaudeSite
from mockcore import wire

EMAIL = "rehearsal@example.invalid"
PASSWORD = "rehearsal-not-a-real-password"

WALL = 1_757_764_800.0
"""2025-09-13T12:00:00Z, the wall clock every test site reads."""


class Client:
    """A browser's worth of behaviour: a cookie jar, and where the mock bound.

    `urllib`'s own redirect handling is left on for GET and turned off here for
    POST, because what a test wants to assert about a sign-in step is the
    `Location` it was sent to.
    """

    def __init__(self, base: str) -> None:
        self.base = base
        self.cookies: dict[str, str] = {}

    def request(
        self,
        path: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        follow: bool = True,
    ) -> tuple[int, str, str]:
        """Status, body and the `Location` header, cookies remembered."""
        request = urllib.request.Request(self.base + path, data=data)
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        if self.cookies:
            request.add_header("Cookie", self._cookie_header())
        handlers: list[urllib.request.BaseHandler] = []
        if not follow:
            handlers.append(NoRedirect())
        opener = urllib.request.build_opener(*handlers)
        try:
            with opener.open(request, timeout=10) as answer:
                body = answer.read().decode("utf-8")
                self._remember(answer.headers.get_all("Set-Cookie") or [])
                return answer.status, body, answer.headers.get("Location", "")
        except HTTPError as failure:
            self._remember(failure.headers.get_all("Set-Cookie") or [])
            return (
                failure.code,
                failure.read().decode("utf-8"),
                failure.headers.get("Location", ""),
            )

    def get_bytes(self, path: str, *, cookies: bool = False) -> tuple[int, bytes]:
        """Status and the raw body: what a download is, and what `request` decodes away.

        Without cookies by default, as the tool's fetch is; with them when a test
        is the browser fetching a link that wants its session.
        """
        request = urllib.request.Request(self.base + path)
        if cookies and self.cookies:
            request.add_header("Cookie", self._cookie_header())
        opener = urllib.request.build_opener()
        try:
            with opener.open(request, timeout=10) as answer:
                return answer.status, answer.read()
        except HTTPError as failure:
            return failure.code, failure.read()

    def post(self, path: str, body: bytes, **headers: str) -> tuple[int, str, str]:
        return self.request(path, data=body, headers=headers, follow=False)

    def post_json(self, path: str, payload: object) -> tuple[int, str, str]:
        """As the page's own script posts: JSON, and a header that says so."""
        return self.post(path, json.dumps(payload).encode(), **{"Content-Type": "application/json"})

    def _cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    def _remember(self, headers: list[str]) -> None:
        for header in headers:
            pair = header.split(";", 1)[0]
            name, _, value = pair.partition("=")
            self.cookies[name.strip()] = value.strip()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


# -- the mock claude.ai ------------------------------------------------------- #


@pytest.fixture
def site() -> ClaudeSite:
    # Fast on purpose: the delay is what a rehearsal configures down, and a test
    # that waited a second per reply would be a test nobody runs.
    # And a fixed wall clock, so an archive's timestamps are the same on every run.
    return ClaudeSite(email=EMAIL, reply_delay_s=0.05, reply_steps=2, wall=lambda: WALL)


@pytest.fixture
def running(site: ClaudeSite) -> Iterator[Client]:
    started = claude_server.serve(site, port=0)
    try:
        yield Client(wire.origin_of("127.0.0.1", started.port))
    finally:
        started.close()


# -- the mock chatgpt.com ----------------------------------------------------- #


@pytest.fixture
def chatgpt_site() -> ChatGPTSite:
    return ChatGPTSite(email=EMAIL, password=PASSWORD, reply_delay_s=0.05, reply_steps=2, wall=lambda: WALL)


@pytest.fixture
def chatgpt_running(chatgpt_site: ChatGPTSite) -> Iterator[Client]:
    started = chatgpt_server.serve(chatgpt_site, port=0)
    try:
        yield Client(wire.origin_of("127.0.0.1", started.port))
    finally:
        started.close()
