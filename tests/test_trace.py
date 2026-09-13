"""The trace file, its header, its guard and the move (`33`).

What is here is the file on its own: the header's bytes, the two clocks, the
guard on every line, the URL rule, `end`, and how a second process finds and
appends to it. What a *run* writes into one — a move per helper, the six
commands that open one — is tested where those live: `test_browser_helpers.py`,
`test_importer.py`, `test_ask.py` and the rest.
"""

import json
import multiprocessing
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from orval import utcnow

from dataporter import log
from dataporter import trace as tracing
from dataporter.browser.cdp import CdpClient
from dataporter.browser.site import Site
from dataporter.config import BrowserSettings, HermesSettings, Settings
from dataporter.exit_codes import ExitCode
from fake_hermes import FakeHermes

SITE = Site("claude", "claude.ai", {"COMPOSER_SELECTOR": 'div[contenteditable="true"]'})
NOW = datetime(2026, 9, 13, 10, 0, 0, tzinfo=UTC)
STAMP = "20260913T100000Z"
RESOLVER = "--host-resolver-rules=MAP claude.ai 127.0.0.1:8443"


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        workspace=tmp_path / "migration",
        browser=BrowserSettings(extra_args=(RESOLVER,)),
        hermes=HermesSettings(executable=tmp_path / "none"),
    )


def opened(tmp_path: Path, **overrides: object) -> tracing.Trace:
    fields: dict[str, object] = {
        "command": "import",
        "flags": ["--pilot"],
        "site": SITE,
        "chrome": "Chromium 141.0.7390.37",
        "agent": "hermes 1.0.0 (scripted agent)",
        "export_fingerprint": "1f844dc5…",
        "stamp": STAMP,
        "now": NOW,
    }
    fields.update(overrides)
    return tracing.Trace.open(settings_for(tmp_path), **fields)  # type: ignore[arg-type]


def lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture(autouse=True)
def no_current_trace() -> None:
    tracing.set_current(None)


# --------------------------------------------------------------------------- #
# The header
# --------------------------------------------------------------------------- #


def test_the_header_is_the_briefs_first_line(tmp_path: Path) -> None:
    """Brief `04` §42's first line, byte for byte, with the table's rule per key."""
    trace = opened(tmp_path)
    trace.close()
    root = tmp_path / "migration"
    assert trace.path == root / "logs" / f"trace-{STAMP}.jsonl"
    assert trace.path.read_text(encoding="utf-8") == (
        '{"trace":1,"kind":"header","ts":"2026-09-13T10:00:00.000Z","command":"import","flags":["--pilot"],'
        '"source":"claude","host":"claude.ai","account":null,"export_fingerprint":"1f844dc5…",'
        '"tool":"dataporter 0.1.0","chrome":"Chromium 141.0.7390.37","agent":"hermes 1.0.0 (scripted agent)",'
        f'"chrome_arguments":["{RESOLVER}"],"root":"{root}"}}\n'
    )
    assert oct(trace.path.stat().st_mode & 0o777) == oct(tracing.FILE_MODE)


def test_the_stamp_is_the_run_logs_when_one_is_enabled(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    run_log = log.enable_run_log(settings.workspace)
    trace = tracing.Trace.open(settings, command="verify", flags=(), site=SITE, chrome=None, agent=None)
    trace.close()
    assert trace.path.name == run_log.name.replace("run-", "trace-")
    assert trace.path.parent == run_log.parent


def test_without_a_run_log_the_stamp_is_the_moment(tmp_path: Path) -> None:
    trace = tracing.Trace.open(settings_for(tmp_path), command="doctor", flags=(), site=SITE, chrome=None, agent=None)
    trace.close()
    stamp = trace.path.stem.removeprefix("trace-")
    assert len(stamp) == len(STAMP)
    assert abs(datetime.strptime(stamp, log.RUN_LOG_STAMP).replace(tzinfo=UTC) - utcnow()) < timedelta(minutes=1)


def test_a_second_trace_in_the_same_second_is_a_second_file(tmp_path: Path) -> None:
    """One header per file: the run log appends, a trace never does."""
    first = opened(tmp_path)
    first.close()
    second = opened(tmp_path)
    second.close()
    third = opened(tmp_path)
    third.close()
    assert first.path.name == f"trace-{STAMP}.jsonl"
    assert second.path.name == f"trace-{STAMP}-2.jsonl"
    assert third.path.name == f"trace-{STAMP}-3.jsonl"
    assert [len(lines(path)) for path in (first.path, second.path, third.path)] == [1, 1, 1]


def test_account_and_fingerprint_are_null_when_absent(tmp_path: Path) -> None:
    trace = opened(tmp_path, export_fingerprint=None)
    trace.close()
    header = lines(trace.path)[0]
    assert header["account"] is None
    assert header["export_fingerprint"] is None
    assert list(header) == [
        "trace",
        "kind",
        "ts",
        "command",
        "flags",
        "source",
        "host",
        "account",
        "export_fingerprint",
        "tool",
        "chrome",
        "agent",
        "chrome_arguments",
        "root",
    ]


# --------------------------------------------------------------------------- #
# Lines, and the two clocks
# --------------------------------------------------------------------------- #


def test_a_line_carries_the_kind_and_both_clocks_first(tmp_path: Path) -> None:
    trace = opened(tmp_path)
    assert trace.observation("navigation", path="/new", query=[]) is True
    trace.close()
    _, written = lines(trace.path)
    assert list(written) == ["kind", "ts", "t_ms", "what", "path", "query"]
    assert written["kind"] == "observation"
    assert isinstance(written["t_ms"], int)
    assert written["t_ms"] >= 0
    assert str(written["ts"]).endswith("Z")


def test_the_move_line_is_the_briefs(tmp_path: Path) -> None:
    trace = opened(tmp_path)
    result = {"kind": "new_chat", "logged_in": True, "composer_chars": 0}
    trace.move("probe", ok=True, elapsed_ms=38, conversation_id=None, result=result, ts="2026-09-13T10:00:00.650Z")
    trace.close()
    _, move = lines(trace.path)
    t_ms = move.pop("t_ms")
    assert isinstance(t_ms, int)
    assert move == {
        "kind": "move",
        "ts": "2026-09-13T10:00:00.650Z",
        "helper": "probe",
        "ok": True,
        "elapsed_ms": 38,
        "conversation_id": None,
        "before": None,
        "after": None,
        "result": result,
    }
    assert list(move) == ["kind", "ts", "helper", "ok", "elapsed_ms", "conversation_id", "before", "after", "result"]


def test_an_attached_trace_counts_from_the_header(tmp_path: Path) -> None:
    """A helper process has its own monotonic clock; the header's `ts` is the shared start."""
    trace = opened(tmp_path, now=utcnow() - timedelta(seconds=2))
    trace.close()
    attached = tracing.Trace.attached(trace.path)
    assert attached is not None
    assert attached.started_at == trace.started_at
    attached.observation("request", path="/api/chats", query=[])
    attached.close()
    assert lines(trace.path)[-1]["t_ms"] >= 2000


def test_attaching_to_a_file_that_is_not_a_trace_is_none(tmp_path: Path) -> None:
    assert tracing.Trace.attached(tmp_path / "missing.jsonl") is None
    garbage = tmp_path / "garbage.jsonl"
    garbage.write_text("not json\n", encoding="utf-8")
    assert tracing.Trace.attached(garbage) is None
    no_ts = tmp_path / "no-ts.jsonl"
    no_ts.write_text('{"trace":1}\n', encoding="utf-8")
    assert tracing.Trace.attached(no_ts) is None


# --------------------------------------------------------------------------- #
# The guard (§46)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", sorted(log.FORBIDDEN_FIELDS))
def test_every_forbidden_field_raises_under_strict_at_any_depth(tmp_path: Path, name: str) -> None:
    trace = opened(tmp_path)
    with pytest.raises(log.ContentLeakError, match=name):
        trace.observation("request", **{name: "x"})
    with pytest.raises(log.ContentLeakError, match=name):
        trace.move("probe", ok=True, elapsed_ms=1, conversation_id=None, result={"nested": {name: "x"}}, ts="t")
    trace.close()
    assert len(lines(trace.path)) == 1


@pytest.mark.parametrize("name", sorted(tracing.TRACE_KEYS))
def test_a_lines_own_keys_cannot_be_fields(tmp_path: Path, name: str) -> None:
    trace = opened(tmp_path)
    with pytest.raises(log.ContentLeakError, match=name):
        trace.append("observation", {"what": "end", name: "x"})
    trace.close()


def test_without_strict_the_line_is_dropped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The process-wide default is what `configure_logging` last left behind and
    # short-circuits the environment, as `test_log.py` notes.
    monkeypatch.setattr(log, "_strict_default", False)
    monkeypatch.setenv(log.STRICT_ENV_VAR, "0")
    trace = opened(tmp_path)
    assert trace.observation("request", title="leak") is False
    assert trace.move("probe", ok=True, elapsed_ms=1, conversation_id=None, result={"email": "x"}, ts="t") is False
    assert trace.observation("request", path="/new", query=[]) is True
    trace.close()
    assert [item["kind"] for item in lines(trace.path)] == ["header", "observation"]
    assert "leak" not in trace.path.read_text(encoding="utf-8")


def test_url_fields_keeps_the_path_and_the_key_names_only() -> None:
    assert tracing.url_fields("https://claude.ai/login?code=s3cret&next=%2Fnew#token=abc") == {
        "path": "/login",
        "query": ["code", "next"],
    }
    assert tracing.url_fields("https://claude.ai") == {"path": "/", "query": []}
    assert tracing.url_fields("https://claude.ai/new?") == {"path": "/new", "query": []}


def test_sanitised_removes_forbidden_keys_and_reduces_urls_at_every_depth() -> None:
    printed = {
        "ok": False,
        "error": "ambiguous_tab",
        "title": {"chars": 3},
        "url": "https://claude.ai/new?x=1",
        "tabs": [{"id": "a", "url": "https://claude.ai/chat/1?y=2#f"}, {"id": "b", "text": "no"}],
        "deep": {"content": "no", "keep": ["yes"]},
    }
    assert tracing.sanitised(printed) == {
        "ok": False,
        "error": "ambiguous_tab",
        "path": "/new",
        "query": ["x"],
        "tabs": [{"id": "a", "path": "/chat/1", "query": ["y"]}, {"id": "b"}],
        "deep": {"keep": ["yes"]},
    }


# --------------------------------------------------------------------------- #
# The end
# --------------------------------------------------------------------------- #


def test_end_writes_the_last_line_and_nothing_after(tmp_path: Path) -> None:
    trace = opened(tmp_path)
    trace.end(ExitCode.PAUSED)
    trace.end(ExitCode.OK)
    written = lines(trace.path)
    assert len(written) == 2
    assert {key: written[-1][key] for key in ("kind", "what", "exit")} == {
        "kind": "observation",
        "what": "end",
        "exit": 5,
    }
    with pytest.raises(tracing.TraceEndedError):
        trace.observation("request")
    with pytest.raises(tracing.TraceEndedError):
        trace.move("probe", ok=True, elapsed_ms=1, conversation_id=None, result={}, ts="t")


def test_a_write_that_fails_is_a_warning_not_an_error(tmp_path: Path) -> None:
    """A descriptor nothing reads from: `BrokenPipeError`, which is an `OSError`."""
    reading, writing = os.pipe()
    os.close(reading)
    trace = tracing.Trace(path=tmp_path / "trace.jsonl", started_at=NOW, _fd=writing)
    assert trace.observation("request", path="/", query=[]) is False
    trace.close()


# --------------------------------------------------------------------------- #
# Finding it from another process
# --------------------------------------------------------------------------- #


def test_current_is_none_with_no_variable_and_no_open_trace() -> None:
    assert tracing.current() is None


def test_current_is_the_process_s_own_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trace = opened(tmp_path)
    monkeypatch.setenv(tracing.TRACE_ENV_VAR, str(tmp_path / "other.jsonl"))
    tracing.set_current(trace)
    assert tracing.current() is trace
    tracing.set_current(None)
    trace.close()


def test_current_attaches_the_file_the_variable_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trace = opened(tmp_path)
    trace.close()
    monkeypatch.setenv(tracing.TRACE_ENV_VAR, str(trace.path))
    found = tracing.current()
    assert found is not None
    assert found.path == trace.path
    found.observation("request", path="/api/chats", query=[])
    found.close()
    assert [item["kind"] for item in lines(trace.path)] == ["header", "observation"]


def test_a_variable_naming_no_trace_is_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(tracing.TRACE_ENV_VAR, str(tmp_path / "gone.jsonl"))
    assert tracing.current() is None
    monkeypatch.setenv(tracing.TRACE_ENV_VAR, "   ")
    assert tracing.current() is None


def _append_many(path: str, tag: str, count: int) -> None:
    attached = tracing.Trace.attached(Path(path))
    assert attached is not None
    for index in range(count):
        attached.observation("request", tag=tag, index=index, pad="x" * 8000)
    attached.close()


@pytest.mark.slow
def test_two_processes_append_whole_lines(tmp_path: Path) -> None:
    """`flock` makes a whole line a contract rather than a habit of the filesystem."""
    trace = opened(tmp_path)
    trace.close()
    count = 300
    workers = [
        multiprocessing.get_context("spawn").Process(target=_append_many, args=(str(trace.path), tag, count))
        for tag in ("a", "b")
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=120)
        assert worker.exitcode == 0
    written = lines(trace.path)
    assert len(written) == 1 + 2 * count
    assert sorted(item["index"] for item in written[1:] if item["tag"] == "a") == list(range(count))
    assert sorted(item["index"] for item in written[1:] if item["tag"] == "b") == list(range(count))


# --------------------------------------------------------------------------- #
# A run's trace: `start`, `finish`, `opened`
# --------------------------------------------------------------------------- #


def test_opened_ends_with_the_body_s_code(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    with tracing.opened(settings, command="verify", flags=(), site=SITE, client=None) as traced:
        assert tracing.current() is traced.trace
        traced.exit_code = ExitCode.FAILED
    assert tracing.current() is None
    assert traced.trace is not None
    assert lines(traced.trace.path)[-1]["exit"] == 1


def test_opened_ends_with_70_when_the_body_raises(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    with pytest.raises(RuntimeError), tracing.opened(settings, command="verify", flags=(), site=SITE, client=None) as t:
        raise RuntimeError("boom")
    assert tracing.current() is None
    assert t.trace is not None
    assert lines(t.trace.path)[-1]["exit"] == 70


def test_opened_keeps_a_code_the_body_set_before_it_raised(tmp_path: Path) -> None:
    """A generator closed after a failed check: `6`, not `70`."""
    settings = settings_for(tmp_path)
    handles: list[tracing.Opened] = []

    def body() -> None:
        with tracing.opened(settings, command="doctor", flags=(), site=SITE, client=None) as traced:
            handles.append(traced)
            traced.exit_code = ExitCode.ENVIRONMENT
            raise GeneratorExit

    with pytest.raises(GeneratorExit):
        body()
    assert handles[0].trace is not None
    assert lines(handles[0].trace.path)[-1]["exit"] == 6


def test_opened_defaults_to_ok(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    with tracing.opened(settings, command="login", flags=("--account",), site=SITE, client=None) as traced:
        pass
    assert traced.trace is not None
    written = lines(traced.trace.path)
    assert written[0]["flags"] == ["--account"]
    assert written[0]["chrome"] is None
    assert written[0]["agent"] is None
    assert written[-1]["exit"] == 0


def test_a_trace_that_cannot_be_made_is_a_warning_and_none(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    settings.workspace.mkdir()
    (settings.workspace / "logs").write_text("a file where the directory goes", encoding="utf-8")
    with tracing.opened(settings, command="login", flags=(), site=SITE, client=None) as traced:
        assert traced.trace is None
        assert tracing.current() is None
    tracing.finish(None, ExitCode.OK)


# --------------------------------------------------------------------------- #
# The marks (§47)
# --------------------------------------------------------------------------- #


def test_the_chrome_line_is_none_without_a_browser() -> None:
    assert tracing.chrome_line(None) is None
    assert tracing.chrome_line(CdpClient(port=1, timeout=0.2)) is None


def test_the_agent_line_is_none_without_a_hermes(tmp_path: Path) -> None:
    assert tracing.agent_line(settings_for(tmp_path)) is None


@pytest.mark.slow
def test_the_agent_line_is_what_hermes_prints(tmp_path: Path) -> None:
    fake = FakeHermes(root=tmp_path / "bin").write(version="hermes 1.0.0 (scripted agent)")
    settings = Settings(workspace=tmp_path / "migration", hermes=HermesSettings(executable=fake.executable))
    assert tracing.agent_line(settings) == "hermes 1.0.0 (scripted agent)"


def test_the_site_is_read_only() -> None:
    with pytest.raises(TypeError):
        SITE.selectors["x"] = "y"  # type: ignore[index]
    assert dict(SITE.selectors) == {"COMPOSER_SELECTOR": 'div[contenteditable="true"]'}
    assert os.environ.get(tracing.TRACE_ENV_VAR) is None
