"""Shared fixtures.

The content guard runs in strict mode for the whole suite, so a record that could
carry conversation content raises here instead of being silently dropped the way it
is in an operator's terminal.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataporter import log


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
