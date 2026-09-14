"""The trace a run that drives a tab leaves (brief `04`, `33`).

One file per run, `<logs>/trace-<UTC ts>.jsonl`, beside the run log and with its
stamp. The first line is the header; every line after it is a move, an
observation or, from `34`, a sketch, in the order they happened. `35` adds the
watch, which writes the observations; this module is the file, the header, the
guard and the move.

## Two processes, one file

A helper Hermes runs is its own process (`08`), and it finds the run's trace
through `DATAPORTER_TRACE`, which `hermes_env` sets for every Hermes it starts —
the way `DATAPORTER_WORKSPACE` already travels. It is read directly, like that
variable, and is never a `Settings` field: a path in `config.toml` would make
every later helper append to an old run's file. A helper run with no variable,
by a person at a terminal, writes no trace.

Every line is one `os.write` on an `O_APPEND` descriptor under `flock`, so a
move from a helper and an observation from the run's own watch cannot land
inside each other.

## What never reaches a trace

§46: the run log's forbidden field names (`log.FORBIDDEN_FIELDS`), at any depth
of any line, and the trace's own keys used as fields. Under the strict switch
(`DATAPORTER_LOG_STRICT`) a violation raises `ContentLeakError`; otherwise the
line is dropped and the run log warns. URLs are reduced to a path and the
names of their query keys by `url_fields`, never a value, never the fragment.

A trace is evidence and the migration is the product: nothing here raises out
of a run for want of a record. A file that cannot be opened or written is a
warning in the run log and nothing else.
"""

import fcntl
import json
import os
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlsplit

from orval import utcnow

from dataporter import PROGRAM_NAME, __version__, log
from dataporter.errors import BrowserError, HermesError
from dataporter.exit_codes import ExitCode

if TYPE_CHECKING:
    from dataporter.browser.cdp import CdpClient
    from dataporter.browser.site import Site
    from dataporter.browser.sketch import Sketch
    from dataporter.config import Settings

_logger = log.get_logger(__name__)

TRACE_VERSION = 1
"""The format version, on the header and nowhere else."""

TRACE_ENV_VAR = "DATAPORTER_TRACE"
"""Set by `hermes_env`, read by `current()`. See the module docstring."""

TRACE_KEYS = frozenset({"trace", "kind", "ts", "t_ms"})
"""The keys a line owns. A field with one of these names would redefine the
line, so it is refused the way a schema field is refused in the run log."""

FILE_MODE = 0o600

HEADER = "header"
MOVE = "move"
OBSERVATION = "observation"
SKETCH = "sketch"
"""The four kinds of line (§42)."""

END = "end"
"""The observation a run writes last, when it ended on its own."""

_MAX_DEPTH = 5
"""How deep `sanitised` walks, `log`'s own limit."""


class TraceEndedError(RuntimeError):
    """A line was offered after `end` — a bug in the caller, never dropped quietly."""


# --------------------------------------------------------------------------- #
# The pieces every line is made of
# --------------------------------------------------------------------------- #


def timestamp(now: datetime | None = None) -> str:
    """Return the wall clock to the millisecond, `Z`.

    The `ts` of every line, and of `actions.jsonl`'s, which is how a move is
    found again there (§42).
    """
    return (now or utcnow()).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def trace_path(logs_dir: Path, stamp: str) -> Path:
    """`<logs_dir>/logs/trace-<stamp>.jsonl`, the run log's stamp beside it."""
    return logs_dir / log.LOGS_DIRNAME / f"trace-{stamp}.jsonl"


LINK_MARKER = "<link>"
"""What stands where a path would while a fetch is redacting (§66)."""

_redacting = threading.Event()
"""Set for the length of a fetch that drives a tab to the link. A process-wide
event rather than a context variable, because the watch writes from a thread
of its own and has to see it."""


@contextmanager
def redacting() -> Iterator[None]:
    """While a fetch drives the tab to the link: hosts, never paths (§66).

    The link is a credential to the archive while it lives, and its secret is
    in its path. Every URL any writer reduces while this is set — the watch's
    navigations and requests, the sketches, the fetch's own move — comes out as
    its host and `<link>`, and a path written by anyone in that time is refused
    by the writer the way §46 refuses a forbidden field.
    """
    _redacting.set()
    try:
        yield
    finally:
        _redacting.clear()


def is_redacting() -> bool:
    return _redacting.is_set()


def url_fields(url: str) -> dict[str, Any]:
    """Return a URL as a trace carries it: the path, and the query's key names (§46).

    Never a value and never the fragment: a sign-in code and an emailed token
    are query values, and a fragment is a value too. While a fetch is
    redacting, the host and a marker instead (§66): a download link's secret is
    its path.
    """
    parts = urlsplit(url)
    if _redacting.is_set():
        return {"host": parts.hostname or "", "path": LINK_MARKER, "query": []}
    return {
        "path": parts.path or "/",
        "query": [key for key, _ in parse_qsl(parts.query, keep_blank_values=True)],
    }


def sanitised(value: Any, depth: int = 0) -> Any:
    """`value` with every forbidden key removed and every `url` reduced, at every depth.

    What a helper printed is one JSON object for Hermes, and a trace carries it
    minus what §46 forbids: `ProbeResult.title` is a forbidden name (the sketch
    carries `title_chars` in its place), and a `Failure`'s `url` — or a
    `TabRef`'s inside its `tabs` — becomes `path` and `query`.
    """
    if isinstance(value, Mapping) and depth < _MAX_DEPTH:
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if key in log.FORBIDDEN_FIELDS:
                continue
            if key == "url" and isinstance(item, str):
                cleaned.update(url_fields(item))
                continue
            cleaned[key] = sanitised(item, depth + 1)
        return cleaned
    if isinstance(value, list | tuple) and depth < _MAX_DEPTH:
        return [sanitised(item, depth + 1) for item in value]
    return value


def _offending(fields: Mapping[str, Any]) -> set[str]:
    found = log.forbidden_names(fields) | (TRACE_KEYS & set(fields))
    if _redacting.is_set():
        found |= _leaking(fields)
    return found


def _leaking(fields: Mapping[str, Any], depth: int = 0) -> set[str]:
    """`path` and `query` fields that carry more than the marker, at every depth (§66)."""
    found: set[str] = set()
    if fields.get("path") not in {None, LINK_MARKER}:
        found.add("path")
    if fields.get("query"):
        found.add("query")
    if depth < _MAX_DEPTH:
        for value in fields.values():
            if isinstance(value, Mapping):
                found |= _leaking(value, depth + 1)
    return found


def _line(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


# --------------------------------------------------------------------------- #
# The marks (§47)
# --------------------------------------------------------------------------- #


def chrome_line(client: "CdpClient | None") -> str | None:
    """Return the `Browser` field of `/json/version`, or `None`.

    The debug port's own answer: one HTTP call the tool already makes, never a
    subprocess.
    """
    if client is None:
        return None
    try:
        found = client.version().get("Browser")
    except BrowserError:
        return None
    return str(found) if found else None


def agent_line(settings: "Settings") -> str | None:
    """Return the first line `hermes --version` prints, verbatim, or `None`.

    `None` when there is no `hermes` to ask or it will not answer: an
    interactive `login` needs no Hermes on the machine, and a header that
    failed the run for want of a version line would make the trace the product.
    """
    # Local, because `hermes.client` imports this module for `hermes_env`.
    from dataporter.hermes import client as hermes_client  # ruff: ignore[import-outside-top-level] - see above

    try:
        finished = hermes_client.HermesCli(settings).run("--version")
    except HermesError:
        return None
    printed = (finished.stdout or finished.stderr).strip().splitlines()
    return printed[0].strip() if printed else None


# --------------------------------------------------------------------------- #
# The file
# --------------------------------------------------------------------------- #


@dataclass
class Trace:
    """One open trace: the file, and where its clocks started.

    Made by `open` (the run's own, which writes the header) or by `attached`
    (a helper's, which found the file through the environment and writes
    nothing but its lines). Both append; only one ever ends it.
    """

    path: Path
    started_at: datetime
    """The header's `ts`. An attached trace counts `t_ms` from it, on the wall
    clock, because a monotonic clock is a process's own."""

    _fd: int = field(repr=False)
    _started_mono: float | None = field(default=None, repr=False)
    """The opener's monotonic start; an attached trace has none."""

    _hashes: set[str] = field(default_factory=set, repr=False)
    """The sketches this file already holds, by hash (`34`): written in full
    the first time, named by the hash after."""

    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    """`flock` keeps two *processes* from tearing a line; this keeps two
    threads of one process — a helper's move and `35`'s watch — from doing
    the same on one descriptor, whose lock they would share."""

    ended: bool = False

    # -- making one --------------------------------------------------------- #

    @classmethod
    def open(
        cls,
        settings: "Settings",
        *,
        command: str,
        flags: Sequence[str],
        site: "Site",
        chrome: str | None,
        agent: str | None,
        export_fingerprint: str | None = None,
        stamp: str | None = None,
        now: datetime | None = None,
    ) -> "Trace":
        """Create `<logs>/trace-<stamp>.jsonl` and write its header.

        The stamp is the run log's when one is enabled, so the two pair by name
        (§42); a caller with no run log gets the moment. `O_EXCL`: a stamp is to
        the second, and a second run in the same second is a second file, never
        an append to the first.
        """
        if stamp is None:
            current = log.current_run_log()
            stamp = current.stem.removeprefix("run-") if current is not None else utcnow().strftime(log.RUN_LOG_STAMP)
        path = trace_path(settings.logs_dir, stamp)
        path.parent.mkdir(parents=True, exist_ok=True)
        started = now or utcnow()
        started = started.replace(microsecond=started.microsecond // 1000 * 1000)
        path, descriptor = _create(path)
        made = cls(path=path, started_at=started, _fd=descriptor, _started_mono=time.monotonic())
        header: dict[str, Any] = {
            "trace": TRACE_VERSION,
            "kind": HEADER,
            "ts": timestamp(started),
            "command": command,
            "flags": list(flags),
            "source": site.source,
            "host": site.host,
            "account": settings.account,
            "export_fingerprint": export_fingerprint,
            "tool": f"{PROGRAM_NAME} {__version__}",
            "chrome": chrome,
            "agent": agent,
            "chrome_arguments": list(settings.browser.extra_args),
            "root": str(settings.logs_dir),
        }
        made._write(_line(header))
        return made

    @classmethod
    def attached(cls, path: Path) -> "Trace | None":
        """Open an existing trace for appending, or `None` when it is not one.

        Reads the header's `ts` so that `t_ms` counts from the same start the
        run's own lines do. A path the variable names that is not a trace — gone,
        or never written — is a warning and `None`, never a raised error.
        """
        try:
            started, hashes = _read_back(path)
            descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            _logger.warning("trace not attached", extra={"trace_path": str(path), "reason": type(exc).__name__})
            return None
        return cls(path=path, started_at=started, _fd=descriptor, _hashes=hashes)

    # -- writing ------------------------------------------------------------ #

    def append(self, kind: str, fields: Mapping[str, Any]) -> bool:
        """Write one line of `kind` with `fields`, or refuse it.

        Refused — raised under the strict switch, dropped with a warning
        otherwise — when a field is forbidden at any depth or is a key the line
        owns. Returns whether the line was written.
        """
        if self.ended:
            raise TraceEndedError(f"trace already ended: {self.path}")
        offending = _offending(fields)
        if offending:
            names = ", ".join(sorted(offending))
            if log.strict_by_default():
                raise log.ContentLeakError(f"trace line carries forbidden field(s): {names}")
            _logger.warning("trace line dropped", extra={"kind": kind, "names": sorted(offending)})
            return False
        payload: dict[str, Any] = {"kind": kind, "ts": timestamp(), "t_ms": self.t_ms()}
        payload.update(fields)
        return self._write(_line(payload))

    def move(
        self,
        helper: str,
        *,
        ok: bool,
        elapsed_ms: int,
        conversation_id: str | None,
        result: Mapping[str, Any],
        ts: str,
        before: str | None = None,
        after: str | None = None,
    ) -> bool:
        """One helper call as it happened (§43), with `actions.jsonl`'s own `ts`."""
        if self.ended:
            raise TraceEndedError(f"trace already ended: {self.path}")
        fields: dict[str, Any] = {
            "helper": helper,
            "ok": ok,
            "elapsed_ms": elapsed_ms,
            "conversation_id": conversation_id,
            "before": before,
            "after": after,
            "result": dict(result),
        }
        offending = _offending(fields)
        if offending:
            names = ", ".join(sorted(offending))
            if log.strict_by_default():
                raise log.ContentLeakError(f"trace line carries forbidden field(s): {names}")
            _logger.warning("trace line dropped", extra={"kind": MOVE, "names": sorted(offending)})
            return False
        payload: dict[str, Any] = {"kind": MOVE, "ts": ts, "t_ms": self.t_ms()}
        payload.update(fields)
        return self._write(_line(payload))

    def observation(self, what: str, **fields: Any) -> bool:
        return self.append(OBSERVATION, {"what": what, **fields})

    def sketch(self, sketch: "Sketch") -> str:
        """Write the sketch if its hash is new to this trace; answer the hash either way.

        A stable page costs one line: a run that polls a page for a minute
        leaves one sketch and sixty moves that point at it (§45).
        """
        digest = sketch.hash
        with self._lock:
            if digest not in self._hashes and self.append(SKETCH, sketch.fields()):
                self._hashes.add(digest)
        return digest

    def end(self, exit_code: ExitCode | int) -> None:
        """Write the last line and close the file. Once; a second call does nothing."""
        if self.ended:
            return
        self.observation(END, exit=int(exit_code))
        self.close()

    def close(self) -> None:
        """Let go of the descriptor without an `end` line: an attached trace's exit."""
        self.ended = True
        with_fd, self._fd = self._fd, -1
        if with_fd >= 0:
            os.close(with_fd)

    # -- the clocks --------------------------------------------------------- #

    def t_ms(self) -> int:
        if self._started_mono is not None:
            return round((time.monotonic() - self._started_mono) * 1000)
        return round((utcnow() - self.started_at).total_seconds() * 1000)

    # -- the write ---------------------------------------------------------- #

    def _write(self, data: bytes) -> bool:
        try:
            with self._lock:
                _locked_write(self._fd, data)
        except OSError as exc:
            _logger.warning("trace not written", extra={"trace_path": str(self.path), "reason": type(exc).__name__})
            return False
        return True


def _read_back(path: Path) -> tuple[datetime, set[str]]:
    """Return the header's start and the hashes of every `sketch` line in the file."""
    with path.open(encoding="utf-8") as handle:
        header = json.loads(handle.readline())
        hashes = _sketch_hashes(handle)
    return datetime.fromisoformat(str(header["ts"])), hashes


def _sketch_hashes(handle: Any) -> set[str]:
    """Return the hashes of the `sketch` lines still to read from an open trace."""
    found: set[str] = set()
    for line in handle:
        if '"kind":"sketch"' not in line:
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and parsed.get("kind") == SKETCH and isinstance(parsed.get("hash"), str):
            found.add(parsed["hash"])
    return found


def _create(path: Path) -> tuple[Path, int]:
    """Create `path`, or the next free `<stem>-N.jsonl` beside it, exclusively.

    A stamp is to the second, and a second run in the same second — a rehearsal's
    steps come fast — is a second file, never an append to the first: a trace has
    one header. The run log, which appends, is shared by both; the suffix keeps
    the stamp in front so the two still pair by it.
    """
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_EXCL
    candidates = [path, *(path.with_name(f"{path.stem}-{n}{path.suffix}") for n in range(2, 100))]
    for candidate in candidates:
        try:
            return candidate, os.open(candidate, flags, FILE_MODE)
        except FileExistsError:
            continue
    raise FileExistsError(str(path))  # pragma: no cover - a hundred runs in one second


def _locked_write(descriptor: int, data: bytes) -> None:
    """Write one line, whole: `flock` around the writes, and every byte written."""
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)


# --------------------------------------------------------------------------- #
# The process's trace
# --------------------------------------------------------------------------- #

_current: Trace | None = None
_attached: dict[str, Trace] = {}
"""What `current()` attached to, by path: a helper takes two sketches and
writes a move in one process, and each would otherwise re-open and re-read
the file."""


def set_current(trace: Trace | None) -> None:
    """Make `trace` the one this process's helpers and `hermes_env` see."""
    global _current  # ruff: ignore[global-statement] - the process's one open trace
    _current = trace


def reset() -> None:
    """Forget the process's trace and every attached one. For tests."""
    set_current(None)
    for attached in _attached.values():
        attached.close()
    _attached.clear()


def current() -> Trace | None:
    """Return the process's open trace, else the one `DATAPORTER_TRACE` names, else `None`."""
    if _current is not None:
        return _current
    named = os.environ.get(TRACE_ENV_VAR, "").strip()
    if not named:
        return None
    cached = _attached.get(named)
    if cached is not None and not cached.ended:
        return cached
    attached = Trace.attached(Path(named))
    if attached is not None:
        _attached[named] = attached
    return attached


def start(
    settings: "Settings",
    *,
    command: str,
    flags: Sequence[str],
    site: "Site",
    client: "CdpClient | None",
    export_fingerprint: str | None = None,
) -> Trace | None:
    """Open the run's trace and make it current, or warn and return `None`.

    The marks are read here — the browser's version off the port, the agent's
    off `hermes --version` — so that a caller has one call to make.
    """
    try:
        made = Trace.open(
            settings,
            command=command,
            flags=flags,
            site=site,
            chrome=chrome_line(client),
            agent=agent_line(settings),
            export_fingerprint=export_fingerprint,
        )
    except OSError as exc:
        _logger.warning("trace not opened", extra={"command": command, "reason": type(exc).__name__})
        return None
    set_current(made)
    return made


def finish(trace: Trace | None, exit_code: ExitCode | int) -> None:
    """End the run's trace, if there is one, and make none current."""
    if trace is not None:
        trace.end(exit_code)
    if _current is trace:
        set_current(None)


@dataclass
class Opened:
    """What `opened` yields.

    The trace, if it could be made, and the exit code the body sets before it
    leaves. Unset is `0` on a return and `70` on a raise; set, it is what the
    trace's last line says either way.
    """

    trace: Trace | None
    exit_code: ExitCode | int | None = None


@contextmanager
def opened(
    settings: "Settings",
    *,
    command: str,
    flags: Sequence[str],
    site: "Site",
    client: "CdpClient | None",
    export_fingerprint: str | None = None,
) -> Iterator[Opened]:
    """`start` on the way in, `finish` on the way out, whatever happened between."""
    handle = Opened(
        trace=start(
            settings,
            command=command,
            flags=flags,
            site=site,
            client=client,
            export_fingerprint=export_fingerprint,
        )
    )
    try:
        yield handle
    except BaseException:
        # A body that set its code before it left — a generator closed after
        # a failed check — keeps it; one that simply raised is `70`.
        finish(handle.trace, ExitCode.INTERNAL if handle.exit_code is None else handle.exit_code)
        raise
    finish(handle.trace, ExitCode.OK if handle.exit_code is None else handle.exit_code)
