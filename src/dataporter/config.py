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

This slice defines the mechanism and the `workspace` field. Later slices add their
own sections (`browser`, `hermes`, `seed`, `pacing`, `retries`, `timeouts`, `run`,
`attachments`, `fidelity`) as nested models; nothing here needs to change for them.
"""

import os
import tomllib
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from pydantic import ValidationError, field_validator
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

_config_file: ContextVar[Path | None] = ContextVar("_config_file", default=None)
"""Set by `load_settings` so the TOML source knows which file to read."""


class ConfigError(Exception):
    """Configuration could not be loaded. The CLI reports this as exit code 2."""


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
    """Where to look for `config.toml`: CLI flag > environment > default."""
    if workspace is not None:
        return workspace
    from_env = os.environ.get(WORKSPACE_ENV_VAR, "").strip()
    if from_env:
        return Path(from_env)
    return DEFAULT_WORKSPACE


def config_file_for(workspace: Path | None = None) -> Path:
    """The `config.toml` path this invocation will read, if it exists."""
    return bootstrap_workspace(workspace) / CONFIG_FILENAME


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
