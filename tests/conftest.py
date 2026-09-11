"""Shared fixtures.

The content guard runs in strict mode for the whole suite, so a record that could
carry conversation content raises here instead of being silently dropped the way it
is in an operator's terminal.
"""

import os
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

import world as world_module
from dataporter import log
from dataporter import seed as seeding
from dataporter.config import AttachmentSettings, SeedSettings, Settings
from dataporter.export import load_export
from world import World

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def strict_content_guard(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Make content leaks loud, and leave no handlers behind between tests."""
    monkeypatch.setenv(log.STRICT_ENV_VAR, "1")
    log.reset_logging()
    yield
    log.reset_logging()


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """No HCM_* variable from the developer's shell leaks into a test."""
    for name in list(os.environ):
        if name.startswith("HCM_"):
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
