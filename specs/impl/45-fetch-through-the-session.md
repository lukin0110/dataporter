# 45 — The fetch through the session

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 06](../06-chatgpt-extraction.md) §63 (amending brief 03 §35), §65
(the link's wall), §66, §67
**Depends on:** [43](43-chatgpt-archive.md), [44](44-chatgpt-session-and-ask.md),
[30](30-store-and-snapshot.md), [35](35-watch.md)
**Enables:** [46](46-extraction-rehearsal.md)
**Status:** Built

## Goal

For a source whose vendor serves the archive only to the signed-in session, point the
source session's own tab at the link, let the browser make the download, catch the file
where it lands, and hand it to `30`'s verify-and-file pipeline unchanged. The cookie never
leaves the browser. The link is in no line the fetch leaves.

## In scope

- **The download** (`browser/download.py`, new, source-agnostic):
  `fetch(settings, session, link, *, into, hosts) -> Downloaded(path, bytes, suffix,
  filename_chars)`. On the browser target, `Browser.setDownloadBehavior` with
  `allowAndName`, the directory, and `eventsEnabled`; on the one tab on `hosts`,
  `Network.enable` and `Page.navigate(link)`; then a wait on both sessions:
  `Browser.downloadWillBegin` (the guid, and the suggested name's length and suffix),
  `Browser.downloadProgress` (`completed` → done; `canceled`; past
  `store.max_download_bytes` → `Browser.cancelDownload` and `too_large`);
  `Network.responseReceived` for the document with a status of `400` or more → `refused`;
  `Page.loadEventFired` with no download begun, after one poll's grace → `page`; the idle
  budget `timeouts.download_idle_s`, reset on every download event → `stalled`. A
  `DownloadStopped(reason, status)` for each, which `extract` turns into a line. The file
  is `<into>/<guid>`: nothing the vendor named ever reaches a path.
- **The fetch** (`extract.fetch`, gaining `flags`): after the scheme check, a source
  whose `fetch_needs_session` is set requires credentials unattended, as the ask does;
  then `_download_through_session`: `launcher.launch` on the source's root, `watched`
  with the extraction site, `_sign_in_to_source` probing the root (a new `url` keyword;
  the fetch has no business on the export page), and under `trace.redacting()` the
  download. What follows — `is_zipfile`, `_read`, `_filing`, `Store.file_archive`, the
  temp file's `unlink`, the ask's deletion, the block — is the one path both fetches
  share. Claude's `urllib` fetch is byte-identical to `30`'s. The lines:
  - refused: `link refused: HTTP 403 — the link may have expired; ask again with:
    dataporter extract --source chatgpt --account work` (`30`'s line, shared);
  - a page: `the link led to a page, not an archive (HTTP 200); sign in with: dataporter
    login --source chatgpt --account work, then try again`;
  - too large: `30`'s line; stalled: `the download stalled for 120s; try again`;
    cancelled: `the browser cancelled the download; try again`.
  All exit `2`, nothing filed, the ask kept. The block, golden, is `43`'s with
  `Downloaded 0.0 MB.` in place of `Filed …`.
- **The trace** (`trace.py`): `redacting()`, a context manager over a process-wide event
  — the watch writes from a thread of its own — and `is_redacting()`. While set,
  `url_fields` answers `{"host", "path": "<link>", "query": []}`, so every navigation,
  request, sketch and move any writer reduces in that time carries the host and never
  the path; and the writer's `_offending` refuses, at every depth, a `path` that is not
  the marker or a `query` that is not empty — dropped, or `ContentLeakError` under
  `DATAPORTER_LOG_STRICT`. `watch._request` records a `Document` request on **any** host
  while redacting, so every hop the vendor sends the link through is a line with its
  host (§65, §66). The download's own move, `download`, carries the host, the marker,
  the size and the name's length and suffix; its `actions.jsonl` line carries no URL at
  all — `record_action` without one, not `record_step`, because the action log writes
  the URL it is given.
- **Tests** (`tests/test_chatgpt_fetch.py`, `slow`; `tests/test_trace.py`): the fake site
  answers a link with the events Chrome sends and writes the archive where
  `Browser.setDownloadBehavior` said; a signed-in tab downloads and the archive is filed
  with the golden block, the ask dropped, the temp directory empty,
  `Browser.setDownloadBehavior` before `Page.navigate`, nothing typed; unattended and
  signed out the walk runs first; no credentials is exit `2` before any browser; refused,
  a page, over the cap (and `Browser.cancelDownload` sent), stalled — each its line,
  nothing filed, the ask kept; the link and its path in no line — stdout, stderr, the run
  log, the trace, `actions.jsonl` — with the navigation and the move carrying the marker,
  whether the fetch succeeded or was refused; `url_fields` and `sanitised` while
  redacting; the writer refusing a leaked path or query under strict mode. Live
  (`requires_a_browser`): a real headless Chrome against a cookie-gated server downloads
  the archive by guid, is refused with `403` once its cookies are cleared, and reports a
  page for a link that is one.
- `fake_chrome` answers `Browser.setDownloadBehavior` and `Browser.cancelDownload`.

## Out of scope

- Reading the profile's cookie jar for a browserless download: rejected (§63, §71).
- An archive the site opens in a new tab (`Target.targetCreated`): not built, §71.
- The inbox, the 24-hour expiry, "already requested": §71.

## Design notes

- **`Browser.setDownloadBehavior` on the browser target with `eventsEnabled`**, not the
  deprecated `Page.setDownloadBehavior`: the progress events are browser-level, and
  `allowAndName` gives a guid file name so a vendor's name — which may carry the
  account's address — never reaches a path or a line.
- **No `driving` around the link.** Rejected: widening the extraction surface with the
  link's host, which is unknown and per link; the wall for the fetch is the string the
  person handed over, and the trace records where it went (§65).
- **One refused line for both fetches**, because the operator's remedy is the same; the
  page case is the one genuinely new line, since a signed-out real site may answer `200`
  with a page where the archive should be.
- **Redaction in the writer, not only in the watch**: §66's rule is enforced where every
  line is written, so a future caller cannot leak a path by not knowing it. A
  process-wide event rather than a context variable, because a thread does not inherit
  one and the watch is a thread.
- **The root, not the export page, for the fetch's sign-in probe**: the fetch has no ask
  to make, and a probe that opened the export page would be one more page in the account
  for no reason.

## Acceptance criteria

- The fake-world tests above pass; `make check` is green; Claude's `--link` tests are
  unchanged.
- The link's path and query appear in no line the fetch leaves, succeeded or refused, and
  under `DATAPORTER_LOG_STRICT=1` a leaked path in a redacting trace raises.
- The live test downloads through a real headless Chrome and is refused signed out.
- *(Live, `46`'s.)* The extraction rehearsal fetches the mock chatgpt.com's link through
  the session and files two snapshots; that is what turns this slice `Done`.

## Risks

- **`Browser.setDownloadBehavior` with `eventsEnabled` and `Browser.downloadProgress` are
  experimental CDP.** Verified on the Chromium the live tier runs; a browser without them
  fails the fetch with a `BrowserError` naming the method, exit `6`.
- **A real site that serves the archive from a third host** works the same and is
  recorded as a hop; one that opens it in a viewer tab would need `Target.setAutoAttach`,
  which is named and not built.
- **The page grace is one poll.** A site whose download begins more than a quarter
  second after its document's load event would be read as a page; the live tier shows
  Chromium fires neither in that order, and `docs/extraction-02.md` is where the real
  site answers.
