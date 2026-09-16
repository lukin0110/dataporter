"""The agent wiring in `.claude/`, held against the tool that keeps rewriting it.

Graft is development tooling with a habit: `reconcileWiring` (its `dist/upkeep.js:240`)
rewrites every file it believes it owns — both `.claude/helpers/` shims, `.claude/settings.json`,
`.claude/skills/graft/` and `.mcp.json` — whenever the version stamp under the git-ignored
`graft/.cache/` disagrees with the running binary. It is called from graft's own session-start
hook and from MCP boot, so it fires at the start of a session, on every upgrade and in every
fresh clone, with nobody running a command at all. Three hand edits were reverted that way in
`35c777e`, went unreviewed inside a commit about test naming, were restored in `9ac30b9`, and
were reverted again the next morning.

The fix is structural and lives in the filenames: graft decides this repo is Claude-wired by
testing for `.claude/helpers/graft-hooks.cjs` and nothing else (`dist/upkeep.js:211`), so the
shims are named `repo-graft-*.cjs` and the refresh finds no hosts to rewrite. That is invisible
in a diff, easy to undo by a rename that looks like tidying, and undone for real by anyone who
runs `graft init`. So the invariants it protects are asserted here, each one a revert that has
already happened at least once:

- **Graft cannot see this repo as wired.** The one check that matters; everything below it is a
  consequence. A graft-named shim reappearing means the off switch is off.
- **`BAKED` is blank.** The refresh bakes in the absolute path of whichever install it ran from
  — an npx cache, one Node version's global lib — and that path exists on exactly one machine.
- **`.mcp.json` launches through `npx`.** The bare `graft` form the refresh writes is what
  produced `Executable not found in $PATH: graft` here; this repo carries no Node toolchain, so
  a global install is not a safe assumption to bury in a committed config.
- **The Bash allowlist is the two commands this repo runs.** The refresh also pre-approves
  `npx graft:*` — an unrelated npm package, not this one — and two aliases used for developing
  graft itself. Copilot's finding on #12.

What is deliberately not asserted is the *content* of the shims or of the skill file. They are
graft 0.18.0's, ours to port forward now (docs/graft.md); pinning their bytes would fail on
every deliberate upgrade, which is the one case that should be easy.
"""

import json
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

HELPERS = REPO / ".claude" / "helpers"
SETTINGS = REPO / ".claude" / "settings.json"
MCP = REPO / ".mcp.json"

GRAFT_OWNED = ("graft-hooks.cjs", "graft-statusline.cjs")
"""The two names `graft init` writes. The first is the one `wiredHostIds` tests for; the second
is here because the pair is renamed together and a half-restore is the confusing failure."""

OURS = ("repo-graft-hooks.cjs", "repo-graft-statusline.cjs")
"""Ours. `graft-hooks.cjs` survives as a substring on purpose: `dist/claude/hooks.js:95` reads
the timeout this repo declares by matching the command string against it."""

ALLOWED = {"Bash(graft:*)", "Bash(npx -y @nanonets/graft:*)"}
"""A set, not a list: Claude Code reads membership, and pinning the order would make a sorted
allowlist a test failure rather than a diff."""


def settings() -> dict[str, Any]:
    return json.loads(SETTINGS.read_text())


# --------------------------------------------------------------------------- #
# The off switch
# --------------------------------------------------------------------------- #


def test_graft_cannot_recognise_this_repo_as_wired() -> None:
    """No graft-named shim, so `wiredHostIds` finds no hosts and the refresh writes nothing.

    A failure here is not cosmetic: it means the next `graft` upgrade rewrites `settings.json`
    and `.mcp.json` too, and the three edits below go with them.
    """
    found = [name for name in GRAFT_OWNED if (HELPERS / name).exists()]

    assert not found, (
        f"{found} is back in .claude/helpers/ — graft will treat this repo as wired again and "
        f"rewrite the whole block on its next version change. Rename it to repo-{found[0]}."
    )


def test_both_shims_are_present_and_runnable() -> None:
    """Renaming is only safe if the pair moved together and Claude Code can still run them."""
    for name in OURS:
        shim = HELPERS / name
        assert shim.exists(), f"{name} is missing — settings.json points at it"
        assert shim.stat().st_mode & 0o111, f"{name} is not executable"


# --------------------------------------------------------------------------- #
# The three edits the refresh keeps undoing
# --------------------------------------------------------------------------- #


def test_no_shim_bakes_in_a_path_from_one_machine() -> None:
    """`BAKED` blank, so resolution finds an installed graft wherever this checkout is."""
    for name in OURS:
        assert 'const BAKED = "";' in (HELPERS / name).read_text(), (
            f"{name} has a baked absolute path again — it resolves for whoever wrote it and "
            f"nobody else. Blank it; the shim's own resolution covers every layout."
        )


def test_the_mcp_server_is_launched_through_npx() -> None:
    """The form that works without a Node toolchain, which is what this repo has."""
    graft = json.loads(MCP.read_text())["mcpServers"]["graft"]

    assert graft == {"command": "npx", "args": ["-y", "@nanonets/graft", "mcp"]}


def test_the_bash_allowlist_is_only_what_this_repo_runs() -> None:
    """Two commands. The extras graft adds pre-approve a package this repo never uses."""
    assert set(settings()["permissions"]["allow"]) == ALLOWED


# --------------------------------------------------------------------------- #
# The rename, held whole
# --------------------------------------------------------------------------- #


def test_every_helper_the_settings_name_exists() -> None:
    """A rename that missed a reference leaves a hook Claude Code runs against nothing.

    Cheap to make — there are eight references — and silent when made: a hook whose command is a
    missing file fails per turn, not at startup.
    """
    named = set(re.findall(r"\.claude/helpers/([\w.-]+)", SETTINGS.read_text()))

    assert named, "settings.json names no helpers at all — the hooks block is gone"
    for name in sorted(named):
        assert (HELPERS / name).exists(), f"settings.json runs {name}, which does not exist"
