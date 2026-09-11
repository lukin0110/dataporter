"""Hermes: the agent that drives the browser, as a subprocess we configure.

`09` built four pieces and nothing else:

- `version` — the least Hermes this build will drive;
- `client` — finding the `hermes` executable and making the short, metadata-shaped
  calls `setup` and `doctor` need, always in an environment we built;
- `profile` — what `setup` writes: a dedicated, locked-down `dataporter` profile;
- `skill` — installing the `claude-migrate` skill into that profile, and reading
  back its name and version;
- `runner` — one `-z` task per call, its output in the workspace, its answer
  validated as a `HermesResult`;
- `doctor` — the ten checks that prove the chain before a migration starts.

What the prompt says is `11`'s; what to do with a result is `12`–`14`'s. Hermes is
never imported as a library here, and nothing in this package reads its API key.
"""

from dataporter.hermes.client import Completed, HermesCli, hermes_env
from dataporter.hermes.doctor import Check
from dataporter.hermes.profile import SetupReport, profile_config, run_setup
from dataporter.hermes.runner import (
    HermesErrorInfo,
    HermesResult,
    HermesRunner,
    HermesUsage,
    RawRun,
    read_usage,
)
from dataporter.hermes.skill import SkillMeta
from dataporter.hermes.version import MINIMUM_VERSION

__all__ = [
    "MINIMUM_VERSION",
    "Check",
    "Completed",
    "HermesCli",
    "HermesErrorInfo",
    "HermesResult",
    "HermesRunner",
    "HermesUsage",
    "RawRun",
    "SetupReport",
    "SkillMeta",
    "hermes_env",
    "profile_config",
    "read_usage",
    "run_setup",
]
"""`doctor.checks` and `skill.install` are deliberately not re-exported: binding
`checks` or `install` here would say less than the module-qualified call does, and
`profile` is both a module of ours and a Hermes concept — `from dataporter.hermes
import profile` must keep meaning the module."""
