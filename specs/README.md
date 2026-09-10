# Specs

Two kinds of document live here, and they are not interchangeable.

| | [`01-initial-brief.md`](01-initial-brief.md) | [`impl/*.md`](impl/) |
| --- | --- | --- |
| **Role** | Briefing | Implementation specs |
| **Answers** | What are we building, and why | How it gets built, in what order |
| **Audience** | Anyone deciding whether this is the right experiment | Whoever is building the next slice |
| **Voice** | Requirements and outcomes | Commands, flags, files, types, schemas, golden outputs |
| **Lifecycle** | Stable — changes only when intent changes | Living — updated as reality lands, marked `Done` when shipped |
| **Numbering** | Section numbers are permanent identifiers, cited as §N | Slice numbers, cited as `NN` |
| **Written by** | The person who wants the thing | The person building it |
| **Examples** | Illustrative, but the output blocks in §9, §10 and §16 are treated as golden strings | Normative |

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
├── README.md             this file — index, sequence, shared decisions
└── impl/
    ├── _template.md      the shape every implementation spec follows
    ├── 01-foundation.md
    └── …
```

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
```

## Dependencies

```text
01 ─┬─> 02 ─> 03 ─> 04 ─> 05
    ├─> 06
    ├─> 07 ─> 08 ─┐
    └─> 09 ───────┴─> 10 ─> 11 ─> 12 ─┬─> 13 ─> 14
                                      ├─> 15
                                      ├─> 16
                                      ├─> 17
                                      └─> 18 ─> 19 ─> 20 ─> 21
      (12 also needs 04, 06, 08, 09;  19 needs 13, 14, 16, 17)
```

Parallelisable once `01` lands: `02→05`, `06`, `07→08` and `09` share nothing.

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
| [06](impl/06-migration-state.md) | Migration state | §6, §7 | Not started |
| [07](impl/07-browser-session.md) | Browser session and login | §8 | Not started |
| [08](impl/08-browser-helpers.md) | Browser helpers | §4, §5, §17 | Not started |
| [09](impl/09-hermes-runner.md) | Hermes profile and runner | §2, §4, §17 | Not started |
| [10](impl/10-attach-spike.md) | Attach spike and Claude UI map | §4, §5, §11 | Not started |
| [11](impl/11-skill.md) | Skill and step protocol | §4, §5, §11, §17 | Not started |
| [12](impl/12-import-loop.md) | Import loop | §6, §10 | Not started |
| [13](impl/13-recovery.md) | Recovery | §11 | Not started |
| [14](impl/14-human-intervention.md) | Human intervention | §12 | Not started |
| [15](impl/15-pacing.md) | Pacing and limits | §13 | Not started |
| [16](impl/16-attachments.md) | Attachments | §14 | Not started |
| [17](impl/17-verification-and-title.md) | Verification and title | §2, §11, §15 | Not started |
| [18](impl/18-progress-output.md) | Progress output | §10 | Not started |
| [19](impl/19-report.md) | Report | §16 | Not started |
| [20](impl/20-pilot.md) | Pilot experiment | §18 | Not started |
| [21](impl/21-scale-up.md) | Scale-up and sign-off | §19 | Not started |

Every brief section §2–§19 is claimed by at least one slice. §1 is the goal and is claimed
by all of them.

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

## Shared decisions

Assumptions, not brief requirements. Change them here and the slices follow.

- **Language / runtime:** Python ≥ 3.12, managed with `uv`. `pydantic` v2 for every model
  that crosses a boundary (export, plan, seeds, state, Hermes results, config).
  `pydantic-settings` for configuration. `typer` for the CLI with plain `print` output —
  no `rich`, no colour, because the output formats are golden strings.
- **`pydantic-ai`:** not a runtime dependency. Hermes is the agent; a second agent loop is
  not needed. It is used once, optionally, in `20` as a semantic-fidelity judge behind the
  `judge` extra. If that stays useful it gets its own slice; if not, it is removed.
- **Hermes:** the external Hermes Agent (Nous Research), installed by the operator with the
  official installer, invoked as a subprocess in one-shot mode (`hermes -z`) inside a
  dedicated Hermes profile named `dataporter`. It is never imported as a library. Its
  built-in `browser_*` tools are used (Browser Use CLI mode is switched off) because they
  are ref-based, verifiable and support `browser_cdp`.
- **Browser:** a Google Chrome (or Chromium / Brave / Edge) instance launched by *our* tool
  with a dedicated `--user-data-dir` inside the workspace and a remote-debugging port on
  `127.0.0.1`. Hermes attaches over CDP. The operator's everyday browser profile is never
  touched, so the source account's login can never leak into the destination session.
- **Division of labour:** Hermes makes the adaptive decisions (find the composer, decide
  the page is in the expected state, recover from surprises). Our helper commands make the
  deterministic moves whose exactness matters (insert a 40 kB seed byte-for-byte, upload a
  file, wait for generation to finish). A seed never passes through an LLM's output tokens.
- **Package and command:** package `dataporter`, CLI `hermes-claude-migrate` exactly as the
  brief writes it in §8–§10.
- **Workspace:** `migration/` next to the export by default, `--workspace` to override.
  Holds `state.json` (§7 shape, nothing else in it), `run.json` (run-level counters and
  pause record), `plan.json`, `seeds/`, `attachments/`, `browser-profile/`, `hermes/`,
  `report.json` and `logs/`. Never inside the export.
- **Output discipline (§10):** no message content and no titles on stdout or in logs at any
  verbosity. Titles live in `state.json` because §7 puts them there, and in seed files
  because they are content. Hermes's own session transcripts contain page snapshots and
  therefore content; they live under the Hermes profile and `setup` documents how to purge
  them.
- **Secrets:** the tool never sees a Claude password (§8). It also never reads or stores the
  API key Hermes uses; that is Hermes's `.env`.

## Open questions

Owned by `10` unless stated.

- Does `browser.cdp_url` in the Hermes profile config make one-shot (`-z`) runs attach to
  our Chrome, or is `/browser connect` (interactive only) required? Fallback ladder in `10`.
- What is the largest text `Input.insertText` can place in the claude.ai composer before the
  UI refuses, truncates or converts it into a "pasted text" attachment? Sets `seed.max_chars`.
- Does the real export archive contain attachment bytes, or only `extracted_content` and
  file names? Decides whether attachment class 2 exists without an operator-supplied
  directory (`02`, `16`).
- Can a chat be renamed through the UI reliably enough to be a verified step? (`17`)
