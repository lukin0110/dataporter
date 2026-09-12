"""The scripted agent, packaged as a `hermes` executable.

§23: *whatever stands where Hermes stands* for a rehearsal is the model-free
procedure the tool's own tests already have, packaged as a `hermes` on the path.
This module is that package. It answers the calls `09` makes on the real Hermes —
a version, a profile, a configuration — and performs every one-shot task the
tool sends, by driving the same Chrome and calling the real helpers.

What makes it worth more than a stub that prints a result object:

- it is a **real process**, started by the real runner, with the environment `09`
  built and the working directory `09` chose, so the subprocess contract is
  exercised rather than asserted;
- it **keeps a profile**, so `setup` really does create one and `doctor` really
  does read back what `setup` set — including the CDP url it is then expected to
  attach to, which is where it finds the browser;
- it **performs the procedure**, from the rendered prompt and nothing else: no
  seed, no part count and no ack line reaches it except through the prompt and
  the files the prompt names.

The three procedures themselves are imported where they are used rather than at
the top of the file, because they live in the tool's *test* tree — that is where
§23 puts them, and it is the tree that already drives them against a fake page —
and a module that could not be imported without it would make writing the
executable depend on having it on the path.

What it is not is an agent. It cannot decide, it cannot recover from a page
nobody anticipated, and a rehearsal is therefore no evidence at all about
whether a model can follow the skill (§27). That is the pilot's question.
"""

import json
import os
import re
import shlex
import stat
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dataporter.browser.cdp import CdpClient
from dataporter.hermes.profile import MODEL_KEYS
from rehearsal.agent import (
    AgentError,
    CdpBrowser,
    CdpSignInBrowser,
    Driver,
    HelperRunner,
    last_json_object,
)

VERSION = "1.0.0"
"""What `--version` prints, as `hermes 1.0.0`. Above `09`'s minimum, and a
version of *this*, not a claim about the real Hermes — the rehearsal record
names both."""

MODEL = "none/scripted-agent"
"""What `doctor`'s `hermes model` line reports. A profile with no model
configured is a failed check, and a rehearsal has no model at all — so the value
says exactly that rather than naming one that is not there."""

STATE_ENV_VAR = "REHEARSAL_HERMES_STATE"
"""Where the profile lives. An environment variable rather than an argument
because the tool builds the whole command line, and a flag it does not pass
would never arrive."""

NONCE = re.compile(r"DATAPORTER-[0-9A-F]+")
CDP_URL = re.compile(r"https?://127\.0\.0\.1:(\d+)")

BLANK_URL = "about:blank"

USAGE_FILE_FLAG = "--usage-file"
TOOLSETS_FLAG = "--toolsets"
ONE_SHOT_FLAG = "-z"

NO_TOKENS = {"input_tokens": 0, "output_tokens": 0, "total_cost_usd": 0.0}
"""What a run with no model costs. Written to `--usage-file` because the runner
reads it, and zero is the honest number."""


# --------------------------------------------------------------------------- #
# The profile
# --------------------------------------------------------------------------- #


@dataclass
class Profiles:
    """The profiles and configuration a `hermes` keeps between invocations."""

    path: Path

    def load(self) -> dict[str, Any]:
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"profiles": [], "config": {}}
        return loaded if isinstance(loaded, dict) else {"profiles": [], "config": {}}

    def save(self, state: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(dict(state), indent=2), encoding="utf-8")

    def config(self) -> dict[str, str]:
        """What `config show` reports: what was set, plus the model.

        The model key is added here rather than by `setup`, because `setup` never
        sets one — `09` leaves it to the operator, and an operator rehearsing has
        nothing to set it to.
        """
        stored = {str(k): str(v) for k, v in self.load().get("config", {}).items()}
        stored.setdefault(MODEL_KEYS[0], MODEL)
        return stored


def rendered(config: Mapping[str, str]) -> str:
    """A configuration as `hermes config show` prints it: one dotted key a line.

    The flat shape, which is one of the three `client.parse_config` reads. `10`
    records which one the real Hermes uses; until it does, a rehearsal proves the
    parser against the simplest of them.
    """
    return "".join(f"{key}: {config[key]}\n" for key in sorted(config))


# --------------------------------------------------------------------------- #
# The one-shot tasks
# --------------------------------------------------------------------------- #


def perform(prompt: str, *, config: Mapping[str, str]) -> str:
    """Whatever this prompt is asking for, done, as the text to print.

    Dispatched on what the prompt *contains*, exactly as an agent would have to:
    each of the tool's five tasks names a different field, and a prompt that
    names none of them is not a task this agent knows how to do.
    """
    if "question file:" in prompt:
        return json.dumps(probe_task(prompt, config=config))
    if "short_id:" in prompt:
        return json.dumps(migration_task(prompt, config=config))
    if "login url:" in prompt:
        return json.dumps(sign_in_task(prompt, config=config))
    if "remote debugging on" in prompt:
        return attach_task(prompt)
    if "terminal tool to run exactly this command" in prompt:
        return helper_task(prompt)
    raise AgentError("the prompt is not a task this agent knows")


def driver_for(config: Mapping[str, str]) -> Driver:
    """The Chrome the profile points at — which is how a rehearsal proves that
    `browser.cdp_url` is what an agent attaches by."""
    url = config.get("browser.cdp_url", "")
    found = CDP_URL.search(url)
    if found is None:
        raise AgentError(f"no usable browser.cdp_url in the profile: {url!r}")
    return Driver(client=CdpClient(port=int(found.group(1)), timeout=30.0))


def migration_task(prompt: str, *, config: Mapping[str, str]) -> dict[str, Any]:
    """`11`'s procedure, against the page the prompt's helper commands read."""
    from fake_agent import ScriptedAgent

    agent = ScriptedAgent(helper=HelperRunner(), browser=CdpBrowser(driver_for(config)))
    return agent.run(prompt)


def sign_in_task(prompt: str, *, config: Mapping[str, str]) -> dict[str, Any]:
    """`24`'s agent half: reach the form, and stop at it. No credential is here,
    and none is passed to this process — the tool types them itself."""
    from fake_agent import ScriptedSignIn

    return ScriptedSignIn(CdpSignInBrowser(driver_for(config))).run(prompt)


def probe_task(prompt: str, *, config: Mapping[str, str]) -> dict[str, Any]:
    """`20`'s follow-up probe: one question, in one chat this run created."""
    from fake_agent import ScriptedProbe

    prober = ScriptedProbe(
        helper=HelperRunner(), browser=CdpBrowser(driver_for(config))
    )
    return prober.run(prompt)


def attach_task(prompt: str) -> str:
    """`doctor`'s first Hermes check: attach, snapshot one tab, name the other.

    The check is deliberately hard to fake — naming the other tab's URL requires
    having listed the targets on the tool's own debug port — and this passes it
    the way it is meant to be passed: by doing that.
    """
    found = CDP_URL.search(prompt)
    if found is None:
        raise AgentError("no cdp url in the attach prompt")
    client = CdpClient(port=int(found.group(1)), timeout=30.0)
    tabs = client.pages()
    blank = [tab for tab in tabs if tab.url == BLANK_URL]
    if not blank:
        raise AgentError(f"no {BLANK_URL} tab to snapshot")
    page = client.attach(blank[0].id)
    try:
        page.evaluate("document.readyState")  # the snapshot, such as it is
    finally:
        page.close()
    others = [tab.url for tab in tabs if tab.url != BLANK_URL]
    if not others:
        raise AgentError("there is no other tab")
    return f"{nonce_in(prompt)}\n{others[0]}\n"


def helper_task(prompt: str) -> str:
    """`doctor`'s second: run one helper through the terminal, report its `ok`."""
    command = command_in(prompt)
    finished = subprocess.run(  # noqa: S603 - the command the prompt named
        command, capture_output=True, text=True, check=False
    )
    printed = last_json_object(finished.stdout) or {}
    return f"{nonce_in(prompt)}\n{json.dumps(printed.get('ok'))}\n"


def nonce_in(prompt: str) -> str:
    found = NONCE.search(prompt)
    if found is None:
        raise AgentError("no nonce in the prompt")
    return found.group()


def command_in(prompt: str) -> list[str]:
    """The indented command line `doctor`'s helper prompt holds."""
    for line in prompt.splitlines():
        if line.startswith("  ") and line.strip():
            return shlex.split(line.strip())
    raise AgentError("no command in the prompt")


# --------------------------------------------------------------------------- #
# The executable
# --------------------------------------------------------------------------- #

BODY = """\
#!{python}
\"\"\"A `hermes` that is not Hermes: `27`'s scripted agent, on the path.\"\"\"

import os
import sys

sys.path[:0] = {paths!r}
os.environ.setdefault({state_var!r}, {state!r})

from rehearsal.hermes import main

sys.exit(main(sys.argv[1:]))
"""


def write_executable(directory: Path, *, repo: Path, state: Path) -> Path:
    """Write a `hermes` into `directory` and make it executable.

    Generated rather than shipped, for the reason `fake_hermes` is generated: it
    has to carry the interpreter that can import this package and the path of the
    profile it keeps, and a checked-in script would have to discover both.
    """
    directory.mkdir(parents=True, exist_ok=True)
    executable = directory / "hermes"
    executable.write_text(
        BODY.format(
            python=sys.executable,
            paths=[str(repo), str(repo / "src"), str(repo / "tests")],
            state_var=STATE_ENV_VAR,
            state=str(state),
        ),
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IEXEC)
    return executable


def main(argv: Sequence[str]) -> int:
    """The five calls `09` makes, and the one-shot it makes them for."""
    arguments = list(argv)
    profiles = Profiles(
        Path(os.environ.get(STATE_ENV_VAR) or Path.home() / ".hermes-scripted.json")
    )

    if "--version" in arguments:
        sys.stdout.write(f"hermes {VERSION}\n")
        return 0

    state = profiles.load()
    if arguments[:2] == ["profile", "list"]:
        sys.stdout.write("".join(f"{name}\n" for name in state["profiles"]))
        return 0
    if arguments[:2] == ["profile", "create"]:
        if arguments[2] not in state["profiles"]:
            state["profiles"].append(arguments[2])
        profiles.save(state)
        return 0

    rest = arguments[2:] if arguments[:1] == ["-p"] else arguments
    if rest[:2] == ["config", "set"]:
        state["config"][rest[2]] = rest[3]
        profiles.save(state)
        return 0
    if rest[:2] == ["config", "show"]:
        sys.stdout.write(rendered(profiles.config()))
        return 0

    if ONE_SHOT_FLAG in rest:
        return one_shot(rest, profiles)

    sys.stderr.write(f"unknown hermes command: {' '.join(arguments)}\n")
    return 2


def one_shot(rest: Sequence[str], profiles: Profiles) -> int:
    """`hermes -z <prompt>`: do the task, print the answer, and account for it."""
    arguments = list(rest)
    prompt = arguments[arguments.index(ONE_SHOT_FLAG) + 1]
    if USAGE_FILE_FLAG in arguments:
        Path(arguments[arguments.index(USAGE_FILE_FLAG) + 1]).write_text(
            json.dumps(NO_TOKENS), encoding="utf-8"
        )
    started = time.monotonic()
    try:
        answer = perform(prompt, config=profiles.config())
    except AgentError as failure:
        # What a Hermes that could not do the task prints: a result object with
        # an outcome the runner's contract knows, and no page text in it.
        sys.stdout.write(
            json.dumps(
                {
                    "outcome": "failed",
                    "conversation_id": None,
                    "last_step": "open",
                    "chunks_acked": 0,
                    "error": {"category": "hermes", "detail": str(failure)},
                }
            )
            + "\n"
        )
        return 0
    sys.stdout.write(answer if answer.endswith("\n") else answer + "\n")
    sys.stderr.write(f"scripted agent: {time.monotonic() - started:.1f}s\n")
    return 0
