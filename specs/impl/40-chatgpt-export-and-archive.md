# 40 — The mock chatgpt.com: the export page and the archive

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 05](../05-chatgpt-mock.md) §54 (*The export page*), §55, and §52
as the goal
**Depends on:** [39](39-chatgpt-mock-site.md),
[`docs/chatgpt-export-format.md`](../../docs/chatgpt-export-format.md)
**Enables:** [41](41-chatgpt-mock-walk.md); the tool's ChatGPT half, when it is written
(§58)
**Status:** Built

## Goal

The mock chatgpt.com grows the page where an export is asked for and the archive the
link downloads: the profile menu, **Settings**, **Data controls**, **Export**, **Confirm
export**, a status, and a link printed instead of an email — and, unlike the mock
claude.ai's, an archive served to the signed-in session and refused to anyone else, in
ChatGPT's own shape as `docs/chatgpt-export-format.md` assumes it. It is the fact the
tool's later fetch has to meet, met here first.

## In scope

- **The pages** (`pages.py`): `SETTINGS_PATH = "/settings"`, a page whose entries include
  **Data controls**; `EXPORT_PAGE_PATH = "/settings/data-controls"`, a page of its own
  holding the **Improve the model for everyone** switch, an **Export data** heading with
  a `button#export` **Export** under it, a `[role="dialog"]` hidden until then with a
  `button#confirm-export` **Confirm export** and words of the mock's own, and a
  `[role="status"]#export-requested` hidden until the ask is counted. No composer, no
  file input. The script: **Export** unhides the dialog, **Confirm export** `POST`s
  `/api/exports` and unhides the status only on `{"ok": true}`, so the ledger is the
  witness and a signed-out `POST`, which lands on the landing page, shows nothing. The
  chat page's `[data-testid="profile-button"]` opens a menu holding **Settings**.
- **The ask as state** (`site.py`): `request_export()` (the core's `Exports`, counts),
  `fetch_export(token)`, `exports()` — `32`'s shape, one ask one link, a second ask a
  second link (§39, 6).
- **The routes** (`server.py`): `GET /settings` and `GET /settings/data-controls` behind
  the session; `POST /api/exports` behind the session, answering `{"ok": true, "link":
  …}` and telling `announce`; and `GET /__mock/exports/{token}.zip`, which answers `403`
  with a sentence to a request with no session **before** looking the token up, `404`
  for a token nobody minted, and the archive otherwise. The link is
  `link_of(export) = "https://chatgpt.com" + ARCHIVE_PATH`, on the site's host. The
  core's listings at `/__mock/exports` and `/__mock/exports.json` stay open.
- **The archive** (`archive.py`, new): `render(chats, *, email, now) -> bytes`, a flat
  deflated zip with fixed entry dates holding `conversations.json` — a JSON array, one
  conversation per chat in creation order — and `user.json` — `{"id": "user-…",
  "email"}`, the id derived from the email — and nothing else. A conversation: `title`,
  `create_time` (the chat's, in seconds), `update_time` (one second per message after
  it), `mapping`, `current_node`, `conversation_id` and `id` (the chat's UUID),
  `is_archived`, `default_model_slug` (`auto`), and the null-or-empty fields the format
  document lists for an ordinary chat. The mapping: one root node, `message: null`,
  `parent: null`, then the turns chained one under the other, `current_node` the last
  (the root when there is none). A message: `id` (its node's), `author` (`role`, `name:
  null`, `metadata: {}`), `create_time`/`update_time` (the chat's plus its index),
  `content` (`content_type: "text"`, `parts` the pasted texts then the typed text, the
  typed text omitted when empty), `status: "finished_successfully"`, `end_turn: true`,
  `weight: 1.0`, `metadata` (`attachments` on a user message that carried files — `id`
  `file-…`, `name`, `mime_type` guessed from the name, `size` the bytes the mock read —
  and `{}` otherwise), `recipient: "all"`, `channel: null`. Finished turns only; ids are
  `uuid5` under the chat's; the same chats render the same bytes.
- **The block**: no `SSL_CERT_FILE` line, no host note, no `no_proxy` line: the tool's
  fetch cannot fetch this link, and telling it how to trust the certificate would be a
  promise the site does not keep.
- **Citations** (`uimap.py`): `settings`, `export page`, `export button`, `export
  confirmation`, `export requested`, `already requested`, `download needs session`,
  `link expired`.
- **Tests**: `test_chatgpt_archive.py` (`zipfile` and `json` and nothing else: the two
  members, the user, every conversation key, the root and the chain walked from
  `current_node`, every message key and its constants, an empty chat's root, a generating
  chat contributing finished turns only, pasted texts as parts before the typed text and
  alone when nothing was typed, files named on the message that carried them with a
  guessed type and a size and carried nowhere, no `attachments` key without files, the
  same bytes twice, ids real and stable); `test_chatgpt_server.py` (Settings, the export
  page at rest, the ask counted and answering with a link on the site host, refused
  without a session, the download `403` without a session and `200` with one — the zip
  round-tripping a renamed chat and the user — a token nobody minted `404` to a session
  and `403` to none, the listings open to a client with no cookies).
- **Docs**: `docs/chatgpt-export-format.md` names this slice and `archive.py` as what
  renders the document's claims; `docs/chatgpt-ui-map.md` says where the mock's spelling
  lives.

## Out of scope

- A ChatGPT export model in the tool, a fetch that carries a session, `--source chatgpt`:
  the tool's ChatGPT half (§58), its own brief.
- An export already requested and still processing, a link that expires, a rate limit,
  the zip's file name, the confirmation screen's real words (§57, §58): the mock has no
  clock, and nobody has looked.
- Reading a real export: `docs/chatgpt-export-format.md`'s last section says how, and
  the document changes first and this slice's `archive.py` follows.
- The members that carry media, an archive split over several conversation files (§58).

## Design notes

- **The link is on the site's host, not the mock's address.** `32` put the mock
  claude.ai's link on `https://127.0.0.1:8443/…` because the tool fetches it with
  Python, which has no resolver rule. This site's link is fetched by whoever holds the
  session, and the browser's session cookie is set on `chatgpt.com`: a link on the
  loopback address would be refused to everyone, the signed-in browser included. So the
  link is `https://chatgpt.com/__mock/exports/<token>.zip`, the browser reaches it
  through the resolver rule with its cookie, and anything without one — the tool's
  fetch, `curl` at the mock's address — is refused. That is the fact the later brief
  has to meet (§54). The listings at `/__mock/exports` are served on the mock's own
  address, open, as §54 says: they stand in for the inbox. Rejected: a link on the
  loopback address with the cookie copied by hand (nobody copies a cookie; the site's
  own link would not be on the loopback address either).
- **Refused before looked up.** A fetch with no session answers `403` whatever the
  token, so `Export.fetched` counts downloads and not attempts, and a token nobody
  minted is `404` only to somebody signed in — as a real site would not tell a stranger
  which links exist. The status is `403` and not a redirect to the landing page because
  a download is not a page: a fetch reads a status, and `403` is the one that says
  "refused" and not "moved". Rejected: `303 /` (the tool's fetch would report a
  redirect it followed to an HTML page, and call it a bad archive rather than a refusal).
- **The shape is the format document's, field for field.** OpenAI publishes nothing, the
  document's every claim is *assumed*, and the mock writes what the document says and
  no more: the two members, the root node, `text` parts only, a file named on the user
  message that carried it and carried nowhere, times one second apart. Where the
  document lists fields an ordinary chat carries as `null` or empty, the mock writes
  them so, because a reader of real exports will look for the keys; where it lists
  fields "newer, seen in 2026 exports" (`is_starred`, `memory_scope`, …) the mock writes
  nothing, because their values in an ordinary chat are the least agreed on. Rejected: a
  richer archive (`export_manifest.json`, `chat.html`, a `system` message first) — each
  an empty claim to a feature the mock does not have, which §55 forbids.
- **Pasted texts are parts.** A seed arrives as an attachment (`39`) and the export's
  `text` content carries `parts`, a list of strings; the pasted texts go first because
  that is the order the reply read them in, and the typed text is omitted when empty so
  a chip-only message is one part and not a part and an empty string. Rejected: a
  `multimodal_text` with an asset pointer per pasted text (the document says the mock
  writes `text` only, and a pointer would point at a `.dat` the archive does not carry).
- **A file's size is kept.** The upload route already knows how many bytes it read, the
  document lists `size` on an attachment, and dropping it would make the one thing the
  mock knows about a file into a `0`. The bytes are still dropped (§55).
- **`user.json` is an object, not `users.json`, not a list.** The document's inventory
  says so; the Claude export's `users.json` is a list. Two shapes, two sites (ADR 0005).

## Acceptance criteria

- `uv run --package mocks pytest mock` covers every route and every branch of the
  archive without a browser.
- Signed out, `GET /settings/data-controls` is `303` to `/`; signed in, it holds the
  switch, the **Export** control, the hidden dialog with **Confirm export** and the hidden
  status, and no composer.
- `POST /api/exports` counts one `exports_requested`, answers with a link under
  `https://chatgpt.com/__mock/exports/`, prints the link note in the mock's terminal, and
  `chatgpt-mock exports` prints the same link.
- The link answers `403` to a request with no session and a zip to the signed-in
  session; the zip's members are `conversations.json` and `user.json` and nothing else;
  `conversations.json` holds every chat with its title, a root node and its finished
  turns chained from it, a file named on the message that carried it; two asks are two
  links; a token nobody minted is `404` to a session.
- In a real Chrome pointed at the mock: the profile menu → **Settings** → **Data
  controls** → **Export** → **Confirm export** shows the status; opening the link in the
  signed-in window downloads the zip; the same link from a window with no session is
  refused; the listing is open to both.
- *(Live, the later brief's.)* The tool's ChatGPT half asks on this page and fetches
  this link with a session; that brief's slice records it, and that is what turns this
  slice `Done` (§56).

The first four were met on 2026-09-13 by the suite, and the fifth by the same headless
Chromium walk `39` records: the status appeared after **Confirm export**, the link the
mock printed was `https://chatgpt.com/__mock/exports/<token>.zip`, a fetch from the
signed-in page returned `200` and 1,582 bytes of zip, the same fetch from a context with
no cookies returned `403`, and the listing returned `200` to it. A walk, not a run: the
status is `Built`.

## Risks

- **Everything about the archive is *assumed*.** A real export may have a `system`
  message first, a `create_time` on the root, a `parts` list that is not all strings. The
  mitigation is the document's last section: read one, change the document, change
  `archive.py`, and the tool's later model reads the document too.
- **`[role="status"]` and `[role="dialog"]` are generic.** The page has one of each and
  nothing else, and the test of the page at rest is what keeps it so.
- **A fetch that follows the browser's cookie jar.** The later brief's fetch has to carry
  a session, and how — a cookie read out of the source session's profile, or a download
  driven through the tab — is that brief's to decide. The mock answers either, and
  refuses everything else.
