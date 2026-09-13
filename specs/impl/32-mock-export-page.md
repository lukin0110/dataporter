# 32 — The mock export page

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 03](../03-extraction-and-backup.md) §40 (a mock source)
**Depends on:** [26](26-mock-claude.md), [30](30-store-and-snapshot.md) (the fetch),
[31](31-source-session-and-ask.md) (the page's shape)
**Enables:** rehearsing extraction — the ask and the fetch — with no account
**Status:** Done

## Goal

The mock claude.ai grows the one page an extraction acts on and a link it prints instead
of sending an email, so that `dataporter extract` runs end to end against it: the ask
presses the mock's button, the fetch downloads the mock's archive, and the ledger counts
the ask. It is not a change to the tool, which stays byte-identical (§22), and not a
change to the rehearsal runner, which still runs the migration protocol only.

## In scope

- **The export page** (`mock/src/claudemock/pages.py`): `export_page()` at the tool's
  placeholder path, built out of `31`'s four rows with the tool's placeholder selectors
  — `[data-testid="export-data"]`, a `[role="dialog"]` holding
  `[data-testid="confirm-export"]`, a `[role="status"][data-testid="export-requested"]`
  — re-typed rather than imported (ADR 0003). A hidden twin of the button first in the
  DOM, as the live fixture has, so a click that did not filter by visibility would miss.
  No composer and no file input. Its script walks the three stages: the button unhides
  the dialog, the confirmation `POST`s `/api/exports`, and the status region is unhidden
  only on `{"ok": true}` — so the ledger is the witness, and a signed-out `POST`, which
  lands on the login page, shows nothing.
- **The ask as state** (`site.py`): `Export(token, requested_at, fetched)`;
  `Site.request_export()` mints a 32-hex token, keeps it, and counts
  `exports_requested`; `Site.export(token)` returns it and counts the fetch, `None` for
  a token nobody minted; `Site.exports()` in the order asked; `Site.all_chats()`.
  `Site` gains a wall clock (`wall=time.time`, injectable) and `Chat` a `created_at`,
  because an archive dates a chat and the monotonic clock replies grow on cannot.
- **The archive** (`archive.py`, new): `render(chats, *, email, now) -> bytes`, a flat
  deflated zip holding `conversations.json` and `users.json` in the export's shape —
  each message's `uuid`, `text`, `content`, `sender`, `created_at`, `updated_at`,
  `attachments`, `files`, `files_v2`, `index`, `parent_message_uuid`; each
  conversation's `uuid` (the chat id), `name` (the title), `summary`, `created_at`,
  `updated_at`, `account`, `chat_messages`, `current_leaf_message_uuid`. Files a chat
  accepted are named on its first message as references and carried as bytes nowhere,
  which is the one gap a Claude export has (§31). Entries carry a fixed timestamp and
  ids are `uuid5` of the chat's, so the same chats render the same bytes.
- **The routes and the link** (`server.py`): `GET /settings/data-privacy-controls`
  behind the session, so signed out it is `/login` like every page; `POST /api/exports`
  behind the session, answering `{"ok": true, "link": …}`; and, under `/__mock/` and
  behind nothing, `GET /__mock/exports` (one link per line), `GET /__mock/exports.json`
  (`token`, `link`, `requested_at`, `fetched`) and `GET /__mock/exports/<token>.zip`,
  which renders the archive at the moment of the fetch and is `404` for a token nobody
  minted. The link is `https://<host>:<port>/__mock/exports/<token>.zip`, spelled from
  the socket `serve` really bound; `create_app` takes the `link_base` and an `announce`
  callable told each link as it is minted.
- **The sixth counter** (`ledger.py`): `("exports_requested", "Exports requested:")`,
  after §21's five. The golden row:

  ```text
  Exports requested:             1
  ```

- **The block, the note, the link and `claude-mock exports`** (`cli.py`): the
  reachability block keeps its two Chrome lines byte for byte and gains, after them,

  ```text
  Set in the tool's environment before fetching an export link from it:

    SSL_CERT_FILE=<cert-dir>/claude-mock.pem

  ```

  the proxy note gains `no_proxy=127.0.0.1` for the fetch; `serve` prints, when the
  confirmation is pressed,

  ```text
  Export requested — the link, instead of an email:

    https://127.0.0.1:8443/__mock/exports/<token>.zip

  ```

  and `claude-mock exports` prints a running mock's links, one per line, oldest first,
  for the terminal the mock is not in.
- **The citation** (`uimap.py`): the four `31` rows — `export page`, `export button`,
  `export confirmation`, `export requested` — with what the mock did about each.
- **Tests** (`mock/tests`, `zipfile` and `json` and nothing of the tool's):
  `test_archive.py` — the two files, every key the tool validates, parents chaining to
  the leaf, a generating chat contributing only its finished turns, accepted files on
  the first message, the same chats giving the same bytes; `test_site.py` — two asks are
  two links in order, an unminted token is `None`, the counters; `test_server.py` — the
  page's markup at rest and the signed-out redirect, the ask counted and answered with a
  link, refused without a session, the link serving a zip whose `conversations.json`
  round-trips a renamed chat, an unminted token `404`, the two listings with `fetched`
  climbing, the link announced as minted; `test_ledger.py` and `test_cli.py` — the
  goldens; `test_uimap.py` — unchanged, and enforcing the four rows.
- **Docs**: `mock/README.md` (the block, the note, *Ask it for an export*, the six-row
  ledger, the page among the behaviours, what it cannot do yet); `README.md` (one
  sentence under *Backing an account up* and one under *Rehearsing it*); `CONTEXT.md`
  (**Ledger** counts exports requested); `docs/claude-ui-map.md` (the paragraph under
  the export rows says where the mock's spelling lives).

## Out of scope

- `rehearsal/run.py` running the ask and the fetch, reconciling `exports requested`
  against asks, and a record of it: a later rehearsal. The runner's rebuilt ledger block
  stays §21's five rows; the sixth is always zero in a migration rehearsal.
- A link that expires and a rate limit on asking (brief `02` §28's failure states on
  cue), an inbox, an email. The mock has no clock a link could die on.
- `src/dataporter`: unchanged, so no line in `pyproject.toml`'s coverage ledger.
- A UI map row for the link or the archive: a download is not something a page shows.

## Design notes

- **The link is on the mock's own host, under `/__mock/`.** The tool downloads a link
  with `urllib` and the default opener (`extract.py`), which checks the scheme and
  nothing else: Chrome's resolver rule and SPKI pin do not reach it, so a link that said
  `claude.ai` would lead the fetch to the real site. `/__mock/` is where the ledger
  already lives — a path no helper will drive (`26`). Rejected: a link on `claude.ai`
  (unreachable by the fetch); plain HTTP (the tool refuses it).
- **Trust for the fetch is the operator's `SSL_CERT_FILE`.** Python's default context
  reads it; the mock's certificate carries `127.0.0.1` as a name. It is configuration an
  operator may write, in the block beside the two Chrome lines, and the tool still has no
  setting that names the mock (ADR 0001). `no_proxy=127.0.0.1` is in the proxy note, not
  the block, because a proxy is a fact about the machine. Rejected: the mock serving the
  link over plain HTTP to spare the certificate (the tool refuses a link that is not
  `https`, and rightly).
- **The ledger grew a row; the runner did not.** §21's five are a migration's verbs and
  §25 reconciles them; an ask is the one thing an extraction asks of the site, and a
  witness that did not count it would be no witness to an extraction rehearsal.
  `rehearsal/run.py` renders its own five labels and reads the mock's JSON with `.get`,
  so a sixth key costs it nothing. Rejected: counting the ask as a rename or a message
  (a lie the reconciliation would then rest on).
- **Site-wide state; links live until restart; a second ask adds a link.** The mock has
  one account and the tool distinguishes nothing finer. A link may be fetched any number
  of times, because an operator whose first fetch failed for a reason on their side
  should not have to ask again, and the mock has no clock to expire one on. Two asks
  yield two links so that two extractions yield two snapshots (§39, 6); a dead link is
  rehearsed with a token nobody minted, which is `404` — `link refused: HTTP 404`, exit
  `2`, the ask left open (§39, 5). Rejected: single-use links (punish a tool-side
  failure); replacing the previous link (loses question 6).
- **The status appears only after the `POST` returns.** The tool reads the page as four
  booleans and writes `ask.json` on `requested`; if the region appeared before the mock
  had counted, the ledger would no longer be the witness. Rejected: the button posting
  directly with no dialog — the ask's second click and "the dialog and its confirm are
  true together" would never be exercised, and the live fixture already has the dialog.
- **The archive is the chats, rendered at fetch time, from finished turns.** A chat still
  generating contributes its transcript and never the prefix of a reply the page is
  still revealing: a half line is text that will never exist in the account. A chat is
  dated by its own creation and its messages one second apart, monotone and needing no
  bookkeeping on a turn. `users.json` is written because the conversations cite an
  account; `projects.json` and `memories.json` are not, because the mock has neither and
  an empty file would claim a feature. Rejected: an archive the operator hands the mock
  at start (whatever they chose, unrelated to the chats, and no round trip); `view(now)`
  unconditionally (ships a prefix as a message).
- **The path and the selectors are re-typed, never imported.** ADR 0003: a helper
  wanted on both sides is duplicated, never imported across. Correcting a row in the
  UI map is one edit in `export_page.py` and one here, and the map's paragraph says so.
  Rejected: reading them out of the tool's source at import time (an import in disguise).

## Acceptance criteria

- `make check` is green, and `uv run --package claude-mock pytest mock` covers every
  route and every branch of the archive without a browser.
- `claude-mock serve` prints the block with the `SSL_CERT_FILE` line, and on a proxied
  machine the note names `no_proxy=127.0.0.1`.
- Signed out, `GET /settings/data-privacy-controls` is `303` to `/login`; signed in, the
  page holds the button, the hidden dialog and the hidden status, and no composer.
- `POST /api/exports` counts one `exports_requested`, answers with a link under
  `/__mock/exports/`, prints the link note in the mock's terminal, and `claude-mock
  exports` prints the same link.
- The link downloads a zip whose `conversations.json` holds every chat with its title
  and its finished turns; a token nobody minted is `404`; two asks are two links.
- *(Live: it needs a headless Chromium and the scripted `hermes`, and no account.)*
  `dataporter --non-interactive extract --account mock` against the running mock exits
  `0` and prints §31's ask block; `--link` with a token nobody minted exits `2` with
  `link refused: HTTP 404` and leaves `ask.json`; `--link` with the printed link files a
  snapshot that `inspect` reads; the archive fetched by hand with `curl` is byte for byte
  the snapshot's `export.zip`; a second ask and fetch file a second snapshot and leave
  the first byte-identical.

Every criterion above was met on 2026-09-13: the first five by the mock's own suite, and
the live one against a real headless Chromium (Playwright's build 1194) driven by the
shipped tool with `27`'s scripted `hermes` on the path and no account. The ask took two
clicks, `export-button` then `export-confirm`, recorded in the account home's
`actions.jsonl` with no content; the dead link exited `2` with `link refused: HTTP 404`
and left `ask.json`; the first fetch filed `2026-09-13T10-22-05Z` with 0 conversations,
and `curl` with the mock's certificate downloaded the same 362 bytes, sha256
`1f844dc5…2d04c`, as its `export.zip`; two chats and one upload driven into the mock, a
second ask and fetch filed `2026-09-13T10-22-50Z` with 2 conversations, 4 messages and
the gap line for the file, `inspect` read it, and the first snapshot's archive hashed the
same as before with its `COMPLETE` in place. The ledger closed at 2 sign-ins, 2 chats, 2
messages, 1 file, 1 rename, 2 exports requested — which is why the status is `Done`
rather than `Built`. It is not evidence about claude.ai (§27): every row the page is
built out of is still `*unknown*`.

## Risks

- **`[role="status"]` is generic.** The tool reads any visible status region as
  "requested"; the page has one and it is hidden until the ask is counted, and nothing
  else on the page is a status. A second status region added later would make the ask
  write `ask.json` on nothing — the test of the page at rest is what catches it.
- **Everything is `*unknown*`.** The page is the tool's guess at claude.ai, served back
  to the tool. A rehearsal against it proves the ask's mechanics and nothing about the
  real page (§27); `docs/extraction-01.md` is still `not yet run`.
- **The record's block and the mock's differ by a row.** A reader comparing
  `docs/rehearsal-NN.md`'s five rows with `claude-mock ledger`'s six may think one is
  stale. The runner's block is §21's; the day a rehearsal also extracts is the day the
  runner learns the sixth row and reconciles it.
- **`SSL_CERT_FILE` steers more than the fetch.** Set in a shell, it replaces the trust
  store for every Python process in it — `uv` included. The README sets it per command.
