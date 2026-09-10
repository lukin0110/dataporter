# 09 — Hermes profile and runner

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §2 (Hermes agent component), §4 (Hermes capabilities), §17 (Hermes permitted only the migration)
**Depends on:** [01](01-foundation.md)
**Enables:** [10](10-attach-spike.md), [11](11-skill.md), [12](12-import-loop.md)
**Status:** Not started

## Goal

Run Hermes as a one-shot subprocess in a dedicated, locked-down profile that attaches to
our Chrome, and turn its final answer into a typed result. `setup` creates the profile,
`doctor` proves the whole chain works before any migration is attempted.

## In scope

- `hermes-claude-migrate setup` (idempotent), shelling out to the `hermes` on `PATH`:
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
     agent.max_turns: 80
     ```

  3. installs the skill from `11` into the profile's skills directory (path confirmed by
     `10`; expected `~/.hermes/profiles/dataporter/skills/dataporter/claude-migrate/`);
  4. prints the model currently configured for the profile, or
     `no model configured — run: hermes -p dataporter setup model` and exits `6`.
     The API key stays in Hermes's `.env`; this tool never reads it.
- `hermes-claude-migrate doctor` prints one line per check, `ok` or `FAIL <reason>`, and
  exits `6` on the first failure:

  ```text
  hermes on PATH            ok  (x.y.z at ~/.local/bin/hermes)
  hermes profile            ok  (dataporter)
  hermes model              ok  (anthropic/claude-sonnet-5)
  hermes config             ok  (browser.backend=off, cdp_url=http://127.0.0.1:9222)
  skill installed           ok  (claude-migrate 0.1.0)
  chrome executable         ok  (/Applications/Google Chrome.app/...)
  chrome launch + cdp       ok  (port 9222, 1.4s)
  hermes attaches to chrome ok  (browser_snapshot of about:blank returned)
  hermes runs helper        ok  (browser probe via terminal tool)
  session                   ok  (logged in)
  ```

  The two `hermes …` checks run a real `hermes -z` task against a throwaway
  `about:blank` tab and require the answer to contain a nonce we supply. Minimum Hermes
  version is pinned in `dataporter/hermes/version.py` and checked here.
- `dataporter/hermes/runner.py`:

  ```python
  class HermesRunner:
      def run(self, prompt: str, *, run_id: str, timeout_s: int) -> HermesResult
  ```

  Invokes, with `cwd=<workspace>` and a minimal environment (`PATH`, `HOME`, `LANG`,
  never `HERMES_YOLO_MODE`):

  ```text
  hermes -p dataporter -z <prompt> --toolsets browser,terminal --usage-file <workspace>/hermes/<run_id>.usage.json
  ```

  Stdout and stderr are captured to `<workspace>/hermes/<run_id>.stdout.txt` and
  `.stderr.txt` (these may contain content; they are workspace files, never logged). On
  timeout the process group is killed and `HermesError(transient=True, detail="timeout")`
  is raised. Exit code `2` from Hermes → `HermesError(transient=False)`.
- Result contract — the last JSON object in stdout (bare or fenced) must validate as:

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

  No parseable object → `HermesError(transient=True, detail="no result json")`; the raw
  stdout path is in the error detail for the operator.
- `usage.json` is parsed opportunistically for tokens and cost into `run.json`; its shape
  is recorded by `10` and absence is not an error.

## Out of scope

- What the prompt says (`11`); what to do with the result (`12`–`14`).

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

## Acceptance criteria

- On a machine with Hermes installed, `setup` then `doctor` print all `ok` lines and exit
  `0`; on a machine without Hermes, `doctor` exits `6` at the first line.
- A fake `hermes` script on `PATH` that prints a fenced JSON block after chatter:
  `HermesRunner.run` returns a validated `HermesResult`; one that prints no JSON raises
  `HermesError(transient=True)`; one that sleeps past the timeout is killed and raises.
- The subprocess environment in a test contains no key other than the allowlist.
- `setup` run twice leaves the profile config identical (compare `hermes -p dataporter
  config show` output).

## Risks

- `browser.cdp_url` may only be read by the interactive `/browser connect` command and
  ignored in `-z` runs. `doctor`'s attach check is exactly the probe for this, and `10`
  owns the fallback ladder.
- Hermes releases fast. The pinned minimum version and `doctor` make an upgrade that
  breaks us visible before a migration starts.
