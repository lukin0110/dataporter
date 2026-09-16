# 64 — The mock catches up with the account

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 03](../03-extraction-and-backup.md) §40 (a mock source),
[Brief 04](../04-trace.md) §49 (a trace as evidence); amends
[brief 02](../02-claude-mock.md) §21 (*What it cannot do yet*: a login expiry in the
middle of a run), [`32`](32-mock-export-page.md)'s export page and its `SSL_CERT_FILE`
tail, [`38`](38-mock-core.md)'s description of that tail as the block's, and
[`46`](46-extraction-rehearsal.md)'s `SSL_CERT_FILE`/`no_proxy` environment
**Depends on:** [32](32-mock-export-page.md), [37](37-traces-as-evidence.md),
[49](49-the-mock-signs-in-by-link.md), [51](51-export-page-address.md),
[52](52-the-paperwork.md)
**Enables:** the extraction rehearsal again, and the first rows marked from a trace
**Status:** Built

## Goal

Bring the mock claude.ai's export surface back into step with the tool. Six real runs
corrected `sources/claude.py` between 2026-09-14 and 2026-09-15 and none of them reached
`mock/`, so `--protocol extraction` was broken twice over: at the ask, because the mock
served `31`'s placeholder path and selectors, and at the fetch, because the mock's link
served one zip where the tool now reads a manifest.

Not a change to the tool. `extract` is byte-identical afterwards, which is the whole
claim a rehearsal makes (§22).

## What was wrong

The mock's export page last changed in `dd64919`. Since then:

| | the mock served | the tool looks for | since |
| --- | --- | --- | --- |
| the page | `/settings/data-privacy-controls` | `/new#settings/data-privacy-controls` | `ae57fea` |
| the row | `[data-testid="export-data"]` | `[data-perf-screen=…] [data-settings-row] button[data-cds="Button"]` | `ae57fea` |
| the confirmation | a `[role="dialog"]` over the page | a second screen at `…/export-data` | `7cd7f2b` |
| the answer | `[role="status"][data-testid="export-requested"]` | `[data-cds="Toast"] [role="dialog"] h2` reading `Export started` | `9f8eaaa` |
| the fetch | one zip, no session | a manifest and its parts, through the session | `adb0494`, `f9e0310` |

## In scope

- **The panel is markup on `/new`** (`pages.settings_panel`), not a page.
  `server.EXPORT_PAGE_PATH` and its route are **gone** — a fragment never reaches a
  server, so the chat page carries the panel and `SETTINGS_JS` opens it from
  `location.hash`. The composer and the file input are behind it, as they are on the real
  panel; `32`'s "no composer and no file input" was right for a page of its own.
- **Six buttons, the first of them invisible** (`pages.settings_root`): a row that is
  there and not shown, a row holding a switch and no button, the Export row, and four
  *Manage* rows. Six is the count a sketch of the real panel took; the invisible one is so
  that *the first visible match* is a claim this page can falsify. `32`'s hidden twin made
  seven and is gone.
- **A second screen at a second address** (`pages.settings_export_screen`),
  `#settings/data-privacy-controls/export-data`, rendered **in place of** the first — a
  sketch of the real second screen counts one confirmation button and no export rows, so
  the screens are `<template>`s and only one is ever in the document. It carries
  `[data-testid="export-confirm-button"]` and the `Conversations from` radiogroup with
  `All` checked, which the ask touches and the mock leaves alone.
- **The toast** (`pages.REQUESTED_TEXT`): `[data-cds="Toast"] > [role="dialog"] > h2`
  reading exactly `Export started`, raised only once the ask is counted.
- **`POST /api/exports` answers `202`**, which is what the real ask answers sixteen times
  over in the traces. The page reads `ok` from the body, so the two agree.
- **The link is an index** (`archive.manifest`, `wire.MANIFEST_PATH`): the vendor's shape,
  `instructions` / `created_at` / `total_files` / `data_files[]` / `version`, each file a
  `batch_index`, `export_url`, `category`, `part` and `filename`. `created_at` is off the
  wall clock, because a manifest is dated.
- **Two parts, category-split** (`archive.render`, `claudemock.EXPORT_CATEGORIES`):
  `light_metadata-000.zip` holds `users.json` and `conversations-000.zip` holds
  `conversations.json`. Only the second is the export an importer reads, which is what
  makes `extract.archive_among`'s choice mean something.
- **A part may be fetched once** (`exports.Exports.spend`): `404` on the second, which the
  manifest says about its own files in its own words. The index may be read again — no
  mock has a clock a link could expire on, and a first fetch that failed on the operator's
  side should not cost them the export.
- **A part's address carries nothing of the index's token**
  (`wire.PART_PATH` = `/__mock/export/{export_id}/download/{part_token}.zip`, the account's
  uuid as a real manifest uses the org's). The tool files the manifest verbatim, so what
  is in a part URL is on disk beside the archive; the part tokens there are spent and the
  index's is not. Found by the rehearsal's own `the link is in no file the run left`.
- **Both routes are behind the session**, because `f9e0310` measured a real link answering
  `403` without one — and **the link is on `claude.ai`**, not on `127.0.0.1:<port>`, since
  a fetch that carries the session must be on the origin that holds the cookie.
- **Served as an attachment** (`server.attachment`). Without
  `Content-Disposition` Chrome *renders* `application/json`, and the fetch correctly
  reports `the link led to a page, not an archive (HTTP 200)`. The real manifest arrives as
  a download with a 90-character filename, so the vendor sends the header too.
- **An involuntary logout** (§21, amended): a request whose session the site no longer
  knows is answered `/logout?involuntary&returnTo=…`, and `/logout` answers
  `/login?from&reauth&returnTo` — two hops, as the trace records. `POST
  /__mock/expire-session` (`wire.EXPIRE_PATH`, `Sessions.close_all`) is the only way to
  cause it: nothing the tool drives can, because an expiry is something that happens *to* a
  run.
- **The dead paperwork goes** (`claudemock/cli.py`): the `SSL_CERT_FILE` tail,
  `FETCH_PROXY_NOTE` and `HOST_NOTE` described a browserless fetch that no source has any
  more. The reachability block is the two Chrome lines and nothing after them, and
  `rehearsal/extraction.environment` sets nothing of its own. Three slices describe
  that tail as current — `32` built it, `38` moved it to `reachability`'s `tail`
  argument, `46` set the two variables — and this slice is where they are amended
  rather than edited.
- **The evidence** (`docs/spike/traces/`, `37`'s directory, until now empty):
  `login-2026-09-15.jsonl` and `login-link-2026-09-15.jsonl`, from the throwaway account,
  read end to end, unedited. Four rows of the UI map are marked from them — `signed out`,
  `link requested`, `sign-in link`, `signed in by the link` — and one is new,
  `involuntary logout`.
- **The rehearsal**: `CLAUDE.session_bound = True`, which puts Claude's two fetches among
  the steps that drive a tab. The auth-host criterion now keys off `len(mock.hosts) > 1`,
  which is the question it was always asking.
- **`60`'s criterion, corrected**: `both fetches file a complete snapshot` compared the
  block against the *start* of a fetch's stdout, and since `60` a fetch prints its
  `downloaded` lines first. It had been wrong since `60` landed and no extraction
  rehearsal had run to say so.

## Out of scope

- **A panel that renders late.** `62` measured the real one at ~2.9 s against a read at
  ~1.4 s and built `_await_button` for it; the mock renders at once, so it cannot exercise
  that wait. A configurable delay, like the obedient reply's, is the shape — in a slice of
  its own.
- **The redirect to another host.** Real part URLs `302` to `storage.googleapis.com`; the
  mock serves its parts off `claude.ai`, so `download.py`'s redirect-chain reasoning is
  still only exercised by the mock chatgpt.com's two hosts.
- **The involuntary logout in the protocol.** The capability and the door are here;
  wiring a drill into `rehearsal/extraction.py`'s step list would change what
  `docs/rehearsal-03.md` recorded, and belongs with the record that replaces it.
- **Marking the four export rows.** The committable traces are of `login` runs; every
  export trace is under an account that is not the throwaway, so those rows stay
  `*unknown*` and the mock takes the simplest behaviour the tool accepts, as §21 says.
- **The fixed ~21 s a download costs.** Measured across every successful fetch in the
  account homes, from 741 B to 22,913 B alike, while the bytes land in about a second.
  Tool-side, unexplained, and recorded in `docs/LIMITATIONS.md` rather than guessed at.

## Design notes

- **Six buttons, not seven.** `32` proved the visibility filter with a hidden twin of the
  one button, which would now make the count seven where a sketch of the real panel counts
  six. Making the *first of the six* invisible keeps both claims: the count is the
  vendor's, and the first match the tool's selector finds is still one a helper that did
  not filter would wrongly press. It is an invention, and it is the same invention `32`
  made, for the same reason, and said so.
- **English, deliberately.** The account these traces come from was served `es-419` —
  every control label in the sketches is Spanish. `REQUESTED_TEXT` is the one signal the
  tool reads by its words, so a mock answering in Spanish would be proving the shipped
  selector cannot work. That is a limitation to write down, not a thing for the mock to
  do; `docs/LIMITATIONS.md` carries it.
- **Templates rather than `hidden`.** A sketch counts `querySelectorAll`, visible or not,
  and the real second screen answers `0` for the export rows. Only a `<template>` makes
  that true of the count and not merely of what is painted.
- **The part URL was a real bug, caught by a criterion.** The first shape hung each part
  under the index's own token, which put a live credential in every filed manifest. The
  rehearsal's `the link is in no file the run left` failed on it before anyone read the
  code — which is the mock earning its keep on the first run after it grew.

## Acceptance criteria

- `make check` passes: `lint`, the tool's suite, and the mock's.
- `tests/test_spike_docs.py` passes with two traces committed: each begins `"trace":1`,
  carries no forbidden field at any depth, and every `*observed*` row cites one by file
  and line.
- `PYTHONPATH=tests uv run python -m rehearsal.run --protocol extraction --root <dir>`
  ends `rehearsal: passed`, with Claude's fourteen criteria green, and files a snapshot
  holding `export.zip`, `manifest.json`, `light_metadata-000.zip`, `snapshot.json` and
  `COMPLETE` — the shape a real snapshot has.
- `PYTHONPATH=tests uv run python -m rehearsal.run --root <dir>` still ends
  `rehearsal: passed`: the panel is on the chat page now, and the migration must not
  notice.
- A part's URL fetched twice answers `200` and then `404`; the index answers `200` twice.
- `claude-mock serve` prints two Chrome lines and nothing after them.

## Risks

- **The mock is now the only thing asserting the export surface, and it is still
  `*unknown*`.** Four rows describe a panel read by a person on one account on one day,
  and nothing under `docs/spike/` backs them. If claude.ai's panel differs from `51`'s
  reading, the mock is wrong in exactly the same way the tool is, and a green rehearsal
  says nothing about it. The next real `extract` trace from a throwaway account is what
  closes this.
- **Six buttons is a number, not a structure.** If the real panel reorders its rows the
  tool presses *Manage* and the mock still passes, because the mock's order is the tool's
  assumption written twice.
