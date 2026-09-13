# 41 — The README's walk

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 05](../05-chatgpt-mock.md) §56 (the walk), §54 (*Two mocks at
once*), §53 (the project's README), and §52 as the goal
**Depends on:** [39](39-chatgpt-mock-site.md), [40](40-chatgpt-export-and-archive.md)
**Enables:** the tool's ChatGPT half (§58), which is written against a mock a person
has walked
**Status:** Built

## Goal

The paperwork that makes the mock chatgpt.com usable before anything drives it: the
project's README rewritten for a project of mocks — how to run each, how to merge the
two reachability blocks into one Chrome, what each does and why, and the walk a person
with a Chrome takes through the mock chatgpt.com — and the specs index updated so that
brief `05`'s sections are claimed. No code.

## In scope

- **`mock/README.md`**, rewritten for the project: what the project is (two sites, one
  core, ADR 0003 and 0007); *Run it* for each command with its block; *Two mocks at
  once* — the operator merges the two blocks into one `--host-resolver-rules` value with
  every `MAP` in it, comma-separated, and one `--ignore-certificate-errors-spki-list`
  value with both pins, comma-separated, because Chrome keeps one value per argument;
  *Ask it for an export* for each site — the mock claude.ai's link fetched by the tool
  with `SSL_CERT_FILE`, the mock chatgpt.com's opened in the signed-in browser and
  refused everywhere else; *Ask it what it did*, two ledgers; *Reading a trace*, `37`'s
  section, unchanged; *What it does, and why*, both sites' behaviours and `rows`; **the
  walk** (§56): point Chrome at it, sign in and be refused with a wrong password, create
  a chat and watch the reply grow, paste past the threshold and put the text back,
  rename, upload, ask for the export, fetch the link signed in and be refused signed
  out, read the ledger — one numbered list, each step naming what to look for; *What
  it cannot do yet*, both sites' lists; *Tests*; the project's layout.
- **`specs/README.md`**: M10's four slices in the sequence, its dependency chain, four
  rows in the status table, the fifth-brief paragraph rewritten to say what claims what,
  and the shared decision on the mocks saying `mocks` since `38`.
- **The tool's `README.md`**: one sentence under *Backing an account up* and two under
  *Rehearsing it*, and `--package mocks` in the command.
- **`Makefile`**, `pyproject.toml`'s workspace comment, ADR 0007's consequence: the
  rename named.

## Out of scope

- A printed merged block for every running mock at once (§58): the README says how to
  merge by hand, and the day a rehearsal needs both is the day a later brief runs one.
- A rehearsal against the mock chatgpt.com, and its record (§58): nothing drives it.
- Turning any row of `docs/chatgpt-ui-map.md` *observed*: a walk of the mock is not
  evidence about chatgpt.com, and the README says so where the walk begins.

## Design notes

- **The walk is written as steps with a signal each,** in the map's words — "the one
  control now reads **Stop streaming**", "a chip reading **Pasted text** with a **Show in
  text field** button" — so that a person walking it is checking the mock against the
  map, not admiring it. The same list is what a later tool-driven run has to reproduce.
- **The merge is prose, not a command.** §54 leaves the printed merged block to a later
  slice, and two lines of prose ("join the `MAP`s with commas; join the pins with
  commas") are what an operator needs today. Rejected: a `mocks` command that prints both
  blocks (it would have to know both sites, which the core does not, or start both mocks,
  which it must not).
- **The README is one file for two sites** because the project is one and the mocks
  leave together (ADR 0007); each site's section is headed by its command so a reader
  looking for one can skip the other.

## Acceptance criteria

- `mock/README.md` names both commands, both blocks, the merge, the walk with every step
  §56 lists, and both lists of what is not built; every `uv run` line in it uses
  `--package mocks`.
- `specs/README.md`'s status table has rows `38`–`41` and its sequence has M10's four
  slices; every section §52–§58 is named as claimed or as the list of what is left.
- A person with a Chrome, following the walk, sees every signal it names. *(Done on
  2026-09-13 by a headless Chromium driven through the same steps; a person's own walk
  is what a reader of the README does next.)*
- *(Live, the later brief's.)* The tool's first run against the mock reproduces the walk;
  that turns this slice `Done` (§56).

## Risks

- **A README that drifts from the pages.** The walk names labels and selectors that
  `pages.py` serves; a correction to a row changes both, and nothing but a reader
  compares them. `chatgpt-mock rows` is the machine-readable half, and the README says
  to read it beside the map.
