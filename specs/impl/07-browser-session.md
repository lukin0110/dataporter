# 07 — Browser session and `login`

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §8
**Depends on:** [01](01-foundation.md)
**Enables:** [08](08-browser-helpers.md), [10](10-attach-spike.md)
**Status:** Not started

## Goal

A Chrome instance that our tool owns: launched with a dedicated profile inside the
workspace and a remote-debugging port, authenticated once by the operator through the
normal claude.ai login, and reused by every later run. The tool never sees, asks for or
stores a password.

## In scope

- `dataporter/browser/launcher.py`:
  - `find_executable()` honours `browser.executable`, else tries in order
    `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`, `google-chrome`,
    `chromium`, `chromium-browser`, `brave-browser`,
    `/Applications/Brave Browser.app/Contents/MacOS/Brave Browser`, `microsoft-edge`.
    None found → `BrowserError`, exit `6`.
  - `launch(url)` runs the binary with exactly:

    ```text
    --user-data-dir=<workspace>/browser-profile
    --remote-debugging-port=<browser.cdp_port>          # default 9222
    --remote-debugging-address=127.0.0.1
    --no-first-run --no-default-browser-check --disable-sync
    --disable-features=TranslateUI
    --window-size=1280,900
    <url>
    ```

    then polls `http://127.0.0.1:<port>/json/version` until it answers (timeout
    `timeouts.browser_start_s`, default `30`). If the port already answers before launch,
    the running instance is adopted only if its `/json/version` reports our profile
    (`userDataDir` matches); otherwise exit `2` `port 9222 is used by another browser`.
  - `close()` sends CDP `Browser.close`, waits for exit, then SIGTERM after 10 s.
- `dataporter/browser/cdp.py` — a minimal synchronous CDP client on
  `websockets.sync.client`, used only by our own code, never by an LLM:
  `targets()` (`GET /json/list`), `attach(target_id)` → `Page` with `send(method, params)`,
  `evaluate(expression) -> value`, `navigate(url)`, `insert_text(text)`,
  `set_file_input_files(selector, paths)`, `close_target(target_id)`. Every call has a
  timeout (`timeouts.cdp_call_s`, default `20`) and raises `BrowserError` on failure.
- `dataporter/browser/probe.py` — `probe(page) -> PageState`, the one place that knows
  what claude.ai looks like. First version (refined by `10`):

  | Field | Signal |
  | --- | --- |
  | `url`, `kind` | `kind` = `login` if path starts `/login`; `new_chat` if path is `/new` or `/`; `chat` if `/chat/<uuid>`; else `other` |
  | `logged_in` | `kind != login` and `composer_present` |
  | `composer_present` | `document.querySelector('div[contenteditable="true"]')` is non-null and visible |
  | `composer_chars` | `innerText.length` of that element |
  | `generating` | a button whose `aria-label` contains `Stop` is present and visible |
  | `send_enabled` | a button whose `aria-label` contains `Send` is present and not disabled |
  | `dialogs` | `pending_dialogs` from CDP `Page.javascriptDialogOpening` events plus any `[role=dialog]` visible |
  | `conversation_id` | uuid from `/chat/<uuid>` or `null` |
  | `tab_count` | number of `page` targets with host `claude.ai` |

- `hermes-claude-migrate login`: launches with `https://claude.ai/new`, prints
  `Log in to Claude in the browser window that just opened.`, polls `probe` every 2 s
  until `logged_in` or `timeouts.login_s` (default `600`), then prints
  `Logged in. Session stored in <workspace>/browser-profile/.` and closes Chrome so the
  profile flushes to disk. Timeout → exit `3`.
- `hermes-claude-migrate session status`: if the port answers, probes it; else launches,
  probes, closes. Prints `logged in` (exit `0`) or `not logged in — run: hermes-claude-migrate
  login` (exit `3`).
- `hermes-claude-migrate session logout`: deletes `<workspace>/browser-profile/` after
  confirming Chrome is not running on the port. Local only; nothing is sent to claude.ai.
- `browser-profile/` is created `0700`; the workspace gets a `.gitignore` containing
  `browser-profile/`, `hermes/`, `seeds/`, `logs/`.

## Out of scope

- Any action on a chat (`08`); Hermes attaching (`09`, `10`).

## Design notes

- A dedicated profile, not the operator's real one, so the source account's session can
  never be the one Hermes drives (§17) and so Chrome 136+'s refusal to open a debug port
  on the default profile is moot.
- Headed only. §12 needs a window the human can act in, and reliability beats headless
  throughput (§13). A `--headless` flag is not offered in this slice.
- Login detection is "a composer is visible on a non-login page". It does not read who is
  logged in; the brief asks to identify the logged-in *state*, not the identity.

## Acceptance criteria

- `login` against a fresh workspace on macOS opens Chrome at claude.ai; after a manual
  login it prints the success line and exits `0`; `session status` then reports
  `logged in` without any interaction.
- `session status` in a workspace with no profile exits `3` with the instruction line.
- A unit test for `probe` runs against static HTML fixtures (`login.html`, `new.html`,
  `chat.html`, `generating.html`) served to a real Chrome and asserts every field.
- Launching twice with the same port and a foreign profile on it exits `2`.
- `grep -r password src/` finds nothing but this sentence's test.

## Risks

- claude.ai may present a bot check on a fresh profile. Headed Chrome with a persistent
  profile is the least suspicious configuration available; `10` records what happens.
