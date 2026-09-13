"""Putting the `claude-migrate` skill where Hermes will find it.

`setup` installs the skill into the `dataporter` profile's skills directory;
`doctor` reads it back and reports its name and version. Both halves live here,
along with the small amount of frontmatter parsing that identifying it takes.

Two things this module is deliberately not:

- **It is not the skill.** The procedure, the step names and the verification
  protocol are `11`'s, and the file shipped today is a placeholder whose
  frontmatter is final and whose body says so. `09` owns *installing* a skill and
  proving one is installed; that is testable now, and it is what `10` needs in
  order to run Hermes at all.
- **It is not a YAML reader.** Only top-level `key: value` lines of the
  frontmatter are read, and only `name` and `version` are used. A skill whose
  frontmatter needs more than that to be identified is a skill `doctor` should
  not be vouching for.

The install path — `<hermes home>/profiles/<profile>/skills/dataporter/claude-migrate/`
— is `09`'s expectation, not an observed fact. `10` confirms it against a real
Hermes and this is the one place it changes.

That bounds what `doctor`'s `skill installed` line is worth: it proves a skill is
where *we* put it and that it identifies itself, not that Hermes reads from
there. Nothing here tells Hermes where its home is (`config.HermesSettings.home`
says why), so the two agree only while `hermes_home` matches the real one — which
it does for the `~/.hermes` default, since `HOME` is forwarded to the subprocess.
Asking Hermes itself what skills it can see would be the stronger check; `10` is
what makes that possible, because it is where the command to ask becomes known.
"""

import shutil
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from dataporter import log
from dataporter.config import Settings
from dataporter.errors import HermesUsageError

_logger = log.get_logger(__name__)

SKILL_NAME = "claude-migrate"
SKILL_NAMESPACE = "dataporter"
"""The namespace directory skills are grouped under, so the migration skill
cannot collide with another `claude-migrate` the operator has."""

SKILLS_DIRNAME = "skills"
PROFILES_DIRNAME = "profiles"
SKILL_FILENAME = "SKILL.md"
FENCE = "---"


@dataclass(frozen=True)
class SkillMeta:
    """How a skill identifies itself: the two fields `doctor` prints."""

    name: str
    version: str

    def __str__(self) -> str:
        return f"{self.name} {self.version}"


def packaged_dir() -> Path:
    """Where the shipped skill lives inside the installed package.

    `importlib.resources` rather than `__file__` arithmetic so that the lookup is
    the one the packaging tools guarantee. A wheel is installed unzipped, so the
    traversable is a real directory; anything else is a packaging failure and is
    reported as one rather than worked around.
    """
    root = resources.files("dataporter") / SKILLS_DIRNAME / SKILL_NAME
    path = Path(str(root))
    if not (path / SKILL_FILENAME).is_file():  # pragma: no cover - packaging
        raise HermesUsageError(detail=f"the {SKILL_NAME} skill is missing from this install: {path}")
    return path


def profile_dir(settings: Settings) -> Path:
    """`<hermes home>/profiles/<profile>/`."""
    return settings.hermes_home / PROFILES_DIRNAME / settings.hermes.profile


def install_dir(settings: Settings) -> Path:
    """Where `setup` writes the skill and `doctor` looks for it."""
    return profile_dir(settings) / SKILLS_DIRNAME / SKILL_NAMESPACE / SKILL_NAME


def frontmatter(text: str) -> dict[str, str]:
    """Return the top-level scalar keys of a `---` fenced header, or `{}`.

    Nested keys are skipped rather than flattened: `metadata.hermes.tags` is for
    Hermes to read, and flattening it here would invite somebody to start
    depending on our reading of it.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != FENCE:
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == FENCE:
            break
        if not line.strip() or line.startswith((" ", "\t")) or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip("\"'")
    return fields


def read_meta(directory: Path) -> SkillMeta | None:
    """Identify the skill in `directory`, or `None` if there is not one there."""
    path = directory / SKILL_FILENAME
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    fields = frontmatter(text)
    name = fields.get("name", "")
    version = fields.get("version", "")
    if not name or not version:
        return None
    return SkillMeta(name=log.safe_token(name), version=log.safe_token(version))


def installed(settings: Settings) -> SkillMeta | None:
    """Return what `doctor`'s `skill installed` line reports."""
    return read_meta(install_dir(settings))


def install(settings: Settings) -> SkillMeta:
    """Copy the packaged skill into the profile, overwriting what is there.

    Overwriting rather than merging or versioning: the skill is ours, the profile
    is ours, and a profile holding half of one release's skill and half of
    another's is the failure mode this avoids. Files the packaged skill does not
    have are left alone, which is what `dirs_exist_ok` means — `setup` does not
    delete from a directory inside the operator's home.
    """
    source = packaged_dir()
    target = install_dir(settings)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, dirs_exist_ok=True)
    except OSError as exc:
        raise HermesUsageError(detail=f"cannot install the skill to {target}: {exc}") from exc
    meta = read_meta(target)
    if meta is None:  # pragma: no cover - the packaged file is checked by a test
        raise HermesUsageError(detail=f"the installed skill at {target} has no name and version")
    _logger.info("skill installed", extra={"skill": str(meta)})
    return meta
