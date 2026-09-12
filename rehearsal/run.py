"""The rehearsal: §23's protocol, §25's pass criteria, §26's record.

One command runs the whole thing. It prepares a workspace an operator could have
prepared by hand — the export, a `config.toml` whose `[browser] extra_args` are
the ones the mock printed, and a `hermes` on the path — and then runs the shipped
tool through the full run's protocol against the mock, black-box, as a
subprocess.

Three rules it is written to keep:

- **The tool is the shipped tool.** Every step is an invocation of the installed
  command with flags an operator may type. Nothing here reaches inside it, and
  nothing it does tells it that the site is a mock (§22, ADR 0001).
- **The ledger is the witness.** What the tool reports about itself is checked
  against what the mock counted, because nothing in the tool can tell a rehearsal
  from a real run (§25).
- **A claim without a number is not a record.** What it prints and what it writes
  is numbers with marks on them, and the pass criteria are computed rather than
  asserted in prose (§26).

What it does **not** do is start the mock or a browser. The mock is a separate
process the operator starts, as Chrome is; the tool launches Chrome itself.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rehearsal import export as exporting
from rehearsal.hermes import VERSION as AGENT_VERSION
from rehearsal.hermes import write_executable

PROGRAM = "hermes-claude-migrate"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8443

EMAIL = "rehearsal@example.invalid"
PASSWORD = "rehearsal-not-a-real-password"
"""The credentials the mock is configured with by default. Invented, and
`.invalid` can never name a real mailbox (§23)."""

LEDGER_PATH = "/__mock/ledger.json"

STEP_TIMEOUT_S = 1_800.0

DRILL_TIMEOUT_S = 300.0
DRILL_POLL_S = 0.5
"""The interruption drill: how long to wait for the run to be mid-conversation
before killing it, and how often to look."""


# --------------------------------------------------------------------------- #
# Reaching the mock
# --------------------------------------------------------------------------- #


def spki_pin(host: str, port: int) -> str:
    """The mock's key, as Chrome's `--ignore-certificate-errors-spki-list` wants.

    Computed from the certificate the mock is actually serving rather than read
    out of the mock's own files, so that this stays true when the mock moves to
    its own repository — and so that a rehearsal is pinned to the key of the
    process it is really talking to. It is the same string the mock printed.
    """
    pem = ssl.get_server_certificate((host, port))
    der = ssl.PEM_cert_to_DER_cert(pem)
    certificate = _public_key_der(der)
    return base64.b64encode(hashlib.sha256(certificate).digest()).decode("ascii")


def _public_key_der(certificate_der: bytes) -> bytes:
    """The SubjectPublicKeyInfo out of a DER certificate.

    `cryptography` is the mock's dependency, not this package's, and it is
    already installed in the workspace it rehearses; importing it here rather
    than at the top keeps a rehearsal's other commands runnable without it.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    loaded = x509.load_der_x509_certificate(certificate_der)
    return loaded.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def ledger(host: str, port: int) -> dict[str, int]:
    """The mock's count, now."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    url = f"https://{host}:{port}{LEDGER_PATH}"
    with urllib.request.urlopen(url, context=context, timeout=30) as answer:
        loaded = json.loads(answer.read().decode("utf-8"))
    return {str(key): int(value) for key, value in loaded.items()}


# --------------------------------------------------------------------------- #
# The workspace an operator would have prepared
# --------------------------------------------------------------------------- #

CONFIG = """\
# Written by `rehearsal.run`. Every line of it is configuration an operator may
# write: the tool has no setting that names the mock (§22).

[browser]
executable = {executable}
headless = {headless}
cdp_port = {cdp_port}
extra_args = [
{extra_args}
]

[hermes]
home = {hermes_home}

[attachments]
dir = {attachments}

[pacing]
delay_between_conversations_s = {delay}
delay_between_parts_s = {parts_delay}

[timeouts]
response_s = {response_s}
"""


@dataclass(frozen=True)
class Settings:
    """Everything a rehearsal needs to know before it starts."""

    root: Path
    mode: str
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    chrome: str | None = None
    headless: bool = True
    delay_s: float = 0.0
    parts_delay_s: float = 0.0
    response_s: float = 120.0
    email: str = EMAIL
    password: str = PASSWORD
    proxy_free: bool = True
    cdp_port: int = 0
    """The debug port the tool launches Chrome on. Zero means "find a free one",
    so that a rehearsal does not meet a browser an earlier one left behind — and
    so that two of them can run side by side."""

    @property
    def workspace(self) -> Path:
        return self.root / "migration"

    @property
    def bin(self) -> Path:
        return self.root / "bin"

    @property
    def unattended(self) -> bool:
        return self.mode == "non-interactive"


def free_port() -> int:
    """A port nothing is listening on, now. Racy by nature and good enough: the
    alternative is meeting the Chrome an earlier rehearsal left on 9222."""
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        return int(held.getsockname()[1])


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def chrome_args(settings: Settings, pin: str) -> list[str]:
    """The `extra_args` the mock told the operator to paste, plus this machine's.

    The first two are the mock's own block. The rest are what a headless,
    sandbox-less, proxied machine needs in order to run *any* browser, and are
    the operator's business rather than the mock's — the rehearsal record names
    them for the same reason it names the pacing.
    """
    arguments = [
        f"--host-resolver-rules=MAP claude.ai {settings.host}:{settings.port}",
        f"--ignore-certificate-errors-spki-list={pin}",
    ]
    if settings.proxy_free:
        # A proxy in the environment resolves the host name itself, so the
        # resolver rule above would never fire.
        arguments.append("--no-proxy-server")
    if settings.headless:
        arguments += ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
    return arguments


class NotFresh(RuntimeError):
    """The mock has already been used. §25 reconciles the report against the
    *whole* of the ledger, so a rehearsal starts against a mock that has counted
    nothing — which is one restart away."""


def prepare(settings: Settings) -> dict[str, Any]:
    """Build the export, write the configuration, put a `hermes` on the path."""
    counted = ledger(settings.host, settings.port)
    if any(counted.values()):
        raise NotFresh(
            "the mock has already counted "
            + ", ".join(f"{key}={value}" for key, value in counted.items() if value)
            + " — restart it, so that its ledger is the whole of this rehearsal"
        )
    export, attachments = exporting.build(settings.root)
    settings.workspace.mkdir(parents=True, exist_ok=True)
    pin = spki_pin(settings.host, settings.port)
    executable = settings.chrome or shutil.which("google-chrome") or ""
    arguments = chrome_args(settings, pin)
    (settings.workspace / "config.toml").write_text(
        CONFIG.format(
            executable=json.dumps(executable),
            headless=json.dumps(settings.headless),
            cdp_port=settings.cdp_port or free_port(),
            extra_args="".join(f"  {json.dumps(item)},\n" for item in arguments).rstrip(
                "\n"
            ),
            hermes_home=json.dumps(str(settings.root / "hermes-home")),
            attachments=json.dumps(str(attachments)),
            delay=settings.delay_s,
            parts_delay=settings.parts_delay_s,
            response_s=settings.response_s,
        ),
        encoding="utf-8",
    )
    write_executable(
        settings.bin, repo=repo_root(), state=settings.bin / "profile.json"
    )
    return {"export": export, "attachments": attachments, "pin": pin}


def environment(settings: Settings) -> dict[str, str]:
    """What every step of the protocol runs with.

    The credentials are here and nowhere else: never in `config.toml`, which the
    tool refuses to read them from, and never on a command line.
    """
    env = dict(os.environ)
    env["PATH"] = f"{settings.bin}{os.pathsep}{env.get('PATH', '')}"
    env["HCM_AUTH__EMAIL"] = settings.email
    env["HCM_AUTH__PASSWORD"] = settings.password
    return env


# --------------------------------------------------------------------------- #
# The protocol
# --------------------------------------------------------------------------- #


@dataclass
class Outcome:
    """One step of the protocol, and what it did."""

    name: str
    argv: tuple[str, ...]
    exit_code: int
    seconds: float
    stdout: str = ""
    stderr: str = ""
    note: str = ""
    deliberate: bool = False
    """Whether a non-zero exit is part of the protocol rather than a failure of
    it: the run the drill kills, `doctor` before anybody has signed in, and the
    two instruments whose last rows are for a person to judge. Each is explained
    in `STANDING_FINDINGS`, so reporting it twice would be noise."""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


@dataclass
class Runner:
    """The tool, as a black-box process."""

    settings: Settings
    env: Mapping[str, str]
    steps: list[Outcome] = field(default_factory=list)
    kept: int = 0
    drill: dict[str, int] = field(default_factory=dict)
    """What the mock counted for the run the drill killed. Measured rather than
    assumed, because it is the one part of the ledger that belongs to work the
    tool never got to record (see `criteria`)."""

    def keep(self, outcome: Outcome) -> None:
        """Every step's output on disk, named for the step.

        A rehearsal that failed somewhere has to be diagnosable afterwards, and
        the terminal only carries the exit codes. Nothing here is printed: a
        step's stdout is the tool's own output and a transcript may carry a
        title.
        """
        directory = self.settings.root / "protocol"
        directory.mkdir(parents=True, exist_ok=True)
        slug = "".join(
            character if character.isalnum() else "-" for character in outcome.name
        ).strip("-")
        self.kept += 1
        stem = directory / f"{self.kept:02d}-{slug}"
        stem.with_suffix(".out").write_text(outcome.stdout, encoding="utf-8")
        stem.with_suffix(".err").write_text(outcome.stderr, encoding="utf-8")

    def command(self, *arguments: str) -> list[str]:
        """The installed command, with the workspace and the mode it was asked
        for. `python -m dataporter` when the console script is not on the path,
        which `25` guarantees is the same program."""
        head = shutil.which(PROGRAM, path=str(self.env.get("PATH", "")))
        base = [head] if head else [sys.executable, "-m", "dataporter"]
        mode = ["--non-interactive"] if self.settings.unattended else []
        return [*base, "--workspace", str(self.settings.workspace), *mode, *arguments]

    def run(
        self, name: str, *arguments: str, note: str = "", deliberate: bool = False
    ) -> Outcome:
        argv = self.command(*arguments)
        started = time.monotonic()
        finished = subprocess.run(  # noqa: S603 - our own command line
            argv,
            capture_output=True,
            text=True,
            env=dict(self.env),
            timeout=STEP_TIMEOUT_S,
            check=False,
        )
        outcome = Outcome(
            name=name,
            argv=tuple(argv),
            exit_code=finished.returncode,
            seconds=round(time.monotonic() - started, 1),
            stdout=finished.stdout,
            stderr=finished.stderr,
            note=note,
            deliberate=deliberate,
        )
        self.steps.append(outcome)
        self.keep(outcome)
        print(
            f"  {name:<34} exit {outcome.exit_code}  {outcome.seconds:>6.1f}s"
            + (f"  — {note}" if note else "")
        )
        return outcome

    def interrupt(self, name: str, *arguments: str) -> Outcome:
        """Start a run, wait until it is mid-conversation, and SIGKILL it.

        Mid-conversation is read off the *mock*, not off the tool: a chat that
        has been created and has an unanswered message in it is a conversation
        in flight, and the mock is the only party that can say so without the
        tool being asked to describe itself.
        """
        argv = self.command(*arguments)
        before = ledger(self.settings.host, self.settings.port)
        started = time.monotonic()
        process = subprocess.Popen(  # noqa: S603 - our own command line
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=dict(self.env),
            start_new_session=True,
        )
        killed = False
        deadline = time.monotonic() + DRILL_TIMEOUT_S
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            counts = ledger(self.settings.host, self.settings.port)
            if counts["messages_received"] > before["messages_received"]:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                killed = True
                break
            time.sleep(DRILL_POLL_S)
        stdout, stderr = process.communicate()
        outcome = Outcome(
            name=name,
            argv=tuple(argv),
            exit_code=process.returncode,
            seconds=round(time.monotonic() - started, 1),
            stdout=stdout,
            stderr=stderr,
            note="SIGKILL mid-conversation" if killed else "was not killed in time",
            deliberate=killed,
        )
        self.steps.append(outcome)
        self.keep(outcome)
        after = ledger(self.settings.host, self.settings.port)
        self.drill = {key: after[key] - before.get(key, 0) for key in after}
        print(
            f"  {name:<34} killed={killed}  {outcome.seconds:>6.1f}s"
            f"  — the killed run: {_counts(self.drill)}"
        )
        return outcome


def _counts(counted: Mapping[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in counted.items() if value)


def protocol(runner: Runner, export: Path) -> dict[str, Any]:
    """§23's protocol, in §23's order.

    `judge` is not part of it: it needs a model, and against the mock it would
    grade noise.
    """
    settings = runner.settings
    runner.run("setup", "setup")
    runner.run(
        "doctor (before login)",
        "doctor",
        note="a signed-out tab has redirected to /login",
        deliberate=True,
    )
    runner.run("login", "login")
    runner.run("doctor (after login)", "doctor")
    runner.run("import --dry-run", "import", str(export), "--dry-run")
    # `--limit`, so that the pilot leaves work for the run the drill interrupts:
    # `20`'s selection would otherwise take the whole of an export this size.
    runner.run("import --pilot", "import", str(export), "--pilot")
    runner.run("report (after pilot)", "report")
    runner.interrupt("import --all (interrupted)", "import", str(export), "--all")
    runner.run("import --all (again)", "import", str(export), "--all", "--force-unlock")
    runner.run("verify", "verify")
    report = runner.run("report", "report")
    counted = ledger(settings.host, settings.port)
    # The ledger is read *here*, before the follow-up probe: `followup` sends one
    # more message per chat, and §25 reconciles the report against the messages
    # the migration sent.
    runner.run("followup", "followup")
    runner.run("status", "status")
    runner.run("session status", "session", "status")
    return {"report_block": report.stdout, "ledger": counted}


def instruments(runner: Runner, export: Path) -> dict[str, Outcome]:
    """The sign-off instruments (§23), run over the rehearsal's own workspace."""
    workspace = str(runner.settings.workspace)
    script = str(repo_root() / "spikes" / "sign_off.py")
    answers: dict[str, Outcome] = {}
    for name, arguments in (
        ("gate", ["gate", "--workspace", workspace]),
        ("drill", ["drill", "--workspace", workspace]),
        ("safety", ["safety", "--workspace", workspace, "--export", str(export)]),
    ):
        started = time.monotonic()
        finished = subprocess.run(  # noqa: S603 - our own script
            [sys.executable, script, *arguments],
            capture_output=True,
            text=True,
            env=dict(runner.env),
            timeout=STEP_TIMEOUT_S,
            check=False,
        )
        outcome = Outcome(
            name=f"sign_off.py {name}",
            argv=(script, *arguments),
            exit_code=finished.returncode,
            seconds=round(time.monotonic() - started, 1),
            stdout=finished.stdout,
            stderr=finished.stderr,
            note="its last rows are for a person to judge" if name != "drill" else "",
            deliberate=name != "drill",
        )
        answers[name] = outcome
        runner.steps.append(outcome)
        runner.keep(outcome)
        print(f"  {'sign_off.py ' + name:<34} exit {outcome.exit_code}")
    return answers


# --------------------------------------------------------------------------- #
# §25's pass criteria
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Criterion:
    """One of §25's checks, with the number that answers it."""

    name: str
    passed: bool
    detail: str

    @property
    def verdict(self) -> str:
        return "pass" if self.passed else "FAIL"


def load(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def criteria(
    settings: Settings,
    *,
    counted: Mapping[str, int],
    steps: Sequence[Outcome],
    signs: Mapping[str, Outcome],
    interrupted: Sequence[str],
    drill: Mapping[str, int] = {},
) -> list[Criterion]:
    """Every check §25 lists, as a number and a verdict.

    `interrupted` is the conversations the drill killed mid-flight. They are the
    one exception to "completed at the first attempt": the protocol itself
    stopped them, and §25's other criterion — the drill loses no conversation and
    creates no duplicate chat — is what judges them.

    `drill` is what the mock counted for the run that was killed. It is on the
    ledger's side of every reconciliation below, because it is work the tool did
    and was killed before it could record: a chat it created and never learned
    the id of, and the part it sent into it. Measured, not assumed — the mock is
    read immediately before the killed run starts and immediately after it dies —
    so a rehearsal still reconciles to the character, with the drill's own cost
    written out rather than waved at.
    """
    workspace = settings.workspace
    state = load(workspace / "state.json")
    run = load(workspace / "run.json")
    report = load(workspace / "report.json")
    entries = {uuid: entry for uuid, entry in state.items() if isinstance(entry, dict)}
    migratable = {
        uuid: entry for uuid, entry in entries.items() if uuid in exporting.MIGRATABLE
    }
    first_time = {
        uuid: entry
        for uuid, entry in migratable.items()
        if entry.get("status") == "completed"
        and (entry.get("attempts") == 1 or uuid in interrupted)
    }
    totals = report.get("totals", {}) if isinstance(report, dict) else {}
    created = int(totals.get("created", 0))
    partial = int(totals.get("partial", 0))
    failed = int(totals.get("failed", 0))
    pending = int(totals.get("pending", 0))
    source = int(totals.get("source_conversations", 0))
    chat_ids = {
        str(entry.get("destination", {}).get("conversation_id"))
        for entry in migratable.values()
        if entry.get("destination", {}).get("conversation_id")
    }
    parts_sent = sum(int(entry.get("chunks_acked", 0)) for entry in entries.values())
    uploaded = sum(
        int(entry.get("attachments", {}).get("uploaded", 0))
        for entry in entries.values()
    )
    titles = sum(
        1
        for entry in migratable.values()
        if "title_not_set" not in (entry.get("limitations") or [])
        and entry.get("status") == "completed"
    )
    logins = sum(1 for step in steps if step.name == "login" and step.ok)
    auto = int(run.get("auto_signins", 0))
    verified = [step for step in steps if step.name == "verify"]
    pauses = int(run.get("human_interventions", 0))

    return [
        Criterion(
            "every migratable conversation completed at its first attempt",
            len(first_time) == len(exporting.MIGRATABLE),
            f"{len(first_time)}/{len(exporting.MIGRATABLE)}"
            + (f", drill interrupted {len(interrupted)}" if interrupted else ""),
        ),
        Criterion(
            "no pause recorded",
            pauses == 0,
            f"human interventions: {pauses}",
        ),
        Criterion(
            "the report reconciles",
            created + partial + failed + pending == source,
            f"{created} + {partial} + {failed} + {pending} == {source}",
        ),
        Criterion(
            "verify finds the source line and every ack line",
            bool(verified) and verified[-1].ok,
            f"exit {verified[-1].exit_code}" if verified else "not run",
        ),
        Criterion(
            "every conversation ends with its title set",
            titles == len(first_time),
            f"{titles}/{len(first_time)} titles set",
        ),
        Criterion(
            "the drill loses no conversation and creates no duplicate chat",
            "drill" in signs and signs["drill"].ok,
            _first_line(signs["drill"].stdout) if "drill" in signs else "not run",
        ),
        _safety(signs.get("safety")),
        _reconciles(
            "chats created == distinct chat ids in the state",
            counted.get("chats_created", 0),
            len(chat_ids),
            drill.get("chats_created", 0),
            "the chat the killed run created and never recorded",
        ),
        _reconciles(
            "messages received == parts sent",
            counted.get("messages_received", 0),
            parts_sent,
            drill.get("messages_received", 0),
            "the part the killed run had sent",
        ),
        _reconciles(
            "files accepted == attachments migrated by upload",
            counted.get("files_accepted", 0),
            uploaded,
            drill.get("files_accepted", 0),
            "an upload the killed run had made",
        ),
        _reconciles(
            "renames == titles set",
            counted.get("renames", 0),
            titles,
            drill.get("renames", 0),
            "a rename the killed run had made",
        ),
        _reconciles(
            "sign-ins == logins + automatic sign-ins",
            counted.get("sign_ins", 0),
            logins + auto,
            drill.get("sign_ins", 0),
            "a sign-in the killed run had made",
            terms=f"{logins} + {auto}",
        ),
    ]


def _reconciles(
    name: str,
    ledger_says: int,
    tool_says: int,
    from_the_drill: int,
    what: str,
    *,
    terms: str = "",
) -> Criterion:
    """One row of §25's reconciliation, with the drill's share written out."""
    detail = f"{ledger_says} == {terms or tool_says}"
    if from_the_drill:
        detail += f" + {from_the_drill} ({what})"
    return Criterion(
        f"ledger: {name}", ledger_says == tool_says + from_the_drill, detail
    )


FOREIGN_HOSTS = "history: other hosts"
UNKNOWN_CHATS = "history: chats this workspace did not create"
OTHER_PATHS = "history: other claude.ai paths"
"""The three rows of the safety audit §25 is about, as `sign_off.py` labels
them. The first two are the criterion; the third is counted for a person to
judge and is why the audit's own exit code is not the answer — a run that signed
in has visited `/login`, and the audit marks that `unknown` rather than `go`."""


def safety_rows(text: str) -> dict[str, tuple[str, str]]:
    """`sign_off.py safety`'s table, as label → (number, verdict)."""
    rows: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        columns = re.split(r"\s{2,}", line.strip())
        if len(columns) >= 3:
            rows[columns[0]] = (columns[1], columns[-1])
    return rows


def _safety(answer: Outcome | None) -> Criterion:
    """§25's audit: no host but claude.ai, and no chat this workspace did not
    create. Read off the audit's own rows rather than off its exit code."""
    name = "the safety audit finds no host but claude.ai"
    if answer is None:
        return Criterion(name, False, "not run")
    rows = safety_rows(answer.stdout)
    wanted = (UNKNOWN_CHATS, FOREIGN_HOSTS)
    if not all(label in rows for label in wanted):
        return Criterion(name, False, _first_line(answer.stdout) or "no rows")
    numbers = {label: rows[label][0] for label in wanted}
    others = rows.get(OTHER_PATHS, ("—", ""))[0]
    return Criterion(
        name,
        all(value == "0" for value in numbers.values()),
        f"other hosts: {numbers[FOREIGN_HOSTS]}, "
        f"chats this workspace did not create: {numbers[UNKNOWN_CHATS]}"
        f" (other claude.ai paths: {others}, for a person to judge)",
    )


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def interrupted_conversations(before: Mapping[str, Any], after: Path) -> list[str]:
    """Which conversations the drill's SIGKILL caught mid-flight.

    Read as "was running when the state was last written and is not on its first
    attempt now" — the entry the next run recovered out of `running`.
    """
    state = load(after)
    return sorted(
        uuid
        for uuid, entry in state.items()
        if isinstance(entry, dict)
        and uuid in exporting.MIGRATABLE
        and int(entry.get("attempts", 0)) > 1
        and uuid not in before
    )


# --------------------------------------------------------------------------- #
# §26's record
# --------------------------------------------------------------------------- #

MARK = "*measured on {date}*"
"""Every number in a record carries one. The discipline the experiment documents
follow, for the reason they follow it: a question nobody answered has to look
different from one answered badly."""

RECORD = """\
# Rehearsal {number:02d} — {mode}

**Kind:** Rehearsal record — what a rehearsal measured, not what was designed.
Produced by [`29`](../specs/impl/29-rehearsal.md).
**Answers:** [§25](../specs/02-claude-mock.md)'s pass criteria, with numbers.
**Rehearsal run:** {date}. **Mode:** `{mode}`.
**Tool:** {tool}. **Scripted agent:** {agent}. **Chrome:** {chrome}.
**Mock:** {mock}.

A rehearsal is the full run's protocol
([`experiment-02.md`](experiment-02.md)) run by the shipped tool against the
mock, with the scripted agent standing where Hermes stands. It is **not evidence
about claude.ai**: every `*unknown*` in [`claude-ui-map.md`](claude-ui-map.md) is
still `*unknown*` after it, semantic fidelity is *not applicable* rather than
passed, and whether a model can follow the skill is the pilot's question (§27).

Nothing here carries conversation content: conversations are named by their
eight-character short id (§10).

## How it was run

| | |
| --- | --- |
| Mode | `{mode}` |
| Pacing | {pacing} |
| Response timeout | {response_s} s |
| Browser | headless: {headless} |
| Chrome extra arguments | {extra_args} |

The two arguments the mock printed are the whole of how the tool reaches it. The
rest are what this machine needs to run any browser at all. The tool itself has
no setting that names the mock (§22).

## The protocol

| Step | Exit | Seconds | Note |
| --- | --- | --- | --- |
{protocol}

## The report, and the ledger beside it

The tool's own §16 block, and what the mock counted while it was produced. The
ledger is read after `verify` and before `followup`, because a follow-up probe
sends one more message per chat and §25 reconciles the migration's messages.

```text
{report_block}
```

```text
{ledger_block}
```

## Pass criteria (§25)

| Criterion | Number | Verdict | Mark |
| --- | --- | --- | --- |
{criteria}

**Verdict:** {verdict}. {mark}

## What it found

{findings}

## What it could not exercise

{gaps}
"""

CANNOT_EXERCISE = """\
- Anything about claude.ai. The mock is a consequence of the UI map, never
  evidence about it.
- Whether a model can follow the skill (§18, questions 4 and 5): a rehearsal
  involves no model.
- Semantic fidelity (§15, §19): *not applicable* against a stand-in that replies
  with the line it was asked for.
- The failure states the mock cannot yet produce (§21): a rate limit, a login
  expiry mid-run, a modal or JavaScript dialog, a generation error, a CAPTCHA or
  security challenge, a code prompt at sign-in.
- `judge`: it needs a model, and against the mock it would grade noise.
"""


def render(
    settings: Settings,
    *,
    number: int,
    date: str,
    steps: Sequence[Outcome],
    checks: Sequence[Criterion],
    report_block: str,
    ledger_block: str,
    findings: Sequence[str],
    versions: Mapping[str, str],
    extra_args: Sequence[str],
) -> str:
    mark = MARK.format(date=date)
    rows = "\n".join(
        f"| `{step.name}` | {step.exit_code} | {step.seconds:g} | {step.note or ''} |"
        for step in steps
    )
    criteria_rows = "\n".join(
        f"| {item.name} | {item.detail} | {item.verdict} | {mark} |" for item in checks
    )
    passed = all(item.passed for item in checks)
    return RECORD.format(
        number=number,
        mode=settings.mode,
        date=date,
        tool=versions.get("tool", "unknown"),
        agent=versions.get("agent", "unknown"),
        chrome=versions.get("chrome", "unknown"),
        mock=versions.get("mock", "unknown"),
        pacing=(
            f"{settings.delay_s:g}s between conversations, "
            f"{settings.parts_delay_s:g}s between parts"
        ),
        response_s=f"{settings.response_s:g}",
        headless=json.dumps(settings.headless),
        extra_args=", ".join(f"`{item}`" for item in extra_args),
        protocol=rows,
        report_block=report_block.strip("\n"),
        ledger_block=ledger_block.strip("\n"),
        criteria=criteria_rows,
        verdict="passed" if passed else "not passed",
        mark=mark,
        findings="\n".join(f"- {item}" for item in findings) or "- Nothing new.",
        gaps=CANNOT_EXERCISE,
    )


def versions_of(settings: Settings, env: Mapping[str, str]) -> dict[str, str]:
    """The four versions a record names, each read rather than assumed."""
    return {
        "tool": _captured(
            [
                shutil.which(PROGRAM, path=str(env.get("PATH", ""))) or PROGRAM,
                "--version",
            ],
            env,
        ),
        "agent": f"scripted agent {AGENT_VERSION}",
        "chrome": _captured([settings.chrome or "google-chrome", "--version"], env),
        "mock": _captured(
            [shutil.which("claude-mock") or "claude-mock", "--version"], env
        ),
    }


def _captured(argv: Sequence[str], env: Mapping[str, str]) -> str:
    try:
        finished = subprocess.run(  # noqa: S603 - a --version call
            list(argv), capture_output=True, text=True, env=dict(env), timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    printed = (finished.stdout or finished.stderr).strip().splitlines()
    return printed[0][:80] if printed else "unknown"


# --------------------------------------------------------------------------- #
# The command
# --------------------------------------------------------------------------- #


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="rehearsal.run", description=__doc__)
    root.add_argument("--root", type=Path, required=True, help="where to work")
    root.add_argument(
        "--mode", choices=("non-interactive", "interactive"), default="non-interactive"
    )
    root.add_argument("--mock-host", default=DEFAULT_HOST)
    root.add_argument("--mock-port", type=int, default=DEFAULT_PORT)
    root.add_argument("--chrome", default=None, help="the browser to drive")
    root.add_argument(
        "--cdp-port", type=int, default=0, help="0 finds a free one (the default)"
    )
    root.add_argument("--headed", action="store_true", help="give Chrome a window")
    root.add_argument("--delay-s", type=float, default=0.0)
    root.add_argument("--parts-delay-s", type=float, default=0.0)
    root.add_argument("--response-s", type=float, default=120.0)
    root.add_argument("--email", default=EMAIL)
    root.add_argument("--password", default=PASSWORD)
    root.add_argument(
        "--record",
        type=Path,
        default=None,
        help="write a rehearsal record here (a complete rehearsal leaves one)",
    )
    root.add_argument("--number", type=int, default=1, help="the record's number")
    return root


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    settings = Settings(
        root=arguments.root,
        mode=arguments.mode,
        host=arguments.mock_host,
        port=arguments.mock_port,
        chrome=arguments.chrome,
        cdp_port=arguments.cdp_port,
        headless=not arguments.headed,
        delay_s=arguments.delay_s,
        parts_delay_s=arguments.parts_delay_s,
        response_s=arguments.response_s,
        email=arguments.email,
        password=arguments.password,
    )
    print(
        f"rehearsal: {settings.mode}, against the mock on {settings.host}:"
        f"{settings.port}"
    )
    prepared = prepare(settings)
    env = environment(settings)
    runner = Runner(settings=settings, env=env)
    before = load(settings.workspace / "state.json")

    answers = protocol(runner, prepared["export"])
    # Before `session logout`, which is the last step of §23's list: the safety
    # audit reads the browser profile's own History database, and `logout`
    # deletes the profile. Recorded as a finding rather than reordered silently.
    signs = instruments(runner, prepared["export"])
    runner.run("session logout", "session", "logout")
    killed = interrupted_conversations(before, settings.workspace / "state.json")
    checks = criteria(
        settings,
        counted=answers["ledger"],
        steps=runner.steps,
        signs=signs,
        interrupted=killed,
        drill=runner.drill,
    )

    print()
    for item in checks:
        print(f"  {item.verdict:<4} {item.name}  ({item.detail})")
    passed = all(item.passed for item in checks)
    print(f"\nrehearsal: {'passed' if passed else 'NOT PASSED'}")

    if arguments.record is not None:
        date = datetime.now(UTC).date().isoformat()
        text = render(
            settings,
            number=arguments.number,
            date=date,
            steps=runner.steps,
            checks=checks,
            report_block=answers["report_block"],
            ledger_block=ledger_block(answers["ledger"]),
            findings=findings_of(runner.steps, checks),
            versions=versions_of(settings, env),
            extra_args=chrome_args(settings, prepared["pin"]),
        )
        arguments.record.parent.mkdir(parents=True, exist_ok=True)
        arguments.record.write_text(text, encoding="utf-8")
        print(f"record: {arguments.record}")
    return 0 if passed else 1


def ledger_block(counted: Mapping[str, int]) -> str:
    """The mock's block, rebuilt from its numbers.

    Rebuilt rather than fetched as text so that a record can be rendered from a
    run whose mock has since been stopped — the shape is §21's, and the mock's
    own tests are what hold it to it.
    """
    labels = (
        ("sign_ins", "Sign-ins:"),
        ("chats_created", "Chats created:"),
        ("messages_received", "Messages received:"),
        ("files_accepted", "Files accepted:"),
        ("renames", "Renames:"),
    )
    lines = ["Mock claude.ai — ledger", ""]
    for key, label in labels:
        lines.append(f"{label}{counted.get(key, 0):>{32 - len(label)}}")
    return "\n".join(lines)


STANDING_FINDINGS = (
    "`doctor` before `login` fails `hermes attaches to chrome`: the check asks "
    "the agent for the URL of the other tab, and a signed-out tab has redirected "
    "to `/login`. True of claude.ai too, so it is recorded rather than worked "
    "around; `doctor` is run again after `login`, where it passes.",
    "The sign-off instruments are run before `session logout` rather than after "
    "it, as §23's order has them: the safety audit reads the browser profile's "
    "own History database, and `logout` deletes the profile.",
    "`sign_off.py gate` and `sign_off.py safety` both exit 1, and neither is a "
    "failed criterion: the gate's third question needs hand-graded semantic "
    "probes, which against the mock are *not applicable* (§27), and its fourth "
    "asks a person to explain the one failure line (the unsupported "
    "conversation); the audit counts the run's own `/login` visit as an "
    "`other claude.ai path` for a person to judge. §25's two safety rows — no "
    "other host, and no chat this workspace did not create — are read off the "
    "audit's table above.",
    "The interruption drill leaves a chat the tool never learned the id of, "
    "because a one-shot agent reports the id when it returns. The retry starts "
    "another chat, and the mock counts both. The tool's own drill instrument "
    "cannot see it; the ledger can, and the reconciliation above carries it.",
)
"""What every rehearsal of this shape has to say, whatever its numbers.

Here rather than in the record's prose because each of them is a *finding* — a
thing this arrangement discovered about the tool or about the protocol — and a
record that stopped reporting one would be a record of a rehearsal that had
stopped doing it.
"""


def findings_of(steps: Sequence[Outcome], checks: Sequence[Criterion]) -> list[str]:
    """What this run has to say, in one line each."""
    found = [
        f"`{step.name}` exited {step.exit_code}."
        + (f" {step.note}" if step.note else "")
        for step in steps
        if not step.ok and not step.deliberate
    ]
    found += [f"{item.name}: {item.detail}." for item in checks if not item.passed]
    return [*found, *STANDING_FINDINGS]


if __name__ == "__main__":
    sys.exit(main())
