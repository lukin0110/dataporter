# 01 — Foundation

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §8, §9, §10, §17 (the command surface, exit and output conventions every later slice relies on)
**Depends on:** nothing
**Enables:** everything
**Status:** Done

## Goal

An installable `hermes-claude-migrate` CLI with the cross-cutting machinery every later
slice depends on: command surface, configuration, logging that cannot leak content, a typed
error taxonomy and an exit-code convention. No migration behaviour.

## In scope

- Package `dataporter`, `src/` layout, `pyproject.toml` managed by `uv`:
  - `requires-python = ">=3.12"`;
  - runtime deps: `pydantic>=2`, `pydantic-settings`, `typer`, `websockets>=12`;
  - dev deps: `ruff`, `ty`, `pytest`, `pytest-cov`;
  - `[project.scripts] hermes-claude-migrate = "dataporter.cli:app"`;
  - optional extra `judge = ["pydantic-ai"]` declared now, empty of use until `20`.
- `make check` = `ruff check`, `ruff format --check`, `ty check --error-on-warning`,
  `pytest`, over `src`, `tests` and (from `10`) `spikes`. CI runs the same command.

  *Amended by [`22`](22-test-performance.md):* there are now two. `make check` runs the
  fast half of the suite and is what CI runs on a pull request; `make check-all` runs
  everything with coverage and is what CI runs on `main`, so the `fail_under` gate lives
  there. `poe` was never added — the Makefile is the only entry point.
- Command surface, all registered now, unimplemented ones exit `69` with
  `not implemented in this build: <command>`:

  ```text
  hermes-claude-migrate login
  hermes-claude-migrate import <export> [--dry-run] [--limit N] [--only UUID]... [--retry-failed] [--retry-partial] [--force] [--skip-attachments] [--attachments-dir DIR] [--pilot]
  hermes-claude-migrate inspect <export> [--json]
  hermes-claude-migrate seeds <export> [--only UUID]... [--out DIR]
  hermes-claude-migrate status [--json]
  hermes-claude-migrate resume
  hermes-claude-migrate verify [--only UUID]...
  hermes-claude-migrate report [--json]
  hermes-claude-migrate setup
  hermes-claude-migrate doctor
  hermes-claude-migrate session status | logout
  hermes-claude-migrate browser probe | paste | attach | await-response | close-extra-tabs
  ```

  Global options, before the subcommand: `--workspace PATH`, `--verbose` / `-v`,
  `--quiet` / `-q`, `--version`.
- `dataporter/config.py`: `Settings(BaseSettings)` with `env_prefix="HCM_"`,
  `env_nested_delimiter="__"`, loaded from `<workspace>/config.toml` when present.
  Precedence: CLI flag > environment > `config.toml` > defaults. This slice defines the
  mechanism and the `workspace` field; later slices add their sections (`browser`, `hermes`,
  `seed`, `pacing`, `retries`, `timeouts`, `run`, `attachments`, `fidelity`).
- `dataporter/errors.py`:

  ```python
  class MigrationError(Exception):
      category: Category      # see table
      transient: bool         # class property, never guessed at the call site
      step: str | None        # last step name, see 11
      detail: str             # operator-facing, never content
      source_conversation_id: str | None
  ```

  | Category | Class | `transient` | Source |
  | --- | --- | --- | --- |
  | `auth` | `AuthError` | no — needs human | §11, §12 |
  | `captcha` | `CaptchaError` | no — needs human | §12 |
  | `security_challenge` | `SecurityChallengeError` | no — needs human | §12 |
  | `rate_limit` | `RateLimitError` (carries `retry_after_s`) | yes | §11, §13 |
  | `generation` | `GenerationError` | yes | §11 |
  | `network` | `NetworkError` | yes | §11 |
  | `navigation` | `NavigationError` | yes | §11 |
  | `dialog` | `DialogError` | yes | §11 |
  | `ui` | `UIError` (composer missing, click failed, ambiguous state) | per instance | §11 |
  | `browser` | `BrowserError` (Chrome gone, CDP unreachable) | per instance | §12 |
  | `hermes` | `HermesError` (process failed, bad result JSON, timeout) | yes | §4 |
  | `export` | `ExportError` (malformed archive) | no | §6 |
  | `unsupported` | `UnsupportedError` | no | §6, §14 |
  | `verification` | `VerificationError` | per instance | §11 |
  | `safety` | `SafetyError` (action outside the allowed surface) | no | §17 |

- Exit codes, `dataporter/exit_codes.py`, used by every command:

  ```text
  0   success
  1   migration finished with at least one failed or partial conversation
  2   usage or configuration error
  3   destination session not authenticated — run `login`
  4   nothing to do (already migrated, or selection empty)
  5   paused for human intervention (non-TTY); run `resume`
  6   environment not ready (Hermes or Chrome missing) — run `doctor`
  69  command not implemented in this build
  70  unexpected internal error
  ```

- `dataporter/log.py`: structured JSON-lines log at `<workspace>/logs/run-<UTC ts>.jsonl`
  plus a human line on stderr at `--verbose`. Records carry identifiers, step names, counts,
  durations, categories and details. A `ContentGuard` filter rejects (raises in tests, drops
  in production) any record whose fields are named `text`, `seed`, `title`, `content`,
  `snapshot` or `stdout`, so content cannot be logged by accident.
- `--version` prints `hermes-claude-migrate <semver>` from package metadata.

## Out of scope

- Reading exports (`02`), any browser or Hermes interaction (`07`–`09`), state (`06`).

## Design notes

- The command surface is fixed here so that `--help` is stable from the first release and
  later slices fill in behaviour rather than rename things. Brief §8–§10 spell the command
  names; the rest follow their style.
- Plain stdout, no colour, no `rich`: §9, §10 and §16 are golden strings and terminal
  decoration would break byte comparison.
- `transient` is a property of the class so that `13` and `19` can derive "retry
  recommended" without a per-call guess.

Resolved while building:

- **`transient` is `bool | None`, not `bool`.** The three rows marked *per instance* (`ui`,
  `browser`, `verification`) default to `None`, meaning "unknown", which is what `13` records
  as a null `retry_recommended` and `19` renders as `retry=unknown`. Only those three accept
  a `transient=` argument; passing one to a fixed row raises `TypeError`, because that is
  exactly the per-call guess this design forbids. **`09` currently writes
  `HermesError(transient=…)`, which this rejects** — either `09` drops the argument or the
  `hermes` row moves to *per instance* here. Whoever builds `09` decides; it fails loudly.
- **`detail` is keyword-only** on every error class, so it cannot slide into `transient`.
- **`conversation_id` is the canonical identifier field name in logs.** `08` already uses it;
  `13` currently writes `uuid` and should follow. Where a banned field name is wanted for a
  path, the path spelling is legal: `seed_path`, `stdout_path`.
- **The record's own keys are reserved** (`ts`, `level`, `logger`, `event`, `exception`). An
  `extra` field with one of those names would redefine the schema `19` parses, so the log
  message *is* the event name. **`13`'s planned retry record `{event: "retry", uuid, …}` hits
  this** and needs writing as `log.info("retry", extra={"attempt": …})`. Extras can never
  overwrite a schema key, and `ContentGuard` raises on a collision in strict mode.
- **`typer>=0.27` specifically.** `typer.TyperException`, the base of the vendored click
  exception hierarchy that the exit-`70` guard catches, does not exist in 0.26 or earlier —
  verified against 0.20, 0.21, 0.23 and 0.26, where typer still depends on real click.
- **`ContentGuard` also scans nested mappings**, not just top-level field names, because
  `extra={"result": {"text": …}}` leaks just as effectively. What no name filter can catch is
  content interpolated into the message itself, so the standing rule is: log messages are
  constants, all variable data goes in `extra`.
- **The run log is opt-in per command** (`log.enable_run_log(workspace)`), not installed by
  the root callback. `05` requires `import --dry-run` to leave no workspace directory behind;
  making the file sink explicit turns that from "nobody logs on this path" into an invariant.
  The handler also opens lazily, so `logs/` appears only when a record is really written.
- **`config.toml` is always read from the bootstrap workspace** (`--workspace` > `HCM_WORKSPACE`
  > `./migration`). A `workspace` key inside it still sets the workspace, but does not
  relocate config discovery — otherwise resolution would be a fixed-point iteration with a
  possible cycle.
- **Exit `2` covers a malformed or invalid `config.toml`**, not just bad arguments; the table
  already says "usage or configuration error". `workspace` is stored absolute, since `09` runs
  Hermes with `cwd=<workspace>`.
- **The flag surface is exactly the list above.** Later specs reference `--all` (`15`, `21`),
  `--delay`, `--max-retries`, `--timeout` (`15`), `--force-unlock` (`06`),
  `browser --target/--expect/--messages` (`08`, `17`) and a `judge` command (`20`). The slice
  that adds the behaviour adds the flag.
- **`typer` ≥ 0.20 vendors `click`** rather than depending on it, so there is no `click`
  import. `add_completion=False`, `pretty_exceptions_enable=False` and `rich_markup_mode=None`
  are all required to get the plain, stable `--help` this slice promises. An unhandled
  exception is turned into exit `70` by a `TyperGroup` subclass, and the `dataporter` logger
  always carries a `NullHandler` so `logging.lastResort` cannot print a traceback to stderr.
- **`ruff` is scoped to `src` and `tests`.** It formats Python blocks inside Markdown, which
  would rewrite these specs.

## Acceptance criteria

- `uv sync && uv run hermes-claude-migrate --version` prints `hermes-claude-migrate 0.1.0`.
- `hermes-claude-migrate import ./nowhere --dry-run` exits `2` with
  `error: export not found: ./nowhere` and no traceback.
- Every unimplemented command exits `69` with the message above.
- `HCM_WORKSPACE=/tmp/x hermes-claude-migrate status` resolves the workspace to `/tmp/x`;
  `--workspace /tmp/y` wins over it; a `config.toml` value loses to both — one test each.
- A test logs a record with a `text` field at `--verbose` and asserts it never reaches the
  log file or stderr.
- Every category in the table has a class and a test asserts the `transient` column.
- `make check` passes on a clean checkout in CI, and `make check-all` passes on `main`.

## Risks

- Over-building. This slice stops at parsing arguments, config, logging and errors. Any
  abstraction a later slice wants, that slice adds.
