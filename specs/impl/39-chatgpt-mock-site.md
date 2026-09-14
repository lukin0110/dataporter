# 39 — The mock chatgpt.com: sign-in and chats

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 05](../05-chatgpt-mock.md) §54 (*Obedient*, *Governed by its UI
map*, *Sign-in*, *Chats*, *The ledger*, *Reachability*, *Lifetime*), §57 (the rows it
builds), and §52 as the goal
**Depends on:** [38](38-mock-core.md), [`docs/chatgpt-ui-map.md`](../../docs/chatgpt-ui-map.md)
**Enables:** [40](40-chatgpt-export-and-archive.md), [41](41-chatgpt-mock-walk.md)
**Status:** Done

## Goal

The second site: a served stand-in for chatgpt.com that a real Chrome can be pointed at
under two host names. It signs somebody in through `auth.openai.com`, takes a message,
answers it, keeps the chat at a URL that survives a reload, turns a long paste into an
attachment, accepts a file, renames a chat through its sidebar entry, and counts what it
was asked to do. It is a consequence of `docs/chatgpt-ui-map.md` and no evidence about
chatgpt.com (§52, §27). Built ahead of its driver: the tool's ChatGPT half (brief `06`)
drives it since 2026-09-14, and `--source chatgpt` is a source since `43`.

## In scope

- **The package** (`mock/src/chatgptmock/`, new): `PROGRAM_NAME = "chatgpt-mock"`,
  `SITE_HOST = "chatgpt.com"`, `AUTH_HOST = "auth.openai.com"`, `DEFAULT_PORT = 8444`,
  `IDENTITY`, and `SITE_ORIGIN`/`AUTH_ORIGIN` — how a page on one host names the other.
- **`site.py`** — the behaviour, no HTTP in it. `PASTE_THRESHOLD = 10_000`;
  `Upload(name, size)`; `Message(role, text, pasted, files)` with `content` — the pasted
  texts, then the typed text — being what a reply reads; `Chat(id, created_at, title,
  messages, reply)` with `view(now)` and `generating(now)`; `Site` with the core's
  `Sessions`, `Exports`, `answer` and `Ledger(IDENTITY.heading)`: `credentials_match`,
  `sign_in` (counts), `signed_in`, `sign_out`, `chat`, `create_chat(text, *, pasted,
  session)` (a version-4 UUID, counts), `receive(chat, text, *, pasted, session)` (the
  files waiting in the composer for that session ride on this message; counts),
  `stop(chat)` (what the page shows becomes the finished turn; not counted),
  `rename` (counts), `sidebar()` (newest first), `accept_file(name, size, *, session)`
  (counts), `pending`, `all_chats` (oldest first), `chat_ids`, `counters`, and `40`'s
  three export methods.
- **`pages.py`** — the markup, selector for selector out of the map's middle column:
  - the landing page at `/`: `button[data-testid="login-button"]` **Log in**, going to
    `https://auth.openai.com/log-in`, and a **Sign up** that goes to the unsupported page;
  - the auth host's pages at paths this slice picked, `/log-in`, `/log-in/email`,
    `/log-in/password`, `/log-in/unsupported`: a visible `input[type="email"]` and a
    **Continue** `button[type="submit"]`, then a visible `input[type="password"]` and
    **Continue**; **Continue with Google**, **Microsoft** and **Apple** buttons that go
    to the unsupported page; a `[role="alert"]` when refused; no banner;
  - the chat page at `/` (signed in) and `/c/<uuid>`: a sidebar with
    `a[data-testid="create-new-chat-button"][href="/"]`, `#history` holding one `<li
    data-chat-id>` per chat, newest first, each with `a[href="/c/<id>"][aria-label=
    "<title>"]`, `button[data-testid="history-item-N-options"]` served visible, a
    `[role="menu"]` of **Share**, **Rename**, **Archive**, **Delete** `[role="menuitem"]`s
    and an `input[aria-label="Chat title"]`; `[data-testid="profile-button"]` with a menu
    holding **Settings**; a `#thread` of `div[data-message-author-role="user"]` (text in
    `.whitespace-pre-wrap`, a pasted text as a `[data-testid="pasted-text-attachment"]`
    chip inside it, a file as a chip by name) and `…="assistant"` (text in `.markdown`, a
    `button[data-testid="copy-turn-action-button"][aria-label="Copy response"]` on a
    finished one); `div#prompt-textarea[contenteditable="true"]`, ProseMirror-shaped;
    `button[data-testid="composer-plus-btn"][aria-label="Add files and more"]` in front
    of a hidden `input[type="file"]`; `#attachments`; and one
    `button#composer-submit-button`, `data-testid="send-button"` with `aria-label`
    **Send prompt** (disabled while nothing is typed, pasted or attached) or
    `data-testid="stop-button"` with **Stop streaming** while generating;
  - the page script: it renders the human turn synchronously on Enter, posts to the API,
    puts the chat's URL in place with `history.replaceState`, inserts the sidebar entry
    at the top and renumbers, polls every 250 ms while generating and swaps the one
    control's `data-testid` and `aria-label`; **a `beforeinput` whose `insertText` or
    `insertFromPaste` would take the composer past the threshold becomes a chip** with a
    **Show in text field** button that appends the text back and removes the chip; a
    submit sends `{text, pasted}`; the plus button clicks the file input, a chosen file
    is posted to `/api/uploads` and its chip grows once the mock has taken the bytes;
    the options button toggles the menu, **Rename** shows the field with the title in
    it, Enter posts the new title (an empty one is not sent), Escape hides the field,
    and the entry's `aria-label`, link text and the document title follow.
- **`server.py`** — one FastAPI application for both hosts, the routes paths alone:
  the core's witness; `GET /` (landing signed out, new chat signed in); `GET /auth/login`
  → `303` to the auth host's `/log-in`; `GET /auth/callback?code=` (a code `Pending`
  holds → the session cookie and `303 /`; any other → `303` to the auth host with
  `?error=refused`); `GET /log-in`, `POST /log-in/email`, `POST /log-in/password` (a
  right pair → `303` to `https://chatgpt.com/auth/callback?code=<one-time>`; a wrong one
  → back to the email step), `GET /log-in/unsupported`; behind the session, `GET
  /c/{id}`, `GET /api/chats/{id}`, `POST /api/chats` (`{text, pasted}`), `POST
  /api/chats/{id}/messages`, `POST /api/chats/{id}/stop`, `POST /api/chats/{id}/title`,
  `POST /api/uploads` (`X-File-Name`, the body read and dropped, its length kept); the
  catch-all is `404` signed in and `303 /` signed out, like every other path.
  `serve(site, *, port, host, material, announce)` on the core's server.
- **`uimap.py`** — `ROWS` and `WHAT_THE_MOCK_DOES` for the twenty-nine rows the mock
  stands on, including the rows it serves *nothing* for and says so (`cookie banner`,
  `interim assistant messages`, `already requested`, `link expired`).
- **`cli.py`** — `chatgpt-mock serve|ledger|exports|rows` on the core's parser, port
  `8444`, the same default pair as `claude-mock`'s. The block, `39`'s golden string:

  ```text
  Mock chatgpt.com listening on https://127.0.0.1:8444

  Add to <workspace>/config.toml before running the tool:

  [browser]
  extra_args = [
    "--host-resolver-rules=MAP chatgpt.com 127.0.0.1:8444, MAP auth.openai.com 127.0.0.1:8444",
    "--ignore-certificate-errors-spki-list=<pin>",
  ]

  ```

  and the ledger block under `Mock chatgpt.com — ledger`. The proxy note names both
  hosts. No `SSL_CERT_FILE` line and no host note: the tool cannot fetch this site's
  link (`40`).
- **Tests**: `test_chatgpt_site.py` (growth, the reply reading the pasted text, the
  canned sentence, stop, one pair, sessions, the six counts under the site's heading, a
  file on the message the session sends next and not another session's, sidebar order,
  rename, the threshold), `test_chatgpt_server.py` (the landing page, every other path
  `303 /`, `/auth/login` to the auth host, both steps and their refusals, the code coming
  back and spent once, the new chat page's controls, a chat at its URL surviving a
  reload with the control and the copy button flipping, a pasted text apart from the
  typed text, a second message, stop, a rename in the sidebar and the title, entries
  numbered newest first, an upload on the next message, the refusals, the ledger),
  `test_chatgpt_cli.py` (the block byte for byte, the note, the refusals, the defaults,
  `exports` and `ledger` against a running mock, the link announced, `rows`),
  `test_chatgpt_uimap.py` (every cited row is in `docs/chatgpt-ui-map.md`, none of them
  is marked *observed*, every cited row has its line).

## Out of scope

- The export page, the link, the archive and the session the download wants:
  [40](40-chatgpt-export-and-archive.md).
- The README's walk and the two-mock merge: [41](41-chatgpt-mock-walk.md).
- The composer as the site serves it after September 2026, the auth host's real screens,
  a code prompt, a CAPTCHA, a rate limit, a generation error, interim assistant messages,
  memory: §57's list and §58's. `uimap.py` names the ones the mock serves nothing for.
- A `dataporter` change of any kind: `--source chatgpt` is refused before and after.

## Design notes

- **Two hosts, one application, and a code between them.** The mock has to answer as
  both names because OpenAI says the sign-in passes through `auth.openai.com`
  (7426629), and a session cookie set on one host is not sent to the other. The simplest
  chain that works in a real browser is an OAuth-shaped one: the auth host's password
  step redirects to `https://chatgpt.com/auth/callback?code=…`, and the site host turns
  the one-time code into its own cookie. The map marks the chain *unknown*, and
  `WHAT_THE_MOCK_DOES` says this is the simplest shape, not a claim. Rejected: one host
  with the auth paths on it (the row says two names, and a driver that met one here would
  meet two there); a cookie domain wide enough for both (`openai.com` and `chatgpt.com`
  share no suffix).
- **The routes are paths alone.** The application does not read the `Host` header:
  the auth paths are ones the site host never serves and the site paths ones the auth
  host never serves, so a request to either name gets the right page, and the tests can
  walk the whole sign-in against `127.0.0.1` by asserting the cross-host `Location` and
  then asking for its path. Rejected: a host-routing middleware (a second thing to be
  wrong about, for a distinction no page depends on).
- **The threshold rule is the page's; the site sees the result.** Whether text the
  browser protocol inserts counts as a paste is *unknown*, so the page applies the rule
  to `insertText` and `insertFromPaste` alike — stricter than the site can be and never
  laxer (§54) — and posts the pasted texts apart from the typed text. The site keeps
  them apart on the message, because the archive (`40`) writes them as parts and the
  reply has to read the seed's footer wherever it landed. Rejected: joining them into
  one text on arrival (the archive would then lie about what was typed).
- **Stop stops.** A control that says **Stop streaming** and did nothing would be a
  state the map does not describe; the mock's stop makes what the page shows the
  finished turn, which is what stopping a reply leaves in an account. Not counted: the
  six counts are what a site is *asked to do*, and stopping asks nothing new.
- **A file belongs to the message that carried it,** because that is where the export
  names it (`docs/chatgpt-export-format.md`) — on the mock claude.ai a file belongs to
  the chat, because that is where `32`'s archive names it. Two shapes, two sites.
- **The sidebar is newest first and the options button is visible.** The position in
  `history-item-N-options` is the entry's position in the list, so a new chat is `0`
  and the script renumbers. The real button appears on hover; a hover is not a state a
  map row names, and the mock serves the button visible and says so.
- **The default pair is the mock claude.ai's.** An operator with both mocks up has one
  thing to remember, and the pair is invalid by construction either way.

## Acceptance criteria

- `uv run --package mocks pytest mock` is green; `chatgpt-mock rows` names only rows
  that exist in `docs/chatgpt-ui-map.md`, none marked *observed*.
- `chatgpt-mock serve` prints the block above with a real pin; a Chrome given those two
  arguments loads `https://chatgpt.com/` from the mock and `https://auth.openai.com/log-in`
  from the same mock, over a certificate naming both.
- The configured pair signs in through the auth host and back; any other pair does not;
  `chatgpt-mock ledger` then reports one sign-in.
- A submit creates a chat with a `/c/<uuid>` URL, the one control reads **Stop
  streaming** and then **Send prompt** again, the reply appears in at least two steps and
  is exactly the line the seed asked for, a copy control appears on the finished turn,
  and reloading the URL shows every turn.
- An insertion past 10,000 characters becomes a chip with **Show in text field**, the
  composer stays empty, the button puts the text back byte for byte, and a seed sent as
  a chip gets the line it asked for.
- A renamed chat still has its new name in the sidebar and the document title after a
  reload; a file put into the file input is counted, shown by name, and is on the message
  that carried it after a reload.
- *(Live, the later brief's.)* The first run of the tool's ChatGPT half against this mock
  walks it; that brief's slice records it, and that is what turns this slice `Done` (§56).

The first six were met on 2026-09-13: the first by the suite, the other five by a real
headless Chromium (Playwright's build 1194) driven through the resolver rule and the
pin — 26 checks, every one passed, the ledger closing at 1 sign-in, 2 chats, 3 messages,
1 file, 1 rename, 1 export requested after the `40` steps of the same walk. That is a
walk, not a run: it turns no row *observed* and does not make the slice `Done`.
  Met on 2026-09-14: the extraction rehearsal (`46`, [`docs/rehearsal-03.md`](../../docs/rehearsal-03.md)) signed in through the walk on both host names, twice; `Done`.

## Risks

- **The composer is the map's highest-risk row.** `#prompt-textarea` is reported gone
  since September 2026 and its replacement described by nobody. The mock serves the
  shape before the redesign because that is the only shape anyone has written down; the
  day a trace of a run against chatgpt.com shows the new one, the map changes first and
  `pages.py` follows (§58).
- **The sign-in is a guess dressed as a flow.** Every part of it the map marks *unknown*
  — the paths, the fields' shapes, the chain — is the simplest thing that works, and a
  driver written against it will meet something else on the real auth host. What limits
  the damage is that the driver is written against the map, not against the mock, and
  the map says *unknown* where it does.
- **The threshold is applied to insertions no real paste makes.** A seed inserted in two
  halves of 6,000 characters would become a chip here and might not there. Stricter, by
  design; a tool that handles the chip handles both.
