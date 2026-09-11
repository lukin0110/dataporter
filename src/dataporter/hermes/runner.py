"""One Hermes task, as a subprocess, and its answer as a typed result.

A run is: build a minimal environment, start `hermes -p dataporter -z <prompt>`
with its stdout and stderr going straight to files in `<workspace>/hermes/`, wait
with a deadline, then read the last result object out of what it printed.

Three properties are the point:

- **Output goes to files, not through a pipe.** A Hermes transcript contains page
  snapshots, and a page snapshot of claude.ai is conversation content (§10). It is
  a workspace file, read back here to be parsed and never logged, never printed
  and never put in an error message — only its *path* is.
- **A timeout kills the process group, not the process.** Hermes starts its own
  children (its `uv` environment, a browser helper of ours, possibly a browser).
  Killing the leader alone would leave them holding the workspace and the debug
  port. The child gets its own session at spawn so that one `killpg` reaches all
  of them and reaches nothing of ours.
- **The answer is a contract, not prose.** `HermesResult` is what `12`, `13` and
  `19` read. Anything else Hermes printed — and it prints a great deal — is
  transcript, kept in the workspace for an operator and ignored here.

`run` raises rather than returning a failure: every failure this module can have
is a failure of the *mechanism* (Hermes is not there, it was killed, it did not
answer in the agreed shape), and `13`'s retry policy is written against
`HermesError`. A conversation that genuinely could not be migrated comes back as
a perfectly valid result with `outcome: "failed"`.
"""

import json
import os
import re
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from dataporter import log
from dataporter.config import Settings
from dataporter.errors import Category, HermesError, HermesUsageError
from dataporter.hermes.client import HermesCli, hermes_env
from dataporter.steps import Step

_logger = log.get_logger(__name__)

ONE_SHOT_FLAG = "-z"
USAGE_FILE_FLAG = "--usage-file"
TOOLSETS_FLAG = "--toolsets"

REJECTED_EXIT_CODE = 2
"""Hermes's own usage exit code. The invocation was wrong, so retrying it is not
a recovery, it is the same mistake at a later time (`HermesUsageError`)."""

RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
"""What a `run_id` may be. It becomes three filenames, and the ids `12` passes
are derived from an export we do not control, so this is checked rather than
trusted. A `ValueError`, not a `MigrationError`: every caller is our own code."""

NEEDS_HUMAN_REASONS = (
    "auth_required",
    "captcha",
    "security_challenge",
    "ambiguous_ui",
    "browser_error",
    "confirmation_required",
)
"""`14` branches on these. Named here because the literal below cannot be
iterated and `19` has to be able to count them."""


# --------------------------------------------------------------------------- #
# The result contract
# --------------------------------------------------------------------------- #


class HermesErrorInfo(BaseModel):
    """Why a run did not complete, in the error taxonomy `01` fixed."""

    model_config = ConfigDict(extra="ignore")

    category: Category
    detail: str = ""


class HermesResult(BaseModel):
    """The last JSON object Hermes printed, validated.

    `extra="ignore"` rather than `forbid`: the producer is an agent following a
    skill, and a run that did everything right and added a field it found useful
    is a success with a surplus, not a failed migration. The fields that matter
    have no defaults, so a result missing one is still a hard failure.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    outcome: Literal["completed", "partial", "failed", "needs_human", "rate_limited"]
    conversation_id: str | None = None
    last_step: str
    chunks_acked: int = 0
    error: HermesErrorInfo | None = None
    needs_human_reason: (
        Literal[
            "auth_required",
            "captcha",
            "security_challenge",
            "ambiguous_ui",
            "browser_error",
            "confirmation_required",
        ]
        | None
    ) = None
    retry_after_s: int | None = None
    actions: int = 0
    """`browser_*` tool calls Hermes reports making. `19` prefers the count in
    `logs/actions.jsonl`, which is ours; this is what the agent believes."""

    @property
    def step(self) -> Step | None:
        """`last_step` as one of `11`'s steps, or `None` if it is not one.

        The wire field stays a plain string, and this is why: the producer is an
        agent, and a run that did the work and then reported where it got to in
        its own words has still told us the outcome, the id and the count. Losing
        all of that to a validation error over a step name would be the strictness
        `extra="ignore"` exists to avoid.

        What may not be loose is `state.json`: `12` records this, never the raw
        string, so a name no procedure has cannot become the "last successful
        step" `19` prints.
        """
        try:
            return Step(self.last_step)
        except ValueError:
            return None


RESULT_KEY = "outcome"
"""The field that makes an object the result.

Needed because Hermes's transcript contains other people's JSON: our own helpers
print one object per call and Hermes quotes what they printed. "The last JSON
object in stdout" would therefore sometimes be a `browser probe` result. The last
object carrying `outcome` is the result, and if that one does not validate it is
an error rather than a reason to keep looking further back — a malformed final
answer must not be silently replaced by an earlier one.
"""


def json_objects(text: str) -> list[dict[str, Any]]:
    """Every top-level JSON object in `text`, in order, fenced or bare.

    Scanned with `raw_decode` from each `{` rather than with a regular
    expression, because a seed acknowledgement or a skill's own prose can contain
    braces and only a parser knows where an object ends. Nesting is handled for
    free: decoding from the outer brace consumes the inner ones, and the scan
    resumes after the object rather than inside it.
    """
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    index = 0
    while True:
        start = text.find("{", index)
        if start == -1:
            return found
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            index = start + 1
            continue
        if isinstance(value, dict):
            found.append(value)
            index = end
        else:  # pragma: no cover - raw_decode at a `{` returns a dict or raises
            index = start + 1


def last_result_object(text: str) -> dict[str, Any] | None:
    """The last object that claims to be a result, or `None`."""
    candidates = [item for item in json_objects(text) if RESULT_KEY in item]
    return candidates[-1] if candidates else None


# --------------------------------------------------------------------------- #
# What `--usage-file` holds
# --------------------------------------------------------------------------- #


class HermesUsage(BaseModel):
    """Tokens and cost for one run, as much of it as the file happens to give.

    Read opportunistically: `10` records the real shape, and until then this
    looks for the names every agent runtime uses for these three numbers at
    whatever depth they appear. An absent or unreadable file is not an error —
    `19` reports a cost of zero as "not recorded", and a migration is not worth
    failing over an accounting file.
    """

    model_config = ConfigDict(frozen=True)

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def empty(self) -> bool:
        return not (self.input_tokens or self.output_tokens or self.cost_usd)


_INPUT_KEYS = ("input_tokens", "prompt_tokens", "tokens_in", "input")
_OUTPUT_KEYS = ("output_tokens", "completion_tokens", "tokens_out", "output")
_COST_KEYS = ("cost_usd", "total_cost_usd", "cost", "total_cost")


def _find_number(payload: Any, names: Sequence[str], depth: int = 0) -> float:
    """The first number under any of `names`, searched breadth-first-ish.

    Breadth before depth because a runtime that reports both a per-step and a
    total puts the total nearer the top, and the first match wins.
    """
    if depth > 5 or not isinstance(payload, Mapping):
        return 0.0
    for name in names:
        value = payload.get(name)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            return float(value)
    for value in payload.values():
        if isinstance(value, Mapping):
            found = _find_number(value, names, depth + 1)
            if found:
                return found
    return 0.0


def read_usage(path: Path) -> HermesUsage:
    """Parse `--usage-file`. Empty on anything unexpected, never an exception."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return HermesUsage()
    return HermesUsage(
        input_tokens=int(_find_number(payload, _INPUT_KEYS)),
        output_tokens=int(_find_number(payload, _OUTPUT_KEYS)),
        cost_usd=_find_number(payload, _COST_KEYS),
    )


# --------------------------------------------------------------------------- #
# Running one task
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RawRun:
    """A finished Hermes process, before anybody looks for a result in it."""

    run_id: str
    returncode: int
    stdout: str
    """Read back from the file. Content-bearing: never logged, never printed."""
    stdout_path: Path
    stderr_path: Path
    usage_path: Path
    elapsed_s: float

    @property
    def usage(self) -> HermesUsage:
        return read_usage(self.usage_path)


class HermesRunner:
    """Invokes Hermes once per call, in the profile `setup` configured."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cli = HermesCli(settings)

    # -- where a run leaves its files --------------------------------------- #

    @property
    def directory(self) -> Path:
        return self.settings.hermes_dir

    def stdout_path(self, run_id: str) -> Path:
        return self.directory / f"{check_run_id(run_id)}.stdout.txt"

    def stderr_path(self, run_id: str) -> Path:
        return self.directory / f"{check_run_id(run_id)}.stderr.txt"

    def usage_path(self, run_id: str) -> Path:
        return self.directory / f"{check_run_id(run_id)}.usage.json"

    def command(self, prompt: str, *, run_id: str) -> list[str]:
        """Exactly what `09` specifies, with the toolsets from configuration."""
        return [
            str(self.cli.path),
            *self.cli.profile_flags(),
            ONE_SHOT_FLAG,
            prompt,
            TOOLSETS_FLAG,
            ",".join(self.settings.hermes.toolsets),
            USAGE_FILE_FLAG,
            str(self.usage_path(run_id)),
        ]

    # -- the two levels ----------------------------------------------------- #

    def run_raw(self, prompt: str, *, run_id: str, timeout_s: float) -> RawRun:
        """Run a task and hand back what it printed, unvalidated.

        `doctor` uses this: its checks ask Hermes for a nonce rather than for a
        migration result, so there is nothing to validate against the contract.
        """
        check_run_id(run_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        stdout_path = self.stdout_path(run_id)
        stderr_path = self.stderr_path(run_id)
        command = self.command(prompt, run_id=run_id)
        started = time.monotonic()
        _logger.info(
            "hermes run", extra={"run_id": run_id, "timeout_s": round(timeout_s, 1)}
        )
        try:
            with (
                open(stdout_path, "wb") as out,
                open(stderr_path, "wb") as err,
            ):
                process = subprocess.Popen(
                    command,
                    cwd=self.settings.workspace,
                    env=hermes_env(self.settings),
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=err,
                    # Its own process group, so a timeout can end everything the
                    # run started without signalling this process.
                    start_new_session=True,
                )
        except OSError as exc:
            raise HermesUsageError(detail=f"cannot run {self.cli.path}: {exc}") from exc

        try:
            returncode = process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            _kill_group(process)
            raise HermesError(
                detail=f"timeout after {timeout_s:g}s; stdout: {stdout_path}"
            ) from exc
        elapsed = time.monotonic() - started
        _logger.info(
            "hermes finished",
            extra={
                "run_id": run_id,
                "exit_code": returncode,
                "elapsed_s": round(elapsed, 1),
            },
        )
        return RawRun(
            run_id=run_id,
            returncode=returncode,
            stdout=_read_text(stdout_path),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            usage_path=self.usage_path(run_id),
            elapsed_s=elapsed,
        )

    def run(self, prompt: str, *, run_id: str, timeout_s: float) -> HermesResult:
        """One Hermes task, reduced to the result contract.

        The exit code is read before the output is. Hermes exiting `2` means it
        never ran the task, so there is no point looking for a result; any other
        non-zero exit is reported only when no valid result was printed, because
        an agent that said `outcome: "failed"` and then exited non-zero has
        already told us everything we wanted to know.
        """
        raw = self.run_raw(prompt, run_id=run_id, timeout_s=timeout_s)
        if raw.returncode == REJECTED_EXIT_CODE:
            raise HermesUsageError(
                detail=f"hermes rejected the invocation (exit "
                f"{REJECTED_EXIT_CODE}); stderr: {raw.stderr_path}"
            )
        payload = last_result_object(raw.stdout)
        if payload is None:
            raise HermesError(
                detail=f"no result json; stdout: {raw.stdout_path}"
                + (f" (hermes exited {raw.returncode})" if raw.returncode != 0 else "")
            )
        try:
            result = HermesResult.model_validate(payload)
        except ValidationError as exc:
            raise HermesError(
                detail=f"invalid result json: {_first_problem(exc)}; "
                f"stdout: {raw.stdout_path}"
            ) from exc
        _logger.info(
            "hermes result",
            extra={
                "run_id": run_id,
                "outcome": result.outcome,
                "last_step": result.last_step,
                "chunks_acked": result.chunks_acked,
            },
        )
        return result


def check_run_id(run_id: str) -> str:
    """The run id, if it is one. It becomes a filename, so it is checked."""
    if RUN_ID.fullmatch(run_id) is None:
        raise ValueError(f"not a usable run id: {run_id!r}")
    return run_id


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    """End the run and everything it started, then reap it.

    `SIGKILL` and not `SIGTERM`: the deadline has already passed, Hermes has had
    its time, and a process group that ignores a polite signal would hold the
    next conversation's turn as well as this one's.
    """
    try:
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:  # pragma: no cover - posix only
            process.kill()
    except OSError:  # pragma: no cover - it exited between the wait and here
        # `ProcessLookupError` is an `OSError`, so one clause covers both the
        # group having gone and the pid having gone. The fallback cannot raise
        # it back: `Popen.send_signal` polls first, returns early once the
        # process is reaped, and suppresses the lookup error from `os.kill`
        # itself (bpo-40550).
        process.kill()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover - killed and unreaped
        _logger.warning("hermes did not exit after being killed")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:  # pragma: no cover - we just wrote it
        return ""


def _first_problem(exc: ValidationError) -> str:
    """One line about the first validation failure. Field names, never values."""
    errors = exc.errors()
    if not errors:  # pragma: no cover - pydantic always reports at least one
        return "does not match the result contract"
    first = errors[0]
    location = ".".join(str(item) for item in first["loc"]) or "(root)"
    return f"{location}: {first['msg']}"
