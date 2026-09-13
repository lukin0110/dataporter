# Specs

Two kinds of document live here, and they are not interchangeable.

| | Briefs: [`01`](01-initial-brief.md) §1–§19, [`02`](02-claude-mock.md) §20–§28, [`03`](03-extraction-and-backup.md) §29–§40 | [`impl/*.md`](impl/) |
| --- | --- | --- |
| **Role** | Briefing | Implementation specs |
| **Answers** | What are we building, and why | How it gets built, in what order |
| **Audience** | Anyone deciding whether this is the right experiment | Whoever is building the next slice |
| **Voice** | Requirements and outcomes | Commands, flags, files, types, schemas, golden outputs |
| **Lifecycle** | Stable — changes only when intent changes | Living — updated as reality lands; `Built` when its tests pass, `Done` when its live criteria are met |
| **Numbering** | Section numbers are permanent identifiers, cited as §N, continuing across briefs | Slice numbers, cited as `NN` |
| **Written by** | The person who wants the thing | The person building it |
| **Examples** | Illustrative, but the output blocks in §9, §10 and §16 are golden strings; the blocks in brief `02` (§21, §23, §25) are illustrative | Normative |

There are three briefs: [`01-initial-brief.md`](01-initial-brief.md) (§1–§19),
[`02-claude-mock.md`](02-claude-mock.md) (§20–§28) and
[`03-extraction-and-backup.md`](03-extraction-and-backup.md) (§29–§40). Section numbers
continue across them,
so `§N` names one section anywhere in the repository (a working rule, below). The words
the briefs use are defined in [`CONTEXT.md`](../CONTEXT.md).

The rule that keeps them apart: **if it could change without changing what we are trying to
achieve, it belongs in `impl/`.** A retry budget, a JSON field, a package name, a CSS
selector and a Hermes config key are all implementation. "Hermes must verify important
actions instead of assuming that clicks succeeded" is intent.

The brief is cited, never edited in passing. Implementation specs quote it by section
(`§11`) so any slice can be traced to the requirement it exists to satisfy, and so a
requirement with no slice pointing at it is visibly unbuilt.

## Layout

```text
specs/
├── 01-initial-brief.md   the briefing — intent, stable
├── 02-claude-mock.md     the rehearsal brief — intent, stable
├── 03-extraction-and-backup.md   the extraction brief — intent, stable
├── README.md             this file — index, sequence, shared decisions
└── impl/
    ├── _template.md      the shape every implementation spec follows
    ├── 01-foundation.md
    └── …
```

Two directories outside `src/` belong to the second brief and to no release:
`mock/` is `26`'s stand-in for claude.ai, a workspace member with its own project
file and README, and `rehearsal/` is `28`'s export and `29`'s protocol. Neither is
in the wheel or the sdist, and `dataporter` imports neither.

## Sequence

Every slice is sized to be built, tested and reviewed in one sitting. Milestones are gates:
nothing in a later milestone starts before the earlier one is `Done`.

```text
M1 — Offline (no browser, no account, no Hermes)
  01  Foundation: package, CLI skeleton, config, logging, errors, exit codes
  02  Export model: conversations.json → pydantic
  03  Classification: migratable / unsupported, attachment classes
  04  Seed generation: chunked migration seeds with acknowledgement tokens
  05  Dry run and inspect: the §9 block, byte-exact
  06  Migration state: the §7 file, atomic, locked, resumable

M2 — Browser and Hermes proven (gate for every slice that writes to an account)
  07  Browser session and `login`: dedicated Chrome profile, CDP, no password
  08  Browser helpers: deterministic CDP primitives Hermes calls (probe, paste, attach, await)
  09  Hermes profile and runner: `setup`, `doctor`, one-shot subprocess, result contract
  10  Attach spike and Claude UI map: prove 07–09 together on one hand-driven chat

M3 — First real migration
  11  Skill: the `claude-migrate` SKILL.md and per-step verification protocol
  12  Import loop: one conversation end to end, state recorded, `--limit`, `--only`
  13  Recovery: every §11 failure mapped to detection, in-run recovery, and retry policy
  14  Human intervention: pause, `resume`, never restart
  15  Pacing and limits: the §13 parameters, rate-limit waits, circuit breaker

M4 — Fidelity and operability
  16  Attachments: uploads through the UI, unsupported recorded
  17  Verification and title: chat exists, parts acknowledged, title renamed
  18  Progress output: the §10 block, byte-exact, TTY and non-TTY
  19  Report: the §16 block, `report.json`, per-failure records, counters

M5 — Experiment
  20  Pilot: 5–10 conversations, the six §18 questions answered with numbers
  21  Scale-up and sign-off: full export, §19 metrics, LIMITATIONS, README, runbook

Tooling — no milestone, may land at any time
  22  Test performance: the fast/slow split, and the cost underneath it (both landed)
  23  Library operations: every command's body in the module that owns it, the CLI an interface
  25  Distribution: metadata, `py.typed`, a licence, and a wheel proven outside the checkout

M6 — Operability
  24  Non-interactive mode: credentials, an agentic sign-in, headless Chrome, never a keypress

M7 — Rehearsal (brief 02, §20–§28) — outside the gates: it needs no account, and §27
     makes a passed rehearsal the precondition for slice 10's live run, not its successor
  26  The mock claude.ai: a served, stateful stand-in, governed by the UI map
  27  The scripted agent as a `hermes`: the model-free procedure, on the path
  28  The rehearsal export: the five kinds and the selection categories
  29  The rehearsal: the protocol, the pass criteria and the record

M8 — Extraction and backup (brief 03, §29–§40)
  30  The store and the snapshot: filing, fetching, listing, import from a snapshot
  31  The source session and the ask: a second profile, the extraction surface, one click
```

## Dependencies

```text
01 ─┬─> 02 ─> 03 ─> 04 ─> 05
    ├─> 06
    ├─> 07 ─> 08 ─┐
    └─> 09 ───────┴─> 10 ─> 11 ─> 12 ─┬─> 13 ─┐
                                      ├─> 14 ─┘
                                      ├─> 15
                                      ├─> 16
                                      ├─> 17
                                      └─> 18 ─> 19 ─> 20 ─> 21
      (12 also needs 04, 06, 08, 09;  19 needs 13, 14, 16, 17)
```

Parallelisable once `01` lands: `02→05`, `06`, `07→08` and `09` share nothing.

M7 is a chain of three and a join: `26` is the site, `27` is what stands where
Hermes stands, `28` is what gets migrated, and `29` is the protocol that runs the
three of them against the shipped tool. `26` depends on the UI map rather than on
any slice's code — it imports nothing from the tool and the tool imports nothing
from it — and `27` depends on `09`, `11` and `24`, whose procedures it packages.

```text
10 (the UI map) ─> 26 ─┐
09, 11, 24 ─────> 27 ──┼─> 29
                  28 ──┘
```

M8 is a chain of two: `30` is everything of brief 03 that needs no browser — the store,
the snapshot, the fetch, `snapshots`, and `import` reading a snapshot — and depends on
`02`'s export source and `23`'s operation shape; `31` is the source session and the ask,
which need `07`'s browser session and `24`'s unattended sign-in as well as `30`'s store to
write the ask into. The split falls on the repository's own gate: nothing that touches an
account is built before the browser half is proven.

```text
02, 23 ─> 30 ─┐
07, 24 ───────┴─> 31
```

`13` and `14` were drawn in series and are not: `13` is what the tool retries on its
own, `14` is what it asks a person to clear, and `13`'s own table hands `needs_human`
straight to `14`. Both need `12` and nothing else, and both were built against it
independently. What they do share is one function — the loop in `Importer._migrate` —
so whoever lands second merges into it rather than beside it, and `14`'s design notes
hold the table of how the two divide. The join is drawn above because `19` reports
both.

`15` is the third of them and shares the same function: a rate limit is waited out and
the conversation attempted again, which is `13`'s shape without `13`'s budget, and a
wait too long to make becomes `14`'s ask. It is drawn parallel to both because it
needs neither, but it landed last and merged into the loop rather than beside it.

`23` depends on everything that is `Done` and changes none of it: it moves each command's
body out of `cli` into the module that owns the domain, and the golden CLI tests are what
prove nothing moved but the code. `24` depends on `23`, because an unattended run is the
same operations called with a different sink and a different intervention, and on `07`,
`09`, `11`, `12` and `14`, each of which it amends.

`10` is deliberately a spike. The brief names the mechanism (Hermes driving the Claude web
UI) but leaves open everything that only observation can settle: whether Hermes attaches to
our Chrome in one-shot mode, how large a seed the composer accepts, how generation
completion looks in the DOM. `10` answers those and updates `11`–`17` before they are built.

## Status

| Spec | Title | Implements | Status |
| ---- | ----- | ---------- | ------ |
| [01](impl/01-foundation.md) | Foundation | §8, §9, §10, §17 | Done |
| [02](impl/02-export-model.md) | Export model | §2, §6 | In progress |
| [03](impl/03-classification.md) | Classification | §6, §14 | Done |
| [04](impl/04-seed-generation.md) | Seed generation | §3, §6, §15 | Done |
| [05](impl/05-dry-run.md) | Dry run and inspect | §9 | Done |
| [06](impl/06-migration-state.md) | Migration state | §6, §7 | Done |
| [07](impl/07-browser-session.md) | Browser session and login | §8 | Built |
| [08](impl/08-browser-helpers.md) | Browser helpers | §4, §5, §17 | Done |
| [09](impl/09-hermes-runner.md) | Hermes profile and runner | §2, §4, §17 | Built |
| [10](impl/10-attach-spike.md) | Attach spike and Claude UI map | §4, §5, §11 | In progress |
| [11](impl/11-skill.md) | Skill and step protocol | §4, §5, §11, §17 | Built |
| [12](impl/12-import-loop.md) | Import loop | §6, §10 | Built |
| [13](impl/13-recovery.md) | Recovery | §11 | Built |
| [14](impl/14-human-intervention.md) | Human intervention | §12 | Done |
| [15](impl/15-pacing.md) | Pacing and limits | §13 | Done |
| [16](impl/16-attachments.md) | Attachments | §14 | Built |
| [17](impl/17-verification-and-title.md) | Verification and title | §2, §11, §15 | Built |
| [18](impl/18-progress-output.md) | Progress output | §10 | Done |
| [19](impl/19-report.md) | Report | §16 | Done |
| [20](impl/20-pilot.md) | Pilot experiment | §18 | In progress |
| [21](impl/21-scale-up.md) | Scale-up and sign-off | §19 | In progress |
| [22](impl/22-test-performance.md) | Test performance | — tooling | Done |
| [23](impl/23-library-operations.md) | Library operations | — tooling | Done |
| [24](impl/24-non-interactive.md) | Non-interactive mode | §8 (amended), §12 | Done |
| [25](impl/25-distribution.md) | Distribution | — tooling | Done |
| [26](impl/26-mock-claude.md) | The mock claude.ai | §21 | Done |
| [27](impl/27-scripted-hermes.md) | The scripted agent as a `hermes` | §23 | Done |
| [28](impl/28-rehearsal-export.md) | The rehearsal export | §24 | Done |
| [29](impl/29-rehearsal.md) | The rehearsal | §22, §23, §25, §26, §27 | Done |
| [30](impl/30-store-and-snapshot.md) | The store and the snapshot | §30, §31, §32, §33, §37, §38 | Built |
| [31](impl/31-source-session-and-ask.md) | The source session and the ask | §31, §35, §36, §38, §39 | Built |

`Built` is the value between `In progress` and `Done`: the slice's code is in and its
tests pass, and the acceptance criteria that need a real Hermes, a real Chrome or a real
account are still marked *unverified* in the slice itself. `10` is `In progress` and its
own text gates `11` onward on its answers; the slices after it were built against the
fakes rather than waiting, which is what this value records. `20` is where those criteria
are met, and it is what turns `Built` into `Done`.

`30` carries the same value for a different half of the world: it needs no Hermes, no
Chrome and no account, and every acceptance criterion it states passes — but no *real*
vendor link has been fetched, and §39's questions about one cannot be answered until an
ask has produced a link. The slice says so in its own first design note.

`31` is `Built` for the reason the browser slices are: its code is in and its tests pass
against a fake export page and, in the live tier, against a checked-in fixture in a real
Chrome — but the page it was written for has never been looked at. Its path and its three
selectors are placeholders, the four export rows of `docs/claude-ui-map.md` are
`*unknown*`, and `docs/extraction-01.md` carries `*not yet run*` against §39's questions
1, 2 and 5. One trip to a throwaway source account — `docs/spike/README.md` has the steps
— is what turns both it and `30` into `Done`.

`21`'s own last item is to sweep this column to `Done` at sign-off, which is why it is
still reporting what is true rather than what the plan hoped: `20` and `21` are built and
unrun, and a column that said otherwise would be the one claim the experiment exists to
make honestly. `docs/experiment-02.md` holds the section the sweep is recorded in.

Every section §2–§19 of the first brief is claimed by at least one slice. §1 is the goal
and is claimed by all of them. Of the second brief, §21–§27 are claimed by `26`–`29`;
§20 is that brief's goal and is claimed by all four, and §28 is its list of what is
deliberately left — a section no slice should claim until one of its items is built.
`22`, `23` and `25` claim none: they are the slices that exist because of how the repo is
worked on and how it is consumed rather than because of what the brief asks for, and they
are outside the milestone gates for the same reason.

Of the third brief, §30–§39 are claimed by `30` and `31`: `30` takes the store, the
snapshot, the fetch and import from a snapshot, `31` takes the ask, the source session
and the safety boundaries, and §31 and §38 are split between them along the same line.
§29 is that brief's goal and is claimed by both; §40 is its list of what is deliberately
left, which no slice claims until one of its items is built. `30` is built; `31` is not
started.

## Working rules

- **New work starts as a slice, not as an edit to the brief.** If the brief turns out to be
  wrong or incomplete, amend it explicitly and say which slices are affected.
- **A slice may resolve what the brief left open**, and must say so in its *Design notes*.
  It may not quietly contradict the brief; that requires an amendment.
- **Discoveries flow back.** `10` will produce facts that invalidate assumptions in `11`–`17`.
  Update those slices when it does — they are living documents.
- **Golden strings, not impressions.** Where the brief shows output, the slice pins a rule
  that reproduces it and a test compares bytes.
- **Copy the template.** `impl/_template.md` is the shape; keeping it uniform is what makes
  the set skimmable.
- **Words come from `CONTEXT.md`.** A term a document needs and the glossary lacks is
  added there first.
- **Section numbers continue across briefs.** `01` ends at §19 and `02` starts at §20, so
  `§N` stays one global identifier and every `Implements: §N` line keeps its meaning.
  `03` starts at §29 where `02` ends, and a fourth starts at §41. Cite `§N`, never `02§N`.

## Shared decisions

Assumptions, not brief requirements. Change them here and the slices follow.

- **Language / runtime:** Python ≥ 3.12, managed with `uv`. `pydantic` v2 for every model
  that crosses a boundary (export, plan, seeds, state, Hermes results, config).
  `pydantic-settings` for configuration. `typer` for the CLI with plain `print` output —
  no `rich`, no colour, because the output formats are golden strings. `tenacity` for
  `13`'s retry loop, and only its loop — the budget, the backoff and the deferral
  discount are the tool's own arithmetic.
- **`pydantic-ai`:** not a runtime dependency. Hermes is the agent; a second agent loop is
  not needed. It is used once, optionally, in `20` as a semantic-fidelity judge behind the
  `judge` extra. If that stays useful it gets its own slice; if not, it is removed. `20`
  imports it dynamically, inside the one function that needs it, so that a build without
  the extra — which is every build `make check` runs on — neither fails to import nor
  fails to type-check.
- **Hermes:** the external Hermes Agent (Nous Research), installed by the operator with the
  official installer, invoked as a subprocess in one-shot mode (`hermes -z`) inside a
  dedicated Hermes profile named `dataporter`. It is never imported as a library. Its
  built-in `browser_*` tools are used (Browser Use CLI mode is switched off) because they
  are ref-based, verifiable and support `browser_cdp`.
- **Browser:** a Google Chrome (or Chromium / Brave / Edge) instance launched by *our* tool
  with a dedicated `--user-data-dir` inside the workspace and a remote-debugging port on
  `127.0.0.1`. Hermes attaches over CDP. The operator's everyday browser profile is never
  touched, so the source account's login can never leak into the destination session.
  Headed by default; headless under `--non-interactive` or `browser.headless` (`24`).
- **Division of labour:** Hermes makes the adaptive decisions (find the composer, decide
  the page is in the expected state, recover from surprises). Our helper commands make the
  deterministic moves whose exactness matters (insert a 40 kB seed byte-for-byte, upload a
  file, wait for generation to finish). A seed never passes through an LLM's output tokens.
- **Package and command:** package `dataporter`, CLI `dataporter`. The brief writes
  `hermes-claude-migrate` in §8–§10; ADR [0004](../docs/adr/0004-the-command-is-dataporter.md)
  renamed the command, the `DATAPORTER_` environment prefix and the tool's internal markers
  after the package, and left the brief as written.
- **Distribution (`25`):** an installable package, not only a checkout. A host project adds
  it from a git URL or a path — there is no PyPI release, because publishing is
  deliberately a later slice — and gets the command, `python -m dataporter`, and the `23`
  operations as a typed library (`py.typed` ships; the operations are reached where they
  live and are never re-exported). The version lives in `dataporter.__version__` and the
  wheel's metadata is derived from it. `typer` stays a required dependency so a bare
  install yields a working command. Hermes is neither imported by the package nor a
  dependency of it: a host project only has to have `hermes` on the `PATH` its process
  inherits.
- **Workspace:** `migration/` next to the export by default, `--workspace` to override.
  Holds `state.json` (§7 shape, nothing else in it), `run.json` (run-level counters and
  pause record), `plan.json`, `seeds/`, `attachments/`, `browser-profile/`, `hermes/`,
  `report.json`, `pilot/` (`20`'s question and probe replies) and `logs/`. Never inside
  the export.
- **Output discipline (§10):** no message content and no titles on stdout or in logs at any
  verbosity. Titles live in `state.json` because §7 puts them there, and in seed files
  because they are content. Hermes's own session transcripts contain page snapshots and
  therefore content; they live under the Hermes profile and `setup` documents how to purge
  them. `20` adds one more content-bearing workspace file, `pilot/probes.json`, which holds
  the probe replies a person grades; it is written, never printed and never logged, and it
  is the only place in the tool where a message Claude wrote is recorded.
- **Secrets:** interactively the tool never sees a Claude password (§8). Unattended (`24`)
  it holds the destination account's email and password in memory for one invocation,
  from the environment or a file and never from `config.toml`, types them into the form
  from its own process, and never writes, logs, prints or hands them to the agent — the
  Hermes environment is built without them. It also never reads or stores the API key
  Hermes uses; that is Hermes's `.env`.
- **Fast and slow tests:** the suite is split by a `slow` marker — anything that spawns a
  subprocess, binds a socket or launches a browser. `make check` runs lint, types and the
  fast half (~870 tests, about three seconds) and is what CI runs on a pull request;
  `make check-all` runs everything with coverage and is what CI runs on `main` after a
  merge, so the `fail_under` gate lives there. `tests/conftest.py` holds the two
  mechanisms that keep the marking honest. `22` removed the cost rather than containing
  it — the whole suite is ~20 seconds across four cores where it was five minutes — so the
  split is now a rail (a pull request is never gated on a browser) rather than the thing
  that makes the loop bearable.
- **The mock and the rehearsal:** the mock is a `uv` workspace member (`mock/`,
  package `claudemock`, command `claude-mock`) with one dependency of its own, and
  the rehearsal is a top-level `rehearsal/` package that is linted, type-checked and
  in neither the wheel nor the sdist. Neither is imported by `dataporter`; `26`'s
  mock imports nothing from it either, and `29`'s runner drives the installed
  command as a subprocess. The scripted agent's *procedures* stay in
  `tests/fake_agent.py`, which is where the tool's own suite drives them.
- **Repo tooling:** [Graft](https://github.com/trailhq/Graft) indexes the repo into a code
  graph that coding agents query instead of re-reading the source. Development tooling only —
  no slice depends on it, `make check` never runs it, and the graph itself is git-ignored.
  `docs/graft.md` says what is committed and how to build your own.

## Open questions

Owned by `10` unless stated. Their answers land in `docs/hermes-attach.md`,
`docs/claude-ui-map.md` and `docs/seed-limits.md`, one marked line each; until they do,
those files say so and `tests/test_spike_docs.py` keeps them saying it.

- Does `browser.cdp_url` in the Hermes profile config make one-shot (`-z`) runs attach to
  our Chrome, or is `/browser connect` (interactive only) required? Fallback ladder in `10`.
- What is the largest text `Input.insertText` can place in the claude.ai composer before the
  UI refuses, truncates or converts it into a "pasted text" attachment? Sets `seed.max_chars`.
- Does the real export archive contain attachment bytes, or only `extracted_content` and
  file names? Decides whether attachment class 2 exists without an operator-supplied
  directory (`02`, `16`).
- Can a chat be renamed through the UI reliably enough to be a verified step? (`17`)
  `17` shipped on the assumption that it can — `fidelity.rename_title` defaults to `true`
  — and made the step best effort so that being wrong costs a line of metadata rather than
  a conversation. `20` is what looks.
