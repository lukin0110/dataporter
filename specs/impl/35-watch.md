# 35 — The watch

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 04](../04-trace.md) §44, §46 (requests, dialogs, URLs), §47 (the
certificate), §50
**Depends on:** [33](33-trace-and-move.md), [34](34-sketch.md)
**Enables:** [36](36-rehearsal-traces.md), [37](37-traces-as-evidence.md)
**Status:** Done

## Goal

The tool's own eyes on the tab for the length of a run: a second CDP session that hears
what the page does — navigations, in-page URL changes, dialogs, its own traffic, the
certificate, tabs — whoever caused it, Hermes's own `browser_*` moves included, and
writes each as an observation. It sends no input, it never stops a run, and it takes a
sketch where the page moved so that a trace shows not only that it did but what it found.

## In scope

- **The watch** (`browser/watch.py`, new): `Watch.start(trace, client, site) -> Watch`
  picks the first page target on `site.host`, attaches its own `Page` (which sends
  `Page.enable`) and, on that connection, sends `Network.enable`,
  `Target.setDiscoverTargets {"discover": true}` and `Accessibility.enable` (`ENABLES`),
  then runs a daemon thread that loops `connection.pull(POLL_S)` — `cdp.Connection.pull`
  is new: it hands every pending event over once, what a `send` in between put aside
  included, and keeps nothing, where `drain`'s memory of everything since the connection
  opened would grow with the run — and maps each event to a line. No trace, no watch.
  `stop()` sets a flag, closes the connection and joins the thread with a five second
  limit; it is the last thing before the command ends the trace, and is safe to call
  twice. The watch sends nothing else: no `Input.*`, no `Page.navigate`, and the only
  `Runtime.evaluate` it ever makes is the sketch's `dataporter:selectors` — `take`
  gains `url=` and `dialogs=` for a caller that heard both as events, so the sketch
  reads neither `location.href` nor `probe`'s dialog list.
- **The observations**, one line each, keys in this order after `kind`, `ts`, `t_ms`,
  `what`:

  | Event | `what` | Fields |
  | --- | --- | --- |
  | `Page.frameNavigated`, `frame.parentId` absent | `navigation` | `path`, `query` |
  | `Page.navigatedWithinDocument` | `url_changed` | `path`, `query` |
  | `Page.javascriptDialogOpening` | `dialog_opened` | `type` (`alert`, `confirm`, `prompt`, `beforeunload`) |
  | `Page.javascriptDialogClosed` | `dialog_closed` | `accepted` (bool) |
  | `Network.requestWillBeSent`, host is `site.host`, `type` in `WATCHED_TYPES` | `request` | `id`, `method`, `path`, `query`, `type` |
  | `Network.loadingFinished` (or `loadingFailed`: status `0`, no type, no bytes) for a watched request | `response` | `id`, `status`, `content_type`, `bytes`, `elapsed_ms` |
  | first `Network.responseReceived` with `securityDetails` for `site.host` | `certificate` | `host`, `issuer`, `subject` |
  | `Target.targetCreated`, `targetInfo.type == "page"` | `target_created` | `path`, `query` |
  | `Target.targetDestroyed` of a page it saw created or attached to | `target_closed` | — |
  | the loop's connection failing | `watch_lost` | `reason` (the exception's class name) |

  `WATCHED_TYPES = ("Document", "XHR", "Fetch", "EventSource", "WebSocket")`; `type` is
  written lower-cased. `id` is `r<n>`, counted per watch from `r1`, never CDP's own
  request id. `bytes` is `Network.loadingFinished.encodedDataLength`, so a `response`
  line is written at `loadingFinished` and not before; `elapsed_ms` is the difference
  between the two events' `timestamp`s, never negative. `content_type` is the
  response's `mimeType`. `issuer` and `subject` are `securityDetails.issuer` and
  `securityDetails.subjectName`, through `log.safe_token`, once per watch. A tab that
  `Target.setDiscoverTargets` announces as created but that existed when the watch
  started — its own included — is not `target_created`. WebSocket frames, headers and
  bodies are never recorded. Every `path`/`query` is `trace.url_fields(url)`.
- **The sketch where the page moved** (§44): a `navigation` takes its sketch at the next
  `Page.loadEventFired`, attributed by writing the sketch line then and nothing else — a
  reader pairs them by order; a `url_changed` takes its sketch at once. Sketches go
  through `trace.sketch`, so a page the run has already drawn costs no line.
- **Losing it** (§44): a `BrowserError` inside the loop — a closed socket, a frame that
  is not JSON — writes `watch_lost`, warns `watch lost` in the run log with the reason,
  and ends the thread. The run goes on. `Importer._open_browser` starts a new watch with
  every browser it opens, the relaunch included, and stops the old one first; the new
  certificate and navigation lines are the record of the restart. A watch that cannot
  start at all — no tab on the host, a failed attach, a refused enable — writes
  `watch_lost` with the reason and returns a stopped `Watch`, and the run goes on. A
  watch whose trace has already ended stops quietly: the last line is written, and
  nothing after it may be.
- **Wired where the trace is opened** (`33`): `watch.watched(settings, command=…,
  flags=…, site=…, browser=…)` wraps `trace.opened` and starts the watch after the
  header and stops it before the end, and is what `browser/session.py`'s `login`,
  `verify.verify_all`, `followup.ask_all`, `hermes/doctor.py::checks` and `extract.ask`
  now enter; `Importer._open_browser` starts one with every browser it opens and
  `_close_browser` stops it, beside the trace `33` gave it. The site is the command's:
  `MIGRATION_SITE` for every destination command, `EXTRACTION_SITE` for the ask and a
  source `login`.
- **Tests**:
  - `tests/test_watch.py` (`slow`, the fake Chrome) — `fake_chrome.push(event)`
    replays each event of the table and the line written is the one expected, byte for
    byte from fixed inputs; a request to another host and a `Stylesheet` to the site's
    host write nothing; a `response` waits for `loadingFinished` and carries its
    `encodedDataLength`; the certificate is written once for two responses; a
    `beforeunload` dialog is `dialog_opened` with its type and never its message; a
    `history.replaceState` is `url_changed` and sketched at once, with the selector
    count the watch's only evaluate; a child frame's navigation is not the page's; a
    `navigation`'s sketch waits for the load and carries no query value; a `Script` and
    a request's headers, body and CDP id never reach the file; a failed load is a
    response of nothing; the certificate is not written for another host; the tabs that
    existed at start are not `target_created`; a frame that is not JSON
    (`FakeChrome.push_raw`, new) and a browser that goes away write `watch_lost` and
    the trace goes on; a tree the browser refuses is a warning and the `url_changed`
    still lands; `stop()` returns within its limit, the fake reports the connection
    closed, and nothing was written; no trace is no watch and no CDP call; no tab, and a
    refused enable, are `watch_lost` before the thread exists; a trace that ended stops
    the watch quietly; `watched` starts after the header and stops before the end; the
    watch's connection sends exactly the four enables.
  - `tests/test_importer.py` (the fake world) — a run enables the four domains on the
    tab before anything is typed and leaves no connection open.
  - Live tier, `tests/test_watch.py`'s `requires_a_browser` cases — against
    `tests/fixtures/pages/`: a new fixture `redirect.html` that sends the browser to
    `/new` as it loads is two `navigation`s, `/redirect` then `/new`, the second with a
    sketch that counts one composer, and the page's own two document loads are the only
    `request` lines; a new fixture `replace-state.html` that calls
    `history.replaceState` to `/chat/<id>` after a click is one `url_changed` with a
    sketch of the chat path. The certificate is not a live case here: the fixture
    server is plain HTTP, and the mock's TLS is what `36`'s rehearsal shows it against.
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
  mock's page makes, and one `certificate` line whose issuer is its own subject —
  `claude.ai` twice, the mark of a certificate signed by itself — all with `t_ms`
  increasing.
- The watch's connection sends exactly `Page.enable`, `Network.enable`,
  `Target.setDiscoverTargets`, `Accessibility.enable`, `Accessibility.getFullAXTree` and
  the sketch's evaluate, and nothing else.
- A browser that goes away, or a frame that is not JSON, leaves `watch_lost` in the
  trace, the trace still writable, and `watch lost` in the run log.
- *(Live: it needs a real Chromium.)* Against the fixture pages, the two live cases
  above hold.

Every criterion above was met on 2026-09-13: the table row by row against the fake
Chrome, and the two live cases against a real Google Chrome 152 on macOS — `/redirect`
then `/new` as two navigations with the second sketched, and a `replaceState` as one
`url_changed` with its sketch. The certificate line, which needs TLS, waits for `36`'s
rehearsal against the mock; the fake shows it written once from `securityDetails`. The
rehearsal's `import --pilot` criterion is `36`'s to run.

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
