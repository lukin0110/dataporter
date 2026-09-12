# 09 — Hermes profile and runner

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §2 (Hermes agent component), §4 (Hermes capabilities), §17 (Hermes permitted only the migration)
**Depends on:** [01](01-foundation.md)
**Enables:** [10](10-attach-spike.md), [11](11-skill.md), [12](12-import-loop.md)
**Status:** Built

## Goal

Run Hermes as a one-shot subprocess in a dedicated, locked-down profile that attaches to
our Chrome, and turn its final answer into a typed result. `setup` creates the profile,
`doctor` proves the whole chain works before any migration is attempted.

## In scope

- `dataporter setup` (idempotent), shelling out to the `hermes` on `PATH`:
  1. `hermes profile create dataporter` if `hermes profile list` lacks it;
  2. `hermes -p dataporter config set <key> <value>` for each of:

     ```yaml
     browser.backend: "off"              # built-in browser_* tools, not Browser Use CLI
     browser.cdp_url: "http://127.0.0.1:9222"   # from browser.cdp_port
     browser.dialog_policy: must_respond
     browser.dialog_timeout_s: 120
     browser.snapshot_threshold: 30000
     browser.inactivity_timeout: 3600
     browser.restrict_evaluate: true
     browser.record_sessions: false
     approvals.mode: manual
     approvals.single_query_mode: deny
     memory.memory_enabled: false
     agent.max_turns: 80                 # from hermes.max_turns
     ```

  3. installs the skill from `11` into the profile's skills directory (path confirmed by
     `10`; expected `~/.hermes/profiles/dataporter/skills/dataporter/claude-migrate/`);
  4. prints the model currently configured for the profile, or
     `no model configured — run: hermes -p dataporter setup model` and exits `6`.
     The API key stays in Hermes's `.env`; this tool never reads it.

  Its output, four aligned lines plus where the transcripts are:

  ```text
  hermes profile   dataporter (created)
  hermes config    12 keys set
  skill            claude-migrate 0.1.0 -> ~/.hermes/profiles/dataporter/skills/dataporter/claude-migrate
  hermes model     anthropic/claude-sonnet-5
  Hermes session transcripts contain page snapshots, and therefore conversation content. They live under …/profiles/dataporter/ — delete that directory to purge them.
  Next: dataporter doctor
  ```

- `dataporter doctor` prints one line per check, `ok` or `FAIL <reason>`, and
  exits `6` on the first failure:

  ```text
  hermes on PATH            ok  (1.0.0 at ~/.local/bin/hermes)
  hermes profile            ok  (dataporter)
  hermes model              ok  (anthropic/claude-sonnet-5)
  hermes config             ok  (browser.backend=off, browser.cdp_url=http://127.0.0.1:9222)
  skill installed           ok  (claude-migrate 0.1.0)
  chrome executable         ok  (/Applications/Google Chrome.app/...)
  chrome launch + cdp       ok  (port 9222, 1.4s)
  hermes attaches to chrome ok  (about:blank snapshotted, our claude.ai tab listed)
  hermes runs helper        ok  (browser probe via terminal tool)
  session                   ok  (logged in)
  ```

  The two `hermes …` checks run a real `hermes -z` task against a throwaway
  `about:blank` tab and require the answer to contain a nonce we supply. Each also has a
  second condition that an agent cannot satisfy by agreeing with us: the attach check
  requires Hermes to report back the URL of the *other* tab in our browser, which it can
  only read from our debug port, and the helper check requires a new `probe` record in
  `<workspace>/logs/actions.jsonl`, which our own helper writes. Minimum Hermes
  version is pinned in `dataporter/hermes/version.py` and checked here.
- `dataporter/hermes/runner.py`:

  ```python
  class HermesRunner:
      def run(self, prompt: str, *, run_id: str, timeout_s: int) -> HermesResult
      def run_raw(self, prompt: str, *, run_id: str, timeout_s: float) -> RawRun
  ```

  Invokes, with `cwd=<workspace>` and a minimal environment (`PATH`, `HOME`, `LANG`
  forwarded when set, `DATAPORTER_WORKSPACE` set, never `HERMES_YOLO_MODE`):

  ```text
  hermes -p dataporter -z <prompt> --toolsets browser,terminal --usage-file <workspace>/hermes/<run_id>.usage.json
  ```

  Stdout and stderr are captured to `<workspace>/hermes/<run_id>.stdout.txt` and
  `.stderr.txt` (these may contain content; they are workspace files, never logged). On
  timeout the process group is killed and `HermesError(transient=True, detail="timeout")`
  is raised. Exit code `2` from Hermes → `HermesUsageError`, whose `transient` is fixed
  `False`.
- Result contract — the last JSON object in stdout (bare or fenced) that carries an
  `outcome` must validate as:

  ```python
  class HermesResult(BaseModel):
      outcome: Literal["completed", "partial", "failed", "needs_human", "rate_limited"]
      conversation_id: str | None
      last_step: str                       # names from 11
      chunks_acked: int = 0
      error: HermesErrorInfo | None = None # {category, detail}  categories from 01
      needs_human_reason: Literal["auth_required", "captcha", "security_challenge",
                                  "ambiguous_ui", "browser_error",
                                  "confirmation_required"] | None = None
      retry_after_s: int | None = None
      actions: int = 0                     # browser_* tool calls Hermes reports making
  ```

  No such object → `HermesError(transient=True, detail="no result json")`; the raw
  stdout path is in the error detail for the operator.
- `usage.json` is parsed opportunistically for tokens and cost into `run.json`
  (`hermes_input_tokens`, `hermes_output_tokens`, `hermes_cost_usd`, summed by
  `StateStore.add_usage`); its shape is recorded by `10` and absence is not an error.
- `config.py` gains a `hermes` section (`executable`, `profile`, `home`, `toolsets`,
  `max_turns`) and three timeouts (`hermes_cli_s`, `hermes_check_s`, `hermes_task_s`).

## Out of scope

- What the prompt says (`11`); what to do with the result (`12`–`14`).
- Spending `timeouts.hermes_task_s` or `StateStore.add_usage`: both exist here and are
  first called by `12`.

## Design notes

- Subprocess, not import: Hermes lives in its own `uv` environment under
  `~/.hermes/hermes-agent/` and `-z` is its documented programmatic mode. Importing it
  would couple us to its internals and its Python version.
- A dedicated profile so its config, memory, skills and session transcripts are separate
  from anything else the operator uses Hermes for, and so `setup` can be strict without
  breaking their defaults.
- `approvals.mode: manual` with `single_query_mode: deny`: a one-shot run has nobody to
  answer a prompt, so anything Hermes's approval layer flags is denied rather than allowed.
  Our helpers are ordinary commands and do not trip it. `HERMES_YOLO_MODE` is deliberately
  never set.
- Browser Use CLI mode is turned off because its single `browser_exec` tool writes
  arbitrary Python against the page; the ref-based tools plus `browser_cdp` are narrower and
  every action is visible in the transcript.
- **The environment is built, not filtered.** (`24` leans on this: `DATAPORTER_AUTH__EMAIL` and
  `DATAPORTER_AUTH__PASSWORD` are deliberately not on the list, so a credential in the parent's
  environment never reaches the agent, and no helper the agent runs can read it either.)
  `client.hermes_env` starts from nothing and
  forwards `PATH`, `HOME` and `LANG` when the parent has them, so `HERMES_YOLO_MODE`
  cannot be set by an operator's shell — a structural guarantee rather than a check
  somebody has to remember. `DATAPORTER_WORKSPACE` is *set*, which `09` adds to the spec: with
  `cwd=<workspace>`, a helper Hermes runs as `dataporter browser probe` with no
  `--workspace` would resolve the default `./migration` *inside* the workspace — a second
  workspace, one level down, with its own config and actions log. `11`'s prompt passes the
  flag too; this makes forgetting it harmless rather than silently wrong.
- **`transient=False` on exit 2 is a class, not a call site.** `01` fixes `transient` as a
  property of the error class so `13` and `19` never have to guess. `errors.HermesUsageError`
  is therefore a subclass of `HermesError` — same `hermes` category, `default_transient =
  False` — and covers the three invocations that cannot succeed by being repeated: Hermes
  missing, Hermes too old, Hermes rejecting the arguments. `01`'s table is unchanged.
- **The result is the last object carrying `outcome`, not simply the last object.** Our
  own helpers print one JSON object per call and Hermes quotes them in its transcript, so
  "the last JSON object in stdout" is sometimes a `browser probe` result. `outcome` is the
  contract's discriminator. An object that carries it and then fails validation is an
  error rather than a reason to keep looking further back: a malformed final answer must
  not be silently replaced by an earlier one. `extra="ignore"` on the model, because a run
  that did everything right and added a field is a success with a surplus.
- **The skill ships inside the package**, at `src/dataporter/skills/claude-migrate/`, not
  at a repository-root `skills/`: `setup` copies it out of the *installed* tool, and only
  files under the package directory are in the wheel. `11` is updated to match. The file
  shipped today has `11`'s final frontmatter and a body that says it is a placeholder and
  refuses to act — `09` owns installing a skill and proving one is installed, which is
  testable now and is what `10` needs to run Hermes at all; `11` writes the procedure.
- `config show` is parsed rather than trusted to one shape: nested YAML, flat dotted keys
  and `key = value` all read, because nobody has seen Hermes's output yet and `10` is
  where it gets pinned. Not a YAML parser — two keys are read, plus whichever names the
  model — so no dependency `01` declined for the export itself.
- `doctor`'s checks are a generator, consumed one line at a time: the two Hermes tasks
  take a minute each, and ten lines arriving at once after two minutes reads like a hang.
  It stops itself after the first failure as well as being stopped by the CLI, so
  `list(checks(...))` costs nothing extra either.
- `doctor` exits `6` for a signed-out session too, rather than `3`: every line in this
  command answers "is the environment ready", and `login` is named in the failure reason.
- A `run_id` is validated against `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` before it becomes
  three filenames. `12` derives it from an export we do not control, so this is a
  `ValueError` — our own contract, exit `70` — and not a `MigrationError`.
- `MINIMUM_VERSION` is `0.1.0`, which accepts everything. The mechanism is the deliverable;
  nobody has run this against a real Hermes, and pinning a number observed nowhere would be
  a fabricated fact. `10` raises it to what it saw and the check starts having teeth.

## Acceptance criteria

- On a machine with Hermes installed, `setup` then `doctor` print all `ok` lines and exit
  `0`; on a machine without Hermes, `doctor` exits `6` at the first line.
- A fake `hermes` script on `PATH` that prints a fenced JSON block after chatter:
  `HermesRunner.run` returns a validated `HermesResult`; one that prints no JSON raises
  `HermesError(transient=True)`; one that sleeps past the timeout is killed and raises.
- The subprocess environment in a test contains no key other than the allowlist — asserted
  both on what is passed and on what the child process sees, allowing for the `LC_CTYPE`
  CPython sets in its own environment after exec (PEP 538).
- A one-shot that starts a child of its own leaves nothing behind when it is timed out:
  the process group goes, not only the leader.
- `setup` run twice leaves the profile config identical (compare `hermes -p dataporter
  config show` output).

## Risks

- `browser.cdp_url` may only be read by the interactive `/browser connect` command and
  ignored in `-z` runs. `doctor`'s attach check is exactly the probe for this, and `10`
  owns the fallback ladder. Its second condition — our other tab's URL in the answer — is
  what distinguishes "attached to our Chrome" from "attached to a Chromium of its own",
  which a nonce alone cannot.
- Hermes releases fast. The pinned minimum version and `doctor` make an upgrade that
  breaks us visible before a migration starts — but only once `10` has raised the minimum
  above `0.1.0`.
- `MODEL_KEYS` and the skills directory are both guesses at Hermes's own spelling. Each is
  one tuple and one function, named in `profile.py` and `skill.py`, for `10` to correct.
- **Nothing tells Hermes where its home is.** `hermes.home` is only *our* view of the
  profile tree: the subprocess environment is built from scratch and carries no
  Hermes-home variable, so `setup` installing a skill and `doctor` finding it again prove
  only that the file is where we put it. For the `~/.hermes` default the two agree, because
  `HOME` is forwarded — but an operator who overrides `hermes.home` to something the
  `hermes` on `PATH` does not use would get `skill installed ok` confirming our own write.
  Propagating the override was not guessed at here for the same reason `MINIMUM_VERSION`
  is `0.1.0`: Hermes's environment interface is not something `09` can know. `10` settles
  how Hermes finds its profiles, and then either propagates the value or narrows the
  setting; the stronger check — asking Hermes which skills it can see — needs the same
  answer. Raised by a review bot on the PR, and a fair hit: the setting's docstring
  promised more than the code did.
