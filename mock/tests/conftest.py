"""A mock on a port of its own, for the tests that need the wire.

The site itself is tested without one — `site.py` holds the behaviour and knows
nothing about HTTP — so this fixture exists for the half that is about cookies,
status codes and redirects.
"""

import ssl
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import pytest
from claudemock import certificate, server
from claudemock.site import Site

EMAIL = "rehearsal@example.invalid"
PASSWORD = "rehearsal-not-a-real-password"


class Client:
    """A browser's worth of behaviour: a cookie jar and a certificate it trusts.

    `urllib`'s own redirect handling is left on for GET and turned off here for
    POST, because what a test wants to assert about a sign-in step is the
    `Location` it was sent to.
    """

    def __init__(self, base: str) -> None:
        self.base = base
        self.cookies: dict[str, str] = {}
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.context.check_hostname = False
        self.context.verify_mode = ssl.CERT_NONE

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
            request.add_header(
                "Cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            )
        handlers: list[urllib.request.BaseHandler] = [
            urllib.request.HTTPSHandler(context=self.context)
        ]
        if not follow:
            handlers.append(_NoRedirect())
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

    def post(self, path: str, body: bytes, **headers: str) -> tuple[int, str, str]:
        return self.request(path, data=body, headers=headers, follow=False)

    def _remember(self, headers: list[str]) -> None:
        for header in headers:
            pair = header.split(";", 1)[0]
            name, _, value = pair.partition("=")
            self.cookies[name.strip()] = value.strip()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


@pytest.fixture(scope="session")
def material(tmp_path_factory: pytest.TempPathFactory) -> certificate.Material:
    """One key pair for the whole session: minting is the slow part."""
    directory: Path = tmp_path_factory.mktemp("cert")
    return certificate.ensure(directory)


@pytest.fixture
def site() -> Site:
    # Fast on purpose: the delay is what a rehearsal configures down, and a test
    # that waited a second per reply would be a test nobody runs.
    return Site(email=EMAIL, password=PASSWORD, reply_delay_s=0.05, reply_steps=2)


@pytest.fixture
def running(site: Site, material: certificate.Material) -> Iterator[Client]:
    started = server.serve(site, port=0, material=material)
    try:
        yield Client(f"https://127.0.0.1:{server.port_of(started)}")
    finally:
        started.shutdown()
        started.server_close()
