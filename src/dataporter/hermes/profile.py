"""What `setup` does: a dedicated Hermes profile, locked down, with our skill in it.

A profile of our own so that Hermes's config, memory, skills and session
transcripts are separate from anything else the operator uses Hermes for, and so
`setup` can be strict about all four without breaking their defaults (§17).

The configuration below is `09`'s, verbatim. Four of the keys are the safety
surface and are worth saying out loud:

- `browser.backend: off` turns Browser Use CLI mode off, so the single
  `browser_exec` tool — which writes arbitrary Python against the page — is not
  available. What remains is the ref-based `browser_*` tools plus `browser_cdp`:
  narrower, verifiable, and visible one call at a time in the transcript.
- `approvals.mode: manual` with `approvals.single_query_mode: deny` means a
  one-shot run, which has nobody to answer a prompt, *denies* whatever the
  approval layer flags instead of waving it through. `HERMES_YOLO_MODE` is never
  set, and `client.hermes_env` is what makes that structural.
- `browser.record_sessions: false` keeps page snapshots — which are conversation
  content — out of Hermes's session store. The transcript of a run still contains
  them; it lives under the Hermes profile and this module's `purge_hint` is what
  `setup` prints about it.
- `memory.memory_enabled: false`: nothing about one conversation may survive into
  the next run, because the only state this migration has is `state.json`.

`setup` is idempotent by construction: every key is set on every run, so two runs
leave the same config, and the skill is copied over whatever was there.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from dataporter import log
from dataporter.config import Settings
from dataporter.hermes import skill as skilling
from dataporter.hermes.client import HermesCli, home_relative

_logger = log.get_logger(__name__)

BACKEND_OFF = "off"
CDP_HOST = "127.0.0.1"
"""Never configurable, for the reason `browser.cdp_port`'s address is not: a debug
port reachable from another machine is a full-privilege handle on a signed-in
Claude account."""

MODEL_KEYS: tuple[str, ...] = (
    "agent.model",
    "agent.model_name",
    "model.name",
    "model",
    "llm.model",
)
"""Candidates for "which model is this profile using", tried in order.

Hermes's own spelling is not something `09` can know without a Hermes to ask, and
`setup` has to print the model before a migration may start. `10` replaces this
tuple with the one key it observed.
"""

NO_MODEL = "no model configured — run: hermes -p {profile} setup model"
"""`09`'s exact string. `setup` exits `6` with it."""


def cdp_url(settings: Settings) -> str:
    return f"http://{CDP_HOST}:{settings.browser.cdp_port}"


def profile_config(settings: Settings) -> dict[str, str]:
    """The keys `setup` sets, in the order `09` lists them.

    Two are derived rather than fixed — the CDP url follows `browser.cdp_port`, so
    an operator who moved the debug port does not have to remember to move it here
    too, and `agent.max_turns` follows `hermes.max_turns` because `15` is going to
    want to tune it. Every other value is a constant on purpose: a profile an
    operator can half-configure is a profile `doctor` cannot vouch for.
    """
    return {
        "browser.backend": BACKEND_OFF,
        "browser.cdp_url": cdp_url(settings),
        "browser.dialog_policy": "must_respond",
        "browser.dialog_timeout_s": "120",
        "browser.snapshot_threshold": "30000",
        "browser.inactivity_timeout": "3600",
        "browser.restrict_evaluate": "true",
        "browser.record_sessions": "false",
        "approvals.mode": "manual",
        "approvals.single_query_mode": "deny",
        "memory.memory_enabled": "false",
        "agent.max_turns": str(settings.hermes.max_turns),
    }


CHECKED_KEYS: tuple[str, ...] = ("browser.backend", "browser.cdp_url")
"""What `doctor`'s `hermes config` line reports, and the two that matter most: one
says the wide tool is off, the other says Hermes is pointed at our Chrome."""


def configured_model(config: Mapping[str, str]) -> str:
    """The model this profile will use, or `""` if none of `MODEL_KEYS` is set."""
    for key in MODEL_KEYS:
        value = config.get(key, "").strip()
        if value:
            return log.safe_token(value)
    return ""


@dataclass(frozen=True)
class SetupReport:
    """What `setup` did, as the lines it prints."""

    profile: str
    created: bool
    keys: int
    skill: skilling.SkillMeta
    skill_dir: str
    model: str

    def lines(self) -> list[str]:
        return [
            f"hermes profile   {self.profile} "
            f"({'created' if self.created else 'already existed'})",
            f"hermes config    {self.keys} keys set",
            f"skill            {self.skill} -> {self.skill_dir}",
            *([f"hermes model     {self.model}"] if self.model else []),
        ]


def purge_hint(settings: Settings) -> str:
    """Where Hermes's own transcripts live, and therefore what to delete.

    §10 keeps content off stdout and out of our logs, but Hermes's transcript of a
    run contains page snapshots whatever we do. `setup` says where they are rather
    than pretending they are not there.
    """
    return (
        f"Hermes session transcripts contain page snapshots, and therefore "
        f"conversation content. They live under "
        f"{home_relative(skilling.profile_dir(settings))}/ — delete that directory "
        f"to purge them."
    )


def run_setup(settings: Settings) -> SetupReport:
    """Create the profile if it is missing, configure it, install the skill.

    The order matters in one place only: the profile has to exist before anything
    can be set on it. Everything after that is idempotent, so a `setup` that dies
    half way is fixed by running it again.
    """
    cli = HermesCli(settings)
    existing = cli.profiles()
    created = cli.profile not in existing
    if created:
        _logger.info("creating hermes profile", extra={"profile": cli.profile})
        cli.create_profile()

    config = profile_config(settings)
    for key, value in config.items():
        cli.config_set(key, value)

    meta = skilling.install(settings)
    return SetupReport(
        profile=cli.profile,
        created=created,
        keys=len(config),
        skill=meta,
        skill_dir=home_relative(skilling.install_dir(settings)),
        model=configured_model(cli.config()),
    )
