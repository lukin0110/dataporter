# 35 — The watch

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 04](../04-trace.md) §44, §46 (requests, dialogs, URLs), §47 (the
certificate), §50
**Depends on:** [33](33-trace-and-move.md), [34](34-sketch.md)
**Enables:** [36](36-rehearsal-traces.md), [37](37-traces-as-evidence.md)
**Status:** Not started

## Goal

The tool's own eyes on the tab for the length of a run: a second CDP session that hears
what the page does — navigations, in-page URL changes, dialogs, its own traffic, the
certificate, tabs — whoever caused it, Hermes's own `browser_*` moves included, and
writes each as an observation. It sends no input, it never stops a run, and it takes a
sketch where the page moved so that a trace shows not only that it did but what it found.

## In scope

- **The watch** (`browser/watch.py`, new): `Watch.start(trace, client, target, site)
  -> Watch` opens its own `client.attach(target.id)` and, on that connection, sends
  `Page.enable`, `Network.enable`, `Target.setDiscoverTargets {"discover": true}` and
  `Accessibility.enable`, then runs a daemon thread that loops `connection.drain(0.25)`
  and maps each event to a line. `stop()` sets a flag, joins the thread with a five
  second limit and closes the connection; it is the last thing before the command ends
  the trace. The watch sends nothing else: no `Input.*`, no `Page.navigate`, and the only
  `Runtime.evaluate` it ever makes is the sketch's `dataporter:selectors`.
- **The observations**, one line each, keys in this order after `kind`, `ts`, `t_ms`,
  `what`:

  | Event | `what` | Fields |
  | --- | --- | --- |
  | `Page.frameNavigated`, `frame.parentId` absent | `navigation` | `path`, `query` |
  | `Page.navigatedWithinDocument` | `url_changed` | `path`, `query` |
  | `Page.javascriptDialogOpening` | `dialog_opened` | `type` (`alert`, `confirm`, `prompt`, `beforeunload`) |
  | `Page.javascriptDialogClosed` | `dialog_closed` | `accepted` (bool) |
  | `Network.requestWillBeSent`, host is `site.host`, `type` in `WATCHED_TYPES` | `request` | `id`, `method`, `path`, `query`, `type` |
  | `Network.responseReceived` for a watched request | `response` | `id`, `status`, `content_type`, `bytes`, `elapsed_ms` |
  | first `Network.responseReceived` with `securityDetails` for `site.host` | `certificate` | `host`, `issuer`, `subject` |
  | `Target.targetCreated`, `targetInfo.type == "page"` | `target_created` | `path`, `query` |
  | `Target.targetDestroyed` of a page it saw created or attached to | `target_closed` | — |
  | the loop's connection failing | `watch_lost` | `reason` (the exception's class name) |

  `WATCHED_TYPES = ("Document", "XHR", "Fetch", "EventSource", "WebSocket")`; `type` is
  written lower-cased. `id` is `r<n>`, counted per trace from `r1`, never CDP's own
  request id. `bytes` is `Network.loadingFinished.encodedDataLength`, so a `response`
  line is written at `loadingFinished` and not before; `elapsed_ms` is the difference
  between the two events' `timestamp`s. `content_type` is the response's
  `mimeType`. `issuer` and `subject` are `securityDetails.issuer` and
  `securityDetails.subjectName`, through `log.safe_token`. WebSocket frames are never
  recorded. Every `path`/`query` is `trace.url_fields(url)`.
- **The sketch where the page moved** (§44): a `navigation` takes its sketch at the next
  `Page.loadEventFired`, attributed by writing the sketch line then and nothing else — a
  reader pairs them by order; a `url_changed` takes its sketch at once. Sketches go
  through `trace.sketch`, so a page the run has already drawn costs no line.
- **Losing it** (§44): any `OSError`, `websockets` closure or `BrowserError` inside the
  loop writes `watch_lost`, warns `watch lost` in the run log with the reason, and ends
  the thread. The run goes on. `Importer._ensure_browser` starts a new watch after a
  relaunch, and the new certificate and navigation lines are the record of the restart.
  A watch that cannot start at all — the attach fails — writes `watch_lost` with the
  reason and returns a stopped `Watch`, and the run goes on.
- **Wired where the trace is opened** (`33`): `Importer._open_browser` (and
  `_ensure_browser`), `browser/session.py`'s `login`, `verify.verify_all`,
  `followup.ask_all`, `hermes/doctor.py::checks`, `extract.ask` — each `Watch.start`
  right after `Trace.open`, on the tab the command is about to drive, and `stop()` right
  before `Trace.end`. The site is the command's: `MIGRATION_SITE` for every destination
  command, `EXTRACTION_SITE` for the ask and a source `login`.
- **Tests**:
  - `tests/test_watch.py` (`slow`, the fake Chrome) — `fake_chrome.push(event)`
    replays each event of the table and the line written is the one expected, byte for
    byte from fixed inputs; a request to another host and a `Stylesheet` to the site's
    host write nothing; a `response` waits for `loadingFinished` and carries its
    `encodedDataLength`; the certificate is written once for two responses; a
    `beforeunload` dialog is `dialog_opened` with its type and never its message; a
    `history.replaceState` is `url_changed`; a closed socket writes `watch_lost` and the
    caller's next line still lands; `stop()` returns within its limit and the fake
    reports the connection closed; the watch's method list is exactly the four enables
    and the sketch's evaluate.
  - `tests/test_importer.py` (the fake world) — a run's trace holds the fake's
    navigations in order; a relaunch mid-run writes `watch_lost` then a second
    `certificate`.
  - Live tier, `tests/test_watch.py`'s `requires_a_browser` cases — against
    `tests/fixtures/pages/`: `login-form.html`'s redirect to `/new` is a `navigation`
    with `path` `/new` followed by a sketch; `responding.html` writes no `request` line
    (a static fixture makes none); a new fixture `replace-state.html` that calls
    `history.replaceState` to `/chat/<id>` after a click is one `url_changed`; the page
    server's self-signed certificate is the `certificate` line, issuer and subject as
    the fixture's certificate names them.
- **Docs**: `README.md`'s trace paragraph gains the watch in one sentence; `docs/runbook.md`
  says what `watch_lost` means and that it means nothing for the migration.

## Out of scope

- Answering a dialog, pressing anything, driving anything: never — the watch is a
  witness (§44). `07`'s poll and the agent decide what to do about a dialog.
- Recording the page's WebSocket frames, request or response headers or bodies: never
  (§46).
- Requests from other hosts, static assets: not recorded (§44). A later slice may widen
  `WATCHED_TYPES` if a mock needs it; the format does not change.
- Gathering the traces a rehearsal leaves: [36](36-rehearsal-traces.md).

## Design notes

- **A second session, not a wrapper around `Connection.send`.** Wrapping the tool's own
  sends would record the tool's own moves twice and Hermes's not at all: the adaptive
  moves are made on the agent's own session, and the only way to hear them is to be on
  the tab when the page reacts. Chrome multiplexes sessions per target, and events are
  delivered to every session that enabled the domain. Rejected: routing Hermes's
  `browser_*` through new helpers (undoes `11`'s one adaptive action); parsing the
  agent's transcript (`19` rejected what the agent believes it did, and the file is
  content).
- **Enabling `Network` is the one thing the watch changes.** It turns request
  interception's reporting on for the session, and nothing else about the page: no
  cache setting, no throttling, no blocked URLs. A run watched and a run unwatched
  fetch the same bytes. Rejected: `Fetch.enable` (it pauses requests until a session
  continues them — a hand, not an eye).
- **Own request ids.** CDP's ids are opaque strings a reader cannot pair by eye, and
  they differ between two runs of the same page; `r1`, `r2` pair a request with its
  response in a diff of two traces. Rejected: the CDP id (noise in every comparison).
- **The sketch waits for `loadEventFired`.** At `frameNavigated` the new document has
  no tree yet; the load event is the earliest moment the page is what a person would
  see. A single-page navigation has no load event, so `url_changed` sketches at once —
  and the page's own polling after it is what the requests show. Rejected: sketching at
  `frameNavigated` (an empty tree, every time); `domContentEventFired` (the composer
  mounts after it on a script-driven page).
- **The certificate once, from the first response that carries one.** It is the mark
  §47 needs and it does not change within a run; a relaunch is a new watch and writes it
  again, which is right. `Security.enable` would give it earlier and adds a domain for
  one field. Rejected: `Security.securityStateChanged` (explanations, not a subject
  name).
- **`watch_lost` is a line, not an exit code.** The migration is the product and the
  trace is its record; a run that ended because its record broke would be the wrong
  priority twice. The run log's warning is what an operator sees. Rejected: a paused
  run (§12 is for pages only a person can clear).
- **The watch is started by the command, on the tab it is about to drive.** It is not
  started by `driving` (which is per helper and per process) and not by the launcher
  (which does not know a trace exists). The importer already tracks its tab across a
  relaunch; the watch follows. Rejected: watching the browser target and every page
  (a second tab the agent opens by mistake is a `target_created` line, not a second
  watch — the trace is of the run's tab).

## Acceptance criteria

- `make check` is green, and `tests/test_watch.py` drives every row of the table against
  the fake Chrome with byte-for-byte lines.
- A trace of a rehearsal's `import --pilot` holds, per conversation, a `url_changed` to
  `/chat/<id>` after the first submit, a `request` and `response` pair per poll the
  mock's page makes, and one `certificate` line naming `claude-mock`, all with `t_ms`
  increasing.
- The watch's connection sends exactly `Page.enable`, `Network.enable`,
  `Target.setDiscoverTargets`, `Accessibility.enable`, `Accessibility.getFullAXTree` and
  the sketch's evaluate, and nothing else, in a full fake-world run.
- Killing the fake's WebSocket mid-run leaves `watch_lost` in the trace, the run's exit
  code unchanged, and `watch lost` in the run log.
- *(Live: it needs a real Chromium.)* Against the fixture pages, the four live cases
  above hold.

## Risks

- **A busy page is a busy trace.** A site that polls every 250 ms writes eight lines a
  second while a reply grows; a minute's reply is a few hundred lines. That is the
  shape the mock has to reproduce and is why it is recorded — but a full run's trace
  will be large. The pilot's is what gets read; `WATCHED_TYPES` is the knob if the
  volume ever hides the signal.
- **Two sessions on one tab.** Chrome delivers an event to every session that enabled
  its domain; the watch's `Page.enable` does not change what Hermes's session sees, and
  the fake Chrome cannot prove it. The live tier's fixtures, driven by the tool with the
  watch on, are the proof that a watched run behaves — and the rehearsal, which runs
  the whole protocol under a watch, is the proof at scale.
- **`loadEventFired` may never fire.** A navigation the page cancels, or a redirect
  chain, can leave a `navigation` without its sketch. The next `navigation` resets the
  wait; a reader sees a `navigation` with no sketch following and knows.
