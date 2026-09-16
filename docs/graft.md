# Graft — the repo's code graph for coding agents

[Graft](https://github.com/trailhq/Graft) (`@nanonets/graft`, MIT) indexes this repo into a
graph an agent can query instead of re-grepping the source on every task: prose nodes that
explain a subsystem, plus a per-symbol wiring graph of who calls what, each hit carrying an
exact `file:line`.

It is **development tooling only**. It has no part in the migration itself: nothing under
`src/dataporter/` imports it, no CLI command shells out to it, `make check` does not run it
and CI never installs it. Not having it installed costs you nothing but the graph.

## What is committed, and what is not

| Path | Committed | What it is |
| --- | --- | --- |
| `.claude/skills/graft/SKILL.md` | yes | Tells the agent to query the graph before grepping. Owned by `graft init`. |
| `.claude/helpers/graft-*.cjs` | yes | Shims Claude Code runs for the statusline and hooks. Both no-op silently when Graft is not installed. |
| `.claude/helpers/ensure-graph.sh` | yes | Builds the graph when a checkout hasn't got one. Ours, not `graft init`'s. |
| `.claude/settings.json` | yes | The `statusLine`, `hooks` and `permissions` blocks `graft init` merged in, plus one `SessionStart` entry of our own. |
| `orca.yaml` | yes | Orca's worktree setup hook, which builds the graph before the first agent terminal opens. |
| `.mcp.json` | yes | Registers Graft's MCP server, exposing its six retrieval tools natively. |
| `.ignore` | yes | Keeps `graft/` greppable by ripgrep even though it is git-ignored. |
| `graft/` | **no** | The graph itself — a regenerable local cache, like `.venv/`. Git-ignored; build your own. |

The split is Graft's own: what you share is the wiring, and each person generates the graph
locally. That also keeps the graph out of review — it is derived from the source, so a stale
copy in a diff would only ever be noise.

## Using it

```bash
npm install -g @nanonets/graft   # once, or drop the -g and use npx
graft build                      # generate graft/ from the current tree
graft ask "where are seeds chunked?" --source
```

`graft build` is deterministic tree-sitter: no API key, no network, no model. Queries refresh
the graph against the working tree before answering, so an answer describes the code as it is
now, uncommitted edits included. `graft build --deep` adds LLM-written summaries and needs a
key for the provider you choose; nothing in this repo requires that pass.

## A fresh checkout has no graph

`graft/` is git-ignored, so a clone starts without it — and so does every Orca workspace,
each one a new git worktree. Graft's own session-start hook does not fill that gap: it reads
`graft/INDEX.md` to build the orientation block it injects, and with no file to read it emits
nothing. The first session would open blind, and the first `graft_*` call would query a graph
nobody built.

`.claude/helpers/ensure-graph.sh` closes it. It builds when `graft/INDEX.md` is missing and
returns instantly when it is there, so it is free to call on every session, and it never exits
non-zero — a missing Graft costs you the graph, not the run. Two things call it:

- **`orca.yaml`**, Orca's setup hook, run once when a workspace is created, beside
  `make install` for the same reason: `.venv/` is git-ignored too, and a fresh worktree has
  neither. `setupAgentStartupPolicy: wait-for-setup` makes the first agent terminal wait for
  it, which is the whole point — the session that opens has both the graph and the
  orientation.
- **A `SessionStart` hook in `.claude/settings.json`**, for a checkout Orca never made. It
  blocks the session start that builds, and only that one.

Neither is Graft's own wiring, and neither is at risk from it: `graft init` and the upkeep
pass replace only the hook entries naming `graft-hooks.cjs` and keep every other one.

## Three local edits to the generated wiring

`graft init --agents claude --no-global` generated all of the above. Three things were changed
by hand afterwards, and all three will be reverted by a plain re-run of `init` — reapply them,
or keep the re-run out of the commit:

- **`const BAKED` in both `.claude/helpers/*.cjs` is blanked.** `init` bakes in the absolute
  path of the npx cache it happened to run from, which exists on exactly one machine. The
  shims already resolve a project-local, node-local or globally installed Graft on their own;
  the baked path only ever misses for everyone else.
- **`.mcp.json` invokes `npx -y @nanonets/graft mcp`, not a bare `graft`.** This repo has no
  Node toolchain of its own, so a global install is not a safe assumption to bury in a
  committed config. `npx` uses the global install when there is one and fetches the package
  when there is not. It is the form Graft's own README gives for registering by hand.
- **The Bash allowlist is cut to the two commands this repo actually runs**, `graft:*` and
  `npx -y @nanonets/graft:*`. `init` also pre-approves `npx graft:*`, `graft-dev:*` and
  `node dist/cli.js:*`. The first is not this package at all — `graft` on npm is an unrelated
  *"Full-Stack JavaScript Through Microservices"* library, and `npx graft …` would fetch and
  run it. The other two are the aliases Graft uses when developing Graft itself (`dist/cli.js`
  is its own `bin` entry); there is no `dist/` here, so they only widen what runs unprompted.
  Raised by Copilot in review on #12.
