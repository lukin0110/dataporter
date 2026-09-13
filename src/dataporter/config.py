"""Configuration.

Precedence, highest first: CLI flag > environment > `<workspace>/config.toml` >
defaults. `settings_customise_sources` expresses that literally — the first source
in the returned tuple wins.

The workspace is the one setting that has to be resolved twice, because
`config.toml` lives *inside* the workspace. A bootstrap pass picks the workspace
from the CLI flag, then `DATAPORTER_WORKSPACE`, then the default, and the config file is
read from there. A `workspace` key inside `config.toml` therefore still sets the
workspace — it just does not relocate config discovery, so there is no fixed-point
to iterate and no possible cycle.

`01` defined the mechanism and the `workspace` field. Later slices add their own
sections (`browser`, `hermes`, `pacing`, `retries`, `timeouts`, `fidelity`) as
nested models; nothing here needs to change for them. `03` is the first to do it,
adding `seed` and `attachments` — plain `BaseModel`s, so `DATAPORTER_SEED__MAX_CHARS`
and a `[attachments]` table in `config.toml` work with no new machinery. `06` adds
`run`; `07` adds `browser` and `timeouts`; `08` adds two fields to `timeouts`;
`09` adds `hermes` and three more `timeouts` fields; `13` adds `retries` and one
more `run` field; `14` adds another `run` field; `15` adds `pacing` and the three
`with_pacing` flags; `17` adds `fidelity` and one more `timeouts` field. `30`
adds `store` and `accounts`, one more `timeouts` field, and the two per-invocation
labels — `source` and `account` — that say whose account a command is about.
"""

import os
import re
import tomllib
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orval import coalesce_lazy
from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    SettingsError,
    TomlConfigSettingsSource,
)

DEFAULT_WORKSPACE = Path("migration")
CONFIG_FILENAME = "config.toml"
WORKSPACE_ENV_VAR = "DATAPORTER_WORKSPACE"
ATTACHMENTS_DIRNAME = "attachments"
SEEDS_DIRNAME = "seeds"
PILOT_DIRNAME = "pilot"
BROWSER_PROFILE_DIRNAME = "browser-profile"
HERMES_DIRNAME = "hermes"
DEFAULT_HERMES_HOME = Path("~/.hermes")
DEFAULT_STORE = Path("~/.dataporter/store")
DEFAULT_ACCOUNTS = Path("~/.dataporter/accounts")

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

    skip: bool = False
    """`--skip-attachments` (`16`): upload nothing.

    A setting rather than a flag the import loop carries, because the decision
    has to reach `03` — an entry nobody will upload is class 3 with the reason
    `skipped_by_flag`, and the seed then says the file was not reproduced rather
    than promising a chip that no run is going to attach.
    """

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

    headless: bool | None = None
    """Whether Chrome runs without a window (`24`).

    `None` — the default — means "headless exactly when the run is
    non-interactive": a window is what §12's pause hands a person, and an
    unattended run has no person. `true` or `false` overrides that either way.
    Read `Settings.headless`, never this.
    """

    extra_args: tuple[str, ...] = ()
    """Extra command-line flags, appended after the fixed ones and before the URL.

    Empty by design: every flag the run depends on is fixed in
    `launcher.LAUNCH_FLAGS` so that two operators launch the same browser, and
    `headless` is a setting of its own. This exists for what a particular
    environment needs on top — a CI container with no user namespaces needs
    `--no-sandbox` — and the test suite is its only user today.
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

    signin_s: float = Field(default=120.0, gt=0)
    """How long the unattended sign-in (`24`) gives the form to become a signed-in
    page after the credentials went in. Two minutes: a redirect or two and no
    person to wait for."""

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

    verify_s: float = 30.0
    """How long `17`'s verification waits for a reloaded chat to render.

    Not `response_s`: nothing is being generated here. The page is navigated to a
    chat that already exists and polled until its transcript is there, which is a
    page load and a render — half a minute is generous for both, and a wait that
    runs out is reported as a failed check rather than as a passed one.
    """

    download_idle_s: float = Field(default=120.0, gt=0)
    """How long one read of a fetched archive may stall (`30`).

    `urllib`'s `timeout` is per socket operation and not per download, and the
    name says so: a two-gigabyte archive on a slow link is not late, a
    connection that has sent nothing for two minutes is. A whole-download
    deadline would have to be guessed from a size nobody knows in advance.
    """

    ask_s: float = Field(default=60.0, gt=0)
    """How long `31`'s ask waits for the export page to say it was requested.

    A minute: the ask is a button, a confirmation dialog and whatever the page
    does about it, none of which is a generation or a download. Greater than
    zero for the reason `hermes_task_s` is — a wait with no time in it would
    report "no confirmation" about a page nobody looked at — and a wait that
    runs out writes no `ask.json`, so the export may have been requested and the
    tool says it cannot tell rather than pretending either way.
    """

    hermes_task_s: float = Field(default=1800.0, gt=0)
    """One conversation's `hermes -z` run (`09`, spent by `12`).

    Greater than zero, not merely non-negative: it becomes a subprocess deadline,
    and a run that is out of time before it starts is not a shorter run.

    Half an hour covers a multi-part seed whose every part waits on generation,
    with room for one recovery attempt inside the run. `15` owns it once a pilot
    has produced real durations.
    """


class FidelitySettings(BaseModel):
    """What `17` tries to reproduce beyond the messages themselves (§15).

    One question, asked twice: is a chat's *title* part of what gets migrated?
    §15 asks for "equivalent titles", the UI is the only way to set one, and
    `10`'s question 7 is whether renaming through it is reliable enough to be a
    verified step. Until somebody has watched it, the default is to try —
    a rename that does not take is recorded as the limitation `title_not_set`
    and costs the conversation nothing.
    """

    rename_title: bool = True
    """Whether the `rename` step runs at all.

    `false` skips it and records `title_not_set` for every conversation, which is
    what an operator sets when `10` finds no rename affordance — or when they
    would rather not have an agent opening chat menus in their account. Either
    way "equivalent titles" is then met only by the header line `04` writes into
    the seed, and `docs/LIMITATIONS.md` says so.
    """

    title_max_chars: int = Field(default=200, ge=1)
    """How much of a source title is typed into the rename field.

    A title comes out of an export we do not control and reaches the page
    through the agent's own `browser_type` (`17`'s design notes), so it is
    bounded before it is sent: anything longer is truncated and ends in `…`, and
    the same truncated string is what verification compares the displayed title
    against. Two hundred characters is longer than any title a person writes and
    short enough to type in one action.
    """


class JudgeSettings(BaseModel):
    """`20`'s optional second opinion on question 3.

    The one place in this tool where a model judges anything, and it is optional:
    every §19 metric is counted, the semantic probe is graded by hand, and this
    grades the same replies again so that a disagreement between the two is
    itself a finding. Nothing here is used unless `judge` is run, and `judge`
    itself is behind the `judge` extra.
    """

    model: str = "anthropic:claude-sonnet-5"
    """What grades a reply, in `pydantic-ai`'s `provider:model` spelling.

    Configurable because the judge is an experiment's instrument and `21` may
    want the same replies graded by something else; the key it authenticates
    with is `ANTHROPIC_API_KEY`, which this tool reads no more than it reads the
    one Hermes uses — it is passed through the environment and never recorded.
    """

    max_seed_chars: int = Field(default=20_000, ge=1)
    """How much of the source conversation the judge is shown.

    A judge that is handed a 40 kB seed is being asked to read the conversation
    rather than to recognise it, and the question is whether a one-sentence
    summary is *about* this conversation. The first part, capped, is what a
    person grading by hand reads too.
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


class StoreSettings(BaseModel):
    """Where snapshots are kept, and how much one fetch may download (`30`).

    Brief `03` §33: the store is a directory on disk today and a bucket later,
    and nothing about a snapshot changes when it is. Only two things about it
    are an operator's to set — where it is, and the ceiling on a download — so
    that is the whole table.
    """

    dir: Path | None = None
    """The store's root. `None` means `~/.dataporter/store`; read
    `Settings.store_dir` for the resolved path and `Settings.store_display` for
    the one an operator reads back."""

    max_download_bytes: int = Field(default=5_000_000_000, ge=1)
    """The ceiling on one fetched archive.

    Five gigabytes: larger than any export anybody has reported and small enough
    that a link leading to something else cannot fill a disk before it is
    refused. Enforced on the stream rather than on a `Content-Length` header,
    which the vendor's storage host is not obliged to send and which a wrong
    link is under no obligation to tell the truth in.
    """


class AccountsSettings(BaseModel):
    """Where the tool keeps what it knows about a source account (`30`, `31`).

    The account home is the operational half of an account: its browser profile,
    its open ask, its logs. None of it is a snapshot, so none of it is in the
    store — brief `03` §33 says the store holds nothing a migration writes, and
    cookies and abandonable records are exactly what a cloud store must never
    receive.
    """

    dir: Path | None = None
    """The root that holds `<source>/<account>/`. `None` means
    `~/.dataporter/accounts`; read `Settings.accounts_dir`."""


class AuthSettings(BaseModel):
    """The credentials of the account this invocation signs in to (`24`, `31`).

    The destination's for everything the first brief describes, and the source
    account's for `31`'s ask — one invocation signs in to one account, so one
    pair of fields serves both and an operator asking for two accounts in one
    command was never a thing this tool did. §35 holds the source to §8's rules
    exactly: held in memory for one invocation, written nowhere, never in a
    snapshot.

    From the environment (`DATAPORTER_AUTH__EMAIL`, `DATAPORTER_AUTH__PASSWORD`) or the
    command line (`--email`, `--password-file`) and never from `config.toml` —
    `_TomlWithoutSecrets` refuses a file that carries them. `SecretStr` keeps
    the value out of `repr`, `model_dump` and every log record; nothing but
    `login_form` ever asks it for the value.
    """

    email: str | None = None
    password: SecretStr | None = None


@dataclass(frozen=True)
class Credentials:
    """Both halves, present. What `signin` asks for and `login_form` types."""

    email: str
    password: SecretStr


class Settings(BaseSettings):
    """Effective settings for one invocation."""

    model_config = SettingsConfigDict(
        env_prefix="DATAPORTER_",
        env_nested_delimiter="__",
        # An empty DATAPORTER_WORKSPACE= in a shell script should mean "unset",
        # not "cwd".
        env_ignore_empty=True,
    )

    workspace: Path = DEFAULT_WORKSPACE
    """Holds state, seeds, logs, the browser profile and the report. Never inside
    the export."""

    non_interactive: bool = False
    """`24`'s mode: nothing waits for a person. Chrome runs headless unless
    `browser.headless` says otherwise, a signed-out session is signed in from
    `auth` rather than handed to an operator, and a page only a person can clear
    is recorded as a pause and exited on. `--non-interactive` or
    `DATAPORTER_NON_INTERACTIVE=1`; never `config.toml`, for the reason `auth` is
    not."""

    source: str = "claude"
    """Which vendor this invocation is talking to (`30`, brief `03` §34).

    One of `store.SOURCES`. Set for one invocation by `with_account`, never by
    `config.toml`: a source in a file would silently send the next `extract` at
    a vendor the operator did not name.
    """

    account: str | None = None
    """The source account's label — the operator's own word for whose account
    this is, never the login (brief `03` §33).

    `None` outside `extract` and `31`'s `login --account`: the commands of the
    first brief mean the destination, and they go on meaning it.
    """

    auth: AuthSettings = AuthSettings()
    store: StoreSettings = StoreSettings()
    accounts: AccountsSettings = AccountsSettings()
    seed: SeedSettings = SeedSettings()
    attachments: AttachmentSettings = AttachmentSettings()
    browser: BrowserSettings = BrowserSettings()
    hermes: HermesSettings = HermesSettings()
    fidelity: FidelitySettings = FidelitySettings()
    pacing: PacingSettings = PacingSettings()
    retries: RetrySettings = RetrySettings()
    timeouts: TimeoutSettings = TimeoutSettings()
    run: RunSettings = RunSettings()
    judge: JudgeSettings = JudgeSettings()

    @property
    def headless(self) -> bool:
        """Whether the browser gets a window: `browser.headless`, else the mode."""
        configured = self.browser.headless
        return self.non_interactive if configured is None else configured

    @property
    def credentials(self) -> Credentials | None:
        """Both halves of `auth`, or nothing: half a credential is no credential.

        Blank counts as absent on both sides. `env_ignore_empty` already drops
        an empty variable, but a whitespace value and a `--password-file` whose
        first line is blank arrive here as strings, and a run that started a
        browser on one would stop at the first form — the opposite of the
        "exit `2` before any browser" promise. (Raised by Copilot in review on
        #33.)
        """
        email = (self.auth.email or "").strip()
        secret = self.auth.password
        if email and secret is not None and secret.get_secret_value().strip():
            return Credentials(email=email, password=secret)
        return None

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
    def store_dir(self) -> Path:
        """Where snapshots are filed: `store.dir`, else `~/.dataporter/store`.

        A property for the reason `attachments_dir` is one — `~` and a relative
        path are resolved for this invocation and not baked into a `config.toml`
        somebody else reads. `store_display` is the same path as an operator
        typed it, which is what the blocks print.
        """
        if self.store.dir is not None:
            return Path(os.path.abspath(self.store.dir.expanduser()))
        return Path(os.path.abspath(DEFAULT_STORE.expanduser()))

    @property
    def store_display(self) -> str:
        """The store as configured, `~` unexpanded when the default was used.

        §31's block prints a snapshot's path, and an operator who has never
        configured a store reads `~/.dataporter/store/…` rather than one
        machine's home directory. `str(Path("~/x"))` keeps the tilde, so this is
        the same join the resolved path makes and not a second spelling of it.
        """
        configured = self.store.dir
        return str(configured if configured is not None else DEFAULT_STORE)

    @property
    def accounts_dir(self) -> Path:
        """Where account homes live: `accounts.dir`, else `~/.dataporter/accounts`."""
        if self.accounts.dir is not None:
            return Path(os.path.abspath(self.accounts.dir.expanduser()))
        return Path(os.path.abspath(DEFAULT_ACCOUNTS.expanduser()))

    @property
    def account_home(self) -> Path | None:
        """`<accounts>/<source>/<account>`, or `None` when no account is named.

        Everything the tool keeps about one source account that is not a
        snapshot: `31`'s browser profile, the open ask, the logs. Never in the
        store (brief `03` §33).
        """
        if self.account is None:
            return None
        return self.accounts_dir / self.source / self.account

    @property
    def logs_dir(self) -> Path:
        """What `log.enable_run_log` is handed: the account home, else the
        workspace. The run log lands in `<it>/logs/` either way.

        An extraction has no workspace — it is about an account rather than
        about a migration — so its records belong beside the account's other
        operational files rather than in a `./migration` that nothing else in
        the command would have created.
        """
        home = self.account_home
        return self.workspace if home is None else home

    @property
    def seeds_dir(self) -> Path:
        """Where `04` writes `part-NN.txt` and `12` reads them from.

        Not configurable: the seeds are an intermediate artefact of one workspace,
        and `seeds --out` already covers wanting them somewhere else for a look.
        """
        return self.workspace / SEEDS_DIRNAME

    @property
    def pilot_dir(self) -> Path:
        """`<workspace>/pilot/`: the follow-up question, and the replies to it.

        Inside the workspace and not configurable, for the reason `seeds_dir` is
        not — and content-bearing for the same reason a seed is: a reply is a
        message out of the destination account, so it lives where §10 already
        keeps conversation text, is never printed and is never logged.
        """
        return self.workspace / PILOT_DIRNAME

    @property
    def browser_profile_dir(self) -> Path:
        """Chrome's `--user-data-dir` (`07`, `31`).

        Not configurable: the point of the dedicated profile is that it is
        *ours*, created by us, deletable by `session logout`, and never the
        operator's everyday one (§17).

        Where it is depends on whose session it is. Without an account it is the
        destination's and lives in the workspace, exactly as `07` put it. With
        one it is that source account's and lives in the account home, because
        one browser profile holds one signed-in identity per site (§35) — a
        source signed in over the destination's profile would sign the
        destination out, and `import` would find somebody else's account behind
        the composer.
        """
        home = self.account_home
        base = self.workspace if home is None else home
        return base / BROWSER_PROFILE_DIRNAME

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
            sources.append(_TomlWithoutSecrets(settings_cls, toml_file=config_file))
        # pydantic-settings appends the defaults source itself.
        return tuple(sources)


NOT_IN_CONFIG_FILE = ("auth", "non_interactive", "source", "account")
"""The keys `config.toml` may not carry (`24`, `30`).

A credential in a file next to the export is a credential somebody will commit,
copy or leave behind; `non_interactive` travels with it because a file that
switches the mode on is a file that expects the credentials to be there too.

`30` adds the other two for a different reason: `source` and `account` say
*whose* account a command is about, and a label left in a file would silently
send the next `login` or `extract` at an account nobody named on the command
line. Like the credentials, they are set per invocation — by `with_account`,
from the flags — and never read out of a file.
"""

CONFIG_FILE_REFUSED = (
    "{keys} belong in the environment or on the command line, not in config.toml"
)


class _TomlWithoutSecrets(TomlConfigSettingsSource):
    """`config.toml`, refused rather than read when it carries `24`'s two tables.

    Refused and not ignored: an operator who put them there would otherwise
    learn that the file did nothing only when the run waited for a person.
    """

    def __call__(self) -> dict[str, Any]:
        found = super().__call__()
        present = [key for key in NOT_IN_CONFIG_FILE if key in found]
        if present:
            raise ConfigError(CONFIG_FILE_REFUSED.format(keys=" and ".join(present)))
        return found


def _workspace_from_env() -> Path | None:
    """`DATAPORTER_WORKSPACE`, or `None` when it is unset or blank.

    Blank is `None` rather than `Path("")`, which is `Path(".")` — an empty
    variable means the operator said nothing, not that the workspace is the
    working directory.
    """
    value = os.environ.get(WORKSPACE_ENV_VAR, "").strip()
    return Path(value) if value else None


def bootstrap_workspace(workspace: Path | None = None) -> Path:
    """Where to look for `config.toml`: CLI flag > environment > default.

    An `orval.coalesce_lazy` chain, which is exactly what this is. It could not
    be one until 0.0.12: `coalesce_lazy` was typed `-> T | None` even when its
    last argument could not be `None`, so `ty` rejected it against `-> Path`.
    0.0.12's overloads narrow the return type for chains of up to five values.
    See `docs/orval-candidates.md` (D2).
    """
    return coalesce_lazy(
        lambda: workspace, _workspace_from_env, lambda: DEFAULT_WORKSPACE
    )


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


SOURCE_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
"""What a source name may look like before it is looked up at all.

The lookup is what actually decides — `SOURCES` is the list of sources that
exist — but a token that could never be a source name is refused with the same
message rather than reaching a path join.
"""

LABEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
"""What an account label may look like.

It becomes a directory name in the store and in the accounts tree, so it is
bounded, lowercase, and free of anything a shell, a path or an object key would
have to be told about. Sixty-four characters is longer than any label anybody
writes twice.
"""

NO_SUCH_SOURCE = "no such source: {token}"
BAD_LABEL = (
    "account label must be letters, digits, dots, dashes or underscores: {token}"
)


def with_account(settings: Settings, source: str | None, account: str) -> Settings:
    """Name whose account this invocation is about (`30`), for this one call.

    `None` for `source` means the flag was not given, and the settings' own
    value — `claude` unless the environment says otherwise — stands; the value
    that results is validated either way, so an impossible source arriving
    through `DATAPORTER_SOURCE` is refused by the same rule as one typed.

    A `model_copy` override in the `with_attachments_dir` family, and for the
    same reason: these are two scalar fields of one invocation rather than a
    table an operator configured, and `config.toml` may carry neither.

    Both are checked before anything joins them to a path. `..` is not a legal
    label under `LABEL_PATTERN` and `claude/../..` is not a legal source, which
    is what keeps `<store>/<source>/<account>/` inside the store.
    """
    effective = settings.source if source is None else source
    if not SOURCE_PATTERN.match(effective) or effective not in _sources():
        raise ConfigError(NO_SUCH_SOURCE.format(token=effective))
    if not LABEL_PATTERN.match(account) or set(account) <= {"."}:
        raise ConfigError(BAD_LABEL.format(token=account))
    return settings.model_copy(update={"source": effective, "account": account})


def _sources() -> tuple[str, ...]:
    """`store.SOURCES`, imported here so that `store` may import this module.

    The same shape as `cli.state_error`: the list of vendors the tool has is a
    fact about the store, and the store is what needs `Settings`.
    """
    from dataporter.store import SOURCES

    return SOURCES


SOURCE_WITHOUT_ACCOUNT = "--source names the vendor of an account; give --account LABEL"


def with_session_account(
    settings: Settings, source: str | None, account: str | None
) -> Settings:
    """Whose session `login`, `session status` and `session logout` mean (`31`).

    `None` for `account` is the destination, which is what those three commands
    have always meant and go on meaning: the settings come back untouched, so
    the profile stays in the workspace and every byte of their output is what it
    was before this slice. A label is a source account, and is applied through
    `with_account` — the same validation, the same two fields, the same refusal
    for a label that could not be a directory name.

    `--source` without `--account` is refused rather than ignored: it names the
    vendor of an account nobody gave, and a flag accepted and quietly dropped is
    what `12` ruled out for `--pilot`.
    """
    if account is None:
        if source is not None:
            raise ConfigError(SOURCE_WITHOUT_ACCOUNT)
        return settings
    return with_account(settings, source, account)


def with_store_dir(settings: Settings, directory: Path | None) -> Settings:
    """Apply `--store DIR`, which outranks every other source.

    A copy of the nested model, and `None` returning the settings unchanged, for
    the reasons `with_attachments_dir` is both.
    """
    if directory is None:
        return settings
    return settings.model_copy(
        update={"store": settings.store.model_copy(update={"dir": directory})}
    )


def with_skip_attachments(settings: Settings, skip: bool) -> Settings:
    """Apply `--skip-attachments` (`16`), which outranks every other source.

    A copy of the nested model for the reason `with_attachments_dir` is one, and
    `False` returns the settings unchanged: the flag is an instruction to skip,
    never an instruction to upload, so an operator who put `skip = true` in
    `config.toml` is not overridden by its absence on the command line.
    """
    if not skip:
        return settings
    return settings.model_copy(
        update={"attachments": settings.attachments.model_copy(update={"skip": True})}
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
    `DATAPORTER_RETRIES__MAX_ATTEMPTS=-1` and a hand-edited `config.toml` are refused
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


def load_settings(
    *,
    workspace: Path | None = None,
    non_interactive: bool = False,
    email: str | None = None,
    password_file: Path | None = None,
) -> Settings:
    """Build `Settings`, honouring the precedence ladder.

    `workspace` is the value of the `--workspace` flag, or `None` when it was not
    given. It must be omitted from the init source entirely when unset — passing
    `None` through would win against the environment and silently blank it. The
    three `24` flags follow the same rule: `--non-interactive` is only an
    override when it was typed, and `--email` and `--password-file` each set the
    one half of `auth` they name, so a flag beside an environment variable is
    the flag winning for that half and the environment keeping the other.

    `password_file` is read here, once, first line only, stripped: a value on
    the command line would be in `ps` and the shell's history, and a file is the
    other channel an operator has that neither can see.

    Raises `ConfigError` for anything an operator can fix by editing config or
    re-running with different arguments; the CLI turns that into exit code 2.
    """
    config_file = config_file_for(workspace)
    overrides: dict[str, Any] = {} if workspace is None else {"workspace": workspace}
    if non_interactive:
        overrides["non_interactive"] = True
    auth: dict[str, Any] = {}
    if email is not None:
        auth["email"] = email
    if password_file is not None:
        auth["password"] = _first_line(password_file)
    if auth:
        # The init source outranks the environment and would replace the whole
        # `auth` table, so the half the flags did not set is read from the
        # environment here and carried along.
        for key in ("email", "password"):
            from_env = os.environ.get(f"DATAPORTER_AUTH__{key.upper()}", "")
            if key not in auth and from_env:
                auth[key] = from_env
        overrides["auth"] = auth

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


def _first_line(path: Path) -> str:
    """The credential in `path`: its first line, stripped. Never logged."""
    try:
        with path.open(encoding="utf-8") as handle:
            return handle.readline().strip()
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror or exc}") from exc


def _describe(exc: ValidationError) -> str:
    """A one-line, operator-facing rendering of a pydantic validation failure."""
    parts = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"]) or "(root)"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)
