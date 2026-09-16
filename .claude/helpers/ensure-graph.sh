#!/usr/bin/env bash
# Build Graft's graph when this checkout hasn't got one.
#
# `graft/` is git-ignored — it is derived from the source and regenerable, like
# `.venv/` (docs/graft.md). That is the right call for a clone you make once and
# the wrong shape for a worktree you make every day: every Orca workspace is a
# fresh checkout, so every Orca workspace starts with no graph at all. Graft's own
# session-start hook does not fill the gap — with no `graft/INDEX.md` to read it
# skips the orientation block and says nothing — so the first session would open
# blind and the first `graft_*` call would query a graph nobody built.
#
# Two callers, one behaviour. `orca.yaml` runs this at worktree creation, before
# the first agent terminal exists; the `SessionStart` hook in
# `.claude/settings.json` runs it for a checkout Orca never made. The existence
# check below is what makes the second call free: it builds once per checkout and
# is a no-op every time after.
#
# It never exits non-zero. Graft is development tooling only, and not having it
# installed costs you nothing but the graph — while a failure here would fail Orca's
# whole worktree setup in one caller, and print an error over the user's first
# prompt in the other. Anything that goes wrong is one line on stderr.
set -u

# `CLAUDE_PROJECT_DIR` when Claude Code runs us, `ORCA_WORKTREE_PATH` when Orca's
# setup runner does (its cwd is not contractual, that variable is), and the script's
# own location for a hand-run from anywhere else. A root that does not exist is the
# one failure worth naming: it means a caller passed a path, not that Graft is absent.
root="${CLAUDE_PROJECT_DIR:-${ORCA_WORKTREE_PATH:-$(dirname "$0")/../..}}"
cd "$root" || {
  echo "ensure-graph: cannot enter \`$root\` — nothing built. Check CLAUDE_PROJECT_DIR / ORCA_WORKTREE_PATH." >&2
  exit 0
}

# INDEX.md and not the directory: graft's hooks create `graft/.cache/` on their own,
# so the directory exists long before a graph does.
[ -f graft/INDEX.md ] && exit 0

# The same two invocation forms `.mcp.json` settles on, for the same reason: this
# repo has no Node toolchain of its own, so a global install is not a safe
# assumption — but it is the fast path when it is there.
#
# `>&2` on both. Graft already prints its per-file progress to stderr but its
# four-line summary to stdout, and a `SessionStart` hook's stdout is not noise —
# Claude Code injects it into the session as context, so a build would open every
# fresh clone with a node count and an absolute path nobody asked for. A terminal
# shows stderr just the same, so Orca's Setup tab keeps the whole build log and the
# hook contributes nothing but the graph.
if command -v graft >/dev/null 2>&1; then
  graft build . >&2 || echo "ensure-graph: \`graft build\` failed; the graph is missing, run it yourself" >&2
elif command -v npx >/dev/null 2>&1; then
  npx -y @nanonets/graft build . >&2 || echo "ensure-graph: \`npx -y @nanonets/graft build\` failed; the graph is missing" >&2
else
  echo "ensure-graph: no graft and no npx on PATH — working without the code graph. See docs/graft.md." >&2
fi

exit 0
