"""The fetch through the session (`45`): the browser downloads, the tool catches and files.

Every branch against `fake_chatgpt_pages.FakeChatgptPages`, which answers a link the way
the mock chatgpt.com does — an archive to a signed-in tab, a 403 to anyone else — and
pushes the events a browser sends for a download. Two live tests at the end drive a real
Chrome against a cookie-gated server, because `Browser.setDownloadBehavior` and its
events are the one thing a fake cannot prove.

The rule this module exists to keep is §66's: the link is in no line the fetch leaves —
not the trace, not the run log, not `actions.jsonl`, not the terminal.
"""

import json
import re
import tempfile
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest
from pydantic import SecretStr

from dataporter import extract, log, store
from dataporter import trace as tracing
from dataporter.browser import download, helpers, launcher
from dataporter.browser.cdp import CdpClient
from dataporter.browser.launcher import BrowserSession
from dataporter.config import (
    AccountsSettings,
    AuthSettings,
    BrowserSettings,
    HermesSettings,
    Settings,
    StoreSettings,
    TimeoutSettings,
    with_account,
)
from dataporter.console import Collected
from dataporter.errors import FetchError, UsageError
from dataporter.exit_codes import ExitCode
from fake_chatgpt_pages import LOGIN_BUTTON, ROOT, FakeChatgptPages, Step, browser
from fake_chrome import FakeChrome
from live_browser import live_browser, requires_a_browser, visit

pytestmark = pytest.mark.slow

ACCOUNT = "work"
EMAIL = "someone@example.test"
SECRET = "hunter2"
TOKEN = "t0ken9f3e2d1c0b"
LINK = f"https://chatgpt.com/__mock/exports/{TOKEN}.zip"


@pytest.fixture
def site(chatgpt_zip: Path) -> FakeChatgptPages:
    made = FakeChatgptPages(archive=chatgpt_zip.read_bytes())
    made.go(Step.HOME)
    return made


@pytest.fixture
def chrome(site: FakeChatgptPages) -> Iterator[FakeChrome]:
    with browser(site) as fake:
        yield fake


@pytest.fixture
def launches(monkeypatch: pytest.MonkeyPatch, chrome: FakeChrome) -> list[str]:
    urls: list[str] = []

    def fake_launch(settings: Settings, url: str) -> BrowserSession:
        urls.append(url)
        return BrowserSession(
            client=CdpClient(port=chrome.port, timeout=2.0),
            profile=settings.browser_profile_dir,
            adopted=True,
        )

    monkeypatch.setattr(launcher, "launch", fake_launch)
    return urls


def make_settings(chrome: FakeChrome, tmp_path: Path, *, credentials: bool = True, idle_s: float = 5.0) -> Settings:
    return with_account(
        Settings(
            workspace=tmp_path / "migration",
            non_interactive=True,
            auth=AuthSettings(email=EMAIL, password=SecretStr(SECRET)) if credentials else AuthSettings(),
            accounts=AccountsSettings(dir=tmp_path / "accounts"),
            store=StoreSettings(dir=tmp_path / "store", max_download_bytes=10_000),
            browser=BrowserSettings(cdp_port=chrome.port),
            hermes=HermesSettings(executable=tmp_path / "no-hermes-here", home=tmp_path / "hermes-home"),
            timeouts=TimeoutSettings(cdp_call_s=2.0, ask_s=0.3, login_s=0.5, signin_s=1.0, download_idle_s=idle_s),
        ),
        "chatgpt",
        ACCOUNT,
    )


@pytest.fixture
def settings(chrome: FakeChrome, tmp_path: Path) -> Settings:
    return make_settings(chrome, tmp_path)


def temp_files(settings: Settings) -> list[Path]:
    home = settings.accounts_dir / settings.source / str(settings.account)
    return sorted((home / extract.TMP_DIRNAME).glob("*"))


def everything_written(settings: Settings, sink: Collected) -> str:
    """Every byte the fetch left, for the one grep §66 is about."""
    home = settings.accounts_dir / settings.source / str(settings.account)
    texts = [sink.stdout, sink.stderr]
    texts.extend(path.read_text(encoding="utf-8") for path in sorted((home / "logs").glob("*.jsonl")))
    return "\n".join(texts)


def trace_lines(settings: Settings) -> list[dict[str, Any]]:
    files = sorted((Path(settings.logs_dir) / "logs").glob("trace-*.jsonl"))
    assert len(files) == 1, files
    return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #


def test_a_signed_in_tab_downloads_the_link_and_the_archive_is_filed(
    site: FakeChatgptPages, chrome: FakeChrome, settings: Settings, launches: list[str], chatgpt_zip: Path
) -> None:
    extract.write_ask(settings, datetime(2026, 9, 30, 18, 12, 44, tzinfo=UTC))
    sink = Collected()
    outcome = extract.fetch(settings, LINK, sink=sink)

    assert outcome.exit_code == ExitCode.OK
    assert outcome.snapshot is not None
    assert outcome.path is not None
    assert launches == [ROOT]
    assert sink.stdout == (
        f"ChatGPT extraction — {ACCOUNT}\n"
        "\n"
        "Downloaded 0.0 MB.\n"
        "Conversations: 3     Files: 2\n"
        "Gaps: 2 files the export does not carry\n"
        "\n"
        f"Snapshot: {settings.store_display}/chatgpt/{ACCOUNT}/2026-09-30T18-12-44Z\n"
    )
    assert (outcome.path / store.ARCHIVE_NAME).read_bytes() == chatgpt_zip.read_bytes()
    assert outcome.snapshot.origin == "ask"
    assert extract.read_ask(settings) is None
    assert temp_files(settings) == []
    assert site.links == [LINK]
    assert site.typed == {}
    methods = chrome.methods()
    assert methods.index("Browser.setDownloadBehavior") < methods.index("Page.navigate")
    assert "Input.insertText" not in methods


def test_unattended_and_signed_out_the_fetch_walks_in_first(
    site: FakeChatgptPages, settings: Settings, launches: list[str]
) -> None:
    site.go(Step.LANDING)
    outcome = extract.fetch(settings, LINK, sink=Collected())

    assert outcome.exit_code == ExitCode.OK
    assert site.clicks == [LOGIN_BUTTON]
    assert site.typed == {"email": EMAIL, "password": SECRET}
    assert site.links == [LINK]


def test_unattended_without_credentials_is_refused_before_any_browser(
    chrome: FakeChrome, tmp_path: Path, launches: list[str]
) -> None:
    with pytest.raises(UsageError, match="DATAPORTER_AUTH__EMAIL"):
        extract.fetch(make_settings(chrome, tmp_path, credentials=False), LINK, sink=Collected())
    assert launches == []


# --------------------------------------------------------------------------- #
# A link that did not become an archive
# --------------------------------------------------------------------------- #


def test_a_refused_link_is_the_same_line_as_the_browserless_fetch(
    site: FakeChatgptPages, settings: Settings, launches: list[str]
) -> None:
    site.link_answers = "refused"
    extract.write_ask(settings, datetime.now(UTC))
    with pytest.raises(FetchError) as raised:
        extract.fetch(settings, LINK, sink=Collected())

    assert str(raised.value) == (
        "link refused: HTTP 403 — the link may have expired; ask again with: "
        f"dataporter extract --source chatgpt --account {ACCOUNT}"
    )
    assert not (settings.store_dir / "chatgpt").exists()
    assert extract.read_ask(settings) is not None
    assert temp_files(settings) == []


def test_a_link_that_leads_to_a_page_names_the_sign_in(
    site: FakeChatgptPages, settings: Settings, launches: list[str]
) -> None:
    site.link_answers = "page"
    with pytest.raises(FetchError) as raised:
        extract.fetch(settings, LINK, sink=Collected())

    assert str(raised.value) == (
        "the link led to a page, not an archive (HTTP 200); sign in with: "
        f"dataporter login --source chatgpt --account {ACCOUNT}, then try again"
    )


def test_a_download_over_the_cap_is_cancelled(
    site: FakeChatgptPages, chrome: FakeChrome, settings: Settings, launches: list[str]
) -> None:
    site.link_answers = "huge"
    with pytest.raises(FetchError) as raised:
        extract.fetch(settings, LINK, sink=Collected())

    assert str(raised.value) == "the download is larger than store.max_download_bytes (10000 bytes)"
    assert "Browser.cancelDownload" in chrome.methods()
    assert temp_files(settings) == []


def test_a_stalled_download_is_refused_on_the_idle_budget(
    site: FakeChatgptPages, chrome: FakeChrome, tmp_path: Path, launches: list[str]
) -> None:
    site.link_answers = "stall"
    settings = make_settings(chrome, tmp_path, idle_s=0.3)
    started = time.monotonic()
    with pytest.raises(FetchError) as raised:
        extract.fetch(settings, LINK, sink=Collected())

    assert str(raised.value) == "the download stalled for 0.3s; try again"
    assert time.monotonic() - started < 3.0


# --------------------------------------------------------------------------- #
# §66: the link is in no line
# --------------------------------------------------------------------------- #


def test_the_link_is_in_no_line_the_fetch_leaves(
    site: FakeChatgptPages, settings: Settings, launches: list[str]
) -> None:
    log.configure_logging()
    sink = Collected()
    extract.fetch(settings, LINK, flags=("--link",), sink=sink)

    written = everything_written(settings, sink)
    assert TOKEN not in written
    assert "/__mock/exports" not in written
    lines = trace_lines(settings)
    assert lines[0]["source"] == "chatgpt"
    assert lines[0]["flags"] == ["--link"]
    navigations = [line for line in lines if line.get("what") == "navigation"]
    assert navigations == [
        {
            "kind": "observation",
            "ts": navigations[0]["ts"],
            "t_ms": navigations[0]["t_ms"],
            "what": "navigation",
            "host": "chatgpt.com",
            "path": "<link>",
            "query": [],
        }
    ]
    moves = [line for line in lines if line["kind"] == "move"]
    assert [move["helper"] for move in moves] == ["download"]
    assert moves[0]["result"] == {
        "host": "chatgpt.com",
        "path": "<link>",
        "query": [],
        "bytes": len(site.archive),
        "suffix": ".zip",
        "filename_chars": len("chatgpt-export.zip"),
    }
    actions = [
        json.loads(line) for line in helpers.actions_path(settings.logs_dir).read_text(encoding="utf-8").splitlines()
    ]
    assert [action["helper"] for action in actions] == ["download"]
    assert "url" not in actions[0]
    assert lines[-1]["what"] == "end"
    assert lines[-1]["exit"] == 0
    assert not tracing.is_redacting()


def test_the_link_is_in_no_line_when_it_was_refused_either(
    site: FakeChatgptPages, settings: Settings, launches: list[str]
) -> None:
    site.link_answers = "refused"
    sink = Collected()
    with pytest.raises(FetchError):
        extract.fetch(settings, LINK, sink=sink)

    assert TOKEN not in everything_written(settings, sink)
    moves = [line for line in trace_lines(settings) if line["kind"] == "move"]
    assert [(move["helper"], move["ok"], move["result"]["reason"]) for move in moves] == [
        ("download", False, "refused")
    ]
    assert not tracing.is_redacting()


# --------------------------------------------------------------------------- #
# The live tier: a real Chrome, a real download
# --------------------------------------------------------------------------- #

COOKIE = "mock_session=1"


class _Gate(BaseHTTPRequestHandler):
    """A page that sets a cookie, and an archive served only to a request that carries it."""

    archive: bytes = b""

    def do_GET(self) -> None:
        if self.path == "/gate":
            body = b"<!doctype html><title>signed in</title><p>gate</p>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Set-Cookie", f"{COOKIE}; Path=/")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/__mock/exports/"):
            if COOKIE not in self.headers.get("Cookie", ""):
                self.send_error(403, "Sign in first.")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="chatgpt-export.zip"')
            self.send_header("Content-Length", str(len(self.archive)))
            self.end_headers()
            self.wfile.write(self.archive)
            return
        self.send_error(404)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def gated(chatgpt_zip: Path) -> Iterator[str]:
    handler = type("_BoundGate", (_Gate,), {"archive": chatgpt_zip.read_bytes()})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


@requires_a_browser
def test_live_a_signed_in_tab_downloads_and_a_signed_out_one_is_refused(gated: str, chatgpt_zip: Path) -> None:
    """`Browser.setDownloadBehavior` and its events, on a real Chrome: the one thing the fake cannot prove."""
    with live_browser() as (session, _server), tempfile.TemporaryDirectory() as directory:
        settings = Settings(workspace=Path(directory) / "migration", timeouts=TimeoutSettings(download_idle_s=20.0))
        into = Path(directory) / "tmp"
        visit(session, f"{gated}/gate")
        got = download.fetch(settings, session, f"{gated}/__mock/exports/t.zip", into=into, hosts=("127.0.0.1",))
        assert got.path.read_bytes() == chatgpt_zip.read_bytes()
        assert got.bytes == len(chatgpt_zip.read_bytes())
        assert (got.suffix, got.filename_chars) == (".zip", len("chatgpt-export.zip"))
        assert re.fullmatch(r"[0-9a-f-]{36}", got.path.name)

        page = session.client.attach(session.client.pages()[0].id)
        try:
            page.send("Network.clearBrowserCookies")
        finally:
            page.close()
        with pytest.raises(download.DownloadStopped) as raised:
            download.fetch(settings, session, f"{gated}/__mock/exports/t.zip", into=into, hosts=("127.0.0.1",))
        assert (raised.value.reason, raised.value.status) == (download.REFUSED, 403)

        with pytest.raises(download.DownloadStopped) as raised:
            download.fetch(settings, session, f"{gated}/gate", into=into, hosts=("127.0.0.1",))
        assert raised.value.reason == download.PAGE
