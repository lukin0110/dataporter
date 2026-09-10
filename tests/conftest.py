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

from dataporter import log

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
