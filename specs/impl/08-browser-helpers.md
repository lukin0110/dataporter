# 08 — Browser helpers

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §4 (enter the seed, submit, wait, detect completion, identify), §5 (verification after each action), §17 (safety boundaries)
**Depends on:** [07](07-browser-session.md)
**Enables:** [10](10-attach-spike.md), [11](11-skill.md), [16](16-attachments.md)
**Status:** Not started

## Goal

The deterministic primitives Hermes calls through its terminal tool: probe the page, insert
a seed byte-exactly, attach a file, wait for generation to finish. Each one verifies its
own effect and prints one JSON object. Each one refuses to act outside the migration
surface.

## In scope

- All helpers live under `hermes-claude-migrate browser …`, connect to
  `browser.cdp_port`, pick the target and print exactly one JSON object on stdout (exit
  `0` when `ok` is true, `1` otherwise, `2` for usage). Nothing else goes to stdout.
- Target selection: the single `page` target with host `claude.ai`. Zero → `{"ok": false,
  "error": "no_claude_tab"}`. More than one → `{"ok": false, "error": "ambiguous_tab",
  "tabs": [...]}` unless `--target ID` is given.
- Safety gate, applied by every helper before acting (§17): the target URL must match
  `^https://claude\.ai/(new|chat/[0-9a-f-]{36})(\?.*)?$`. Any other URL → `SafetyError`,
  `{"ok": false, "error": "outside_migration_surface", "url": "..."}`, exit `1`. Paths
  under `/settings`, `/admin`, `/billing`, `/organizations` and `/project` are named
  explicitly in the test suite.
- `browser probe [--target ID]` prints `PageState` from `07` plus `last_message`:
  `{"role": "human"|"assistant"|null, "chars": n, "contains": [...]}` where `contains` is
  the list of `--expect TEXT` values found in the last message (used for the ack line).
- `browser paste --seed PATH [--method insert_text|exec_command] [--append]`:
  1. refuse if the composer is missing (`composer_missing`) or, without `--append`,
     non-empty (`composer_not_empty`);
  2. focus the composer via `Runtime.evaluate` (`el.focus()`);
  3. `insert_text`: CDP `Input.insertText` with the whole file; `exec_command`:
     `document.execCommand("insertText", false, text)` via `Runtime.evaluate`;
  4. verify: read `innerText`, normalise both sides (`\r\n`→`\n`, NBSP→space, strip
     trailing whitespace per line, strip), compare SHA-256;
  5. print `{"ok": true, "chars": n, "sha256": "...", "method": "insert_text",
     "elapsed_ms": n}` or `{"ok": false, "error": "text_mismatch", "expected_sha256":
     "...", "observed_sha256": "...", "observed_chars": n}`.
- `browser attach --file PATH`: finds `input[type="file"]` (hidden is fine), calls
  `DOM.setFileInputFiles`, then polls up to `timeouts.attach_s` (default `60`) for an
  element whose text contains the file name outside the composer (the attachment chip).
  Prints `{"ok": true, "file_name": "...", "bytes": n}` or `{"ok": false, "error":
  "chip_not_found" | "input_not_found" | "upload_rejected", "detail": "..."}`.
- `browser await-response [--timeout S] [--expect TEXT]`: polls `probe` every 1 s until
  `generating` is false **and** the last message is from the assistant **and** its char
  count is unchanged for 3 consecutive polls. Prints `{"ok": true, "elapsed_s": n,
  "conversation_id": "...", "last_message": {...}}`; on timeout `{"ok": false, "error":
  "response_timeout", "elapsed_s": n, "generating": true|false}`. Default timeout
  `timeouts.response_s` (`300`).
- `browser close-extra-tabs`: closes `page` targets whose URL is `about:blank` or a
  duplicate `https://claude.ai/new`; never closes a `/chat/<uuid>` tab. Prints
  `{"ok": true, "closed": n}`.
- Every helper appends one line to `<workspace>/logs/actions.jsonl`:
  `{"ts": "...", "helper": "paste", "ok": true, "elapsed_ms": n, "conversation_id": "..."}`.
  `19` sums these into `Browser actions`.

## Out of scope

- Deciding *when* to call these (`11`); submitting the message (Hermes presses Enter or
  clicks Send itself, so submission stays an observed, verifiable agent action).

## Design notes

- Seeds go in through `Input.insertText`, not through `browser_type` and not through the
  clipboard. `browser_type` would route tens of kilobytes through the model's output tokens,
  where it can be altered; clipboard pastes above a few thousand characters are converted
  by claude.ai into a "pasted text" attachment. `insert_text` is what Playwright's
  `keyboard.insertText` uses and it bypasses the paste handler. `exec_command` is the
  fallback if ProseMirror ignores the CDP input event; `10` decides the default.
- Verification by hash after normalisation, because ProseMirror rewrites leading spaces as
  NBSP and may collapse blank lines. The normalisation is written down here so a mismatch
  means something.
- The safety gate lives in the helpers, not only in the prompt, because a prompt is advice
  and a regex is a wall.

## Acceptance criteria

- Against a local static page with a `contenteditable` ProseMirror-like editor: `paste`
  of the 40-turn fixture seed (≈ 45 kB) reports `ok: true` and the editor's text hashes to
  the seed; `--method exec_command` does the same.
- `paste` on a non-empty composer without `--append` exits `1` with `composer_not_empty`.
- Every helper run against a tab at `https://claude.ai/settings/profile` exits `1` with
  `outside_migration_surface` and performs no CDP call other than reading the URL.
- `await-response` against a fixture that toggles a Stop button off after 4 s returns
  `ok: true` with `elapsed_s` between 4 and 8; against one that never toggles, times out
  with `response_timeout`.
- `attach` against a page with a hidden file input sets the file and finds the chip.
- Two claude.ai tabs open → `ambiguous_tab`; with `--target` → proceeds.

## Risks

- claude.ai's composer may ignore `Input.insertText` or apply its paste heuristics to it
  anyway. `10` tests both methods on the real page before `11` is written.
