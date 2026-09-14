"""A `hermes` that is not Hermes.

`09` shells out to an external agent nobody can install in CI, so the tests give
it one: a generated Python script on `PATH` named `hermes`, which answers the five
calls our code makes (`--version`, `profile list`, `profile create`, `config set`,
`config show`) and pretends to run a one-shot task.

Two properties make it worth more than a stub of `subprocess`:

- it is a **real process**, so the environment allowlist, the working directory,
  the output files and the process-group kill are exercised as they will be in
  production rather than asserted against a mock's call record;
- it **keeps state**, so `setup` run twice really does meet a profile that already
  exists, and `config show` really does report what `config set` was given —
  which is what `09`'s idempotence criterion is about.

Every invocation is appended to `calls.jsonl` with its argv, its environment and
its working directory. A test reads that instead of trusting what the fake says.
"""

import json
import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NONCE_PLACEHOLDER = "__NONCE__"
"""What `spec["answer"]` may contain; the fake replaces it with the nonce it
found in the prompt. `doctor` mints a fresh nonce per run, so a test cannot write
one into the answer up front."""

_BODY = """
import json
import os
import re
import sys
import time
from pathlib import Path

SPEC = Path("__SPEC__")
STATE = Path("__STATE__")
CALLS = Path("__CALLS__")


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


spec = load(SPEC, {})
state = load(STATE, {"profiles": [], "config": {}})
argv = sys.argv[1:]

CALLS.parent.mkdir(parents=True, exist_ok=True)
with CALLS.open("a", encoding="utf-8") as handle:
    handle.write(
        json.dumps({"argv": argv, "env": dict(os.environ), "cwd": os.getcwd()}) + "\\n"
    )


def save():
    STATE.write_text(json.dumps(state), encoding="utf-8")


def merged():
    config = dict(state["config"])
    config.update(spec.get("config_extra", {}))
    for key in spec.get("config_drop", []):
        config.pop(key, None)
    return config


def displayed(config):
    # What the real `hermes config show` prints, in shape: a decorated display
    # with capitalised labels, and the model as a dict repr rather than a value.
    # `59` observed it. The fake prints it so that nothing in the tool can
    # quietly go back to parsing a screen.
    lines = ["", "  Hermes Configuration", "", "* Model"]
    model = config.get("model.default")
    if model is not None:
        lines.append("  Model:        {'default': '" + model + "', 'provider': 'custom'}")
    for key in sorted(config):
        if key == "model.default":
            continue
        label = key.rsplit(".", 1)[-1].replace("_", " ").capitalize()
        lines.append("  " + label + ":        " + config[key])
    return "\\n".join(lines) + "\\n"


if "--version" in argv:
    sys.stdout.write(spec.get("version", "hermes 9.9.9") + "\\n")
    sys.exit(spec.get("version_exit", 0))

if argv[:2] == ["profile", "list"]:
    # The column table the real one prints: a header, a rule, then a row a
    # profile with the active one marked. `59` observed it.
    rows = [" Profile        Model", " " + "─" * 15 + "    " + "─" * 20]
    for index, name in enumerate(state["profiles"]):
        rows.append(" " + ("◆" if index == 0 else " ") + name + "      a/model")
    sys.stdout.write("\\n".join(rows) + "\\n")
    sys.exit(spec.get("list_exit", 0))

if argv[:2] == ["profile", "create"]:
    if argv[2] not in state["profiles"]:
        state["profiles"].append(argv[2])
    save()
    sys.exit(spec.get("create_exit", 0))

rest = argv[2:] if argv[:1] == ["-p"] else argv

if rest[:2] == ["config", "set"]:
    state["config"][rest[2]] = rest[3]
    save()
    sys.exit(spec.get("set_exit", 0))

if rest[:2] == ["config", "show"]:
    sys.stdout.write(spec.get("config_show", displayed(merged())))
    sys.exit(spec.get("show_exit", 0))

if rest[:2] == ["config", "get"]:
    value = merged().get(rest[2])
    if value is None:
        # What Hermes does for a key it has not got, exit `0` included.
        sys.stdout.write("Config key not set: " + rest[2] + "\\n")
    else:
        sys.stdout.write(json.dumps(value) + "\\n")
    sys.exit(spec.get("get_exit", 0))

if "-z" in rest:
    index = rest.index("-z")
    prompt = rest[index + 1] if len(rest) > index + 1 else ""
    if spec.get("child"):
        # A grandchild in this process group, which writes a file a few seconds
        # from now. `09` kills the group rather than the leader, so the file is
        # what proves the kill reached further than the process we started: if it
        # appears, something survived. Deliberately a *negative* signal — no pid
        # to inspect, so nothing here depends on who reaps a zombie.
        code = (
            "import sys, time; "
            "time.sleep(float(sys.argv[2])); "
            "open(sys.argv[1], 'w').write('survived')"
        )
        delay = str(spec.get("child_delay", 3))
        os.spawnv(
            os.P_NOWAIT,
            sys.executable,
            [sys.executable, "-c", code, spec["child"], delay],
        )
    usage = spec.get("usage")
    if usage is not None and "--usage-file" in rest:
        Path(rest[rest.index("--usage-file") + 1]).write_text(
            json.dumps(usage), encoding="utf-8"
        )
    if spec.get("append_probe"):
        # What our own `browser probe` would have written. The workspace comes
        # from DATAPORTER_WORKSPACE, so a test that breaks the allowlist breaks here.
        actions = Path(os.environ["DATAPORTER_WORKSPACE"]) / "logs" / "actions.jsonl"
        actions.parent.mkdir(parents=True, exist_ok=True)
        with actions.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps({"helper": "probe", "ok": True, "elapsed_ms": 1}) + "\\n"
            )
    delay = float(spec.get("sleep", 0))
    if delay:
        time.sleep(delay)
    # Which one-shot this is. `answers` and `exits` are indexed by it, so a test
    # can make the first `doctor` task succeed and the second one fail.
    done = sum(
        1
        for line in CALLS.read_text(encoding="utf-8").splitlines()
        if line.strip() and "-z" in json.loads(line)["argv"]
    )


    def nth(values, fallback):
        if not values:
            return fallback
        return values[min(done - 1, len(values) - 1)]

    found = re.search(r"DATAPORTER-[0-9A-F]+", prompt)
    answer = nth(spec.get("answers"), spec.get("answer", ""))
    answer = answer.replace("__NONCE__", found.group() if found else "NO-NONCE")
    sys.stdout.write(answer)
    sys.stderr.write(spec.get("stderr", ""))
    sys.exit(nth(spec.get("exits"), spec.get("exit", 0)))

sys.stderr.write("unknown hermes command: " + " ".join(argv) + "\\n")
sys.exit(2)
"""


@dataclass
class Call:
    """One invocation of the fake, as it saw itself."""

    argv: list[str]
    env: dict[str, str]
    cwd: str

    @property
    def one_shot(self) -> bool:
        return "-z" in self.argv

    @property
    def prompt(self) -> str:
        return self.argv[self.argv.index("-z") + 1]

    def flag(self, name: str) -> str:
        return self.argv[self.argv.index(name) + 1]


@dataclass
class FakeHermes:
    """A generated `hermes` executable and the files that drive it."""

    root: Path
    spec: dict[str, Any] = field(default_factory=dict)

    @property
    def executable(self) -> Path:
        return self.root / "hermes"

    @property
    def spec_path(self) -> Path:
        return self.root / "spec.json"

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    @property
    def calls_path(self) -> Path:
        return self.root / "calls.jsonl"

    def write(self, **spec: Any) -> "FakeHermes":
        """Create or re-point the fake. Later calls replace the spec outright."""
        self.root.mkdir(parents=True, exist_ok=True)
        self.spec = dict(spec)
        self.spec_path.write_text(json.dumps(self.spec), encoding="utf-8")
        body = (
            _BODY
            .replace("__SPEC__", str(self.spec_path))
            .replace("__STATE__", str(self.state_path))
            .replace("__CALLS__", str(self.calls_path))
        )
        self.executable.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        self.executable.chmod(self.executable.stat().st_mode | stat.S_IEXEC)
        return self

    def with_profile(self, name: str, **config: str) -> "FakeHermes":
        """Pretend `setup` has already run once."""
        self.state_path.write_text(json.dumps({"profiles": [name], "config": dict(config)}), encoding="utf-8")
        return self

    @property
    def profiles(self) -> list[str]:
        return self._state()["profiles"]

    @property
    def config(self) -> dict[str, str]:
        return self._state()["config"]

    def _state(self) -> dict[str, Any]:
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"profiles": [], "config": {}}
        return loaded

    @property
    def calls(self) -> list[Call]:
        try:
            lines = self.calls_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        return [Call(**json.loads(line)) for line in lines if line.strip()]

    @property
    def one_shots(self) -> list[Call]:
        return [call for call in self.calls if call.one_shot]

    def on_path(self, monkeypatch: Any) -> "FakeHermes":
        """Put the fake first on `PATH`, for the lookup `doctor` does."""
        monkeypatch.setenv("PATH", f"{self.root}{os.pathsep}{os.environ['PATH']}")
        return self
