"""The world one `import` run happens in.

`12` built this to drive the real import loop between two fakes that already
existed — `fake_hermes`, a real process on disk that answers `-z` with whatever a
test told it to, and `fake_composer`'s modelled claude.ai page. Everything
between them is the real thing: the real planner, the real seed generator, the
real prompt, the real runner, the real state store.

It lives in its own module because `13` was the second slice to need it, and
`14` the third. The loop
and its recovery policy are two subjects and two test modules, and a second
spelling of "a workspace, a fake Hermes and a fake browser" would be a second
thing to keep in step with `09` and `08`.

`conftest.py` wraps `build` as the `world` fixture, so a test asks for it by name
and never imports it.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from dataporter import importer as importing
from dataporter import state
from dataporter.browser import launcher
from dataporter.browser.cdp import CdpClient
from dataporter.config import (
    BrowserSettings,
    HermesSettings,
    RetrySettings,
    RunSettings,
    Settings,
    TimeoutSettings,
)
from dataporter.hermes import skill as skilling
from dataporter.hermes.profile import profile_config
from dataporter.steps import Step
from fake_chrome import entered
from fake_composer import Browser, FakePage
from fake_hermes import FakeHermes

MODEL = "anthropic/claude-sonnet-5"
NEW_URL = "https://claude.ai/new"

FIRST = "aa000001-1111-4111-8111-111111111111"
LONG = "bb000002-2222-4222-8222-222222222222"
THIRD = "cc000003-3333-4333-8333-333333333333"
ATTACHED = "dd000004-4444-4444-8444-444444444444"
EMPTY = "ff000006-6666-4666-8666-666666666666"
"""The fixture's first conversation, its longest, its third, the one with
attachments (`16`) and its unmigratable one."""

CHART = "q3-chart.png"
INLINED = "q3-summary.txt"
"""`ATTACHED`'s two files: one named with no bytes anywhere — class 2 as soon as
an operator supplies them — and one the export inlined."""

CHAT = "b6f0a2d4-1c88-4e3a-9a1f-2f0e5d7c8b91"
OTHER_CHAT = "c7e1b3f5-2d99-4f4b-8b2a-3a1f6e8d9c02"

CONTENT: tuple[str, ...] = (
    "Listing files",
    "Postgres questions",
    "Shorter loop",
    "Q3 report",
    "Naming the tool",
    "pathlib",
)
"""Titles and a phrase from the fixture's messages. §10: none of these may appear
on stdout, at any verbosity, at any point in a run."""


def completed(conversation_id: str = CHAT, **fields: Any) -> str:
    """Return what a Hermes run that migrated one conversation prints last."""
    payload: dict[str, Any] = {
        "outcome": "completed",
        "conversation_id": conversation_id,
        "last_step": str(Step.DONE),
        "chunks_acked": 1,
    }
    payload.update(fields)
    return result(**payload)


def needs_human(reason: str = "auth_required", **fields: Any) -> str:
    """Return what a Hermes run that cannot safely proceed prints last (`14`).

    Not a failure and not a retry: `13` leaves it alone because no second
    identical attempt clears it, and `14` asks a person instead.
    """
    payload: dict[str, Any] = {
        "outcome": "needs_human",
        "needs_human_reason": reason,
        "last_step": str(Step.OPEN),
        "error": {"category": "auth", "detail": "sign-in form shown at /login"},
    }
    payload.update(fields)
    return result(**payload)


def result(**fields: Any) -> str:
    payload: dict[str, Any] = {
        "outcome": "failed",
        "last_step": str(Step.OPEN),
        "chunks_acked": 0,
        "actions": 4,
    }
    payload.update(fields)
    # Prefixed, because a real transcript is pages of prose and helper objects
    # with the result at the end of it.
    return f"done.\n{json.dumps(payload)}\n"


@dataclass
class World:
    """A workspace, a fake Hermes, a fake browser and the export to migrate."""

    settings: Settings
    hermes: FakeHermes
    browser: Browser
    page: FakePage
    export: Path
    launches: list[str] = field(default_factory=list)
    pauses: list[float] = field(default_factory=list)

    def answers(self, *answers: str) -> None:
        """Set what the fake Hermes prints, one per `-z` run, last one repeating."""
        self.hermes.write(
            version="hermes 1.0.0",
            config_extra={"agent.model": MODEL},
            answers=list(answers),
            append_probe=True,
        )

    def exits(self, *codes: int) -> None:
        self.hermes.write(
            version="hermes 1.0.0",
            config_extra={"agent.model": MODEL},
            answers=list(self.hermes.spec.get("answers", [])),
            exits=list(codes),
            append_probe=True,
        )

    def retries(self, **fields: Any) -> None:
        """Change `13`'s budget for this run.

        A test that wants one attempt per conversation says `max_attempts=1` rather than
        counting fake answers.
        """
        self.settings.retries = RetrySettings(**fields)

    def store(self) -> state.StateStore:
        return state.StateStore(self.settings.workspace)

    def entry(self, uuid: str) -> state.ConversationState:
        return self.store().load()[uuid]

    def run(self, **selection: Any) -> importing.RunSummary:
        return self.importer().run(self.export, state.Selection(**selection))

    def importer(self, **kwargs: Any) -> importing.Importer:
        return importing.Importer(self.settings, **kwargs)


def build(tmp_path: Path, export_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    """One world, wired up and torn down. The `world` fixture's whole body."""
    page = FakePage(url=NEW_URL, composer="", send_enabled=True)
    browser = Browser(page)
    entered(browser)
    hermes = FakeHermes(root=tmp_path / "bin")
    settings = Settings(
        workspace=tmp_path / "migration",
        browser=BrowserSettings(cdp_port=browser.chrome.port),
        hermes=HermesSettings(executable=hermes.executable, home=tmp_path / "hermes-home"),
        timeouts=TimeoutSettings(cdp_call_s=2.0, hermes_cli_s=30.0, hermes_task_s=60.0),
        run=RunSettings(max_conversations=10),
    )
    created = World(
        settings=settings,
        hermes=hermes,
        browser=browser,
        page=page,
        export=export_dir,
    )
    created.answers(completed())
    # The end state `setup` would leave, reached without the fifteen subprocesses
    # `run_setup` reaches it with — `profile list`, `profile create`, twelve
    # `config set` and a `config show`, per test that asks for a world, which `22`
    # measured at ~45 s across the suite. What those subprocesses prove (the
    # environment allowlist, the working directory, the process-group kill) is
    # `09`'s subject and stays covered in `test_hermes_setup.py` and
    # `test_hermes_doctor.py`, which call `run_setup` for real; what a world is
    # for is `Importer`'s decisions, and those read the profile rather than the
    # making of it. The skill is still installed for real, because it is a file
    # copy rather than a subprocess and `12`'s preflight checks for it.
    hermes.with_profile(settings.hermes.profile, **profile_config(settings))
    skilling.install(settings)

    def fake_launch(settings: Settings, url: str) -> launcher.BrowserSession:
        """`07`'s adoption, without a Chrome.

        `adopted` so nothing tries to close a browser the test owns.
        """
        created.launches.append(url)
        return launcher.BrowserSession(
            client=CdpClient(port=browser.chrome.port, timeout=2.0),
            profile=settings.browser_profile_dir,
            adopted=True,
        )

    monkeypatch.setattr(launcher, "launch", fake_launch)
    # Every wait a run makes — the gap between conversations and `13`'s backoff —
    # recorded rather than slept through. The `pause` function itself is tested
    # in `test_importer.py`.
    monkeypatch.setattr(importing, "pause", created.pauses.append)
    try:
        yield created
    finally:
        browser.chrome.stop()


def cli_env(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the world's settings into the environment the CLI loads them from.

    Here rather than in one test module for the reason `World` is: `12` runs
    `import` through the CLI and `14` runs `import` and then `resume`.
    """
    monkeypatch.setenv("DATAPORTER_WORKSPACE", str(world.settings.workspace))
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", str(world.browser.chrome.port))
    monkeypatch.setenv("DATAPORTER_HERMES__EXECUTABLE", str(world.settings.hermes.executable))
    monkeypatch.setenv("DATAPORTER_HERMES__HOME", str(world.settings.hermes_home))
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__CDP_CALL_S", "2")
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__HERMES_TASK_S", "60")
