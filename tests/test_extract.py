"""The fetch, the filing and the open ask (`30`).

The fetch is tested through an injected opener rather than through a server: a
`BytesIO` is a body, an `HTTPError` is an expired link, and a `URLError` is no
network, which is every branch the real `urlopen` has and none of its cost. One
`slow` test at the end drives the real `urlopen` against a local server, because
the streaming path — a socket timeout, a body read in chunks — is the one thing
a fake body cannot prove.

The rule this module exists to keep is §32's: the link is never written down.
Every test that produces output checks the link is not in it, and the last one
checks the run log too.
"""

import dataclasses
import io
import json
import types
import urllib.error
import zipfile
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread
from types import MappingProxyType
from typing import Any

import pytest
from orval import pretty_bytes
from typer.testing import CliRunner

from dataporter import cli, extract, log, sources, store
from dataporter.config import Settings, load_settings, with_account, with_store_dir
from dataporter.console import Collected
from dataporter.errors import FetchError, NetworkError, StoreError, UsageError
from dataporter.exit_codes import ExitCode
from dataporter.sources.claude import CLAUDE

LINK = "https://downloads.example.com/export.zip?signature=secret-token"
MOMENT = datetime(2026, 9, 12, 20, 51, 7, tzinfo=UTC)
STAMP = "2026-09-12T20-51-07Z"


BROWSERLESS = dataclasses.replace(CLAUDE, fetch_needs_session=False, link_serves_manifest=False)
"""Claude in every respect but the two this file's fetch tests need.

What they are about is the fetch's own mechanics — the size cap, the zip that is
not an export, the ask's lifecycle, the link's absence from every record — and
they drive it through the browserless path because that is the one without a
browser in it. Claude's own fetch goes through the source session since a real
link answered `HTTP 403` to a plain request, and its link serves a manifest
rather than the archive; brief 03 §35's other shape is still a shape, still
built, and still what Gemini may turn out to need.
"""


@pytest.fixture(autouse=True)
def _browserless(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve every source in this module to `BROWSERLESS`. See its docstring.

    Autouse and module-wide rather than named on eleven tests: the object differs
    from `CLAUDE` in one boolean, so a test that is not about the fetch cannot
    tell it apart.

    The registry and not `of`, because `of` is not the only way a source is
    reached: `--from` gets one out of `recognised`, and `extract` compares the
    two with `is`. Patching one of them makes an archive look like a Claude
    export and not a Claude one.
    """
    monkeypatch.setattr(
        sources,
        "REGISTRY",
        MappingProxyType({**sources.REGISTRY, CLAUDE.name: BROWSERLESS}),
    )


@pytest.fixture
def settings(tmp_path: Path, workspace: Path) -> Settings:
    """One invocation, pointed at a store and an accounts tree under `tmp_path`."""
    loaded = with_store_dir(load_settings(), tmp_path / "store")
    return with_account(
        loaded.model_copy(update={"accounts": loaded.accounts.model_copy(update={"dir": tmp_path / "accounts"})}),
        "claude",
        "old-personal",
    )


def opener(body: bytes) -> Callable[..., Any]:
    """Return an opener that answers with `body` and records what it was asked for."""

    def open_url(link: str, timeout: float | None = None) -> io.BytesIO:
        open_url.asked.append((link, timeout))  # type: ignore[attr-defined]
        return io.BytesIO(body)

    open_url.asked = []  # type: ignore[attr-defined]
    return open_url


def refusing(exc: Exception) -> Callable[..., Any]:
    def open_url(link: str, timeout: float | None = None) -> io.BytesIO:
        raise exc

    return open_url


def never_called() -> Callable[..., Any]:
    def open_url(link: str, timeout: float | None = None) -> io.BytesIO:
        raise AssertionError("the opener was called")

    return open_url


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(LINK, code, "Forbidden", {}, None)  # type: ignore[arg-type]


def open_ask(settings: Settings, asked_at: datetime = MOMENT) -> store.Ask:
    return extract.write_ask(settings, asked_at)


def filed(settings: Settings, stamp: str) -> Path:
    return settings.store_dir / settings.source / str(settings.account) / stamp


def temp_files(settings: Settings) -> list[Path]:
    home = settings.accounts_dir / settings.source / str(settings.account)
    return sorted((home / extract.TMP_DIRNAME).glob("*"))


# --------------------------------------------------------------------------- #
# The fetch
# --------------------------------------------------------------------------- #


def test_a_body_is_filed_as_a_snapshot(settings: Settings, export_zip: Path) -> None:
    sink = Collected()
    open_url = opener(export_zip.read_bytes())
    outcome = extract.fetch(settings, LINK, open_url=open_url, sink=sink)

    assert outcome.exit_code == ExitCode.OK
    assert outcome.snapshot is not None
    directory = outcome.path
    assert directory is not None
    # §39's question 2: the archive the tool files is the one it was sent.
    assert (directory / store.ARCHIVE_NAME).read_bytes() == export_zip.read_bytes()
    assert outcome.snapshot.origin == "link"
    assert outcome.snapshot.counts.conversations == 6
    assert open_url.asked[0][1] == settings.timeouts.download_idle_s  # type: ignore[attr-defined]
    assert LINK not in sink.stdout + sink.stderr


def test_the_block_is_the_brief_block(settings: Settings, export_zip: Path) -> None:
    """§31's block, and `60`'s line before it: the archive as it lands, under the store's name.

    The clock is injected, as the opener is, so the block's bytes can be pinned:
    66.4 seconds is `1m 6s`, whole seconds and nothing finer.
    """
    sink = Collected()
    outcome = extract.fetch(
        settings, LINK, open_url=opener(export_zip.read_bytes()), sink=sink, clock=iter((0.0, 66.4)).__next__
    )
    assert outcome.snapshot is not None
    size = f"{export_zip.stat().st_size / 1_000_000:.1f}"

    assert sink.stdout == (
        f"downloaded  export.zip  {pretty_bytes(export_zip.stat().st_size, 'ds', precision=1)}\n"
        "Claude extraction — old-personal\n"
        "\n"
        f"Downloaded {size} MB in 1m 6s.\n"
        "Filed without an ask on record.\n"
        "Conversations: 6     Projects: 0     Memories: 1\n"
        "Gaps: 3 files the export does not carry\n"
        "\n"
        f"Snapshot: {outcome.path}\n"
    )


def test_quiet_drops_the_lines_and_keeps_the_block(settings: Settings, export_zip: Path) -> None:
    """`-q` is for progress (`18`): the `downloaded` line goes, the block stays (`60`)."""
    sink = Collected()
    extract.fetch(settings, LINK, open_url=opener(export_zip.read_bytes()), sink=sink, quiet=True)

    assert sink.stdout.startswith("Claude extraction — old-personal\n")
    assert "downloaded" not in sink.stdout


def test_an_open_ask_sets_the_stamp_and_is_gone_afterwards(settings: Settings, export_zip: Path) -> None:
    open_ask(settings)
    sink = Collected()
    outcome = extract.fetch(settings, LINK, open_url=opener(export_zip.read_bytes()), sink=sink)

    assert outcome.snapshot is not None
    assert outcome.snapshot.stamp == STAMP
    assert outcome.snapshot.origin == "ask"
    assert outcome.snapshot.asked_at == MOMENT
    assert not extract.ask_path(settings).exists()
    assert extract.NO_ASK_ON_RECORD not in sink.stdout


def test_no_ask_says_so(settings: Settings, export_zip: Path) -> None:
    sink = Collected()
    extract.fetch(settings, LINK, open_url=opener(export_zip.read_bytes()), sink=sink)

    assert extract.NO_ASK_ON_RECORD in sink.stdout


def test_a_link_that_is_not_https_is_refused_before_any_request(
    settings: Settings,
) -> None:
    with pytest.raises(FetchError) as raised:
        extract.fetch(settings, "http://downloads.example.com/e.zip", open_url=never_called())

    assert str(raised.value) == extract.LINK_NOT_HTTPS


def test_a_refused_link_says_how_to_ask_again(settings: Settings, export_zip: Path) -> None:
    open_ask(settings)

    with pytest.raises(FetchError) as raised:
        extract.fetch(settings, LINK, open_url=refusing(http_error(403)))

    assert str(raised.value) == (
        "link refused: HTTP 403 — the link may have expired; ask again with: "
        "dataporter extract --source claude --account old-personal"
    )
    # §31: the ask stays open, so the person can try again with a new link.
    assert extract.ask_path(settings).exists()
    assert not settings.store_dir.exists()
    assert LINK not in str(raised.value)


def test_no_network_is_the_environment(settings: Settings) -> None:
    with pytest.raises(NetworkError) as raised:
        extract.fetch(settings, LINK, open_url=refusing(urllib.error.URLError("no route")))

    assert "no route" in (raised.value.detail or "")
    assert LINK not in (raised.value.detail or "")
    assert not settings.store_dir.exists()


def test_a_body_over_the_cap_is_refused_and_leaves_no_temp_file(settings: Settings, export_zip: Path) -> None:
    capped = settings.model_copy(update={"store": settings.store.model_copy(update={"max_download_bytes": 8})})

    with pytest.raises(FetchError) as raised:
        extract.fetch(capped, LINK, open_url=opener(export_zip.read_bytes()))

    assert "max_download_bytes" in str(raised.value)
    assert temp_files(capped) == []
    assert not capped.store_dir.exists()


def test_a_body_that_is_not_a_zip_is_refused(settings: Settings) -> None:
    with pytest.raises(FetchError) as raised:
        extract.fetch(settings, LINK, open_url=opener(b"not an archive at all"))

    assert str(raised.value) == extract.NOT_A_ZIP
    assert temp_files(settings) == []


def test_a_zip_without_conversations_is_not_an_export(settings: Settings, tmp_path: Path) -> None:
    other = tmp_path / "other.zip"
    with zipfile.ZipFile(other, "w") as archive:
        archive.writestr("readme.txt", "nothing to see")

    with pytest.raises(FetchError) as raised:
        extract.fetch(settings, LINK, open_url=opener(other.read_bytes()))

    # Named as "the download", never as the uuid temp file it landed in.
    assert str(raised.value) == (f"conversations.json missing from export: {extract.DOWNLOAD_DISPLAY}")
    assert temp_files(settings) == []


def test_a_second_fetch_under_the_same_ask_is_refused(settings: Settings, export_zip: Path) -> None:
    """The stamp is the ask's, so the second one lands on the first's directory."""
    open_ask(settings)
    extract.fetch(settings, LINK, open_url=opener(export_zip.read_bytes()))
    open_ask(settings)

    with pytest.raises(StoreError) as raised:
        extract.fetch(settings, LINK, open_url=opener(export_zip.read_bytes()))

    assert str(raised.value) == f"snapshot already exists: {filed(settings, STAMP)}"


# --------------------------------------------------------------------------- #
# An archive a person already has
# --------------------------------------------------------------------------- #


def test_from_files_an_archive(settings: Settings, export_zip: Path) -> None:
    sink = Collected()
    outcome = extract.file(settings, export_zip, sink=sink)

    assert outcome.snapshot is not None
    assert outcome.snapshot.origin == "file"
    assert outcome.snapshot.asked_at is None
    assert sink.stdout.splitlines()[2] == f"Filed {export_zip.name}."
    assert extract.NO_ASK_ON_RECORD not in sink.stdout


def test_from_refuses_a_directory(settings: Settings, export_dir: Path) -> None:
    with pytest.raises(FetchError) as raised:
        extract.file(settings, export_dir)

    assert str(raised.value) == extract.NOT_AN_ARCHIVE


def test_from_refuses_something_that_is_not_a_zip(settings: Settings, tmp_path: Path) -> None:
    loose = tmp_path / "notes.txt"
    loose.write_text("hello")

    with pytest.raises(FetchError) as raised:
        extract.file(settings, loose)

    assert str(raised.value) == extract.NOT_A_ZIP_FILE.format(path=loose)


def test_from_refuses_a_path_that_is_not_there(settings: Settings, tmp_path: Path) -> None:
    with pytest.raises(FetchError) as raised:
        extract.file(settings, tmp_path / "nowhere.zip")

    assert "no such file" in str(raised.value)


# --------------------------------------------------------------------------- #
# The open ask
# --------------------------------------------------------------------------- #


def test_a_second_ask_while_one_is_open_is_refused(settings: Settings) -> None:
    open_ask(settings)

    with pytest.raises(StoreError) as raised:
        open_ask(settings, MOMENT + timedelta(hours=1))

    assert "--abandon" in str(raised.value)


def test_the_ask_is_not_in_the_store(settings: Settings) -> None:
    open_ask(settings)

    assert extract.ask_path(settings).exists()
    assert not settings.store_dir.exists()


def test_abandon_removes_it(settings: Settings) -> None:
    open_ask(settings)
    sink = Collected()
    outcome = extract.abandon(settings, sink=sink)

    assert outcome.exit_code == ExitCode.OK
    assert not extract.ask_path(settings).exists()
    assert sink.stdout == "Abandoned the open ask for claude/old-personal.\n"


def test_abandon_with_no_ask_is_exit_2(settings: Settings) -> None:
    with pytest.raises(StoreError) as raised:
        extract.abandon(settings)

    assert str(raised.value) == "no ask is open for claude/old-personal"


def test_an_unreadable_ask_stops_the_fetch(settings: Settings, export_zip: Path) -> None:
    """Reading it as "no ask" would stamp the snapshot with the wrong moment."""
    open_ask(settings)
    extract.ask_path(settings).write_text("{not json")

    with pytest.raises(StoreError) as raised:
        extract.fetch(settings, LINK, open_url=opener(export_zip.read_bytes()))

    assert "invalid ask.json" in str(raised.value)


# --------------------------------------------------------------------------- #
# The command
# --------------------------------------------------------------------------- #


def test_the_two_flag_combinations_are_refused(settings: Settings, export_zip: Path) -> None:
    with pytest.raises(UsageError) as both:
        extract.extract_command(settings, extract.ExtractRequest(link=LINK, from_path=export_zip))
    assert str(both.value) == extract.LINK_AND_FILE

    with pytest.raises(UsageError) as abandoning:
        extract.extract_command(settings, extract.ExtractRequest(link=LINK, abandon=True))
    assert str(abandoning.value) == extract.ABANDON_ALONE


def test_no_mode_flag_is_the_ask(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """Which mode the flags name is this module's.

    What the ask then does is `31`'s, and `test_ask.py` is where it has a browser to do
    it with.
    """
    asked: list[str] = []

    def record(settings: Settings, *, sink: Collected, flags: tuple[str, ...] = ()) -> extract.ExtractOutcome:
        asked.append(settings.account or "")
        return extract.ExtractOutcome()

    monkeypatch.setattr(extract, "ask", record)
    outcome = extract.extract_command(settings, extract.ExtractRequest())

    assert asked == ["old-personal"]
    assert outcome.exit_code == ExitCode.OK


def test_an_invocation_with_no_account_is_refused(workspace: Path) -> None:
    with pytest.raises(UsageError) as raised:
        extract.extract_command(load_settings(), extract.ExtractRequest(abandon=True))

    assert str(raised.value) == extract.ACCOUNT_REQUIRED


# --------------------------------------------------------------------------- #
# Nothing writes the link down
# --------------------------------------------------------------------------- #


def test_the_link_is_in_no_log_record(settings: Settings, export_zip: Path) -> None:
    log.configure_logging()  # the root callback always runs first; it sets the level
    sink = Collected()
    extract.fetch(settings, LINK, open_url=opener(export_zip.read_bytes()), sink=sink)

    logs = list((settings.logs_dir / "logs").glob("run-*.jsonl"))
    assert logs, "the fetch writes a run log under the account home"
    written = "\n".join(path.read_text() for path in logs)
    assert LINK not in written
    assert "secret-token" not in written
    records = [json.loads(line) for line in written.splitlines()]
    assert {"download complete", "snapshot filed"} <= {record["event"] for record in records}


# --------------------------------------------------------------------------- #
# The streaming path, against a real server
# --------------------------------------------------------------------------- #


@pytest.fixture
def served(export_zip: Path) -> Iterator[str]:
    """Yield the fixture archive on a local HTTP server, and its URL."""

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self) -> None:
            body = export_zip.read_bytes()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/export.zip"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.slow
def test_the_real_opener_streams_a_served_archive(
    settings: Settings, served: str, export_zip: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one test that uses `urllib` itself: chunks, a socket timeout, a body.

    Served over plain HTTP, because a local server cannot present a certificate
    anybody trusts, so the one scheme the tool follows is relaxed for this call.
    What is being proved here is the streaming — a real socket, a body read in
    chunks, a timeout that is per read — and
    `test_a_link_that_is_not_https_is_refused_before_any_request` is what proves
    the rule this stands down.
    """
    monkeypatch.setattr(extract, "LINK_SCHEME", "http")
    outcome = extract.fetch(settings, served)

    assert outcome.path is not None
    assert (outcome.path / store.ARCHIVE_NAME).read_bytes() == export_zip.read_bytes()


# --------------------------------------------------------------------------- #
# The command, as an operator types it
# --------------------------------------------------------------------------- #


def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    monkeypatch.setenv("DATAPORTER_ACCOUNTS__DIR", str(tmp_path / "accounts"))
    return ["--store", str(tmp_path / "store")]


def test_a_source_the_tool_does_not_have_exits_2(runner: CliRunner, workspace: Path) -> None:
    result = runner.invoke(
        cli.app,
        ["extract", "--source", "gemini", "--account", "a"],
        catch_exceptions=False,
    )

    assert result.exit_code == ExitCode.USAGE
    assert result.stderr == "error: no such source: gemini\n"


def test_a_label_that_is_not_one_exits_2(runner: CliRunner, workspace: Path) -> None:
    result = runner.invoke(cli.app, ["extract", "--account", "Old Personal"], catch_exceptions=False)

    assert result.exit_code == ExitCode.USAGE
    assert result.stderr == (
        "error: account label must be letters, digits, dots, dashes or underscores: Old Personal\n"
    )


def test_a_missing_account_is_a_usage_error(runner: CliRunner, workspace: Path) -> None:
    result = runner.invoke(cli.app, ["extract"], catch_exceptions=False)

    assert result.exit_code == ExitCode.USAGE


def test_from_files_a_snapshot_through_the_cli(
    runner: CliRunner,
    workspace: Path,
    export_zip: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flags = cli_env(tmp_path, monkeypatch)
    result = runner.invoke(
        cli.app,
        ["extract", "--account", "a", *flags, "--from", str(export_zip)],
        catch_exceptions=False,
    )

    assert result.exit_code == ExitCode.OK
    filed_in = sorted((tmp_path / "store" / "claude" / "a").iterdir())
    assert len(filed_in) == 1
    assert sorted(item.name for item in filed_in[0].iterdir()) == sorted(store.SNAPSHOT_FILES)


def test_a_dead_link_exits_2_through_the_cli(
    runner: CliRunner,
    workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flags = cli_env(tmp_path, monkeypatch)
    monkeypatch.setattr(extract, "fetch", lambda *args, **kwargs: _raise(FetchError("link refused")))
    result = runner.invoke(
        cli.app,
        ["extract", "--account", "a", *flags, "--link", LINK],
        catch_exceptions=False,
    )

    assert result.exit_code == ExitCode.USAGE
    assert result.stderr == "error: link refused\n"


def test_no_network_exits_6_through_the_cli(
    runner: CliRunner,
    workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one clause `30` adds to the CLI.

    A `NetworkError` is the environment, not the operator's typing, and without it this
    would exit `70`.
    """
    flags = cli_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        extract,
        "fetch",
        lambda *args, **kwargs: _raise(NetworkError(detail="cannot reach the host")),
    )
    result = runner.invoke(
        cli.app,
        ["extract", "--account", "a", *flags, "--link", LINK],
        catch_exceptions=False,
    )

    assert result.exit_code == ExitCode.ENVIRONMENT
    assert result.stderr == "error: cannot reach the host\n"


def _raise(exc: Exception) -> None:
    raise exc


def test_an_export_with_no_file_references_has_no_gap(settings: Settings, tmp_path: Path) -> None:
    """No references, no gap: a snapshot with nothing missing says nothing."""
    plain = tmp_path / "plain.zip"
    with zipfile.ZipFile(plain, "w") as archive:
        archive.writestr(
            "conversations.json",
            json.dumps([
                {
                    "uuid": "c1",
                    "name": "A chat",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "chat_messages": [],
                }
            ]),
        )
    sink = Collected()
    outcome = extract.file(settings, plain, sink=sink)

    assert outcome.snapshot is not None
    assert outcome.snapshot.gaps == []
    assert "Gaps:" not in sink.stdout


def test_one_missing_file_is_not_one_files(settings: Settings, tmp_path: Path) -> None:
    """The reason is read as part of the block's sentence, so it has two spellings.

    (Raised by Copilot in review on #43.)
    """
    one = tmp_path / "one.zip"
    with zipfile.ZipFile(one, "w") as archive:
        archive.writestr(
            "conversations.json",
            json.dumps([
                {
                    "uuid": "c1",
                    "name": "A chat",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "chat_messages": [
                        {
                            "uuid": "m1",
                            "text": "here it is",
                            "sender": "human",
                            "created_at": "2026-01-01T00:00:00Z",
                            "files": [{"file_name": "notes.txt"}],
                        }
                    ],
                }
            ]),
        )
    sink = Collected()
    outcome = extract.file(settings, one, sink=sink)

    assert outcome.snapshot is not None
    assert outcome.snapshot.gap_count == 1
    assert "Gaps: 1 file the export does not carry\n" in sink.stdout


# --------------------------------------------------------------------------- #
# A link that serves an index
# --------------------------------------------------------------------------- #


def test_a_manifest_is_read_or_is_not_one(tmp_path: Path, export_zip: Path) -> None:
    """Claude's link serves a JSON index of the real files, not the archive."""
    good = tmp_path / "m.json"
    good.write_text(
        json.dumps({
            "instructions": "Download each file using the export_url.",
            "total_files": 1,
            "data_files": [
                {
                    "batch_index": 0,
                    "export_url": "https://claude.ai/export/x/download/y",
                    "category": "conversations",
                    "part": 0,
                    "filename": "conversations-000.zip",
                }
            ],
            "version": "1.0",
        })
    )
    manifest = extract.manifest_of(good)
    assert manifest is not None
    assert [item.filename for item in manifest.data_files] == ["conversations-000.zip"]
    assert manifest.data_files[0].category == "conversations"

    # An archive is not an index, and neither is the sign-in page a dead link
    # answers with — both are what this has to tell apart.
    assert extract.manifest_of(export_zip) is None
    page = tmp_path / "p.html"
    page.write_text("<!doctype html><title>Claude</title>")
    assert extract.manifest_of(page) is None


def test_the_archive_among_the_parts_is_the_one_the_source_owns(tmp_path: Path, export_zip: Path) -> None:
    """Claude splits its export by category, and one part carries the conversations.

    The others are the account's data too and are kept beside it, but an importer
    reads `conversations.json` and only one part has it.
    """
    metadata = tmp_path / "light_metadata-000.zip"
    with zipfile.ZipFile(metadata, "w") as archive:
        archive.writestr("users.json", "{}")
        archive.writestr("login_history.json", "[]")

    assert extract.archive_among([metadata, export_zip], CLAUDE) == export_zip

    with pytest.raises(FetchError) as raised:
        extract.archive_among([metadata], CLAUDE)
    assert str(raised.value) == "none of the 1 files the manifest names is a Claude export"


def _index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manifest: object) -> list[str]:
    """Fake `download.fetch` so the index walk can be read without a browser.

    Every body after the first is a zip, because what the walk does with them is
    rename them; which one is the archive is `archive_among`'s question.
    """
    asked: list[str] = []

    def fetched(settings: Settings, browser: object, link: str, *, into: Path, hosts: object) -> object:
        asked.append(link)
        target = into / f"guid-{len(asked)}.tmp"
        target.write_bytes(json.dumps(manifest).encode() if len(asked) == 1 else b"PK\x03\x04 not really a zip")
        return types.SimpleNamespace(path=target, bytes=target.stat().st_size)

    monkeypatch.setattr(extract.download, "fetch", fetched)
    return asked


MANIFEST = {
    "total_files": 2,
    "data_files": [
        {"export_url": "https://claude.ai/export/x/download/a", "filename": "light_metadata-000.zip", "part": 0},
        {"export_url": "https://claude.ai/export/x/download/b", "filename": "conversations-000.zip", "part": 0},
    ],
}


def test_the_index_is_kept_and_every_file_it_names_is_fetched(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One session, the index first, then each file it names, under its own name."""
    asked = _index(tmp_path, monkeypatch, MANIFEST)

    manifest_path, parts = extract.index_and_files(settings, None, CLAUDE, LINK, tmp_path, collected=[])

    assert asked == [LINK, *(item["export_url"] for item in MANIFEST["data_files"])]
    assert manifest_path.name == extract.MANIFEST_FILENAME
    # Named as the vendor named them: a snapshot holding `guid-2.tmp` describes nothing.
    assert [part.name for part in parts] == ["light_metadata-000.zip", "conversations-000.zip"]
    assert json.loads(manifest_path.read_text())["total_files"] == 2


def test_a_link_that_serves_neither_an_archive_nor_an_index_says_so(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _index(tmp_path, monkeypatch, "not a manifest at all")

    with pytest.raises(FetchError) as raised:
        extract.index_and_files(settings, None, CLAUDE, LINK, tmp_path, collected=[])

    assert str(raised.value) == extract.NOT_A_MANIFEST


def test_an_index_naming_nothing_is_refused(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty index is a fetch with nothing to fetch, and never an empty snapshot."""
    _index(tmp_path, monkeypatch, {"total_files": 0, "data_files": []})

    with pytest.raises(FetchError) as raised:
        extract.index_and_files(settings, None, CLAUDE, LINK, tmp_path, collected=[])

    assert str(raised.value) == extract.NO_FILES_IN_MANIFEST


def test_what_the_walk_downloaded_is_collected_before_it_is_judged(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An index naming nothing still leaves a file on disk, and the caller deletes it.

    `extra` is only known once the archive among the parts is, so a failure
    before that point had nothing to clean up by and left the download under the
    account home. (Raised by Copilot in review on #52.)
    """
    _index(tmp_path, monkeypatch, {"total_files": 0, "data_files": []})
    collected: list[Path] = []

    with pytest.raises(FetchError):
        extract.index_and_files(settings, None, CLAUDE, LINK, tmp_path, collected=collected)

    assert [item.name for item in collected] == [extract.MANIFEST_FILENAME]
    assert collected[0].exists()


# --------------------------------------------------------------------------- #
# The filing is named for the operator reading `-v`
# --------------------------------------------------------------------------- #


def _filed_paths(settings: Settings) -> list[str]:
    """Return the `path` of every `filed` record in the run log, oldest first."""
    return _events(settings, "filed")


def test_each_filed_file_is_named_under_verbose(settings: Settings) -> None:
    """One `filed` line per file — the archive, then each part — at its store path.

    The path is spelled as the store was configured, the same as §31's block, and
    the vendor's own part names appear (§66 keeps them out of the trace, not out
    of a snapshot that already records them). The recognised part is `export.zip`,
    the store's own name, not whatever the vendor called it.
    """
    log.configure_logging()
    log.enable_run_log(settings.logs_dir)
    snapshot = store.Snapshot(
        source="claude",
        account="old-personal",
        stamp=STAMP,
        origin="link",
        filed_at=MOMENT,
        tool_version="test",
        archive=store.Archive(name=store.ARCHIVE_NAME, bytes=1, sha256="a"),
        parts=[store.Archive(name="manifest.json"), store.Archive(name="light_metadata-000.zip")],
    )

    extract._log_filed(settings, snapshot)

    base = Path(settings.store_display) / "claude" / "old-personal" / STAMP
    assert _filed_paths(settings) == [
        str(base / store.ARCHIVE_NAME),
        str(base / "manifest.json"),
        str(base / "light_metadata-000.zip"),
    ]


def test_a_manifest_fetch_names_the_archive_and_every_part(
    settings: Settings, export_zip: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: the archive is `export.zip`, the manifest and the other part beside it.

    The browser is stubbed out at `_download_manifest_and_parts`, so the real
    `archive_among` and `store.file_archive` run and the `filed` lines name what
    was actually kept. `CLAUDE` itself, not this module's browserless stand-in,
    because the manifest branch is the thing under test.
    """
    monkeypatch.setattr(sources, "REGISTRY", MappingProxyType({**sources.REGISTRY, CLAUDE.name: CLAUDE}))

    def fake(
        settings: Settings,
        source: object,
        link: str,
        into: Path,
        *,
        sink: object,
        flags: object,
        collected: list[Path],
        quiet: bool,
    ) -> tuple[Path, list[Path]]:
        manifest = into / extract.MANIFEST_FILENAME
        manifest.write_text(json.dumps(MANIFEST))
        collected.append(manifest)
        metadata = into / "light_metadata-000.zip"
        with zipfile.ZipFile(metadata, "w") as archive:
            archive.writestr("users.json", "{}")
        collected.append(metadata)
        conversations = into / "conversations-000.zip"
        conversations.write_bytes(export_zip.read_bytes())
        collected.append(conversations)
        return manifest, [metadata, conversations]

    monkeypatch.setattr(extract, "_download_manifest_and_parts", fake)

    outcome = extract.fetch(settings, LINK, sink=Collected())

    assert outcome.path is not None
    base = Path(settings.store_display) / "claude" / "old-personal"
    stamp = outcome.path.name
    assert _filed_paths(settings) == [
        str(base / stamp / store.ARCHIVE_NAME),
        str(base / stamp / "manifest.json"),
        str(base / stamp / "light_metadata-000.zip"),
    ]
    written = "\n".join(path.read_text() for path in (settings.logs_dir / "logs").glob("run-*.jsonl"))
    assert LINK not in written
    assert "secret-token" not in written


def _events(settings: Settings, name: str) -> list[str]:
    """Return the `path` of every record of one event in the run log, oldest first."""
    logs = list((settings.logs_dir / "logs").glob("run-*.jsonl"))
    records = [json.loads(line) for path in logs for line in path.read_text().splitlines()]
    return [record["path"] for record in records if record["event"] == name]


def test_a_download_names_where_it_landed_as_it_lands(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each file says where it is the moment it is written, under its own name.

    The staging path, minutes before the filing: that is where an operator
    watching `-v` would go to look at what has arrived so far.
    """
    log.configure_logging()
    log.enable_run_log(settings.logs_dir)
    _index(tmp_path, monkeypatch, MANIFEST)

    extract.index_and_files(settings, None, CLAUDE, LINK, tmp_path, collected=[])

    assert _events(settings, "downloaded") == [
        str(tmp_path / extract.MANIFEST_FILENAME),
        str(tmp_path / "light_metadata-000.zip"),
        str(tmp_path / "conversations-000.zip"),
    ]


def test_each_download_is_a_line_as_it_lands(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One line on stdout per file, the moment it lands: the index, then each part (`60`).

    Named as the vendor named them, in `pretty_bytes`'s unit: a 21-byte part
    reads `21.0 B` here and `0.0 MB` in the block, whose unit is the brief's.
    """
    _index(tmp_path, monkeypatch, MANIFEST)
    sink = Collected()

    extract.index_and_files(settings, None, CLAUDE, LINK, tmp_path, collected=[], sink=sink)

    assert sink.stdout == (
        "downloaded  manifest.json  245.0 B\n"
        "downloaded  light_metadata-000.zip  21.0 B\n"
        "downloaded  conversations-000.zip  21.0 B\n"
    )


def test_a_body_names_where_it_landed(settings: Settings, export_zip: Path) -> None:
    """A source that serves one archive names its temp file too."""
    log.configure_logging()
    extract.fetch(settings, LINK, open_url=opener(export_zip.read_bytes()), sink=Collected())

    downloaded = _events(settings, "downloaded")
    assert len(downloaded) == 1
    assert downloaded[0].endswith(".zip")
    assert extract.TMP_DIRNAME in downloaded[0]


def test_a_vendor_name_cannot_forge_a_line_of_output(settings: Settings, tmp_path: Path) -> None:
    """The last component of a staging path is the vendor's, so it is bounded — twice.

    `HumanFormatter` prints an extra as it is given, so a manifest naming a file
    with a newline in it could otherwise add a line to what an operator reads
    under `-v`; and `60`'s stdout line prints the same name, so it is bounded
    there as well. (Raised by Copilot in review on #53.)
    """
    log.configure_logging()
    log.enable_run_log(settings.logs_dir)
    forged = tmp_path / "conversations\n19:39:41 info    all is well.zip"
    sink = Collected()

    extract._landed(forged, name=forged.name, size=21, sink=sink, quiet=False)

    written = _events(settings, "downloaded")
    assert len(written) == 1
    assert "\n" not in written[0]
    assert str(tmp_path) in written[0], "the directory is ours and stays whole"
    assert sink.stdout == "downloaded  conversations?19:39:41 info    all is well.zip  21.0 B\n"
