# 25 — Distribution: an installable package, not a checkout

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** nothing in the brief — tooling, like `22` and `23`. §8–§10 fix the command
surface and this slice leaves every command, flag, message and exit code where they were.
**Depends on:** [23](23-library-operations.md)
**Enables:** any host project that has `hermes` on its `PATH`
**Status:** Done

## Goal

Make `dataporter` something another Python project can depend on: `uv add` it from a git
URL or a path, import it, and call the operations `23` built. The package was already
shaped like one — `src/` layout, hatchling, a console script — and was distributable in
name only: no licence, five fields of metadata, no `py.typed`, a version written twice,
and nothing anywhere that had ever built the wheel and looked inside it.

**Publishing is deliberately not in this slice.** No PyPI workflow, no trusted publishing,
no release automation, no version-bump tool. What lands is a package that could be
published later with no further shaping, installed today from a git URL, and proven to
work from outside this checkout.

## In scope

- **`pyproject.toml`** — the metadata a dependency needs:

  | Field | Value | Why it is here |
  | --- | --- | --- |
  | `dynamic = ["version"]` + `[tool.hatch.version]` | reads `src/dataporter/__init__.py` | One version. `--version`, a caller reading `__version__`, and the wheel's `Version` are now the same line. |
  | `license` / `license-files` | `MIT`, `LICENSE` | PEP 639's SPDX expression. No `License ::` classifier beside it — the classifiers were deprecated by that PEP, and a modern backend rejects both together. |
  | `authors` | `[{ name = "lukin0110" }]` | No email: this repository's git history carries no author identity, and an address is the owner's to add. |
  | `keywords`, `classifiers` | seven classifiers | `Development Status :: 3 - Alpha` because `21`'s run has not happened; `Typing :: Typed` because `py.typed` ships. |
  | `[project.urls]` | homepage, repository, issues | Where an installed package points back to. |
  | `requires = ["hatchling>=1.27"]` | the build backend's floor | 1.27 is where PEP 639's two fields are read. The backend is not a locked dependency, so this line is the only thing that says it; `uv.lock` will not notice a stale hatchling. |

  The sdist `exclude` list gains `.claude`, `.agents`, `.mcp.json`, `skills-lock.json` and
  `graft` beside `spikes`, `specs` and `docs` — the coding agents' scaffolding, which is
  development tooling no consumer of the source needs. `tests` stays in: an sdist somebody
  can run `make check` against is worth more than a smaller one.

- **`src/dataporter/py.typed`** — empty, and the most load-bearing file in the slice.
  Without it PEP 561 tells a consumer's `ty` or `mypy` to treat every
  `from dataporter import …` as `Any`, which would quietly undo what `23` was for.

- **`src/dataporter/__main__.py`** — `python -m dataporter`, the same `cli:app` the console
  script names, called the same way. One command surface, two spellings of how to reach
  it; the easier one from inside another project's environment, where a script may not be
  on `PATH`.

- **`LICENSE`** — MIT, `Copyright (c) 2026 lukin0110`.

- **`tests/test_packaging.py`** — every test `slow`, `uv build` once per session into a
  temporary directory, then `zipfile` and `tarfile` (no new dependency, nothing installed).
  It asserts the wheel carries `dataporter/py.typed` and
  `dataporter/skills/claude-migrate/SKILL.md`, that its metadata `Version` equals
  `dataporter.__version__`, the console-script entry point verbatim, the MIT expression and
  the licence file, `Requires-Python: >=3.12` with the five runtime requirements and
  `pydantic-ai` still behind the `judge` extra, and that nothing outside `dataporter/` and
  the `dist-info` is in the wheel at all. For the sdist: the project, the code, `py.typed`
  and the suite present, the prose and the scaffolding absent. One test is not about the
  build — `python -m dataporter --version` in a subprocess, which is the whole of
  `__main__.py`.

- **A second CI job, `install`** — build, `uv venv --python 3.12 /tmp/consumer`,
  `uv pip install dist/*.whl`, then from `/tmp` run `dataporter --version`,
  `python -m dataporter --version`, and a `python -c` that imports the package, builds an
  `ImportRequest`, a `Collected` sink, and calls `hermes.skill.packaged_dir()`.

- **`README.md`** — *Requirements* separates what a host project needs (Python ≥ 3.12,
  `hermes` on the inherited `PATH`) from what developing on this repository needs (`uv`);
  *Install* leads with `uv add git+…` and keeps clone-and-`make install` as the third
  option; and a new **From another project** section, promoted out of *Developing*, holds
  the `console.Collected` example, points at `23`'s operations table as the API, and states
  the four things a library caller needs that a CLI user does not.

- **`src/dataporter/__init__.py`** — the module docstring says where the API is and what
  `py.typed` promises. No code change.

## Out of scope

- **Publishing.** A release workflow, trusted publishing to PyPI, tags, changelogs and a
  version-bump tool are all a later slice. This one is why that slice would be small.
- **A `cli` extra for `typer`.** `typer` stays a required dependency, so a library-only
  consumer inherits it and the three wheels behind it (`click`, `rich`, `shellingham`).
  The trade-off is recorded in *Design notes* rather than left for the next person to
  re-derive.
- **Re-exports.** `23` fixed where the operations live and this slice does not add a second
  spelling. The import surface is documented, not widened.
- **Any behaviour.** No command, flag, message, exit code or golden string moves. The
  eighty-odd `CliRunner` tests are the proof, unchanged.

## Design notes

- **The version is `__version__` and the metadata is derived from it**, rather than the two
  being kept equal by whoever remembers. Hatchling reads the line by regex, so the module
  stays the obvious place to look, and the packaging test asserts the artefact agrees —
  which is what makes it a mechanism.
- **`py.typed` is the slice.** Everything else here is metadata and prose; that file is the
  one whose absence would be invisible in this repository and visible in every consumer.
  `Typing :: Typed` in the classifiers is the same claim made where an installer can read
  it, and the two ship together or not at all.
- **`typer` stays required.** `[project.scripts]` points at `dataporter.cli:app`, so a
  bare `pip install dataporter` has to yield a working command; an optional extra buys a
  library consumer three fewer wheels and costs a console script that fails on import for
  anyone who did not read the README, plus a second install shape for `make check` to
  keep testing. The CLI is the product's documented surface in brief §8–§10, not an
  add-on. Rejected for now, cheap to revisit: it is one line moved.
- **The proof is split, because the two halves prove different things.** A test inside the
  suite can read a built artefact but cannot leave the repository: an import works in the
  checkout whether or not the file is in the wheel. CI's `install` job is the other half —
  a fresh interpreter, in `/tmp`, with nothing of ours on `sys.path`. Its last line is
  `skill.packaged_dir()`, which resolves the shipped `SKILL.md` through
  `importlib.resources` out of site-packages: exactly what `setup` does on a host machine,
  and the branch `hermes/skill.py` marks `# pragma: no cover - packaging` because it can
  only fail there. Nothing had ever run it.
- **A separate job, not a step in `check`.** `check` runs on every pull request and is the
  one name branch protection requires; a build-and-install cycle belongs beside it.
- **`__main__.py`'s guard is excluded from coverage, not counted.** It runs in a
  subprocess, where coverage does not follow, and `exclude_also` says so in one line.
  Lowering `fail_under` for one uncoverable statement would have been the dishonest fix.
- **The licence was the one decision not taken silently.** The repository carried none,
  which legally means all rights reserved, and MIT is a decision about the owner's work
  rather than a packaging detail. It is recorded here as a decision to reverse by replacing
  one file and one line — and the fallback, if the answer is "not yet", is
  `classifiers = ["Private :: Do Not Upload"]` with no `LICENSE`, which still installs from
  a git URL and refuses to publish.
- **Nothing in `src/` reads a repository file at runtime**, which is what made this slice
  metadata rather than a refactor. Every `docs/…` and `specs/…` mention under `src/` is
  prose inside a docstring; the only shipped non-code file is the skill, and `09` had
  already put it inside the package and reached it through `importlib.resources` for
  exactly this reason.

## Acceptance criteria

- `uv build` produces a wheel containing `dataporter/py.typed`,
  `dataporter/skills/claude-migrate/SKILL.md`, the `dataporter` entry point and
  nothing outside `dataporter/` and its `dist-info`; `tests/test_packaging.py` asserts each.
- The wheel's metadata `Version` equals `dataporter.__version__`, and `pyproject.toml`
  contains no version literal.
- `uv pip install` of that wheel into a venv elsewhere, run from `/tmp`:
  `dataporter --version` and `python -m dataporter --version` both print
  `dataporter <version>`, and `hermes.skill.packaged_dir()` returns a path under
  that venv's `site-packages`. CI's `install` job is this, on every push and pull request.
- A host project that has the package installed and runs `ty check` over
  `from dataporter import importer` resolves real signatures, not `Any`.
- `make check-all` passes with the coverage gate unchanged.

## Risks

- **`uv build` needs the network** to fetch the build backend on a cold cache. The
  packaging tests skip — with the reason stated — when `uv` is not on `PATH`, but a
  sandbox with `uv` and no network fails them rather than skipping. CI has both.
- **`hatchling>=1.27` is a floor nothing locks.** The build backend is resolved at build
  time, so a machine with an older one gets the licence fields ignored or the build
  rejected. The floor is declared and the packaging test asserts the licence reached the
  metadata, which is what would catch it.
- **The install smoke proves the package imports, not that a migration runs.** It cannot:
  a migration needs Hermes, a model, an API key and Chrome. `doctor` is still the thing
  that answers "is this environment ready", and `10` is still unrun.
- **A dependency added without thought now reaches every host project.** The packaging test
  lists the five requirements literally, so adding a sixth fails until somebody writes it
  down there too. That is the intent, and it will read as an annoyance the first time.
