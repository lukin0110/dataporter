"""Shelling out to the `hermes` on `PATH`.

Hermes is a subprocess, never an import (`09`): it lives in its own `uv`
environment under `~/.hermes/hermes-agent/`, `-z` is its documented programmatic
mode, and importing it would couple this tool to its internals and its Python
version.

This module is the narrow part of that: finding the executable, running it with
an environment we built rather than inherited, and reading back the two kinds of
output `setup` and `doctor` need — a version string and a profile's
configuration. `runner` does the one thing this does not: a long `-z` task whose
output is large, may contain conversation content, and therefore goes to files in
the workspace instead of through a pipe into this process.

## The environment

Every Hermes process starts from `hermes_env()`: `PATH`, `HOME` and `LANG`
forwarded when the parent has them, `DATAPORTER_WORKSPACE` set to the absolute
workspace, and nothing else. Two reasons, and they point the same way:

- `HERMES_YOLO_MODE` cannot be set, by construction rather than by a check,
  because the variable never reaches the child. `09` says the approval layer
  denies what it flags; an inherited variable that turns approvals off would
  make that promise depend on the operator's shell.
- `DATAPORTER_WORKSPACE` has to be set, not merely allowed. The runner uses
  `cwd=<workspace>`, so a helper Hermes invokes as
  `dataporter browser probe` with no `--workspace` would resolve the
  default `./migration` *inside* the workspace — a second workspace, with its own
  config and its own actions log, one level down. `11`'s prompt passes the flag
  as well; this makes forgetting it harmless rather than silently wrong.
"""

import os
import shlex
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from dataporter import log
from dataporter.config import Settings
from dataporter.errors import HermesError, HermesUsageError
from dataporter.hermes import version as versioning

_logger = log.get_logger(__name__)

HERMES_EXECUTABLE = "hermes"
"""What to look for on `PATH` when `hermes.executable` is unset."""

PASSED_THROUGH_ENV: tuple[str, ...] = ("PATH", "HOME", "LANG")
"""Inherited when the parent has them. `PATH` so Hermes can find its own
interpreter and our helper commands, `HOME` so it can find its profile and its
`.env`, `LANG` so its output is UTF-8 on a system whose default is not."""

WORKSPACE_ENV_VAR = "DATAPORTER_WORKSPACE"
"""Set, not forwarded. See the module docstring."""

INSTALL_HINT = (
    "hermes not found — install the Hermes Agent, or set hermes.executable in the "
    "workspace config.toml"
)


def hermes_env(settings: Settings) -> dict[str, str]:
    """The complete environment every Hermes subprocess gets."""
    env = {name: os.environ[name] for name in PASSED_THROUGH_ENV if name in os.environ}
    env[WORKSPACE_ENV_VAR] = str(settings.workspace)
    return env


@dataclass(frozen=True)
class Completed:
    """One finished `hermes` invocation whose output fits in memory."""

    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def failure(self) -> str:
        """Why it failed, in one line, for a `doctor` line or an error detail.

        The last non-empty line of stderr, falling back to stdout and then to the
        exit code: a CLI that explains itself puts the explanation last, after
        whatever it had already printed.
        """
        for stream in (self.stderr, self.stdout):
            lines = [item.strip() for item in stream.splitlines() if item.strip()]
            if lines:
                return log.safe_token(lines[-1])
        return f"exited {self.returncode}"


class HermesCli:
    """The `hermes` executable, as the handful of calls `09` makes on it.

    Stateless apart from the resolved path, which is looked up once: `doctor`
    makes five calls in a row and a `PATH` that changes underneath them would be
    a stranger problem than the one the lookup is solving.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._path: Path | None = None

    # -- invocation --------------------------------------------------------- #

    @property
    def path(self) -> Path:
        """Where `hermes` is. Raises `HermesUsageError` when it is nowhere.

        `shutil.which` for a configured value too, so a bare name and an absolute
        path are resolved the same way and both are checked for being executable
        — the rule `browser.launcher.find_executable` already follows.
        """
        if self._path is not None:
            return self._path
        configured = self.settings.hermes.executable
        candidate = (
            str(Path(configured).expanduser())
            if configured is not None
            else HERMES_EXECUTABLE
        )
        found = shutil.which(candidate)
        if found is None:
            detail = (
                f"configured hermes executable not found: {configured}"
                if configured is not None
                else INSTALL_HINT
            )
            raise HermesUsageError(detail=detail)
        self._path = Path(found)
        return self._path

    @property
    def profile(self) -> str:
        return self.settings.hermes.profile

    def profile_flags(self) -> tuple[str, ...]:
        return ("-p", self.profile)

    def run(self, *args: str, timeout_s: float | None = None) -> Completed:
        """Run `hermes <args>` and capture both streams.

        For the short, metadata-shaped calls only. The cwd is inherited rather
        than set to the workspace, because `setup` runs before a workspace
        necessarily exists and none of these calls reads a file from it.
        """
        command = (str(self.path), *args)
        limit = self.settings.timeouts.hermes_cli_s if timeout_s is None else timeout_s
        # `call`, not `args`: `args` is a `LogRecord` attribute and `logging`
        # refuses an `extra` that would overwrite one.
        _logger.debug("hermes call", extra={"call": " ".join(args)})
        try:
            finished = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=hermes_env(self.settings),
                stdin=subprocess.DEVNULL,
                timeout=limit,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise HermesError(
                detail=f"hermes {args[0] if args else ''} timed out after {limit:g}s"
            ) from exc
        except OSError as exc:
            raise HermesUsageError(detail=f"cannot run {self.path}: {exc}") from exc
        return Completed(
            command=command,
            returncode=finished.returncode,
            stdout=finished.stdout or "",
            stderr=finished.stderr or "",
        )

    def checked(self, *args: str, timeout_s: float | None = None) -> Completed:
        """`run`, but a non-zero exit is a `HermesUsageError`.

        For the calls `setup` makes, where a failure means the profile is not in
        the state the rest of `setup` assumes and continuing would leave it half
        configured.
        """
        finished = self.run(*args, timeout_s=timeout_s)
        if not finished.ok:
            raise HermesUsageError(
                detail=f"hermes {' '.join(args)}: {finished.failure}"
            )
        return finished

    # -- the calls ---------------------------------------------------------- #

    def version(self) -> tuple[int, ...]:
        """The installed version. Raises when it cannot be read or parsed."""
        finished = self.checked("--version")
        parsed = versioning.parse_version(finished.stdout or finished.stderr)
        if parsed is None:
            raise HermesUsageError(
                detail=f"cannot read a version from: {finished.failure}"
            )
        return parsed

    def profiles(self) -> list[str]:
        """The profile names `hermes profile list` reports."""
        return parse_profile_list(self.checked("profile", "list").stdout)

    def create_profile(self) -> None:
        self.checked("profile", "create", self.profile)

    def config_set(self, key: str, value: str) -> None:
        self.checked(*self.profile_flags(), "config", "set", key, value)

    def config_show_text(self) -> str:
        """`config show`, verbatim. `09`'s idempotence test compares these."""
        return self.checked(*self.profile_flags(), "config", "show").stdout

    def config(self) -> dict[str, str]:
        """The profile's configuration, flattened to dotted keys."""
        return parse_config(self.config_show_text())


# --------------------------------------------------------------------------- #
# Reading what the CLI prints
# --------------------------------------------------------------------------- #

_LIST_MARKERS = "*-•>"
"""Leading decoration a `profile list` line may carry for the active profile."""


def parse_profile_list(text: str) -> list[str]:
    """Profile names out of `hermes profile list`.

    Lenient on purpose: the output may be a bare list, a bulleted one, or one
    with the active profile marked and annotated. The first whitespace-separated
    token of a line, with leading decoration removed, is the name; a line whose
    token ends in `:` is a heading and not a profile.
    """
    names: list[str] = []
    for line in text.splitlines():
        stripped = line.strip().lstrip(_LIST_MARKERS).strip()
        if not stripped:
            continue
        token = stripped.split()[0]
        if token.endswith(":") or token.startswith("("):
            continue
        names.append(token)
    return names


def parse_config(text: str) -> dict[str, str]:
    """`hermes -p … config show`, flattened to `{"browser.backend": "off"}`.

    Hermes's config is YAML and `config show` may print it nested, flat with
    dotted keys, or as `key = value`; `10` records which. Rather than guess, this
    reads all three: indentation opens a prefix, a dotted key is kept as typed,
    and a value-less key is a parent rather than an empty string.

    Deliberately not a YAML parser. Nothing here needs lists, multi-line strings
    or anchors — two keys are read, `browser.backend` and `browser.cdp_url`, plus
    whichever one names the model — and a real parser would mean a dependency
    `01` did not take for the export itself.
    """
    flat: dict[str, str] = {}
    stack: list[tuple[int, str]] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line.strip().startswith("-"):
            continue  # a list item: no key, nothing to flatten it under
        indent = len(line) - len(line.lstrip())
        key, separator, value = _split_setting(line.strip())
        if not separator:
            continue
        while stack and stack[-1][0] >= indent:
            stack.pop()
        prefix = ".".join(name for _, name in stack)
        dotted = f"{prefix}.{key}" if prefix else key
        cleaned = _unquote(value.strip())
        if cleaned:
            flat[dotted] = cleaned
        else:
            stack.append((indent, key))
    return flat


def _split_setting(text: str) -> tuple[str, str, str]:
    """`key: value` or `key = value`, whichever comes first."""
    colon = text.find(":")
    equals = text.find("=")
    if colon == -1 and equals == -1:
        return text, "", ""
    if colon != -1 and (equals == -1 or colon < equals):
        return text[:colon].strip(), ":", text[colon + 1 :]
    return text[:equals].strip(), "=", text[equals + 1 :]


def _unquote(value: str) -> str:
    """Strip one layer of matching quotes, and a trailing comment."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    head = value.split(" #", 1)[0].strip()
    return head


def mismatches(config: Mapping[str, str], expected: Mapping[str, str]) -> list[str]:
    """The keys of `expected` the profile does not agree with, described.

    Compared case-insensitively, because `off`, `Off` and `"off"` are all things
    a YAML round trip may hand back for a key we set to `off`. The description is
    what a `doctor` FAIL line says, so it names the key, what is there and what
    was wanted — an operator re-runs `setup` on the strength of that line alone.
    """
    wrong: list[str] = []
    for key, value in expected.items():
        found = config.get(key)
        if found is None:
            wrong.append(f"{key} unset, expected {value}")
        elif found.casefold() != value.casefold():
            wrong.append(f"{key}={log.safe_token(found)}, expected {value}")
    return wrong


def home_relative(path: Path) -> str:
    """`~/.hermes/profiles/…` rather than the operator's name on every line.

    Here rather than in either caller because both `setup` and `doctor` print
    paths under the operator's home — Hermes keeps everything there — and `doctor`
    imports `profile` rather than the other way round. Still copy-pasteable into a
    shell, which is the point of `~` over a truncation.
    """
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


def quoted(command: Sequence[str]) -> str:
    """A command as a prompt can show it, quoted so a path with a space survives."""
    return shlex.join(command)
