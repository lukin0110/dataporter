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
| `.claude/settings.json` | yes | The `statusLine`, `hooks` and `permissions` blocks `graft init` merged in. |
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

## Two local edits to the generated wiring

`graft init --agents claude --no-global` generated all of the above. Two things were changed
by hand afterwards, and both will be reverted by a plain re-run of `init` — reapply them, or
keep the re-run out of the commit:

- **`const BAKED` in both `.claude/helpers/*.cjs` is blanked.** `init` bakes in the absolute
  path of the npx cache it happened to run from, which exists on exactly one machine. The
  shims already resolve a project-local, node-local or globally installed Graft on their own;
  the baked path only ever misses for everyone else.
- **`.mcp.json` invokes `npx -y @nanonets/graft mcp`, not a bare `graft`.** This repo has no
  Node toolchain of its own, so a global install is not a safe assumption to bury in a
  committed config. `npx` uses the global install when there is one and fetches the package
  when there is not. It is the form Graft's own README gives for registering by hand.
