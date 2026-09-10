# 14 — Human intervention

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §12
**Depends on:** [13](13-recovery.md)
**Enables:** [19](19-report.md) (interventions counter)
**Status:** Not started

## Goal

When Hermes cannot safely proceed, the run pauses with a clear ask, the human acts in the
visible browser window, and the run continues from the same conversation and step — it
never restarts.

## In scope

- On `HermesResult.outcome == "needs_human"`, `Importer` writes to `run.json`:

  ```json
  "paused": {
    "conversation_uuid": "…",
    "reason": "auth_required",
    "detail": "sign-in form shown at /login",
    "last_step": "open",
    "conversation_id": null,
    "since": "2026-09-10T14:03:11Z"
  }
  ```

  leaves the conversation `running`, increments `run.json.human_interventions`, and prints
  exactly:

  ```text
  Human intervention required

  Reason:       authentication required
  Conversation: 3f9c2a1e (12 of 127)
  Last step:    open
  Browser:      the Chrome window is open — complete the step there

  Press Enter to resume, or Ctrl-C to stop.
  ```

  Reason phrases, exact: `authentication required`, `CAPTCHA`, `security challenge`,
  `ambiguous UI state`, `unrecoverable browser error`, `confirmation required:
  <detail>`. Labels are padded to 14 characters.
- TTY: the tool blocks on Enter. On Enter it re-probes; if the reason was
  `auth_required` and `probe.logged_in` is still false it prints `still not logged in`
  and waits again. Then it re-runs the same conversation with `resume_from = last_step`
  and the recorded `conversation_id`, clears `paused`, and continues the selection.
- Non-TTY: prints the block, keeps `paused`, releases the lock, exits `5`.
  `hermes-claude-migrate resume` re-locks, re-probes, and continues exactly as the TTY
  path does; with no `paused` record it exits `4` `nothing to resume`.
- Ctrl-C at the prompt: `paused` stays, the conversation stays `running` (crash recovery in
  `06` will convert it on the next start), lock released, exit `5`.
- `confirmation_required`: the printed detail is Hermes's description of the action it
  wanted; the human either performs it in the window or not. Resuming never grants Hermes
  permission to do it — the skill rule (`11`) still applies; the human's action is what
  changes the page.
- Intervention budget: `run.max_interventions` (default `5`) per run; when exceeded the
  run stops with exit `1` and `too many interventions — see report`.

## Out of scope

- Waiting out a rate limit is not an intervention (`15`), unless the wait would exceed
  `pacing.max_rate_limit_wait_s`, in which case it becomes one with reason
  `confirmation required: rate limit until <time>`.

## Design notes

- The run resumes the *same* conversation from its *last successful step* (§12 "resume
  rather than restart") because the chat may already exist; restarting would duplicate
  it.
- The pause record is in `run.json`, not `state.json`, so the §7 file keeps its shape and
  the conversation's status is still one of the five.

## Acceptance criteria

- A fake Hermes returning `needs_human`/`auth_required` once, then `completed`: on a
  pseudo-TTY the block above is printed byte-exactly, an Enter resumes, the conversation
  ends `completed` with `attempts == 2`, `human_interventions == 1`, and the second prompt
  contains `resume_from: open`.
- The same with stdin not a TTY: exit `5`, `paused` present; `resume` completes the run.
- Ctrl-C at the prompt leaves `paused` and a `running` entry; the next `import` converts
  it per `06` and offers `resume`.
- Six interventions in one run stop it with exit `1`.

## Risks

- The human may fix the page in a way the skill does not expect (e.g. sends a message
  themselves). The `resume_from` re-probe and the `identify` step make the chat id the
  source of truth, not the assumed state.
