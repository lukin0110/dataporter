"""Configuration.

Precedence, highest first: CLI flag > environment > `<workspace>/config.toml` >
defaults. `settings_customise_sources` expresses that literally — the first source
in the returned tuple wins.

The workspace is the one setting that has to be resolved twice, because
`config.toml` lives *inside* the workspace. A bootstrap pass picks the workspace
from the CLI flag, then `HCM_WORKSPACE`, then the default, and the config file is
read from there. A `workspace` key inside `config.toml` therefore still sets the
workspace — it just does not relocate config discovery, so there is no fixed-point
to iterate and no possible cycle.

`01` defined the mechanism and the `workspace` field. Later slices add their own
sections (`browser`, `hermes`, `pacing`, `retries`, `timeouts`, `fidelity`) as
nested models; nothing here needs to change for them. `03` is the first to do it,
adding `seed` and `attachments` — plain `BaseModel`s, so `HCM_SEED__MAX_CHARS` and
a `[attachments]` table in `config.toml` work with no new machinery. `06` adds
`run`.
"""

import os
import tomllib
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    SettingsError,
    TomlConfigSettingsSource,
)

DEFAULT_WORKSPACE = Path("migration")
CONFIG_FILENAME = "config.toml"
WORKSPACE_ENV_VAR = "HCM_WORKSPACE"
ATTACHMENTS_DIRNAME = "attachments"
SEEDS_DIRNAME = "seeds"

_config_file: ContextVar[Path | None] = ContextVar("_config_file", default=None)
"""Set by `load_settings` so the TOML source knows which file to read."""


class ConfigError(Exception):
    """Configuration could not be loaded. The CLI reports this as exit code 2."""


class SeedSettings(BaseModel):
    """How much rendered conversation goes into one chat, and into one message."""

    max_chars: int = 50_000
    """Budget for a single seed part. `04` splits on it; `03` counts parts with it.

    Declared here rather than in `04` because `ConversationPlan.chunk_count` is a
    `03` field and a chunk count without a chunk budget is not a number. `10`
    measures what the composer really accepts and owns the value from then on.
    """

    hard_max_chars: int = 400_000
    """Above this a conversation is not migrated at all.

    Chunking spreads a seed across messages but not across a chat's context, so
    there is a size no number of parts rescues. `10` may lower it.
    """


class AttachmentSettings(BaseModel):
    """The operator's observed claude.ai upload limits.

    *Assumed* until `10` and `16` confirm them against the real UI.
    """

    dir: Path | None = None
    """Where attachment bytes are, when the operator has them. `None` means
    `<workspace>/attachments`; read `Settings.attachments_dir`, never this."""

    max_bytes: int = 30_000_000
    max_per_chat: int = 20
    accepted_types: tuple[str, ...] = (
        "csv",
        "docx",
        "gif",
        "html",
        "jpeg",
        "jpg",
        "js",
        "json",
        "md",
        "pdf",
        "png",
        "py",
        "ts",
        "txt",
        "webp",
        "xlsx",
        "xml",
        "yaml",
    )
    """Extensions, lowercase, without a dot. Sorted so the default reads as a set
    rather than as a ranking; `03` matches against it and never iterates it."""

    @field_validator("accepted_types")
    @classmethod
    def _normalise(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        # `03` compares against a casefolded suffix, so `PDF` or `.pdf` in an
        # operator's config.toml would silently accept nothing.
        return tuple(item.strip().lstrip(".").casefold() for item in value)


class RunSettings(BaseModel):
    """How much one invocation is allowed to do."""

    max_conversations: int = 10
    """Where an unset `--limit` comes from (`06`).

    A default rather than "everything": the experiment is a slow, sequential,
    account-modifying run, and a mistyped command that migrates ten conversations
    is recoverable in a way that one migrating twelve hundred is not. `21` raises
    it or passes `--limit` for the full export.
    """


class Settings(BaseSettings):
    """Effective settings for one invocation."""

    model_config = SettingsConfigDict(
        env_prefix="HCM_",
        env_nested_delimiter="__",
        # An empty HCM_WORKSPACE= in a shell script should mean "unset", not "cwd".
        env_ignore_empty=True,
    )

    workspace: Path = DEFAULT_WORKSPACE
    """Holds state, seeds, logs, the browser profile and the report. Never inside
    the export."""

    seed: SeedSettings = SeedSettings()
    attachments: AttachmentSettings = AttachmentSettings()
    run: RunSettings = RunSettings()

    @property
    def attachments_dir(self) -> Path:
        """Where `03` looks for attachment bytes.

        A property rather than a validator default because `attachments.dir` and
        `workspace` are set from different sources at different precedences, and
        resolving one against the other at validation time would freeze whichever
        happened to be validated first.
        """
        if self.attachments.dir is not None:
            return Path(os.path.abspath(self.attachments.dir))
        return self.workspace / ATTACHMENTS_DIRNAME

    @property
    def seeds_dir(self) -> Path:
        """Where `04` writes `part-NN.txt` and `12` reads them from.

        Not configurable: the seeds are an intermediate artefact of one workspace,
        and `seeds --out` already covers wanting them somewhere else for a look.
        """
        return self.workspace / SEEDS_DIRNAME

    @field_validator("workspace")
    @classmethod
    def _absolute(cls, value: Path) -> Path:
        # `09` runs Hermes with cwd=<workspace>, so this must be absolute well
        # before any subprocess starts. abspath, not resolve: no symlink chasing.
        return Path(os.path.abspath(value))

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings]
        config_file = _config_file.get()
        if config_file is not None:
            # Reads to {} when the file is absent, so no existence check here.
            sources.append(
                TomlConfigSettingsSource(settings_cls, toml_file=config_file)
            )
        # pydantic-settings appends the defaults source itself.
        return tuple(sources)


def bootstrap_workspace(workspace: Path | None = None) -> Path:
    """Where to look for `config.toml`: CLI flag > environment > default.

    Written out rather than as an `orval.coalesce_lazy` chain, which is what this
    is: `coalesce_lazy` is typed `-> T | None` even when its last argument cannot
    be `None`, so `ty` rejects it against `-> Path`. Reaching for a helper and
    then adding a `cast` to silence what it cost is not a trade worth making.
    See `docs/orval-candidates.md` (D2).
    """
    if workspace is not None:
        return workspace
    from_env = os.environ.get(WORKSPACE_ENV_VAR, "").strip()
    if from_env:
        return Path(from_env)
    return DEFAULT_WORKSPACE


def config_file_for(workspace: Path | None = None) -> Path:
    """The `config.toml` path this invocation will read, if it exists."""
    return bootstrap_workspace(workspace) / CONFIG_FILENAME


def with_attachments_dir(settings: Settings, directory: Path | None) -> Settings:
    """Apply `--attachments-dir`, which outranks every other source.

    A copy of the loaded settings rather than a reload with an init override:
    `attachments.dir` is one field of a nested model, and handing
    `attachments={"dir": ...}` to `Settings` would replace the whole `[attachments]`
    table, silently dropping whatever else an operator put in `config.toml`.

    `None` means the flag was not given, and returns the settings unchanged —
    passing it through as a value would blank a configured directory.
    """
    if directory is None:
        return settings
    return settings.model_copy(
        update={
            "attachments": settings.attachments.model_copy(update={"dir": directory})
        }
    )


def load_settings(*, workspace: Path | None = None) -> Settings:
    """Build `Settings`, honouring the precedence ladder.

    `workspace` is the value of the `--workspace` flag, or `None` when it was not
    given. It must be omitted from the init source entirely when unset — passing
    `None` through would win against the environment and silently blank it.

    Raises `ConfigError` for anything an operator can fix by editing config or
    re-running with different arguments; the CLI turns that into exit code 2.
    """
    config_file = config_file_for(workspace)
    overrides: dict[str, Any] = {} if workspace is None else {"workspace": workspace}

    token = _config_file.set(config_file)
    try:
        return Settings(**overrides)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid config file: {config_file}: {exc}") from exc
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration: {_describe(exc)}") from exc
    except SettingsError as exc:
        raise ConfigError(f"invalid configuration: {exc}") from exc
    finally:
        _config_file.reset(token)


def _describe(exc: ValidationError) -> str:
    """A one-line, operator-facing rendering of a pydantic validation failure."""
    parts = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"]) or "(root)"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)
