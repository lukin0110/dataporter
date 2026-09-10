# 01 — Foundation

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §8, §9, §10, §17 (the command surface, exit and output conventions every later slice relies on)
**Depends on:** nothing
**Enables:** everything
**Status:** Not started

## Goal

An installable `hermes-claude-migrate` CLI with the cross-cutting machinery every later
slice depends on: command surface, configuration, logging that cannot leak content, a typed
error taxonomy and an exit-code convention. No migration behaviour.

## In scope

- Package `dataporter`, `src/` layout, `pyproject.toml` managed by `uv`:
  - `requires-python = ">=3.12"`;
  - runtime deps: `pydantic>=2`, `pydantic-settings`, `typer`, `websockets>=12`;
  - dev deps: `ruff`, `mypy`, `pytest`, `pytest-cov`;
  - `[project.scripts] hermes-claude-migrate = "dataporter.cli:app"`;
  - optional extra `judge = ["pydantic-ai"]` declared now, empty of use until `20`.
- `make check` (or `uv run poe check`) = `ruff check`, `ruff format --check`,
  `mypy --strict src`, `pytest`. CI runs the same command.
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
- `make check` passes on a clean checkout in CI.

## Risks

- Over-building. This slice stops at parsing arguments, config, logging and errors. Any
  abstraction a later slice wants, that slice adds.
