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
