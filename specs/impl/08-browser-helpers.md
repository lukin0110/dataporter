# 08 — Browser helpers

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §4 (enter the seed, submit, wait, detect completion, identify), §5 (verification after each action), §17 (safety boundaries)
**Depends on:** [07](07-browser-session.md)
**Enables:** [10](10-attach-spike.md), [11](11-skill.md), [16](16-attachments.md)
**Status:** Done

## Goal

The deterministic primitives Hermes calls through its terminal tool: probe the page, insert
a seed byte-exactly, attach a file, wait for generation to finish. Each one verifies its
own effect and prints one JSON object. Each one refuses to act outside the migration
surface.

## In scope

- All helpers live under `hermes-claude-migrate browser …` in
  `dataporter/browser/helpers.py`, connect to `browser.cdp_port`, pick the target and
  print exactly one JSON object on stdout (exit `0` when `ok` is true, `1` otherwise,
  `2` for usage). Nothing else goes to stdout.
- Target selection: the single `page` target with host `claude.ai`. Zero → `{"ok": false,
  "error": "no_claude_tab"}`. More than one → `{"ok": false, "error": "ambiguous_tab",
  "tabs": [{"id": "...", "url": "..."}]}` unless `--target ID` is given; a `--target` that
  names no page target is `{"ok": false, "error": "unknown_target", "detail": "ID"}`.
- Safety gate, applied by every helper before acting (§17): the target URL must match
  `^https://claude\.ai/(new|chat/[0-9a-f-]{36})(\?.*)?$`. Any other URL → `SafetyError`,
  `{"ok": false, "error": "outside_migration_surface", "url": "..."}`, exit `1`. Paths
  under `/settings`, `/admin`, `/billing`, `/organizations` and `/project` are named
  explicitly in the test suite. The gate runs twice: on the URL in the target list, so a
  tab outside the surface is refused with no CDP call at all, and on the live URL after
  attaching, because the target list is a snapshot.
- `browser probe [--target ID] [--expect TEXT]…` prints `PageState` from `07` plus `ok`
  and `last_message`: `{"role": "human"|"assistant"|null, "chars": n, "contains": [...]}`
  where `contains` is the list of `--expect TEXT` values found in the last message (used
  for the ack line). The search happens in the page, so the message text never crosses
  the wire.
- `browser paste --seed PATH [--method insert_text|exec_command] [--append]
  [--target ID]`:
  1. refuse if the composer is missing (`composer_missing`) or, without `--append`,
     non-empty (`composer_not_empty`);
  2. focus the composer via `Runtime.evaluate` (`el.focus()`, then a collapsed range at
     the end — an editable with no selection swallows the insert);
  3. `insert_text`: CDP `Input.insertText` with the whole file; `exec_command`:
     `document.execCommand("insertText", false, text)` via `Runtime.evaluate`;
  4. verify: read the composer's text, normalise both sides (`\r\n`→`\n`, NBSP→space,
     strip trailing whitespace per line, strip), compare SHA-256;
  5. print `{"ok": true, "chars": n, "sha256": "...", "method": "insert_text",
     "elapsed_ms": n}` or `{"ok": false, "error": "text_mismatch", "expected_sha256":
     "...", "observed_sha256": "...", "observed_chars": n}`. A `--seed` that is missing or
     not UTF-8 is `seed_not_found` / `seed_unreadable`, exit `2`, with no CDP call made.
- `browser attach --file PATH [--target ID]`: finds `input[type="file"]` (hidden is fine),
  calls `DOM.setFileInputFiles`, then polls up to `timeouts.attach_s` (default `60`) for an
  element whose text contains the file name outside the composer (the attachment chip).
  Prints `{"ok": true, "file_name": "...", "bytes": n}` or `{"ok": false, "error":
  "chip_not_found" | "input_not_found" | "upload_rejected", "detail": "..."}`. A `--file`
  that is not there is `file_not_found`, exit `2`.
- `browser attachments [--file PATH]… [--target ID]` (added by `16`): one look at the
  page for every chip at once, which is how the skill checks that the composer carries as
  many files as the conversation has before it pastes into it. Prints
  `{"ok": true, "file_names": [...], "count": n}`, or `chip_not_found` with the missing
  names in `detail`. No files is `{"ok": true, "count": 0}` and no CDP call: a
  conversation with no attachments asks a question with a true answer. Nothing here waits
  — `attach` has already waited for each chip — so it reads no timeout.
- `browser await-response [--timeout S] [--expect TEXT]… [--target ID]`: polls `probe`
  every 1 s until `generating` is false **and** the last message is from the assistant
  **and** its char count is unchanged for 3 consecutive polls. Prints `{"ok": true,
  "elapsed_s": n, "conversation_id": "...", "last_message": {...}}`; on timeout
  `{"ok": false, "error": "response_timeout", "elapsed_s": n, "generating": true|false}`.
  Default timeout `timeouts.response_s` (`300`). The gate is re-applied on every poll, so
  a tab that redirects mid-wait stops the wait instead of being watched.
- `browser close-extra-tabs`: closes `page` targets whose URL is `about:blank` or a
  duplicate `https://claude.ai/new`; never closes a `/chat/<uuid>` tab. Prints
  `{"ok": true, "closed": n}`.
- Every helper appends one line to `<workspace>/logs/actions.jsonl`:
  `{"ts": "...", "helper": "paste", "ok": true, "elapsed_ms": n, "conversation_id": "..."}`.
  `19` sums these into `Browser actions`.
- `timeouts.attach_s` (`60`) and `timeouts.response_s` (`300`) are added to `config.py`.

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
- **The composer's text is not its `innerText`.** Measured against Chromium 141 while this
  slice was built: `innerText` is worth *two* line breaks at a `<p>` boundary and two more
  for the `<p><br></p>` an empty line becomes, so a seed with one blank line comes back
  with three. `probe.PRELUDE_JS` therefore reads the composer as an editor's own plain-text
  projection — one line per block element, a `<br>` as a line break, inline elements folded
  into their line — which round-trips both shapes an editable takes: a paragraph per line,
  and the leading bare text node plus `<div>`s that Chrome's native editing produces. The
  same reader backs `07`'s `composer_chars`, which refines that row of `07`'s table:
  an empty ProseMirror composer holds `<p><br></p>` and would otherwise have counted one
  character and made every `paste` refuse a new chat as `composer_not_empty`. `10` checks
  the reader against the real composer.
- The safety gate lives in the helpers, not only in the prompt, because a prompt is advice
  and a regex is a wall. It is coarser than `probe.conversation_id_of`, which parses the
  uuid properly, because a wall is easier to trust when it is one line long. The host and
  the pattern travel together as a `Surface`, passed as an argument and never read from
  config or the environment: every command passes `helpers.CLAUDE`, and the test suite is
  the only caller that substitutes another, so the wall has no door that ships.
- `close-extra-tabs` does not select a target. It cannot: the state it exists to clear up
  is exactly the state that makes target selection ambiguous. What stands in for the gate
  there is that the only URLs it will close are `about:blank` and a second or later new
  chat — a set strictly narrower than the surface, and one that cannot contain a
  conversation.
- Failures that are *answers* are returned as `{"ok": false, …}`; only the gate raises,
  because nothing after it may run and a `return` can be forgotten. Anything else in the
  error taxonomy that escapes a helper — a browser that has gone away, most often — is
  printed as its category (`{"ok": false, "error": "browser", "detail": "..."}`) rather
  than as a message on stderr, so that Hermes reads one object per call whatever happened.
- Helpers do not open a run log. They are called dozens of times per conversation and a
  timestamped log file per call would bury the workspace; `actions.jsonl` is their record,
  and `--verbose` still puts diagnostics on stderr. Writing it is best effort: the helper
  has already acted on the page by then, and losing the result to a read-only workspace
  would be the worse trade.
- Each page expression carries its name in a leading comment (`/* hcm:composer_text */`). It costs
  nothing in the page, names the expression in a CDP trace, and is how the test suite's
  fake browser answers an expression it cannot execute — which is what keeps every line of
  this module covered on a machine with no browser installed.

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
- `attach` against a page with a hidden file input sets the file and finds the chip;
  `attachments` over two such files answers with both names in one evaluate, and names the
  one whose chip is missing when only one attached (`16`).
- Two claude.ai tabs open → `ambiguous_tab`; with `--target` → proceeds.
- Every helper appends one line to `logs/actions.jsonl`, a refusal included, and nothing
  else appears in `logs/`.

## Risks

- claude.ai's composer may ignore `Input.insertText` or apply its paste heuristics to it
  anyway. `10` tests both methods on the real page before `11` is written.
- The transcript selectors (`[data-testid="user-message"]`,
  `[data-testid="assistant-message"]`) and the block-per-line reading of the composer are
  informed guesses until `10` checks them. Both are in `07`'s `probe`, in one place, so
  correcting them is a small edit.
