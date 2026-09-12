# 23 — Library operations; the CLI as an interface

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** nothing in the brief — tooling, like `22`. §8–§10 fix the command surface
and this slice leaves every command, flag and golden string where they were.
**Depends on:** every slice that is `Done`
**Enables:** [24](24-non-interactive.md), and any Python caller
**Status:** Done

## Goal

Make `dataporter` a Python library with a command-line interface on top, rather
than a command-line tool whose behaviour lives in its argument parser. Every command becomes
one shape — parse the flags, take the settings the root callback resolved, call the one
library function that owns the command, hand it somewhere to put its lines, exit with the
code it returns — and everything else that `cli.py` used to do moves into the module that
owns the domain. A caller who imports `dataporter` and never touches `typer` can then do
exactly what the CLI does and read exactly what it would have printed.

It is not a change of behaviour. No command, flag, message or exit code moves, and the
proof of that is the eighty-odd `CliRunner` tests written against `01`–`21`, none of which
changed by a byte.

## In scope

- **`dataporter/console.py`** — the seam. A `Sink` protocol with three channels: `line`
  (stdout, newline appended), `block` (stdout verbatim, for §9's, §10's and §16's blocks,
  which already end in a newline) and `note` (stderr). Three implementations: `Terminal`,
  which resolves `sys.stdout`/`sys.stderr` at write time so that `CliRunner`'s stream
  swap is honoured; `Collected`, which keeps the lines and exposes them as `stdout` and
  `stderr` strings; and `DISCARD`, the library default, because a library that prints is a
  library nobody can call quietly. `HasExitCode` is the one thing the CLI reads off an
  outcome.
- **`errors.UsageError`** — an operator-fixable contradiction in what was asked (`--limit`
  above the ceiling without `--all`, a selection flag beside `--pilot`, an export path that
  is not there). Not a `MigrationError`: nothing failed. `cli._RootGroup` prints `error:
  <text>` and exits `2` for it, the row `ConfigError` already had; `judge.JudgeError` gets
  the exit-`6` row the same way. Those clauses are the whole of the CLI's knowledge of
  exit codes for errors; a code an operation *returns* needs none.
- **`dataporter/selection.py`** — `export_path`, `selected_conversations`,
  `selection_for` (raises `UsageError`; `TOO_MANY` lives here), `plan_for` (takes
  `Settings`, not a Typer context) and `inspect_export`. `pilot.PILOT_CHOOSES` moves
  beside the selection it protects.
- **One operation per command**, in the module that owns it, each taking `Settings` and
  keyword options, each returning a frozen dataclass with `exit_code` and its own facts:

  | Command | Operation | Outcome |
  | --- | --- | --- |
  | `login` | `browser.session.login(settings, *, sink)` | `LoginOutcome` — raises `AuthError` on a timed-out wait |
  | `session status` | `browser.session.status(settings, *, sink)` | `StatusOutcome(signed_in, exit_code)` — a line and a code, never an `error:` |
  | `session logout` | `browser.session.logout(settings, *, sink)` | `LogoutOutcome(removed)` |
  | `import` | `importer.import_command(settings, ImportRequest, *, quiet, sink)` | `ImportOutcome(exit_code, summary, plan, choices)` — the run, the dry run and the pilot |
  | `resume` | `importer.resume_command(settings, *, quiet, sink)` | `ImportOutcome` |
  | `inspect` | `selection.inspect_export(settings, export, *, attachments_dir, json_output, sink)` | `InspectOutcome(plan)` |
  | `seeds` | `seed.write_seeds(settings, export, *, only, out, quiet, sink)` | `SeedsOutcome(written, skipped, exit_code)` |
  | `extract` | `extract.extract_command(settings, ExtractRequest, *, sink)` | `ExtractOutcome(snapshot, path, exit_code)` — the fetch, `--from`, `--abandon`, and `69` for the ask `31` builds |
  | `snapshots` | `store.list_command(settings, *, json_output, sink)` | `SnapshotsOutcome(rows, exit_code)` |
  | `status` | `report.status(settings, *, json_output, sink)` | `StatusOutcome(migration, counters)` |
  | `report` | `report.show(settings, *, json_output, sink)` | `ReportOutcome(report)` |
  | `verify` | `verify.verify_all(settings, *, only, sink)` | `VerifyOutcome(found, exit_code)` |
  | `followup` | `followup.ask_all(settings, *, only, sink)` | `FollowupOutcome(probes, exit_code)` |
  | `judge` | `judge.judge_all(settings, *, only, sink)` | `JudgeOutcome(verdicts, exit_code)` |
  | `setup` | `hermes.profile.setup(settings, *, sink)` | `SetupOutcome(report)` — raises `HermesError` after the lines when no model is configured |
  | `doctor` | `hermes.doctor.run_doctor(settings, *, sink)` | `DoctorOutcome(checks, exit_code)` |

  `ImportRequest` mirrors `import`'s flags one field each, `export` as the `str` typed so a
  missing path is echoed back unchanged. The `browser *` helpers were already one call, one
  object, one exit (`08`) and are untouched.
- **`log.enable_run_log`** is called by the operations that write to the workspace and by
  nothing else — not `cli`, not the `Importer` class, and never on the dry-run or `inspect`
  path. It replaces a file sink already installed rather than adding a second, so one process
  that runs `import` and then `verify` logs each once.
- **`cli.py`** shrinks from 1 292 lines to the plumbing, the option types (they are the
  help text), a `finish(outcome)` and command bodies of four to twelve lines. It imports
  neither `state`, `launcher`, `probe` nor `summary`; the two exception classes it must
  name from those modules are fetched inside `_RootGroup`.

## Out of scope

- Any new behaviour. Non-interactive operation, credentials and headless Chrome are
  [24](24-non-interactive.md), which is what this slice makes possible.
- A change to the progress output. `progress.Reporter` is `18`'s own sink and keeps
  printing §10's block itself; an operation constructs it from `quiet` as the CLI did.
- A public API document. The operations table above is the API; a caller reads the
  docstrings.

## Design notes

- **A sink, not a generator.** `doctor` already streamed its checks through a generator,
  and the exit code and the stop-at-first-failure rule then lived in the consumer, which is
  exactly the logic that had to move. `verify`, `followup`, `judge` and `seeds` each
  interleave lines with side effects and end in a code, and `seeds` writes to both streams;
  a sink with three channels serves all of them, and a generator that also returns is
  awkward for the caller this exists for.
- **The words moved with the code.** `LOGIN_PROMPT`, `SIGNED_IN`, `TOO_MANY`,
  `PILOT_CHOOSES` and the rest live beside the function that emits them, and the tests that
  named them through `cli` were repointed rather than served by re-exports: a re-export is
  a second spelling of where a thing lives.
- **Errors raise, results return.** A path that ends in `error: …` raises the class whose
  `_RootGroup` clause prints that prefix and that code; a path that ends in a line without
  the prefix — `session status` saying `not logged in`, `resume` saying `nothing to resume`
  — returns an outcome whose `exit_code` says `3` or `4`. That is the same distinction the
  CLI made with `fail()` versus `typer.Exit`, made once.
- **`Reporter` is the exception.** A run's progress is drawn on the terminal by `18`'s
  reporter whether the run was started from the CLI or from Python, and the sink receives
  §16's block afterwards. Routing the progress through the sink too would mean a second
  implementation of the redraw, and `18` is a golden string.
- **Two exceptions are imported lazily.** `state.StateError` and `launcher.PortInUse` are
  named in `_RootGroup`'s clauses and nowhere else in `cli.py`; fetching them inside a
  function keeps the module's import list the statement the acceptance test checks —
  nothing in `cli` opens a workspace or a browser.

## Acceptance criteria

- Every `CliRunner` test written before this slice passes without a changed assertion;
  the four that named a `cli` attribute (`cli.selection_for`, `cli.PILOT_CHOOSES`,
  `cli.LOGIN_PROMPT`, `cli.require_export`) name the moved one.
- `tests/test_cli.py::test_every_command_is_an_interface`: no function registered on
  `app`, `session_app` or `browser_app` contains a `for`, `while`, `try`, `with` or `if`.
- `tests/test_cli.py::test_the_cli_opens_no_workspace_and_no_browser_itself`: `cli.py`
  imports none of `state`, `launcher`, `probe`, `summary`, `load_export`.
- `tests/test_operations.py`: `inspect`, `import --dry-run`, `import --dry-run --pilot`,
  `seeds`, `status`, `report`, `session logout`, `resume` and a real run each produce, through
  `console.Collected`, the bytes and the code the CLI produces with the same settings.
- `tests/test_log.py::test_a_second_run_log_replaces_the_first`.
- `make check-all` passes with the coverage gate unchanged.

## Risks

- The shape test is opinionated. If a future command genuinely needs a branch in the CLI
  — a flag that changes which operation is called — the test should be narrowed to the
  loop-and-lock half rather than the branch half, and the branch should still be one line.
- `followup.ask_all` and `seed.write_seeds` import `importer` and `selection` inside the
  function to keep the module graph acyclic. A future move that makes either import
  top-level should check `importer` does not import them back.
