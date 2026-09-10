"""Structured logging that cannot leak conversation content.

Two sinks, both optional:

- a JSON-lines file at `<workspace>/logs/run-<UTC ts>.jsonl`, installed by
  `enable_run_log()`;
- one human line per record on **stderr**, installed by `configure_logging()` only
  at `--verbose`.

stdout is never a log sink. `18` owns stdout during a run and `08`'s browser
helpers print exactly one JSON object there, so a stray log line would corrupt
output that is compared byte for byte.

The file sink is opt-in per command rather than installed at startup, because `05`
requires `import --dry-run` to leave no workspace directory behind. Commands that
write to the workspace call `enable_run_log()`; dry runs and the read-only helpers
do not. The handler also opens lazily, so even then the directory appears only if a
record is actually written.

## Content guard

Records carry identifiers, step names, counts, durations, categories and details —
never message text. `ContentGuard` enforces the "never" half: any record carrying a
field named `text`, `seed`, `title`, `content`, `snapshot` or `stdout` is rejected.
It raises in strict mode (the test suite) and drops the record otherwise, so a
mistake fails loudly in CI and silently in an operator's terminal rather than
writing content to disk. `DATAPORTER_LOG_STRICT` turns strict mode on for any
spelling `orval.to_bool` reads as true (`1`, `true`, `yes`, `y`, `t`, `on`);
anything else, an unrecognised value included, leaves it off.

The guard sits on every *handler*, never on a logger: `Logger.callHandlers` walks
ancestor loggers' handlers directly and never consults their filters, so a filter
on the `dataporter` logger would not see records from `dataporter.cli`. Handlers
are only ever constructed by `_guarded()` below, which is what makes that a
guarantee rather than a convention.

What the guard cannot catch is content interpolated into the message itself
(`log.info("seed=%s", seed)`). The rule that closes that hole is not enforceable by
a name filter: **log messages are constants, all variable data goes in `extra`.**

Nor can it catch a control character *inside* a legal value: a `file_name` with a
`\n` in it turns one human-formatted record into two, and the same value printed
for an operator forges a line of output. `safe_token()` is what callers pass
export-derived strings through before either.

## Field-name conventions

`conversation_id` is the canonical identifier spelling. Where a banned name is
genuinely wanted for a path, the path spelling is legal and the content is not:
`seed_path`, `stdout_path`.

The record's own keys (`SCHEMA_FIELDS`) are reserved: the log message is the event
name, so `event`, `level`, `ts`, `logger` and `exception` are never passed as
fields. `ContentGuard` raises on either violation in strict mode.
"""

import json
import logging
import os
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from io import TextIOWrapper
from pathlib import Path
from typing import Any

from orval import to_bool, utcnow

LOGGER_NAME = "dataporter"
LOGS_DIRNAME = "logs"
STRICT_ENV_VAR = "DATAPORTER_LOG_STRICT"

FORBIDDEN_FIELDS = frozenset({"text", "seed", "title", "content", "snapshot", "stdout"})
"""Field names that would carry conversation content. See `01` and §10 of the brief."""

SCHEMA_FIELDS = frozenset({"ts", "level", "logger", "event", "exception"})
"""Keys the JSON-lines record owns.

An `extra` field with one of these names would redefine the schema `19` parses —
`extra={"level": "BOGUS"}` makes `level` stop meaning the log level. The message
*is* the event name, so none of these is ever passed as a field. `13`'s planned
retry record (`{event: "retry", uuid, …}`) needs rewriting as
`log.info("retry", extra={"attempt": …})` for this reason."""

_MAX_SCAN_DEPTH = 5

CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
"""Characters no legitimate identifier, name or reason carries.

Public because `03` needs the same set for a different reason: here one would
forge a line of output, and in `plan.safe_component` one would reach a path.
The export is trusted or distrusted once, so both read the same rule.
"""

_TOKEN_LIMIT = 120


def safe_token(value: str, limit: int = _TOKEN_LIMIT) -> str:
    """An export-derived string, reduced to something that cannot forge a line.

    A name, an id or a reason may legally contain a newline — the export is not
    ours — and neither the content guard nor `JsonlFormatter` stops one from
    splitting a `HumanFormatter` record in two or from adding a line to what an
    operator reads on stderr. Control characters become `?` and the result is
    bounded; nothing else is altered, because this is for identifiers, not for
    display.
    """
    return CONTROL_CHARACTERS.sub("?", value)[:limit] or "(empty)"


_RESERVED_RECORD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime"}
"""Derived, not hardcoded, so stdlib additions (`taskName` in 3.12) stay reserved."""

_strict_default = False

_NULL_HANDLER = logging.NullHandler()
"""Always attached. Without a handler, `logging.lastResort` prints the record —
traceback and all — straight to stderr, which is exactly what exit code 70 exists
to avoid. A NullHandler discards everything, so it needs no content guard."""


class ContentLeak(AssertionError):
    """A log record carried a field that could contain conversation content."""


class SchemaClash(AssertionError):
    """A log record carried a field that would redefine a JSON-lines schema key."""


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    """The caller-supplied `extra` fields, with stdlib record attributes removed."""
    return {
        key: value
        for key, value in record.__dict__.items()
        if key not in _RESERVED_RECORD_ATTRS
    }


def _forbidden_names(fields: Mapping[str, Any], depth: int = 0) -> set[str]:
    """Forbidden field names in `fields`, including inside nested mappings.

    The spec says "fields are named", i.e. top level. Nested mappings are scanned
    too because `extra={"result": {"text": ...}}` leaks just as effectively and the
    JSON formatter would serialise it happily.
    """
    found = {key for key in fields if key in FORBIDDEN_FIELDS}
    if depth < _MAX_SCAN_DEPTH:
        for value in fields.values():
            if isinstance(value, Mapping):
                found |= _forbidden_names(value, depth + 1)
    return found


class ContentGuard(logging.Filter):
    """Enforces the two field-naming rules: no content, no schema collisions.

    The two failures are not equally severe, so they are not handled the same way.
    A content field is dropped — writing it is the thing we must never do. A schema
    collision is let through, because `JsonlFormatter` already refuses to let extras
    overwrite schema keys, and losing a diagnostic record to a naming mistake would
    be a worse trade. Both raise in strict mode, so tests catch either at once.
    """

    def __init__(self, *, strict: bool = False) -> None:
        super().__init__()
        self.strict = strict

    def filter(self, record: logging.LogRecord) -> bool:
        fields = _extras(record)

        offending = _forbidden_names(fields)
        if offending:
            if self.strict:
                # Raised outside Handler.emit's try/except, so it reaches the caller
                # rather than being swallowed by logging.handleError.
                raise ContentLeak(
                    f"log record carries content field(s): "
                    f"{', '.join(sorted(offending))}"
                )
            return False

        clashing = SCHEMA_FIELDS & set(fields)
        if clashing and self.strict:
            raise SchemaClash(
                f"log record redefines schema field(s): {', '.join(sorted(clashing))}; "
                f"the message is the event name"
            )
        return True


class JsonlFormatter(logging.Formatter):
    """One JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            # The type only. An exception's message is not guaranteed content-free.
            payload["exception"] = record.exc_info[0].__name__
        # Extras never overwrite a schema key: `extra={"level": ...}` would make
        # `level` stop meaning the log level, silently, for every downstream parser.
        for key, value in _extras(record).items():
            if key not in SCHEMA_FIELDS:
                payload[key] = value
        return json.dumps(payload, default=str)


class HumanFormatter(logging.Formatter):
    """One plain line per record. No colour: `--verbose` output is read by people
    and by tests, and terminal decoration breaks byte comparison."""

    def format(self, record: logging.LogRecord) -> str:
        stamp = datetime.fromtimestamp(record.created, UTC).strftime("%H:%M:%S")
        line = f"{stamp} {record.levelname.lower():<7} {record.getMessage()}"
        extras = _extras(record)
        if extras:
            line += " " + " ".join(f"{k}={v}" for k, v in sorted(extras.items()))
        return line


class _JsonlFileHandler(logging.FileHandler):
    """A file handler that creates `logs/` only when it actually writes."""

    def _open(self) -> TextIOWrapper:
        Path(self.baseFilename).parent.mkdir(parents=True, exist_ok=True)
        return super()._open()


def _guarded(handler: logging.Handler, *, strict: bool) -> logging.Handler:
    """The only place an emitting handler is added to this package's logger."""
    handler.addFilter(ContentGuard(strict=strict))
    return handler


def package_logger() -> logging.Logger:
    """The `dataporter` logger, guaranteed to have at least a NullHandler."""
    logger = logging.getLogger(LOGGER_NAME)
    if _NULL_HANDLER not in logger.handlers:
        logger.addHandler(_NULL_HANDLER)
    return logger


def strict_by_default() -> bool:
    """Whether new handlers raise on a content field rather than dropping it.

    `to_bool` rather than "neither empty nor `0`": that spelling made
    `DATAPORTER_LOG_STRICT=false` turn strict mode *on*, which is the opposite of
    what anyone typing it meant. An unrecognised value leaves it off for the same
    reason — a setting nobody can explain must not change how the logger behaves.
    """
    return _strict_default or to_bool(os.environ.get(STRICT_ENV_VAR, ""), default=False)


def run_log_path(workspace: Path, now: datetime | None = None) -> Path:
    """`<workspace>/logs/run-<UTC ts>.jsonl`.

    Basic ISO 8601 — no colons, so it is a legal filename everywhere, and it sorts
    lexicographically by time.
    """
    stamp = (now or utcnow()).strftime("%Y%m%dT%H%M%SZ")
    return workspace / LOGS_DIRNAME / f"run-{stamp}.jsonl"


def configure_logging(*, verbose: bool = False, strict: bool | None = None) -> None:
    """Install the stderr sink. Called once, from the CLI's root callback.

    `--quiet` is not an argument here: it suppresses stdout progress output (`18`)
    and has nothing to say about diagnostics on stderr, so `-v -q` is a coherent
    combination rather than a contradiction.
    """
    global _strict_default
    _strict_default = strict_by_default() if strict is None else strict

    reset_logging()
    logger = package_logger()
    logger.setLevel(logging.DEBUG)
    # Nothing from this package reaches the root logger, and nothing a third-party
    # library logs reaches our sinks. Containment, not filtering.
    logger.propagate = False

    if verbose:
        stderr: logging.Handler = logging.StreamHandler(sys.stderr)
        stderr.setFormatter(HumanFormatter())
        logger.addHandler(_guarded(stderr, strict=_strict_default))


def enable_run_log(workspace: Path, *, strict: bool | None = None) -> Path:
    """Install the JSON-lines file sink and return its path.

    Only commands that already write to the workspace call this.
    """
    path = run_log_path(workspace)
    handler = _JsonlFileHandler(path, mode="a", encoding="utf-8", delay=True)
    handler.setFormatter(JsonlFormatter())
    guard_strict = _strict_default if strict is None else strict
    package_logger().addHandler(_guarded(handler, strict=guard_strict))
    return path


def reset_logging() -> None:
    """Remove every emitting handler this package installed. For tests and re-entry."""
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        if handler is _NULL_HANDLER:
            continue
        logger.removeHandler(handler)
        handler.close()


def get_logger(name: str) -> logging.Logger:
    """A logger under the package root, e.g. `get_logger(__name__)`."""
    package_logger()
    if name == LOGGER_NAME or name.startswith(f"{LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
