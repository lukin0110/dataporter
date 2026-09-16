#!/usr/bin/env node
// Graft's Claude Code hooks shim — renamed out of graft's way on purpose.
//
// The name is the off switch. `reconcileWiring` (graft's `dist/upkeep.js:240`) rewrites every
// file graft believes it owns — both shims, `.claude/settings.json`, `.claude/skills/graft/`
// and `.mcp.json` — whenever the stamp under the git-ignored `graft/.cache/` disagrees with
// the running binary, which is every upgrade and every fresh clone. It is called from graft's
// own session-start hook and from MCP boot, so it runs at the start of every session; nobody
// has to run `graft init` for the rewrite to happen, and none of the reverts here involved it.
// `wiredHostIds` (`dist/upkeep.js:211`) decides this repo is Claude-wired by testing one exact
// path — `.claude/helpers/graft-hooks.cjs` — and `claude` is not in graft's host registry, so
// nothing else can vote it back in. Under this name the refresh finds no hosts and returns
// before writing a byte. docs/graft.md carries the whole story.
//
// `graft-hooks.cjs` survives as a *substring* of the filename, and that is load-bearing in the
// other direction: `hookTimeoutIn` (`dist/claude/hooks.js:95`) finds the budget this hook is
// running under by matching the command string in settings.json against it, and the comment
// there explains that guessing the timeout high gets the whole hook SIGKILLed.
//
// Below this header is graft 0.18.0's generated shim, unmodified but for `BAKED`. Ours now:
// a newer graft will not refresh it, so port improvements deliberately (docs/graft.md).
const path = require('path');
const fs = require('fs');
const { pathToFileURL } = require('url');
const { execFileSync } = require('child_process');
const dir = process.env.CLAUDE_PROJECT_DIR || process.cwd();
// Blanked deliberately: the wiring pass bakes in the absolute path of whichever install
// it ran from — an npx cache, or one Node version's global lib — and that path exists on
// exactly one machine. Resolution below finds a project-local, node-local or globally
// installed @nanonets/graft anywhere, so a baked path only ever misses for everybody else.
const BAKED = "";

// The dist/claude dir of @nanonets/graft resolved from a base whose node_modules is searched.
function fromPkg(base) {
  try {
    const pkg = require.resolve('@nanonets/graft/package.json', { paths: [base] });
    return path.join(path.dirname(pkg), 'dist', 'claude');
  } catch { return null; }
}

// The global node_modules dir per npm (handles Homebrew/Windows/volta). Queried on demand.
function globalRoot() {
  try {
    const root = execFileSync('npm', ['root', '-g'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], shell: process.platform === 'win32' }).trim();
    return root || null;
  } catch { return null; /* npm unavailable */ }
}

// The version of the package a dist/claude dir belongs to, or null if unreadable.
function versionOf(distClaude) {
  try {
    return JSON.parse(fs.readFileSync(path.join(distClaude, '..', '..', 'package.json'), 'utf8')).version || null;
  } catch { return null; }
}

// Numeric-dotted compare of the release part; an unreadable version loses to any known one.
function newer(a, b) {
  if (!a) return false;
  if (!b) return true;
  const p = (v) => String(v).split('-')[0].split('.').map((n) => Number(n) || 0);
  const pa = p(a), pb = p(b);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d !== 0) return d > 0;
  }
  return false;
}

// The highest-versioned dir in `dirs` that actually contains `name`, or null.
function best(dirs, name) {
  let bestDir = null, bestVer = null;
  for (const d of dirs) {
    if (!d || !fs.existsSync(path.join(d, name))) continue;
    const v = versionOf(d);
    if (bestDir === null || newer(v, bestVer)) { bestDir = d; bestVer = v; }
  }
  return bestDir;
}

function entry(name) {
  // Cheap candidates first, and only shell out to npm when every one of them misses.
  const cheap = [BAKED, fromPkg(dir), fromPkg(path.join(path.dirname(process.execPath), '..', 'lib'))];
  const hit = best(cheap, name);
  if (hit) return path.join(hit, name);
  const gr = globalRoot();
  const global = gr && path.join(gr, '@nanonets', 'graft', 'dist', 'claude');
  if (global && fs.existsSync(path.join(global, name))) return path.join(global, name);
  return path.join(dir, 'dist', 'claude', name); // last-ditch; import will no-op if absent
}

import(pathToFileURL(entry("hooks.js")).href).then((m) => m.main(process.argv[2])).catch(() => { /* graft unavailable — no-op */ });
