"""Logging, and the guarantee that content cannot reach a sink."""

import json
import logging
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataporter import cli, log


def read_lines(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def test_every_handler_carries_the_guard(workspace: Path) -> None:
    """The filter is only as good as the promise that no handler escapes the
    factory, so assert the promise rather than the filter."""
    log.configure_logging(verbose=True)
    log.enable_run_log(workspace)
    handlers = logging.getLogger(log.LOGGER_NAME).handlers
    # A NullHandler discards everything, so it is the one exemption.
    emitting = [h for h in handlers if not isinstance(h, logging.NullHandler)]
    assert len(emitting) == 2
    for handler in emitting:
        assert any(isinstance(f, log.ContentGuard) for f in handler.filters)


def test_a_null_handler_is_always_present() -> None:
    """Without one, logging.lastResort prints records straight to stderr."""
    log.reset_logging()
    logger = log.get_logger("test")
    assert any(
        isinstance(h, logging.NullHandler)
        for h in logging.getLogger(log.LOGGER_NAME).handlers
    )
    assert logger.name == "dataporter.test"


def test_content_field_reaches_neither_sink(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log.configure_logging(verbose=True, strict=False)
    path = log.enable_run_log(workspace, strict=False)
    logger = log.get_logger("test")

    # A benign record first, so "the file does not exist" cannot pass by accident.
    logger.info("started", extra={"conversation_id": "abc-123"})
    logger.info("seed built", extra={"text": "the user's private message"})

    captured = capsys.readouterr()
    assert "private message" not in captured.err
    assert "private message" not in captured.out
    assert "started" in captured.err

    lines = read_lines(path)
    assert [line["event"] for line in lines] == ["started"]
    assert "private message" not in path.read_text()


@pytest.mark.parametrize("field", sorted(log.FORBIDDEN_FIELDS))
def test_strict_mode_raises_for_every_forbidden_field(
    workspace: Path, field: str
) -> None:
    log.configure_logging(verbose=True, strict=True)
    with pytest.raises(log.ContentLeak, match=field):
        log.get_logger("test").info("oops", extra={field: "secret"})


def test_nested_content_is_caught_too(workspace: Path) -> None:
    """`extra={"result": {"text": ...}}` leaks just as effectively as a top-level
    field, and the JSON formatter would serialise it happily."""
    log.configure_logging(verbose=True, strict=True)
    with pytest.raises(log.ContentLeak, match="snapshot"):
        log.get_logger("test").info("oops", extra={"result": {"snapshot": "<html>"}})


def test_allowed_fields_survive(workspace: Path) -> None:
    log.configure_logging(verbose=True, strict=True)
    path = log.enable_run_log(workspace, strict=True)
    log.get_logger("test").info(
        "step done",
        extra={
            "conversation_id": "abc-123",
            "step": "paste",
            "category": "network",
            "detail": "connection reset",
            "count": 3,
            "duration_ms": 812,
            "seed_path": "/w/seeds/abc/part-01.txt",
            "stdout_path": "/w/hermes/run.stdout.txt",
        },
    )
    (record,) = read_lines(path)
    assert record["event"] == "step done"
    assert record["level"] == "info"
    assert record["logger"] == "dataporter.test"
    assert record["conversation_id"] == "abc-123"
    assert record["step"] == "paste"
    assert record["duration_ms"] == 812
    assert record["seed_path"] == "/w/seeds/abc/part-01.txt"
    assert str(record["ts"]).endswith("Z")


@pytest.mark.parametrize("field", sorted(log.SCHEMA_FIELDS))
def test_strict_mode_raises_on_a_schema_collision(workspace: Path, field: str) -> None:
    log.configure_logging(verbose=True, strict=True)
    with pytest.raises(log.SchemaClash, match=field):
        log.get_logger("test").info("oops", extra={field: "BOGUS"})


def test_extras_never_overwrite_the_schema(workspace: Path) -> None:
    """`13` plans `{event: "retry", uuid, ...}`; without this, `event` would stop
    meaning the message and `19`'s parser would silently misread every record."""
    log.configure_logging(verbose=False, strict=False)
    path = log.enable_run_log(workspace, strict=False)
    log.get_logger("test").info(
        "retry scheduled",
        extra={"event": "retry", "level": "BOGUS", "attempt": 2},
    )
    (record,) = read_lines(path)
    assert record["event"] == "retry scheduled"
    assert record["level"] == "info"
    # The record is kept: a naming mistake should not cost a diagnostic.
    assert record["attempt"] == 2


def test_schema_collision_does_not_drop_the_record(workspace: Path) -> None:
    """Unlike a content leak, which must never be written, a collision is survivable."""
    log.configure_logging(verbose=False, strict=False)
    path = log.enable_run_log(workspace, strict=False)
    log.get_logger("test").info("kept", extra={"logger": "BOGUS"})
    assert len(read_lines(path)) == 1


@pytest.mark.parametrize(
    ("value", "strict"),
    [
        ("", False),
        ("0", False),
        ("false", False),
        ("off", False),
        ("no", False),
        # Not a spelling anybody recognises. It must not turn the guard on by
        # being merely non-empty, which is how the old rule read it.
        ("bogus", False),
        ("1", True),
        ("true", True),
        ("yes", True),
        ("ON", True),
    ],
)
def test_the_strict_env_var_reads_the_way_an_operator_writes_it(
    monkeypatch: pytest.MonkeyPatch, value: str, strict: bool
) -> None:
    """`DATAPORTER_LOG_STRICT=false` used to turn strict mode *on*."""
    # The process-wide default is what `configure_logging` last left behind, and
    # it short-circuits the environment; this test is about the environment.
    monkeypatch.setattr(log, "_strict_default", False)
    monkeypatch.setenv(log.STRICT_ENV_VAR, value)
    assert log.strict_by_default() is strict


def test_a_falsy_strict_env_var_drops_rather_than_raises(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> None:
    """The value has to reach the handler, not just `strict_by_default`."""
    monkeypatch.setattr(log, "_strict_default", False)
    monkeypatch.setenv(log.STRICT_ENV_VAR, "off")
    log.configure_logging(verbose=False)
    path = log.enable_run_log(workspace)
    # Dropped, not raised: that is what non-strict mode means.
    log.get_logger("test").info("leak", extra={"text": "conversation content"})
    assert read_lines(path) == []


def test_a_truthy_strict_env_var_raises(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> None:
    monkeypatch.setattr(log, "_strict_default", False)
    monkeypatch.setenv(log.STRICT_ENV_VAR, "yes")
    log.configure_logging(verbose=False)
    log.enable_run_log(workspace)
    with pytest.raises(log.ContentLeak, match="text"):
        log.get_logger("test").info("leak", extra={"text": "conversation content"})


def test_nothing_is_created_until_a_record_is_written(workspace: Path) -> None:
    """`05` requires `import --dry-run` to leave no workspace behind."""
    target = workspace / "ws"
    log.configure_logging(verbose=False)
    log.enable_run_log(target)
    assert not target.exists()

    log.get_logger("test").info("now")
    assert (target / log.LOGS_DIRNAME).is_dir()


def test_dry_run_leaves_no_workspace_directory(
    runner: CliRunner, workspace: Path
) -> None:
    export = workspace / "export"
    export.mkdir()
    runner.invoke(
        cli.app, ["-v", "import", str(export), "--dry-run"], catch_exceptions=False
    )
    # The file sink is opt-in per command, so a verbose dry run writes nothing.
    assert not (workspace / "migration").exists()


def test_run_log_filename_is_sortable(workspace: Path) -> None:
    path = log.run_log_path(workspace)
    assert path.parent == workspace / log.LOGS_DIRNAME
    assert path.name.startswith("run-")
    assert path.suffix == ".jsonl"
    assert ":" not in path.name  # a legal filename everywhere


def test_quiet_does_not_silence_diagnostics(workspace: Path) -> None:
    """`--quiet` is about stdout progress; `--verbose` is about stderr."""
    log.configure_logging(verbose=True)
    assert logging.getLogger(log.LOGGER_NAME).handlers


def test_package_logger_does_not_propagate(workspace: Path) -> None:
    """Third-party libraries cannot reach our sinks, and we cannot reach root's."""
    log.configure_logging(verbose=True)
    assert logging.getLogger(log.LOGGER_NAME).propagate is False


def test_get_logger_stays_under_the_package_root() -> None:
    assert log.get_logger("browser.cdp").name == "dataporter.browser.cdp"
    assert log.get_logger("dataporter.cli").name == "dataporter.cli"


def test_safe_token_cannot_forge_a_second_line() -> None:
    """The guard rejects a content *field*; it says nothing about a newline inside
    a legal value, which is what would split one record into two."""
    assert log.safe_token("chart\n.png") == "chart?.png"
    assert log.safe_token("a\x00b\x7fc") == "a?b?c"
    assert log.safe_token("ordinary-name.png") == "ordinary-name.png"
    assert log.safe_token("x" * 300) == "x" * 120
    assert log.safe_token("") == "(empty)"
