# 33 — The trace file and the move

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 04](../04-trace.md) §42, §43, §46, §47 (the header's marks), §50
**Depends on:** [01](01-foundation.md) (the guard), [08](08-browser-helpers.md),
[31](31-source-session-and-ask.md) (the account home's logs)
**Enables:** [34](34-sketch.md), [35](35-watch.md)
**Status:** Done

## Goal

The file, its header, its guard, and the move: every command that drives a tab opens a
trace beside its run log, every helper call and every export click writes a move into
it, and a helper run by Hermes finds the trace through its environment. No sketch and no
watch yet — `before` and `after` are `null` until `34`, and what the page did on its own
waits for `35` — so a trace this slice leaves is the moves and the two end lines, in a
shape the next two slices only add to.

## In scope

- **The site** (`browser/site.py`, new): `Site(source: str, host: str, selectors:
  Mapping[str, str])`, frozen. What the trace, the sketch and the watch are told about a
  source, and all they are told (§50). `probe.py` gains `SELECTORS`, the public spelling
  of its `_SELECTORS` table, and `MIGRATION_SITE = Site("claude", CLAUDE_HOST,
  SELECTORS)`; `export_page.py` gains `EXTRACTION_SITE`, the same host with the
  migration selectors, its own three (`EXPORT_BUTTON_SELECTOR`,
  `CONFIRM_BUTTON_SELECTOR`, `REQUESTED_SELECTOR`) and `login_form`'s two
  (`EMAIL_SELECTOR`, `PASSWORD_SELECTOR`), each under its constant's name. `site.py`
  imports nothing from `probe`, `export_page` or `login_form`; they import it.
- **The file** (`trace.py`, new): `trace_path(logs_dir, stamp)` is
  `<logs_dir>/logs/trace-<stamp>.jsonl` with `log.run_log_path`'s stamp format
  (`log.RUN_LOG_STAMP`), and the stamp is the run log's whenever one is enabled
  (`log.current_run_log()`, new), so the two pair by name (§42); a caller with no run
  log gets the moment. `Trace.open(settings, *, command, flags, site, chrome, agent,
  export_fingerprint=None, stamp=None, now=None)` creates the file `O_CREAT | O_EXCL |
  O_APPEND`, mode `0o600` — a second run in the same second gets `trace-<stamp>-2.jsonl`,
  never an append to the first, since a trace has one header — and writes the header,
  the brief's first line, keys in this order and no other:

  ```text
  {"trace":1,"kind":"header","ts":"2026-09-13T10:00:00.000Z","command":"import","flags":["--pilot"],"source":"claude","host":"claude.ai","account":null,"export_fingerprint":"1f844dc5…","tool":"dataporter 0.1.0","chrome":"Chromium 141.0.7390.37","agent":"hermes 1.0.0 (scripted agent)","chrome_arguments":["--host-resolver-rules=MAP claude.ai 127.0.0.1:8443","--ignore-certificate-errors-spki-list=…"],"root":"/home/me/export/migration"}
  ```

  | Key | Value |
  | --- | --- |
  | `trace` | `1`, the format version; on no other line |
  | `ts` | `orval.utcnow()` to the millisecond, `Z` |
  | `command` | the command's name as the CLI spells it: `login`, `import`, `resume`, `verify`, `followup`, `doctor`, `extract` |
  | `flags` | the long names of the options the command was given on its command line, in the order Typer declares them, never a value — `--email` is one |
  | `source`, `host` | `site.source`, `site.host` |
  | `account` | `settings.account`, else `null` |
  | `export_fingerprint` | the export's, for `import` and `resume`; `null` otherwise |
  | `tool` | `f"{PROGRAM_NAME} {__version__}"` |
  | `chrome` | the `Browser` field of `client.version()`, the debug port's own answer |
  | `agent` | the first line `hermes --version` prints, stripped, read through `HermesCli.run("--version")` by `trace.agent_line`; `null` when there is no `hermes` on the path or it fails — never a raised error |
  | `chrome_arguments` | `list(settings.browser.extra_args)` as configured, never the launcher's own |
  | `root` | `str(settings.logs_dir.parent)`: the workspace or the account home |

  Every line is one JSON object, `json.dumps(obj, separators=(",", ":"),
  ensure_ascii=False)` and a newline, written by one `os.write` on the `O_APPEND`
  descriptor under `fcntl.flock(LOCK_EX)`. `Trace.append(kind, fields)` fills `ts` and
  `t_ms` — `round((time.monotonic() - started) * 1000)` — and refuses a line that breaks
  §46: any key in `log.FORBIDDEN_FIELDS` at any depth (`log.forbidden_names`, the
  existing `_forbidden_names` made public, depth `_MAX_SCAN_DEPTH`) or any of the
  trace's own keys (`TRACE_KEYS = {"trace", "kind", "ts", "t_ms"}`) used as a field.
  Under `log.strict_by_default()` that is `ContentLeakError`; otherwise the line is
  dropped and the run log warns `trace line dropped` with the kind and the sorted names.
  `Trace.end(exit_code)` appends `{"kind":"observation",…,"what":"end","exit":<code>}`
  and closes the descriptor; nothing is ever written after it — a later `append` is
  `TraceEndedError`, a bug in the caller. The two marks are read by `trace.chrome_line`
  and `trace.agent_line`; `trace.start(...)` reads them, opens the file and makes it the
  process's current trace, or warns and returns `None` when the file cannot be made, and
  `trace.finish(trace, exit_code)` ends it and makes none current.
- **Finding it from another process**: `TRACE_ENV_VAR = "DATAPORTER_TRACE"`, read
  directly like `config.WORKSPACE_ENV_VAR`, never from `config.toml` and never a
  `Settings` field. `Trace.attached(path)` opens an existing trace for appending, reads
  the header's `ts` so that its `t_ms` counts from the same start, and never writes a
  header. `trace.current()` returns the process's open trace, else `attached` of the
  file the variable names, else `None` — a helper run by a person at a terminal, with no
  variable, writes no trace. `hermes/client.py::hermes_env` sets the variable when
  `trace.current()` is not `None`, beside `DATAPORTER_WORKSPACE`; a `signin` run through
  the runner inherits it the same way.
- **The move** (`helpers.run`, `export_page._record`): where `record_action` is called,
  `trace.move(...)` is called with the same `ts` — `record_action` gains a `ts` keyword,
  and `run` computes the one stamp both lines carry, which is how a move is found again
  in `actions.jsonl` (§42). The line, keys in this order:

  ```text
  {"kind":"move","ts":"…","t_ms":650,"helper":"probe","ok":true,"elapsed_ms":38,"conversation_id":null,"before":null,"after":null,"result":{"kind":"new_chat","logged_in":true,"composer_present":true,"composer_chars":0,"generating":false,"send_enabled":false,"tab_count":1}}
  ```

  `result` is `outcome.result.model_dump(mode="json", exclude_none=True)` with every
  forbidden key removed at every depth (`trace.sanitised`) — `ProbeResult.title`
  is one, and `34`'s sketch carries `title_chars` in its place — and a `Failure`'s `url`
  replaced by `path` and `query` under §46's URL rule (`trace.url_fields(url)`: the path,
  and the query's key names in order, never a value or the fragment). For the two export
  clicks `helper` is `export-button` or `export-confirm`, `conversation_id` is `null`,
  and `result` is `{"selector": …, "path": …, "query": […]}`. `before` and `after` are
  `null` in this slice.
- **The commands that open one** (§42): each opens the trace once the browser is up and
  ends it in the `finally` that closes the browser, with the exit code the operation is
  about to return — `trace.opened(settings, …)` is a context manager yielding an
  `Opened` whose `.exit_code` the body sets; unset is `0`, and a body that raises ends
  the trace with `70` unless it set a code first (a generator closed after a failed
  check, which is `doctor`'s case). Every one of them takes `flags: Sequence[str]`,
  which `cli.given_flags(ctx)` fills — the long names of the options given, the root's
  first — and a library caller may leave empty. `browser/session.py`'s `login` (not
  `status`, not `logout`: neither drives a tab), whose site is `session.site_of`: the
  migration's, or the extraction's for a source account; `Importer._open_browser` on
  its first call, ended in `_under_lock`'s `finally` with the summary's code — one
  trace per invocation, a mid-run relaunch continues it; `verify.verify_all`;
  `followup.ask_all`; `doctor`'s browser half in `hermes/doctor.py::checks`;
  `extract.ask`. `import --dry-run`, `fetch`, `file`, `report`, `status`, `snapshots`,
  `inspect`, `seeds`: none, and a test says so.
- **Tests**:
  - `tests/test_trace.py` — the header line byte for byte from fixed inputs, against
    the block above with the table's rule per key; `t_ms` counts from the header's `ts`
    in an `attached` trace; every forbidden field, nested, raises under strict and is
    dropped with a warning otherwise; a trace key used as a field is refused the same
    way; `url_fields` keeps the path and the key names and drops the values and the
    fragment; `end` writes the last line and a later `append` raises; two processes
    (`multiprocessing`) appending 8 KB lines three hundred times each leave a file
    every line of which parses; `current()` is `None` with no variable and no open
    trace, and `attached` with the variable; `opened` ends with the body's code, `70`
    on a raise, and the code a body set before it raised; a trace that cannot be made
    is a warning and `None`; the marks are `None` without a browser or a `hermes`.
  - `tests/test_browser_helpers.py` — each helper's move, keys in order, `title` absent
    from a probe's `result`, a `Failure`'s `url` become `path`; the export clicks' two
    moves with their selectors; the move's `ts` equals the `actions.jsonl` line's.
  - `tests/test_hermes_client.py` — `hermes_env` carries `DATAPORTER_TRACE` when a trace
    is open and not otherwise.
  - `tests/test_importer.py`, `tests/test_browser_session.py` (`login`),
    `tests/test_verify.py`, `tests/test_followup.py`, `tests/test_hermes_doctor.py`,
    `tests/test_ask.py` (all against the fakes, `slow`) — one trace file after a run,
    its header's `command` and `flags`, an `end` line with the run's exit code (`70`
    for a `login` that gave up and a run that met a signed-out session), the same stamp
    as the run log, and the one-shot Hermes told `DATAPORTER_TRACE`; `import --dry-run`
    leaves no `logs/` at all (`test_log.py`, as `05` requires).
  - `tests/test_cli.py` — the surface rows unchanged: no new command, no new flag.
- **Docs**: `README.md` (one paragraph under the workspace's files: what a trace is,
  what it never holds); `specs/README.md` (the workspace bullet names
  `logs/trace-<ts>.jsonl`); `pyproject.toml`'s coverage ledger for the new modules.

## Out of scope

- The sketch, and `before`/`after` that are not `null`: [34](34-sketch.md).
- The watch and every observation but `end`: [35](35-watch.md).
- Gathering a rehearsal's traces: [36](36-rehearsal-traces.md).
- Committing a real trace and citing it: [37](37-traces-as-evidence.md).
- A renderer, a comparison: brief §51.

## Design notes

- **A second file, not a wider `actions.jsonl`.** The journal has two consumers, `19`'s
  count and the rule that it holds no page text, and the trace exists to hold page
  text of a kind — labels, paths, the shape of traffic. Widening the journal would put
  its rule at risk on every line for the sake of one reader. A move links to its journal
  line by `ts` and helper instead. Rejected: extending the run log (its guard bans a
  field even named `snapshot`, which is exactly the thing a trace is about); a single
  `trace.jsonl` per directory with a run id per line (a query where a file was wanted,
  and the file is what gets handed to Claude Code).
- **The path travels in the environment, parent to child, and is not a setting.** A
  `Settings` field would be readable from `config.toml`, and a stale path there would
  make every later helper append to an old run. `DATAPORTER_TRACE` is read the way
  `DATAPORTER_WORKSPACE` is and set by `hermes_env` alone. Rejected: the helper deriving
  the newest `trace-*.jsonl` in `logs/` (a helper run by hand during a spike would
  append to whatever run happened last).
- **One `os.write` under a lock.** From `35` two processes append to one file: a helper
  writing its move and the run's own watch writing an observation. `O_APPEND` keeps a
  short line whole on a local filesystem in practice; `flock` makes it a contract, and a
  sketch is not short. Rejected: a single writer fed by pipes (the helper is its own
  process by `08`'s design, and a pipe would be a second protocol beside its one JSON
  object on stdout).
- **The guard is the run log's, made public, not copied.** One list of forbidden names
  for every file the tool writes about a run (§46), and one strict switch. Rejected: a
  trace-specific list (two lists drift, and the one that drifts is the one nobody
  tests).
- **`agent` may be `null`, and `chrome` comes from the port.** An interactive `login`
  needs no Hermes on the machine, and a header that failed the run for want of a version
  line would make the trace the product. The browser's version is one HTTP call the
  tool already makes, not a subprocess. Rejected: `hermes --version` as a hard
  requirement (it is `doctor`'s job to insist).
- **The move is written where the action is counted.** `record_action` has two callers
  and both now write a move; the importer's own in-process tidy-up
  (`close_extra_tabs` before a run) is neither counted nor a move today, and `35` sees
  the tab close. Rejected: a move for every `Page` call (a trace of CDP, not of the
  procedure).
- **Flags by name.** `--email`'s value is a credential and `--only`'s are ids; a rule
  that keeps no value is simpler than a list of which, and the header still says what
  kind of run it was. Rejected: `argv` verbatim.
- **The exit code is the operation's.** `end` is written by the command with the code
  it returns, so a trace and the run log agree on how a run ended; a killed run has no
  `end` line, which is the record of the kill (§42). Rejected: an `atexit` hook (a
  SIGKILL runs none, and the line would then be a promise).

## Acceptance criteria

- `make check` is green; `make check-all` keeps the coverage gate with the new modules
  in it.
- `dataporter --workspace w import --pilot e` in the fake world leaves exactly one
  `w/logs/trace-<ts>.jsonl`, `<ts>` equal to the run log's, whose first line is the
  header with `"command":"import"` and `"flags":["--pilot"]` and whose last line is
  `{"kind":"observation",…,"what":"end","exit":0}`.
- Every `dataporter browser …` call made with `DATAPORTER_TRACE` set appends one move
  whose `ts` is the `actions.jsonl` line's; made without it, appends nothing and prints
  the same object.
- `dataporter import --dry-run e` creates no `logs/` directory.
- With `DATAPORTER_LOG_STRICT=1`, a field named `title`, `email` or `link` anywhere in a
  line raises `ContentLeakError`; without it, the line is absent from the file and the
  run log carries `trace line dropped`.
- A header written against a browser launched with `--host-resolver-rules=…` carries
  that argument in `chrome_arguments`, verbatim.
- *(Live: it needs a real Chromium and the scripted `hermes`, and no account.)* A
  rehearsal's `login`, `import --pilot`, `verify` and `followup` each leave a trace whose
  `agent` says `hermes 1.0.0` and whose moves match `actions.jsonl` line for line.

Every criterion but the live one was met on 2026-09-13 against the fakes: the header
and the move lines byte for byte, the guard on every forbidden name at depth, the
strict switch both ways, two processes appending 600 lines of 8 KB with none torn,
and one trace per invocation from `login`, `import`, `verify`, `followup`, `doctor` and
`extract` in their own suites — 1782 tests, `trace.py` at 100% and the gate at 99.52%.
The live criterion was met the same day by rehearsal 02 (`docs/rehearsal-02.md`): eight
steps drove a tab and left one trace each, every header says `hermes 1.0.0 (scripted
agent)`, and the pilot's 47 moves are its `actions.jsonl` lines, stamp for stamp.

## Risks

- **Two processes, one file, one lock.** A helper that dies holding the lock releases
  it with its descriptor; a helper that hangs holding it blocks the watch. The lock is
  held for one `write` and nothing else, and a test times a thousand contended appends.
- **`hermes --version` costs a subprocess per command.** About a hundred milliseconds
  on every browser command, once. If it ever matters, `doctor`'s answer can be cached in
  the Hermes profile; nothing in the format would change.
- **The header is written before the page is seen.** `chrome` and `agent` are known;
  what the site is — mock or real — is not, and the brief says the reader judges from
  `35`'s certificate. A trace from this slice alone carries the arguments and the agent
  line and no certificate, which is two marks of three.
