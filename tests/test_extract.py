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

import io
import json
import urllib.error
import zipfile
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread
from typing import Any

import pytest
from typer.testing import CliRunner

from dataporter import cli, extract, log, store
from dataporter.config import Settings, load_settings, with_account, with_store_dir
from dataporter.console import Collected
from dataporter.errors import FetchError, NetworkError, StoreError, UsageError
from dataporter.exit_codes import ExitCode

LINK = "https://downloads.example.com/export.zip?signature=secret-token"
MOMENT = datetime(2026, 9, 12, 20, 51, 7, tzinfo=UTC)
STAMP = "2026-09-12T20-51-07Z"


@pytest.fixture
def settings(tmp_path: Path, workspace: Path) -> Settings:
    """One invocation, pointed at a store and an accounts tree under `tmp_path`."""
    loaded = with_store_dir(load_settings(), tmp_path / "store")
    return with_account(
        loaded.model_copy(
            update={
                "accounts": loaded.accounts.model_copy(
                    update={"dir": tmp_path / "accounts"}
                )
            }
        ),
        "claude",
        "old-personal",
    )


def opener(body: bytes) -> Callable[..., Any]:
    """An opener that answers with `body` and records what it was asked for."""

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
    sink = Collected()
    outcome = extract.fetch(
        settings, LINK, open_url=opener(export_zip.read_bytes()), sink=sink
    )
    assert outcome.snapshot is not None
    size = f"{export_zip.stat().st_size / 1_000_000:.1f}"

    assert sink.stdout == (
        "Claude extraction — old-personal\n"
        "\n"
        f"Downloaded {size} MB.\n"
        "Filed without an ask on record.\n"
        "Conversations: 6     Projects: 0     Memories: 1\n"
        "Gaps: 3 files the export does not carry\n"
        "\n"
        f"Snapshot: {outcome.path}\n"
    )


def test_an_open_ask_sets_the_stamp_and_is_gone_afterwards(
    settings: Settings, export_zip: Path
) -> None:
    open_ask(settings)
    sink = Collected()
    outcome = extract.fetch(
        settings, LINK, open_url=opener(export_zip.read_bytes()), sink=sink
    )

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
        extract.fetch(
            settings, "http://downloads.example.com/e.zip", open_url=never_called()
        )

    assert str(raised.value) == extract.LINK_NOT_HTTPS


def test_a_refused_link_says_how_to_ask_again(
    settings: Settings, export_zip: Path
) -> None:
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
        extract.fetch(
            settings, LINK, open_url=refusing(urllib.error.URLError("no route"))
        )

    assert "no route" in (raised.value.detail or "")
    assert LINK not in (raised.value.detail or "")
    assert not settings.store_dir.exists()


def test_a_body_over_the_cap_is_refused_and_leaves_no_temp_file(
    settings: Settings, export_zip: Path
) -> None:
    capped = settings.model_copy(
        update={"store": settings.store.model_copy(update={"max_download_bytes": 8})}
    )

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


def test_a_zip_without_conversations_is_not_an_export(
    settings: Settings, tmp_path: Path
) -> None:
    other = tmp_path / "other.zip"
    with zipfile.ZipFile(other, "w") as archive:
        archive.writestr("readme.txt", "nothing to see")

    with pytest.raises(FetchError) as raised:
        extract.fetch(settings, LINK, open_url=opener(other.read_bytes()))

    # Named as "the download", never as the uuid temp file it landed in.
    assert str(raised.value) == (
        f"conversations.json missing from export: {extract.DOWNLOAD_DISPLAY}"
    )
    assert temp_files(settings) == []


def test_a_second_fetch_under_the_same_ask_is_refused(
    settings: Settings, export_zip: Path
) -> None:
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


def test_from_refuses_something_that_is_not_a_zip(
    settings: Settings, tmp_path: Path
) -> None:
    loose = tmp_path / "notes.txt"
    loose.write_text("hello")

    with pytest.raises(FetchError) as raised:
        extract.file(settings, loose)

    assert str(raised.value) == extract.NOT_A_ZIP_FILE.format(path=loose)


def test_from_refuses_a_path_that_is_not_there(
    settings: Settings, tmp_path: Path
) -> None:
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


def test_an_unreadable_ask_stops_the_fetch(
    settings: Settings, export_zip: Path
) -> None:
    """Reading it as "no ask" would stamp the snapshot with the wrong moment."""
    open_ask(settings)
    extract.ask_path(settings).write_text("{not json")

    with pytest.raises(StoreError) as raised:
        extract.fetch(settings, LINK, open_url=opener(export_zip.read_bytes()))

    assert "invalid ask.json" in str(raised.value)


# --------------------------------------------------------------------------- #
# The command
# --------------------------------------------------------------------------- #


def test_the_two_flag_combinations_are_refused(
    settings: Settings, export_zip: Path
) -> None:
    with pytest.raises(UsageError) as both:
        extract.extract_command(
            settings, extract.ExtractRequest(link=LINK, from_path=export_zip)
        )
    assert str(both.value) == extract.LINK_AND_FILE

    with pytest.raises(UsageError) as abandoning:
        extract.extract_command(
            settings, extract.ExtractRequest(link=LINK, abandon=True)
        )
    assert str(abandoning.value) == extract.ABANDON_ALONE


def test_no_mode_flag_is_the_ask(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Which mode the flags name is this module's; what the ask then does is
    `31`'s, and `test_ask.py` is where it has a browser to do it with."""
    asked: list[str] = []

    def record(settings: Settings, *, sink: Collected) -> extract.ExtractOutcome:
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
    assert {"download complete", "snapshot filed"} <= {
        record["event"] for record in records
    }


# --------------------------------------------------------------------------- #
# The streaming path, against a real server
# --------------------------------------------------------------------------- #


@pytest.fixture
def served(export_zip: Path) -> Iterator[str]:
    """The fixture archive on a local HTTP server, and its URL."""

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server's spelling
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


def test_a_source_the_tool_does_not_have_exits_2(
    runner: CliRunner, workspace: Path
) -> None:
    result = runner.invoke(
        cli.app,
        ["extract", "--source", "chatgpt", "--account", "a"],
        catch_exceptions=False,
    )

    assert result.exit_code == ExitCode.USAGE
    assert result.stderr == "error: no such source: chatgpt\n"


def test_a_label_that_is_not_one_exits_2(runner: CliRunner, workspace: Path) -> None:
    result = runner.invoke(
        cli.app, ["extract", "--account", "Old Personal"], catch_exceptions=False
    )

    assert result.exit_code == ExitCode.USAGE
    assert result.stderr == (
        "error: account label must be letters, digits, dots, dashes or "
        "underscores: Old Personal\n"
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
    assert sorted(item.name for item in filed_in[0].iterdir()) == sorted(
        store.SNAPSHOT_FILES
    )


def test_a_dead_link_exits_2_through_the_cli(
    runner: CliRunner,
    workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flags = cli_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        extract, "fetch", lambda *args, **kwargs: _raise(FetchError("link refused"))
    )
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
    """The one clause `30` adds to the CLI: a `NetworkError` is the environment,
    not the operator's typing, and without it this would exit `70`."""
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


def test_an_export_with_no_file_references_has_no_gap(
    settings: Settings, tmp_path: Path
) -> None:
    """ "No references, no gap": a snapshot with nothing missing says nothing."""
    plain = tmp_path / "plain.zip"
    with zipfile.ZipFile(plain, "w") as archive:
        archive.writestr(
            "conversations.json",
            json.dumps(
                [
                    {
                        "uuid": "c1",
                        "name": "A chat",
                        "created_at": "2026-01-01T00:00:00Z",
                        "updated_at": "2026-01-01T00:00:00Z",
                        "chat_messages": [],
                    }
                ]
            ),
        )
    sink = Collected()
    outcome = extract.file(settings, plain, sink=sink)

    assert outcome.snapshot is not None
    assert outcome.snapshot.gaps == []
    assert "Gaps:" not in sink.stdout


def test_one_missing_file_is_not_one_files(settings: Settings, tmp_path: Path) -> None:
    """The reason is read as part of the block's sentence, so it has two
    spellings. (Raised by Copilot in review on #43.)"""
    one = tmp_path / "one.zip"
    with zipfile.ZipFile(one, "w") as archive:
        archive.writestr(
            "conversations.json",
            json.dumps(
                [
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
                ]
            ),
        )
    sink = Collected()
    outcome = extract.file(settings, one, sink=sink)

    assert outcome.snapshot is not None
    assert outcome.snapshot.gap_count == 1
    assert "Gaps: 1 file the export does not carry\n" in sink.stdout
