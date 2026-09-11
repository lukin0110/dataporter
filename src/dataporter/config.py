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
`run`; `07` adds `browser` and `timeouts`; `08` adds two fields to `timeouts`;
`09` adds `hermes` and three more `timeouts` fields; `13` adds `retries` and one
more `run` field; `14` adds another `run` field; `15` adds `pacing` and the three
`with_pacing` flags.
"""

import os
import tomllib
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator
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
BROWSER_PROFILE_DIRNAME = "browser-profile"
HERMES_DIRNAME = "hermes"
DEFAULT_HERMES_HOME = Path("~/.hermes")

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
    measures what the composer really accepts and owns the value from then on;
    `docs/seed-limits.md` holds the measurement and the reason for the number.
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


class BrowserSettings(BaseModel):
    """The Chrome our tool owns (`07`)."""

    executable: Path | None = None
    """The browser binary. `None` means "look for one"; see
    `browser.launcher.find_executable`."""

    cdp_port: int = 9222
    """The remote-debugging port, always bound to `127.0.0.1`. The address is not
    configurable: a debug port reachable from another machine is a full-privilege
    handle on a signed-in Claude account."""

    extra_args: tuple[str, ...] = ()
    """Extra command-line flags, appended after the fixed ones and before the URL.

    Empty by design: the migration runs headed (§12 needs a window a human can act
    in), and every flag the run depends on is fixed in `launcher.LAUNCH_FLAGS` so
    that two operators launch the same browser. This exists for environments that
    cannot run that browser at all — a CI container with no display and no user
    namespaces needs `--headless=new --no-sandbox` — and the test suite is its
    only user today.
    """


class HermesSettings(BaseModel):
    """The external Hermes Agent, as `09` invokes it."""

    executable: Path | None = None
    """The `hermes` binary. `None` means "look for `hermes` on `PATH`"; see
    `hermes.client.HermesCli.path`."""

    profile: str = "dataporter"
    """The dedicated profile `setup` creates. Its config, memory, skills and
    session transcripts are separate from anything else the operator uses Hermes
    for, which is what lets `setup` be strict without breaking their defaults."""

    home: Path | None = None
    """*Our* view of where Hermes keeps its profiles. `None` means `~/.hermes`;
    read `Settings.hermes_home`, never this.

    This is the tree `setup` installs the skill into and `doctor` looks for it in.
    It does **not** tell Hermes anything: the subprocess environment is built from
    scratch (`hermes.client.hermes_env`) and carries no Hermes-home variable, so a
    value that disagrees with where the `hermes` on `PATH` really keeps its
    profiles would have `setup` write a skill Hermes never reads — and `doctor`
    confirm our own write. Override it only to match a Hermes whose home is not
    `$HOME/.hermes`, and see `09`'s Risks. `10` is where how Hermes finds its
    profiles stops being an assumption, and decides whether an override has to be
    propagated to the subprocess.

    Exists because the test suite needs a profile tree it can throw away.
    """

    toolsets: tuple[str, ...] = ("browser", "terminal")
    """`--toolsets` for every run. `browser` for the ref-based `browser_*` tools
    the skill drives the page with, `terminal` for our own helper commands.
    Nothing else: a run that can read the operator's files or reach the network
    directly is a wider surface than the migration needs (§17)."""

    max_turns: int = 80
    """`agent.max_turns` in the profile. One conversation is a dozen steps plus
    whatever recovery costs; `15` owns the number once there is evidence."""


class PacingSettings(BaseModel):
    """How slowly the run goes, and how long it will wait when told to (`15`).

    §13 asks for a run that is deliberately conservative, and these are the
    numbers that make it one. They are separate from `retries` because the two
    answer different questions: that one is *how many times*, this one is *how
    far apart*, and a run with no failures in it still spends every value here.
    """

    delay_between_conversations_s: float = Field(default=20.0, ge=0)
    """The gap after one conversation's terminal status and before the next one
    starts. `--delay`.

    Twenty seconds because the experiment is about reliability rather than
    throughput (§13): with a 300 s response budget it bounds a ten-conversation
    run to under an hour, and it keeps the request rate below what a person
    working through the same list by hand would produce.
    """

    delay_between_parts_s: float = Field(default=5.0, ge=0)
    """The gap between one part's acknowledgement and the next part's paste.

    Spent by the agent rather than by us — the whole per-part loop happens inside
    one Hermes run — so it reaches the page through the task prompt (`11`) and is
    the one pacing value this process does not itself sleep for.
    """

    max_rate_limit_wait_s: float = Field(default=3600.0, ge=0)
    """The longest wait the run will make on its own when the account asks for
    one. Beyond it the wait becomes `14`'s ask, because an hour is already longer
    than an operator who started a migration expects to watch nothing happen, and
    a tool that quietly sleeps until tomorrow has stopped being one.
    """


class RetrySettings(BaseModel):
    """How often one conversation is tried again, and how long between tries (`13`).

    The budget is per conversation, not per run: one pathological chat must not
    be able to spend every attempt the run has, and a run of ten conversations
    where the fourth needs two retries is not a run in trouble.
    """

    max_attempts: int = Field(default=3, ge=1)
    """Attempts per conversation, the first one included.

    At least one: a budget of zero would run a conversation once and then record
    `retry_recommended: false` about a failure nothing had retried, which is the
    statement `13` wrote the field to avoid.

    Counted against `state.json`'s `attempts`, which is cumulative over every run
    the workspace has seen — so a conversation that has already had three goes
    gets one more per invocation rather than three more, and an operator who asks
    for it again with `--retry-failed` is never silently refused.
    """

    backoff_s: tuple[float, ...] = (30.0, 120.0, 300.0)
    """The wait before attempt `n + 1`, indexed by the attempt that just failed.

    Growing, and generous: the failures worth retrying are a busy account, a
    dropped connection and a generation that fell over, none of which is helped
    by trying again immediately. A list shorter than `max_attempts` repeats its
    last value rather than running off the end; an empty one means no wait.
    """


class TimeoutSettings(BaseModel):
    """How long each wait is allowed to take, in seconds."""

    browser_start_s: float = 30.0
    """From spawning the browser to its debug port answering."""

    cdp_call_s: float = 20.0
    """One CDP request. Every call has one, so a wedged browser cannot hang a run."""

    login_s: float = 600.0
    """How long `login` waits for the operator to sign in. Ten minutes: it covers
    a password manager, an email code and a second factor without hurrying."""

    attach_s: float = 60.0
    """How long `browser attach` waits for the attachment chip to appear (`08`).

    An upload that claude.ai is still processing has not failed yet, and a minute
    covers the largest file `attachments.max_bytes` allows on a slow link.
    """

    response_s: float = 300.0
    """How long `browser await-response` waits for generation to finish (`08`).

    Five minutes: a seed is tens of kilobytes and the reply to it is a short
    acknowledgement, but the destination account may be busy. `15` owns what
    happens after the wait runs out.
    """

    hermes_cli_s: float = 60.0
    """One short `hermes` call — `--version`, `profile list`, `config set` (`09`).

    These are local and read or write a file; a minute is already generous, and it
    is short enough that `doctor` fails rather than hangs when the executable on
    `PATH` is something that never exits.
    """

    hermes_check_s: float = 300.0
    """One of `doctor`'s two `hermes -z` tasks (`09`).

    The task itself is trivial — snapshot a blank tab, run one helper — but Hermes
    has a model round trip and an environment to start, and the check exists to
    distinguish "does not work" from "is slow".
    """

    hermes_task_s: float = Field(default=1800.0, gt=0)
    """One conversation's `hermes -z` run (`09`, spent by `12`).

    Greater than zero, not merely non-negative: it becomes a subprocess deadline,
    and a run that is out of time before it starts is not a shorter run.

    Half an hour covers a multi-part seed whose every part waits on generation,
    with room for one recovery attempt inside the run. `15` owns it once a pilot
    has produced real durations.
    """


class RunSettings(BaseModel):
    """How much one invocation is allowed to do."""

    max_conversations: int = 10
    """Where an unset `--limit` comes from (`06`).

    A default rather than "everything": the experiment is a slow, sequential,
    account-modifying run, and a mistyped command that migrates ten conversations
    is recoverable in a way that one migrating twelve hundred is not. `21` raises
    it or passes `--limit` for the full export.
    """

    stop_after_consecutive_failures: int = 3
    """How many conversations may fail the same way in a row before the run stops.

    The circuit breaker (`13`): three `network` failures back to back say the
    connection is gone, not that three conversations were unlucky, and every
    further attempt is an account-modifying action taken on a broken premise.
    Declared here and spent by `12`'s loop; `15` owns the number once a pilot has
    shown what a real run's failure runs look like.
    """

    max_interventions: int = 5
    """How many times one run will stop and ask a human for help (`14`).

    A budget rather than a limitless loop because §12's pause is for the
    exceptional case. A run that has asked six times is not being helped through
    a CAPTCHA; something about the account or the page is wrong in a way that
    more Enters will not fix, and the honest end is to stop and let the report
    say what kept happening.

    Separate from `13`'s `retries.max_attempts` because the two count different
    things: that one bounds what the tool will try again on its own, this one
    bounds what it will ask a person to do. Both end the run when they run out,
    and `19` reports them apart.
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
    browser: BrowserSettings = BrowserSettings()
    hermes: HermesSettings = HermesSettings()
    pacing: PacingSettings = PacingSettings()
    retries: RetrySettings = RetrySettings()
    timeouts: TimeoutSettings = TimeoutSettings()
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

    @property
    def browser_profile_dir(self) -> Path:
        """Chrome's `--user-data-dir` (`07`).

        Inside the workspace and not configurable: the point of the dedicated
        profile is that it is *ours*, created by us, deletable by
        `session logout`, and never the operator's everyday one (§17).
        """
        return self.workspace / BROWSER_PROFILE_DIRNAME

    @property
    def hermes_dir(self) -> Path:
        """`<workspace>/hermes/`: one run's stdout, stderr and usage file (`09`).

        Inside the workspace and not configurable, for the same reason the seeds
        directory is not: these are intermediate artefacts of one migration, and
        the stdout of a Hermes run contains page snapshots — so it belongs in the
        directory `.gitignore` already excludes and `session logout` leaves alone.
        """
        return self.workspace / HERMES_DIRNAME

    @property
    def hermes_home(self) -> Path:
        """Where Hermes keeps its profiles — `~/.hermes` unless configured.

        A property rather than a validator default for the reason
        `attachments_dir` is one: `~` has to be expanded somewhere, and doing it
        at validation time would bake one operator's home into a `config.toml`
        another operator reads.
        """
        configured = self.hermes.home
        if configured is not None:
            return Path(os.path.abspath(configured.expanduser()))
        return Path(os.path.abspath(DEFAULT_HERMES_HOME.expanduser()))

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


def with_pacing(
    settings: Settings,
    *,
    delay: float | None = None,
    max_retries: int | None = None,
    timeout: float | None = None,
) -> Settings:
    """Apply `15`'s three `import` flags, which outrank every other source.

    §13 names four configurable parameters and gives three of them a flag;
    `--limit` is the fourth and is not here, because it is a property of the
    selection rather than of the settings and `06` already records it as one.

    Copies of the nested models rather than a reload with an init override, for
    the reason `with_attachments_dir` is a copy: `Settings(pacing={...})` would
    replace the whole `[pacing]` table and silently drop whatever else an
    operator put in `config.toml`. `None` means the flag was not given.

    `max_retries` is *retries*, as §13 words it, and `retries.max_attempts` is
    attempts — so `--max-retries 0` is one attempt and no second one. The two
    names differ by one on purpose: an operator thinks in "how many more goes",
    and `13`'s budget counts the goes themselves.

    Rebuilt rather than `model_copy(update=...)`, which does **not** validate:
    that is what let `--max-retries -1` through as a budget of zero attempts,
    and a conversation with no attempts has its first failure recorded
    `retry_recommended: false` — a statement about a retry nothing made. The
    constraint lives on the field rather than on the flag so that
    `HCM_RETRIES__MAX_ATTEMPTS=-1` and a hand-edited `config.toml` are refused
    by the same rule, in one place. (Raised by Copilot in review on #24.)
    """
    changes: dict[str, Any] = {}
    if delay is not None:
        changes["pacing"] = _revalidated(
            settings.pacing, delay_between_conversations_s=delay
        )
    if max_retries is not None:
        changes["retries"] = _revalidated(
            settings.retries, max_attempts=max_retries + 1
        )
    if timeout is not None:
        changes["timeouts"] = _revalidated(settings.timeouts, hermes_task_s=timeout)
    if not changes:
        return settings
    return settings.model_copy(update=changes)


def _revalidated[T: BaseModel](model: T, **changes: Any) -> T:
    """One nested settings table, rebuilt with `changes` and validated.

    Raises `ConfigError` for a value an operator can fix by typing a different
    one, which the CLI already reports as exit `2` — the same code and the same
    shape of message `--limit` gets for being negative.
    """
    try:
        return type(model)(**{**model.model_dump(), **changes})
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration: {_describe(exc)}") from exc


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
