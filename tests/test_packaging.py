"""What a wheel has to contain for somebody else's project to install it.

`25` made this package installable rather than merely cloneable, and almost
nothing about that claim is visible from inside the checkout: an import works
here whether or not the file it needs is in the distribution, because here the
file is simply on disk. So the claim is checked against a built artefact. The
module builds the wheel and the source distribution once and then reads them —
`zipfile` and `tarfile`, no new dependency, nothing installed.

Three of the assertions below are the ones that would otherwise fail on a
stranger's machine and nowhere else:

- **`dataporter/py.typed`.** Without it PEP 561 tells a consumer's type checker
  to treat every `from dataporter import …` as `Any`, which would quietly undo
  what `23` built. Nothing in this repository notices its absence.
- **`dataporter/skills/claude-migrate/SKILL.md`.** `hermes.skill.packaged_dir`
  reads it out of the install through `importlib.resources`, and its failure
  branch is marked `# pragma: no cover - packaging` precisely because it can only
  happen in a wheel. A build that dropped the file would pass the whole suite and
  fail at `setup` on a host machine.
- **The metadata version.** `pyproject.toml` has no version of its own any more;
  hatchling reads `dataporter.__version__`. Asserting that the artefact agrees is
  what makes that a mechanism rather than an intention.

What is deliberately *not* here is installing the wheel into a venv and running
it. That is the other half of the proof and it belongs in CI's `install` job,
where a fresh interpreter in a directory that holds none of our files is cheap to
arrange and is the point; a test that did it would be the slowest in the suite
and would still be running inside the repository it is trying to leave.
"""

import importlib
import shutil
import subprocess
import sys
import tarfile
import zipfile
from email import message_from_string
from email.message import Message
from pathlib import Path

import pytest

from dataporter import PROGRAM_NAME, __version__, cli

pytestmark = pytest.mark.slow
"""Every test here spends a build, which is a subprocess and then some."""

REPO = Path(__file__).resolve().parents[1]

DIST_INFO = f"dataporter-{__version__}.dist-info"
PACKAGE_ROOT = "dataporter/"

REQUIREMENTS = (
    "orval>=0.0.12",
    "pydantic>=2",
    "pydantic-settings>=2",
    "tenacity>=9",
    "typer>=0.27",
    "websockets>=12",
)
"""`pyproject.toml`'s runtime dependencies, as the metadata spells them.

Listed again rather than read back out of `pyproject.toml`, which would compare
the file with itself. A dependency added without a thought about what a host
project inherits should fail here and be added here deliberately."""

WHEEL_ROOTS = (PACKAGE_ROOT, f"{DIST_INFO}/")
"""The only two things a wheel of ours may contain at its top level.

Stated as a whitelist rather than a list of directories to keep out: `specs/`,
`docs/` and `tests/` are the ones somebody would think to exclude, and the next
directory this repository grows is the one a blacklist would miss."""

requires_uv = pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed (it builds the artefacts)")


@pytest.fixture(scope="session")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Return the wheel and the source distribution, built once for the whole module.

    `uv build` builds the sdist and then builds the wheel *from* it, so a file
    the sdist omits cannot reach the wheel — one command exercises both halves of
    the file selection. Into a temporary directory rather than `dist/`, so a run
    of the suite leaves nothing in the working tree.
    """
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(
        ["uv", "build", "--out-dir", str(out)],  # ruff: ignore[start-process-with-partial-path] — the `uv` on the developer's PATH
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
        timeout=600,
    )
    (wheel,) = out.glob("*.whl")
    (sdist,) = out.glob("*.tar.gz")
    return wheel, sdist


@pytest.fixture(scope="session")
def wheel_names(built: tuple[Path, Path]) -> list[str]:
    with zipfile.ZipFile(built[0]) as archive:
        return archive.namelist()


@pytest.fixture(scope="session")
def metadata(built: tuple[Path, Path]) -> Message:
    """`METADATA` parsed as the RFC 822 document it is.

    An email message rather than a dict: `Requires-Dist` and `Classifier` repeat,
    and `get_all` is the one reader that does not lose the repetitions.
    """
    with zipfile.ZipFile(built[0]) as archive:
        return message_from_string(archive.read(f"{DIST_INFO}/METADATA").decode())


@pytest.fixture(scope="session")
def sdist_names(built: tuple[Path, Path]) -> list[str]:
    """Member names with the `dataporter-<version>/` prefix taken off."""
    prefix = f"dataporter-{__version__}/"
    with tarfile.open(built[1]) as archive:
        return [name.removeprefix(prefix) for name in archive.getnames() if name.startswith(prefix)]


# --------------------------------------------------------------------------- #
# The wheel
# --------------------------------------------------------------------------- #


@requires_uv
def test_the_wheel_ships_the_typing_marker(wheel_names: list[str]) -> None:
    """`py.typed`, or a consumer's checker sees `Any` and `23` was for nothing."""
    assert "dataporter/py.typed" in wheel_names


@requires_uv
def test_the_wheel_ships_the_skill(wheel_names: list[str]) -> None:
    """The one file `packaged_dir` reads out of the install."""
    assert "dataporter/skills/claude-migrate/SKILL.md" in wheel_names


@requires_uv
def test_the_wheel_version_is_the_module_version(metadata: Message) -> None:
    """One version, in `__init__.py`, reached by both readers."""
    assert metadata["Version"] == __version__


@requires_uv
def test_the_wheel_declares_the_console_script(built: tuple[Path, Path]) -> None:
    with zipfile.ZipFile(built[0]) as archive:
        entry_points = archive.read(f"{DIST_INFO}/entry_points.txt").decode()

    assert entry_points.splitlines() == [
        "[console_scripts]",
        f"{PROGRAM_NAME} = dataporter.cli:app",
    ]


@requires_uv
def test_the_wheel_carries_the_licence(metadata: Message, wheel_names: list[str]) -> None:
    """The SPDX expression, and the file it names, in the artefact."""
    assert metadata["License-Expression"] == "MIT"
    assert f"{DIST_INFO}/licenses/LICENSE" in wheel_names


@requires_uv
def test_the_wheel_states_what_a_host_project_inherits(metadata: Message) -> None:
    """The floor and the six dependencies, as an installer reads them."""
    assert metadata["Requires-Python"] == ">=3.12"
    every = metadata.get_all("Requires-Dist", [])
    required = [value for value in every if "extra ==" not in value]
    assert sorted(required) == sorted(REQUIREMENTS)


@requires_uv
def test_the_judge_stays_an_extra(metadata: Message) -> None:
    """`20`'s instrument is opt-in, and a plain install must not pull its tree."""
    assert metadata.get_all("Provides-Extra") == ["judge"]
    assert "pydantic-ai; extra == 'judge'" in metadata.get_all("Requires-Dist", [])


@requires_uv
def test_the_wheel_is_typed_in_its_metadata_too(metadata: Message) -> None:
    """The classifier and the marker file are one claim; they ship together."""
    assert "Typing :: Typed" in metadata.get_all("Classifier", [])


@requires_uv
def test_the_wheel_is_the_package_and_nothing_else(wheel_names: list[str]) -> None:
    """A wheel is the package, not the project that produces it."""
    assert [name for name in wheel_names if not name.startswith(WHEEL_ROOTS)] == []


# --------------------------------------------------------------------------- #
# The source distribution
# --------------------------------------------------------------------------- #


@requires_uv
def test_the_sdist_is_source_somebody_can_check(sdist_names: list[str]) -> None:
    """Enough to run `make check` from: the project, the code and the suite."""
    for name in ("pyproject.toml", "Makefile", "LICENSE", "README.md"):
        assert name in sdist_names
    assert "src/dataporter/__init__.py" in sdist_names
    assert "src/dataporter/py.typed" in sdist_names
    assert "tests/test_packaging.py" in sdist_names


@requires_uv
def test_the_sdist_leaves_the_scaffolding_behind(sdist_names: list[str]) -> None:
    """The prose and the agents' tooling are the repository's, not a consumer's."""
    excluded = ("specs/", "docs/", "spikes/", ".claude/", ".agents/", "graft/")
    assert [name for name in sdist_names if name.startswith(excluded)] == []
    assert "skills-lock.json" not in sdist_names
    assert ".mcp.json" not in sdist_names


# --------------------------------------------------------------------------- #
# The other spelling of the command
# --------------------------------------------------------------------------- #


def test_the_module_is_the_cli_and_not_a_second_one() -> None:
    """`__main__` imports the app; it does not build one.

    In-process, so the import statement is covered here rather than only in the
    subprocess below, where coverage does not follow it — and so a `__main__`
    that grew a parser of its own would fail on the identity rather than on a
    golden string somebody would then update. `__name__` is
    `dataporter.__main__` under an import, so the guard does not fire.
    """
    module = importlib.import_module("dataporter.__main__")

    assert module.app is cli.app


def test_the_module_runs_as_a_command() -> None:
    """`python -m dataporter`, which is the rest of `__main__.py`.

    A subprocess because that is the only way the module's guard is entered, and
    the reason the guard is excluded from coverage rather than counted: coverage
    does not follow a child. No build needed — this asks the interpreter running
    the suite, which has the package importable.
    """
    done = subprocess.run(
        [sys.executable, "-m", "dataporter", "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert done.stdout == f"{PROGRAM_NAME} {__version__}\n"
