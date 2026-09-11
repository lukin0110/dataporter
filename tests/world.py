"""The world one `import` run happens in.

`12` built this to drive the real import loop between two fakes that already
existed — `fake_hermes`, a real process on disk that answers `-z` with whatever a
test told it to, and `fake_composer`'s modelled claude.ai page. Everything
between them is the real thing: the real planner, the real seed generator, the
real prompt, the real runner, the real state store.

It lives in its own module because `13` is the second slice to need it. The loop
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
from dataporter.hermes import profile as profiling
from dataporter.steps import Step
from fake_composer import Browser, FakePage
from fake_hermes import FakeHermes

MODEL = "anthropic/claude-sonnet-5"
NEW_URL = "https://claude.ai/new"

FIRST = "aa000001-1111-4111-8111-111111111111"
LONG = "bb000002-2222-4222-8222-222222222222"
THIRD = "cc000003-3333-4333-8333-333333333333"
EMPTY = "ff000006-6666-4666-8666-666666666666"
"""The fixture's first conversation, its longest, its third and its
unmigratable one."""

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
    """What a Hermes run that migrated one conversation prints last."""
    payload: dict[str, Any] = {
        "outcome": "completed",
        "conversation_id": conversation_id,
        "last_step": str(Step.DONE),
        "chunks_acked": 1,
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
        """What the fake Hermes prints, one per `-z` run, last one repeating."""
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
        """Change `13`'s budget for this run. A test that wants one attempt per
        conversation says `max_attempts=1` rather than counting fake answers."""
        self.settings.retries = RetrySettings(**fields)

    def store(self) -> state.StateStore:
        return state.StateStore(self.settings.workspace)

    def entry(self, uuid: str) -> state.ConversationState:
        return self.store().load()[uuid]

    def run(self, **selection: Any) -> importing.RunSummary:
        return self.importer().run(self.export, state.Selection(**selection))

    def importer(self, **kwargs: Any) -> importing.Importer:
        return importing.Importer(self.settings, **kwargs)


def build(
    tmp_path: Path, export_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[World]:
    """One world, wired up and torn down. The `world` fixture's whole body."""
    page = FakePage(url=NEW_URL, composer="", send_enabled=True)
    browser = Browser(page)
    browser.__enter__()
    hermes = FakeHermes(root=tmp_path / "bin")
    settings = Settings(
        workspace=tmp_path / "migration",
        browser=BrowserSettings(cdp_port=browser.chrome.port),
        hermes=HermesSettings(
            executable=hermes.executable, home=tmp_path / "hermes-home"
        ),
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
    profiling.run_setup(settings)

    def fake_launch(settings: Settings, url: str) -> launcher.BrowserSession:
        """`07`'s adoption, without a Chrome. `adopted` so nothing tries to
        close a browser the test owns."""
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
