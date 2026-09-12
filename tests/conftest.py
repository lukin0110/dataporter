"""Shared fixtures, and the line between the fast suite and the slow one.

The content guard runs in strict mode for the whole suite, so a record that could
carry conversation content raises here instead of being silently dropped the way it
is in an operator's terminal.

`22` is where the *cost* of the slow half got fixed — a teardown that was half a
second of `select` timeout, and a Hermes profile rebuilt with fifteen subprocesses
per test — so the split is now a rail rather than a necessity. This file is where
the two halves are told apart, and it does that twice over:

- **The marker follows the fixture.** A test that asks for `world` binds two
  ports and spawns a real `hermes` per conversation, so
  `pytest_collection_modifyitems` marks it `slow` rather than leaving that to
  whoever writes the next one. The wholly-slow modules carry a module-level
  `pytestmark` instead, which is one line each and says the same thing.
- **And the fast half is held to it.** Marking by hand is a rule that rots
  silently: a test that builds a `FakeChrome` inline has no fixture name to give
  it away, and a fast suite that quietly grows a half-second teardown is a fast
  suite nobody notices losing. So `no_expensive_fakes` makes constructing one an
  error in an unmarked test. Green is then a proof rather than a hope, and the
  failure lands on the pull request that introduced it.

Neither mechanism decides what `slow` *means*; `pyproject.toml`'s `markers` does.
Both exist so the meaning cannot drift away from what the suite actually does.
"""

import hashlib
import os
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

import world as world_module
from dataporter import log
from dataporter import seed as seeding
from dataporter import store as storing
from dataporter.config import AttachmentSettings, SeedSettings, Settings
from dataporter.export import load_export
from fake_chrome import FakeChrome
from fake_hermes import FakeHermes
from fake_pages import PageServer
from world import World

FIXTURES = Path(__file__).parent / "fixtures"

SLOW_FIXTURES = frozenset({"world"})
"""Fixtures whose cost is a process or a socket, wherever they are asked for.

`world` alone, because it is the only expensive fixture shared across modules —
it writes a `hermes` executable, binds a fake Chrome's two ports, and hands the
run a real subprocess per conversation. The module-local ones (`chrome`, `fake`,
`browser`, `new_chat`) are not listed: their names are generic, five modules
spell them differently, and a list of them would rot on the first rename. Those
modules carry a module-level `pytestmark` instead, and `no_expensive_fakes` is
what catches anything either mechanism misses.

Still `slow` after `22`, and not only by inertia: a world costs about 50 ms where
it cost 500, and the marker is about what a test *does* — spawn, bind, launch —
rather than about a threshold it currently sits under.
"""

EXPENSIVE = "{name} is expensive; mark the test `slow` (see pyproject.toml markers)"
"""What an unmarked test that reaches for a fake is told.

Named rather than inlined so the test that proves the guard is armed can match on
it instead of on a phrase somebody may reword.
"""


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Mark by fixture, so `slow` cannot drift away from what a test costs."""
    for item in items:
        if SLOW_FIXTURES & set(getattr(item, "fixturenames", ())):
            item.add_marker(pytest.mark.slow)


@pytest.fixture(autouse=True)
def no_expensive_fakes(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In a test that is not `slow`, building a fake is an error.

    The attribute is patched on the class object rather than on the module
    namespace, because `fake_composer` imports `FakeChrome` by name — a
    module-level patch would have to be made in two places and would still miss
    the third importer.

    Silent about it when the test *is* marked: the guard is a statement about the
    fast half, and the slow half is where these belong.
    """
    if request.node.get_closest_marker("slow") is not None:
        return

    def refuse(name: str) -> Callable[..., None]:
        """One guard per class, so the message names the one that was built."""

        def guard(*args: object, **kwargs: object) -> None:
            raise AssertionError(EXPENSIVE.format(name=name))

        return guard

    monkeypatch.setattr(FakeChrome, "__init__", refuse("FakeChrome"))
    monkeypatch.setattr(FakeHermes, "__init__", refuse("FakeHermes"))
    monkeypatch.setattr(PageServer, "__enter__", refuse("PageServer"))


@pytest.fixture(autouse=True)
def strict_content_guard(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Make content leaks loud, and leave no handlers behind between tests."""
    monkeypatch.setenv(log.STRICT_ENV_VAR, "1")
    log.reset_logging()
    yield
    log.reset_logging()


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """No DATAPORTER_* variable from the developer's shell leaks into a test."""
    for name in list(os.environ):
        if name.startswith("DATAPORTER_"):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty directory that is also the cwd, so `./migration` is predictable."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def export_dir() -> Path:
    """The checked-in synthetic export. Read-only: never write through this."""
    return FIXTURES / "export-small"


@pytest.fixture
def attachments_dir(tmp_path: Path) -> Path:
    """Where `03` looks for attachment bytes. Empty until a test drops a file in."""
    target = tmp_path / "attachments"
    target.mkdir()
    return target


@pytest.fixture
def world(
    tmp_path: Path, export_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[World]:
    """A workspace, a fake Hermes and a fake browser, ready to run `import`.

    Here rather than in one test module because `12` and `13` both drive it;
    `world.py` holds the whole body, and this is the name a test asks for.
    """
    yield from world_module.build(tmp_path, export_dir, monkeypatch)


@pytest.fixture
def export_zip(export_dir: Path, tmp_path: Path) -> Path:
    """The same fixture as an archive, built here rather than checked in.

    A binary blob in the tree cannot be reviewed, and building it from the
    directory keeps the two byte-identical by construction.
    """
    target = tmp_path / "export-small.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(export_dir.iterdir()):
            archive.write(item, item.name)
    return target


@pytest.fixture
def snapshot_dir(export_zip: Path, tmp_path: Path) -> Path:
    """The same fixture, filed as a snapshot (`30`).

    Filed by the store's own `file_archive` rather than by three `write_bytes`
    calls, so a test that reads one is reading what `extract` really writes —
    and by that function rather than through `extract` itself, because a
    snapshot is a thing on disk and the fetch is not what is under test here.
    """
    export = load_export(export_zip)
    directory, _ = storing.Store(tmp_path / "store").file_archive(
        export_zip,
        storing.Filing(
            source="claude",
            account="fixture",
            stamp="2026-09-12T20-51-07Z",
            origin="file",
            sha256=hashlib.sha256(export_zip.read_bytes()).hexdigest(),
            bytes=export_zip.stat().st_size,
            export_fingerprint=export.fingerprint,
            counts=storing.Counts(
                conversations=len(export.conversations),
                projects=export.projects,
                memories=export.memories,
            ),
        ),
    )
    return directory


@pytest.fixture
def truncated_zip(export_zip: Path, tmp_path: Path) -> Path:
    """An archive whose end-of-central-directory record is gone."""
    target = tmp_path / "truncated.zip"
    target.write_bytes(export_zip.read_bytes()[: export_zip.stat().st_size // 2])
    return target


LONG_CONVERSATION = "bb000002-2222-4222-8222-222222222222"
"""The one fixture conversation long enough to need two parts at 4 000 chars."""


@pytest.fixture
def two_part_seed(export_dir: Path, attachments_dir: Path) -> seeding.Seed:
    """A real two-part seed, for the slices that need one to point at.

    Here rather than in one test module because `11` needs it twice — once to
    render a prompt and once to migrate through it — and a second way of
    building "the two-part fixture" is a second thing to keep in step with `04`.
    """
    settings = Settings(
        workspace=attachments_dir.parent,
        seed=SeedSettings(max_chars=4_000),
        attachments=AttachmentSettings(dir=attachments_dir),
    )
    outcome = next(
        item
        for item in seeding.SeedGenerator(settings).seeds(
            load_export(export_dir).conversations
        )
        if item.conversation_uuid == LONG_CONVERSATION
    )
    assert outcome.seed is not None
    return outcome.seed
