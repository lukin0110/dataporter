"""Driving a real browser from the test suite.

`07` and `08` are both tested twice: once against `FakeChrome`, which answers
whatever a test says and covers every line on a machine with no browser, and
once against a real Chrome rendering the checked-in page fixtures, which is the
only way to know the selectors match and that a 45 kB seed survives a composer.

The second half is what lives here — finding a browser, launching it headless
over a fixture server, and the marker that skips when there is none — so that
both test modules ask for it the same way.
"""

import os
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from dataporter.browser import launcher
from dataporter.config import BrowserSettings, Settings, TimeoutSettings
from dataporter.errors import BrowserError
from fake_chrome import free_port
from fake_pages import PageServer

BROWSER_ENV_VAR = "DATAPORTER_TEST_BROWSER"

HEADLESS_ARGS = (
    "--headless=new",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
)
"""A CI runner has no display and may have no user namespaces. The migration
itself is headed (§12); this is the test suite's own escape hatch."""


def real_browser() -> Path | None:
    """A browser to drive, or `None`. Never raises: absence is a skip."""
    override = os.environ.get(BROWSER_ENV_VAR, "").strip()
    if override:
        found = shutil.which(override)
        return Path(found) if found else None
    try:
        return launcher.find_executable()
    except BrowserError:
        return None


_MARKS = (
    pytest.mark.skipif(
        real_browser() is None,
        reason=f"no browser installed (set {BROWSER_ENV_VAR} to point at one)",
    ),
    pytest.mark.live,
    pytest.mark.slow,
)
"""The three marks a live test carries, because they answer three questions.

`skipif` is the old one: there may be no browser to drive. `slow` is what keeps
these off a pull request — they launch a real Chrome, they are the most expensive
tests that exist, and on `ubuntu-latest`, which ships Google Chrome, they had
been running on every PR without anybody having decided that. `live` is narrower
than `slow` and exists so a later change can put *these* on a nightly schedule
without re-marking anything: every `live` test is `slow`, and most `slow` tests
are not `live`.
"""


def requires_a_browser[F: Callable[..., Any]](test: F) -> F:
    """Apply all three, one at a time.

    A function rather than `pytest.mark.slow(pytest.mark.live(...))`, which looks
    like it composes and does not: a `MarkDecorator` is itself callable, so the
    outer mark takes the inner one as an *argument* and only `slow` ends up on
    the test. `pytest --collect-only -m live` collecting nothing is what that
    mistake looks like, and `tests/test_suite_shape.py` is what keeps it caught.
    """
    for mark in _MARKS:
        test = mark(test)
    return test


@contextmanager
def live_browser() -> Iterator[tuple[launcher.BrowserSession, PageServer]]:
    """A real browser and the fixture server it is pointed at.

    Expensive — a process and a profile directory — so the fixtures that use it
    are module-scoped.
    """
    executable = real_browser()
    if executable is None:  # pragma: no cover - the marker skips first
        pytest.skip("no browser installed")
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(
            workspace=Path(directory) / "migration",
            browser=BrowserSettings(
                executable=executable, cdp_port=free_port(), extra_args=HEADLESS_ARGS
            ),
            timeouts=TimeoutSettings(browser_start_s=60.0, cdp_call_s=30.0),
        )
        with PageServer() as server:
            session = launcher.launch(settings, server.url("/new"))
            try:
                yield session, server
            finally:
                session.close()


def visit(session: launcher.BrowserSession, url: str) -> None:
    """Leave the browser with exactly one tab, on `url`, finished loading.

    Exactly one, because that is the state the helpers are specified against:
    a second tab is `ambiguous_tab`, which is a different test.
    """
    tabs = session.client.pages()
    for extra in tabs[1:]:
        session.client.close_target(extra.id)
    page = session.client.attach(tabs[0].id)
    try:
        page.navigate(url)
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if (
                page.evaluate("document.readyState") == "complete"
                and page.evaluate("location.href") == url
            ):
                return
            time.sleep(0.05)
        raise AssertionError(f"{url} never finished loading")  # pragma: no cover
    finally:
        page.close()
