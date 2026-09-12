# 07 — Browser session and `login`

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §8
**Depends on:** [01](01-foundation.md)
**Enables:** [08](08-browser-helpers.md), [10](10-attach-spike.md)
**Status:** Built

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

    plus `browser.extra_args` (empty by default; see *Design notes*), then polls
    `http://127.0.0.1:<port>/json/version` until it answers (timeout
    `timeouts.browser_start_s`, default `30`). A browser that exits while we wait is
    reported as itself rather than as a timeout. If the port already answers before
    launch, the running instance is adopted only if it is the one we started —
    `<profile>/dataporter-cdp.json` records the port and the browser target's uuid, and
    both must match; otherwise exit `2` `port 9222 is used by another browser`.
  - `close()` sends CDP `Browser.close`, waits for exit, then SIGTERM after 10 s.
- `dataporter/browser/cdp.py` — a minimal synchronous CDP client on
  `websockets.sync.client`, used only by our own code, never by an LLM:
  `targets()` (`GET /json/list`), `attach(target_id)` → `Page` with `send(method, params)`,
  `evaluate(expression) -> value`, `navigate(url)`, `insert_text(text)`,
  `set_file_input_files(selector, paths)`, `close_target(target_id)`. Every call has a
  timeout (`timeouts.cdp_call_s`, default `20`) and raises `BrowserError` on failure.
  `Target` has an id, a type, a URL and a socket — and deliberately no `title`, because a
  claude.ai tab's title is a conversation title (§10). Unsolicited events are kept rather
  than dropped, which is where `probe`'s JavaScript dialogs come from.
- `dataporter/browser/probe.py` — `probe(page) -> PageState`, the one place that knows
  what claude.ai looks like. First version (refined by `10`):

  | Field | Signal |
  | --- | --- |
  | `url`, `kind` | `kind` = `login` if path starts `/login`; `new_chat` if path is `/new` or `/`; `chat` if `/chat/<uuid>`; else `other` |
  | `logged_in` | `kind != login` and `composer_present` |
  | `composer_present` | `document.querySelector('div[contenteditable="true"]')` is non-null and visible |
  | `composer_chars` | the length of that element's text. **Refined by `08`:** one line per block child rather than `innerText`, which is worth two line breaks at a `<p>` boundary and would count an empty ProseMirror composer as one character |
  | `generating` | a button whose `aria-label` contains `Stop` is present and visible |
  | `send_enabled` | a button whose `aria-label` contains `Send` is present and not disabled |
  | `dialogs` | `javascript:<kind>` per CDP `Page.javascriptDialogOpening` not yet matched by a `…Closed`, plus `dom` per visible `[role=dialog]`. Kinds only: the message is page text |
  | `conversation_id` | uuid from `/chat/<uuid>` or `null` |
  | `tab_count` | number of `page` targets with host `claude.ai` |

- `dataporter/browser/session.py` — the flows the three commands are made of: choose the
  claude.ai tab (an existing one, else a blank one navigated rather than a second window
  opened, else a created one), probe it, wait for a login, delete the profile. `12` asks
  the same questions without going through the CLI.
- `hermes-claude-migrate login`: launches with `https://claude.ai/new`, prints
  `Log in to Claude in the browser window that just opened.`, polls `probe` every 2 s
  until `logged_in` or `timeouts.login_s` (default `600`), then prints
  `Logged in. Session stored in <workspace>/browser-profile/.` and closes Chrome so the
  profile flushes to disk. Timeout → exit `3`.
- `hermes-claude-migrate session status`: if the port answers, probes the browser it
  adopts; else launches, probes, closes. A workspace with no profile *and* no browser on
  the port answers without starting anything. Prints `logged in` (exit `0`) or
  `not logged in — run: hermes-claude-migrate login` (exit `3`).
- `hermes-claude-migrate session logout`: deletes `<workspace>/browser-profile/` after
  confirming Chrome is not running on the port; a browser still on it is exit `2` and the
  profile is left alone. Local only; nothing is sent to claude.ai.
- `browser-profile/` is created `0700`; the workspace gets a `.gitignore` containing
  `browser-profile/`, `hermes/`, `seeds/`, `logs/`, merged into whatever is already there
  rather than overwriting it.
- Exit codes: a missing browser, a port that never opens and a CDP call that goes
  unanswered are `BrowserError` → exit `6`; `PortInUse` — the port is occupied by a
  browser we must not touch — is its own subclass and exits `2`, because nothing is
  missing and the operator fixes it by closing something.

## Out of scope

- Any action on a chat (`08`); Hermes attaching (`09`, `10`).

## Design notes

- A dedicated profile, not the operator's real one, so the source account's session can
  never be the one Hermes drives (§17) and so Chrome 136+'s refusal to open a debug port
  on the default profile is moot.
- Headed by default. §12 needs a window the human can act in, and reliability beats
  headless throughput (§13). `24` added the one exception: under `--non-interactive`
  there is no human to hand a window to, and `browser.headless` overrides either way
  (`Settings.headless`, `launcher.HEADLESS_FLAG`).
- Login detection is "a composer is visible on a non-login page". It does not read who is
  logged in; the brief asks to identify the logged-in *state*, not the identity.
- **Adoption is by marker, not by `userDataDir`.** This spec assumed `/json/version` would
  report the profile. It does not — Chrome does not expose `--user-data-dir` over CDP at
  all — so `launch` writes `<profile>/dataporter-cdp.json` with the port, the pid and the
  browser target's uuid, and adopts only when the uuid on the port matches. The uuid is
  minted per browser process, so a match means the same instance and not merely the same
  port. Anything else is `PortInUse`: attaching to the operator's everyday Chrome would
  put the run inside the profile §17 exists to stay out of, and closing it afterwards
  would shut their windows.
- **`browser.extra_args`** is an escape hatch for environments that cannot show a window:
  a CI container has no display and may have no user namespaces, so the probe test passes
  `--headless=new --no-sandbox`. It is empty by default and the migration stays headed;
  every flag a run depends on is fixed in `launcher.LAUNCH_FLAGS` so that two operators
  launch the same browser.
- `probe` opens a connection per call and closes it, so the tab is resolved afresh each
  time and a login flow that replaces the tab is followed rather than watched from a
  target that no longer exists. The cost is that a JavaScript dialog opened before the
  connection existed is invisible to it — not a hole in practice, since a modal `alert()`
  blocks the page's JavaScript and the probe's own `Runtime.evaluate` then times out —
  and `12`, which holds one connection open for a whole conversation, sees the events.

## Acceptance criteria

- `login` against a fresh workspace on macOS opens Chrome at claude.ai; after a manual
  login it prints the success line and exits `0`; `session status` then reports
  `logged in` without any interaction. *(Manual: it needs a real account. Everything
  below is automated.)*
- `session status` in a workspace with no profile exits `3` with the instruction line.
- A unit test for `probe` runs against static HTML fixtures (`login.html`, `new.html`,
  `chat.html`, `generating.html`, `dialog.html`) served over HTTP at claude.ai's own paths
  to a real Chrome, and asserts every field. It skips where no browser is installed, so
  every line it covers is covered by the fake browser as well.
- Launching twice with the same port and a foreign profile on it exits `2`.
- Outside the four modules `24` names as the credentials seam (`config.py`, `cli.py`,
  `signin.py`, `browser/login_form.py`), `grep -r password src/` finds only prose — no
  name, field, prompt or key — and inside them no string constant is a value and no log
  call passes a forbidden field: `test_the_secret_stays_in_the_credentials_seam` parses
  the package and checks the code rather than the prose. (Before `24` this read "finds
  two sentences promising not to ask for one".)

## Risks

- claude.ai may present a bot check on a fresh profile. Headed Chrome with a persistent
  profile is the least suspicious configuration available; `10` records what happens.
