# mocks

Served stand-ins for whole sites, for **rehearsing** against: the shipped tool,
unchanged, driven through its protocol by a real Chrome, on a machine with no
account and no model. Two sites today, and one project (brief `05` §53,
[ADR 0007](../docs/adr/0007-the-mocks-are-one-project.md)):

- **the mock claude.ai** — `claude-mock`, on `127.0.0.1:8443`. Brief `02`'s (§21):
  the site a migration is rehearsed into, and since `32` a source an extraction is
  rehearsed from.
- **the mock chatgpt.com** — `chatgpt-mock`, on `127.0.0.1:8444`. Brief `05`'s
  (§54): built *ahead* of the tool's ChatGPT half, out of what OpenAI documents and
  what others have reported, so that half meets a sign-in on two host names, a
  composer that turns a long paste into an attachment, and a download that wants a
  session, before it meets the real ones. The tool's ChatGPT half (brief `06`) drives
  it since 2026-09-14 — `docs/rehearsal-03.md` is the record — and [the walk](#the-walk)
  below is what a person takes through it by hand.

What the two share — a certificate minted for a site's host names and a key Chrome
is told to trust, a session that survives the browser closing, the witness routes
the tool never drives, the ledger and its block, the reachability block, the
obedient reply, a link minted instead of an email — is `mockcore`, a package
neither site owns. Each site is a package beside it: its pages, its paths, its
selectors, its archive, its citations of its UI map.

Each behaves on its own. It is not scripted per run, there is no model behind it,
and nothing in it knows what a rehearsal is doing. What it knows is how to be a
site: sign somebody in, take a message, answer it, keep the chat at a URL that
survives a reload, accept a file, take a new name for a chat, take an ask for the
account's export and hand out a link instead of an email.

> This is a **separate project** that lives in this repository for now. It
> imports nothing from `dataporter` and `dataporter` imports nothing from it;
> moving it out is a directory move ([ADR
> 0003](../docs/adr/0003-the-mock-is-a-separate-project.md)), and the mocks leave
> together.

## Run it

```sh
uv run --package mocks claude-mock serve
uv run --package mocks chatgpt-mock serve
```

Each prints the one thing you need in order to reach it — nobody composes a
resolver rule by hand. The mock claude.ai:

```text
Mock claude.ai listening on https://127.0.0.1:8443

Add to <workspace>/config.toml before running the tool:

[browser]
extra_args = [
  "--host-resolver-rules=MAP claude.ai 127.0.0.1:8443",
  "--ignore-certificate-errors-spki-list=AbCdEf0123456789AbCdEf0123456789AbCdEf0123456789=",
]

Set in the tool's environment before fetching an export link from it:

  SSL_CERT_FILE=/home/you/.cache/claude-mock/claude-mock.pem

```

The mock chatgpt.com answers two names, because OpenAI documents that signing in
passes through `auth.openai.com` as well as `chatgpt.com`, so its rule maps both
and its certificate names both; and its block has no `SSL_CERT_FILE` line, because
the tool cannot fetch its export link at all (below):

```text
Mock chatgpt.com listening on https://127.0.0.1:8444

Add to <workspace>/config.toml before running the tool:

[browser]
extra_args = [
  "--host-resolver-rules=MAP chatgpt.com 127.0.0.1:8444, MAP auth.openai.com 127.0.0.1:8444",
  "--ignore-certificate-errors-spki-list=ZyXwVu9876543210ZyXwVu9876543210ZyXwVu9876543210=",
]

```

On a machine whose environment names a proxy — `https_proxy` and friends, which
Chrome reads on Linux — each mock prints a note, because a proxy resolves the host
name itself and the resolver rule would never fire. `"--no-proxy-server"` in the
same list is the answer for Chrome, and for the mock claude.ai `no_proxy=127.0.0.1`
beside `SSL_CERT_FILE` is the answer for the tool's own fetch of an export link,
which reads the same proxy.

The tool then reaches a mock the way any operator's configuration reaches
anything: Chrome maps the host names, and trusts **this key and no other**. There
is no flag, no environment variable and no host setting in the tool that names a
mock ([ADR 0001](../docs/adr/0001-no-door-in-the-wall.md)). Each mock keeps its
key under `~/.cache/<command>/` between runs, so a pin written into a config keeps
working after a restart; delete the directory and the next start mints a new key
and prints a new pin.

The credentials are invented and configured here. Both mocks default to
`rehearsal@example.invalid` and `rehearsal-not-a-real-password`; `--email` and
`--password` change them. Exactly that pair signs in, and any other is refused, so
a wrong credential fails a run rather than passing it.

### Two mocks at once

A rehearsal that extracts from one site and migrates into another needs both mocks
up in one Chrome, and Chrome keeps **one value per argument**: two
`--host-resolver-rules` in one list and the second silently wins. Merge the two
blocks by hand — every `MAP` into one rule, comma-separated, and both pins into one
list, comma-separated:

```toml
[browser]
extra_args = [
  "--host-resolver-rules=MAP claude.ai 127.0.0.1:8443, MAP chatgpt.com 127.0.0.1:8444, MAP auth.openai.com 127.0.0.1:8444",
  "--ignore-certificate-errors-spki-list=AbCdEf0123456789AbCdEf0123456789AbCdEf0123456789=,ZyXwVu9876543210ZyXwVu9876543210ZyXwVu9876543210=",
]
```

A printed merged block is left for the day a rehearsal needs one (§58).

## Ask it for an export

Both mocks serve the page where the site lets a user ask for their data, and, having
no inbox to email, print the link in their own terminal and list it for any other:

```sh
uv run --package mocks claude-mock exports       # one link per line, oldest first
uv run --package mocks chatgpt-mock exports
```

The archive a link downloads is the mock's own chats, rendered in the site's own
export shape at the moment of the fetch — so a run can migrate into a mock and then
extract what it migrated. One ask mints one link, at once; a second ask adds a
second link, so two extractions file two snapshots. A link lives until the process
stops, and a link nobody asked for is `404`. Here the two sites part:

- **The mock claude.ai's link needs no session** (brief 03 §35). It is an address
  on the mock's own host and port, under `/__mock/`, and the tool fetches it with
  Python rather than with Chrome — which is why the block also names the
  certificate to trust, and why on any other `--host` the tool cannot fetch a link
  and `serve` says so. Both moves of an extraction, end to end, with no account:

  ```sh
  export DATAPORTER_AUTH__EMAIL=rehearsal@example.invalid
  export DATAPORTER_AUTH__PASSWORD=rehearsal-not-a-real-password
  dataporter --non-interactive login --account mock          # the source session
  dataporter --non-interactive extract --account mock         # the ask; the mock prints the link
  LINK=$(uv run --package mocks claude-mock exports | tail -n 1)
  SSL_CERT_FILE=~/.cache/claude-mock/claude-mock.pem no_proxy=127.0.0.1 \
    dataporter extract --account mock --link "$LINK"          # the fetch; a snapshot is filed
  dataporter snapshots
  ```

  An unattended `login` needs a `hermes` on the path for the sign-in, which is
  `24`'s agent half; `rehearsal/` writes a model-free one. Interactively, the
  window is open and you sign in yourself.

- **The mock chatgpt.com's link wants a session.** OpenAI documents that the
  export must be downloaded "while you are signed in to the same account that
  requested it", and the mock mirrors it: the link is
  `https://chatgpt.com/__mock/exports/<token>.zip` — on the site's host, where the
  browser's session cookie is — and the archive is served to the signed-in session
  and refused with `403` to anyone else. Open the link in the signed-in Chrome and
  the zip downloads; open it in a window with no session, or fetch it with `curl`
  at the mock's address, and it is refused. The listing of links stays open: it
  stands in for the inbox, and the inbox is not the account. The tool's fetch,
  which downloads without a browser, cannot fetch it; that is the fact the tool's
  ChatGPT half has to meet, and it meets it here first (§54).

## Ask it what it did

```sh
uv run --package mocks claude-mock ledger
uv run --package mocks chatgpt-mock ledger
```

```text
Mock chatgpt.com — ledger

Sign-ins:                      2
Chats created:                 8
Messages received:            11
Files accepted:                2
Renames:                       8
Exports requested:             1

```

This is the witness. Nothing in the tool can tell a rehearsal from a real run, so
the mock is the only party that can say what really happened on the other side of
the wire — and a rehearsal record whose numbers do not reconcile with these is not a
rehearsal (§25). The same six counts for every site, under a heading that names it,
because two mocks running at once keep two ledgers. The numbers are printed when the
process is stopped, and served as JSON at `/__mock/ledger.json` on each mock's own
host and port.

## Reading a trace

Every run of the tool that drives a tab leaves a **trace**, `logs/trace-<ts>.jsonl`
beside its run log (the tool's brief `04`), and a trace of a run against a real site is
what its mock is corrected against. A mock reads one the way a person does — as a file,
in the shape the brief describes — and imports nothing from the tool that wrote it (ADR
0003). Four kinds of line:

- **`header`**, the first line: the command, the source and host, the tool, browser and
  agent versions, and the browser's arguments. A trace of a *mock* shows the resolver
  rule that points the site's names at it in `chrome_arguments`, and the certificate
  line below shows an issuer equal to its subject, since a mock signs its own; a trace of
  the real site shows neither.
- **`sketch`**: a page in outline. Its `controls` — a button, a text box, a dialog, a
  status region, each by role and label — are the labels the mock's pages should carry;
  everything else is a role, a count and a length. Its `selectors` object says how many
  elements each of the tool's own selectors found on the real page, by the constant's
  name, which is the middle column of the UI map counted for real: a `0` where the mock's
  markup would give `1` is a row to correct, in the map first and then in the site's
  `pages.py`.
- **`move`**: one helper call, with the sketch before and after it by hash and what the
  helper printed. The sequence of moves is the procedure the mock is driven through.
- **`observation`**: what the page did on its own — a `navigation`, a `url_changed`
  after the first submit, a `dialog_opened` by type, a `request` and its `response` by
  method, path, status, type, size and timing, the `certificate`, a tab appearing. The
  requests are the traffic a page script should make and the pace it should make it at;
  the URL change is the moment `history.replaceState` should fire.

A row of a UI map corrected from a trace cites it by file and line, and a line of a
site's `uimap.WHAT_THE_MOCK_DOES` may name the same citation. The traces of a rehearsal
against a mock are the baseline — `docs/rehearsal-NN.md` lists them — and are never
committed as evidence about the site.

## What it does, and why

Every state a mock can show is a row of its UI map —
[`docs/claude-ui-map.md`](../docs/claude-ui-map.md) for the one,
[`docs/chatgpt-ui-map.md`](../docs/chatgpt-ui-map.md) for the other — and `rows`
prints each row beside what the mock decided it meant:

```sh
uv run --package mocks claude-mock rows
uv run --package mocks chatgpt-mock rows
```

The Claude map's rows are the tool's own guesses, every one *unknown*; the ChatGPT
map's come from what OpenAI documents and what others have reported, marked
*reported* with the source and *unknown* where nobody has looked. Where a row is
*unknown*, the mock takes the simplest behaviour the shape admits and says that it
did. A behaviour a mock needs and its map has no row for is added to the map first.
**A mock run never turns a row *observed***: only a person watching the real site
does that, or reading a trace of a run against it, and a rehearsal or a walk is not
evidence about the site (§27, §56).

The behaviours both mocks have, and worth knowing before you read the code:

- **Obedient.** A migration seed ends by asking the model to reply with exactly one
  line. The mock finds that line and replies with exactly it — after a non-zero
  delay, growing in at least two steps, so that "the reply stopped growing" is
  something a rehearsal really waits for. A message that asks for no particular
  line gets one canned sentence. The seed is the tool's own, so this is the core's.
- **Chats.** A submit creates a chat with its own id and URL; reloading that URL
  shows every turn; a rename survives a reload; a file input takes a file and shows
  it by name.
- **An export page.** A control, a confirmation, and a status region that appears
  only once the ask has been counted and a link minted.
- **In memory.** State lives for as long as the process does, so a run in several
  sessions sees the same chats throughout. Restarting resets it.

### `claude-mock`

- **Two-step sign-in.** A banner that hides the form until it is dismissed once,
  buttons for other providers and a passkey that lead nowhere, then the email step
  and the password step.
- **The chat's own menu** carries the title and renames it.
- **The export page** at the tool's placeholder path, with the tool's placeholder
  selectors, all of them *unknown*; the link on the mock's own address, behind no
  session.

### `chatgpt-mock`

- **Sign-in on two hosts.** A landing page at the root with a **Log in** control
  and a **Sign up** that leads nowhere useful; **Log in** goes to
  `https://auth.openai.com/log-in`, where the email step and the password step each
  have a **Continue**, and **Continue with Google**, **Microsoft** and **Apple**
  lead nowhere useful; a right pair comes back to `chatgpt.com` with a one-time code
  that becomes the session. No banner: no source reports one. The auth host's
  screens are *unknown* and the mock's are the simplest shape.
- **One send-and-stop control.** `button[data-testid="send-button"]` with
  **Send prompt** becomes `data-testid="stop-button"` with **Stop streaming** while
  the reply is being written — one element that changes what it is called — and a
  **Copy response** control appears on a finished turn, so that "the reply stopped
  growing" is not the only signal.
- **A long paste becomes an attachment.** Any insertion that would take the
  composer past 10,000 characters — a paste, or text the browser protocol inserts —
  becomes a chip reading **Pasted text** with a **Show in text field** button that
  puts it back. Stricter than the site can be and never laxer; the reply reads the
  chip's text too, so a seed sent as a chip gets the line it asked for.
- **The rename is in the sidebar.** The chat's entry, `#history
  a[aria-label="<title>"]`, has an options button, `[data-testid=
  "history-item-N-options"]`, opening a menu with **Rename**; then an
  `input[aria-label="Chat title"]` that confirms on Enter and cancels on Escape.
- **The export page** is **Settings** → **Data controls** → **Export** →
  **Confirm export** → a status; the link is on the site's host and wants a
  session.

## The walk

The tool's own run through this mock is `rehearsal/run.py --protocol extraction`
(brief `06`, `46`); the walk is the same trip taken by a person with a Chrome, which is
how the mock was proven before the tool could drive it (§56). Start it, add its two
lines to a Chrome — a throwaway profile is enough:

```sh
uv run --package mocks chatgpt-mock serve
chromium --user-data-dir=/tmp/walk \
  '--host-resolver-rules=MAP chatgpt.com 127.0.0.1:8444, MAP auth.openai.com 127.0.0.1:8444' \
  --ignore-certificate-errors-spki-list=<the pin it printed> \
  --no-proxy-server https://chatgpt.com/
```

and walk it, checking each signal against [the map](../docs/chatgpt-ui-map.md):

1. **Land.** `https://chatgpt.com/` is a page with a **Log in** button and a **Sign
   up** button. Any other address — `https://chatgpt.com/c/anything` — comes back
   here.
2. **Sign in, and be refused.** **Log in** takes you to
   `https://auth.openai.com/log-in`: an email field and **Continue**, and the three
   providers. Enter `rehearsal@example.invalid`, then a wrong password: you are back
   at the email step with an alert. Enter the right pair: you are on
   `https://chatgpt.com/` with a composer, a sidebar, a **New chat** link and a
   profile button.
3. **Create a chat and watch the reply grow.** Type a line and press Enter. The
   address becomes `https://chatgpt.com/c/<uuid>`, your turn is on the page as a
   `user` turn, the one control now reads **Stop streaming**, and the reply appears
   after a moment and grows. When it is whole the control reads **Send prompt**
   again and the turn carries **Copy response**. A message that asks for no
   particular line gets one canned sentence. Reload: every turn is still there.
4. **Paste past the threshold and put the text back.** Open **New chat** and paste
   more than 10,000 characters — a seed, with `Reply with exactly one line:` and the
   line under it at its foot. The text does not land in the composer: a chip
   reading **Pasted text** appears beside it with a **Show in text field** button.
   Press it: the text is in the composer, byte for byte, and the chip is gone.
   Paste again and press Enter: the reply is exactly the line the seed asked for.
5. **Rename.** In the sidebar, the chat's entry has an options button (**…**); it
   opens a menu of **Share**, **Rename**, **Archive**, **Delete**. **Rename** shows a
   field labelled **Chat title**; type a name and press Enter (Escape cancels). The
   entry and the tab title carry the name, and still do after a reload.
6. **Upload.** Press **Add files and more** (the **+**) and choose a file. A chip
   with its name appears beside the composer; send a message, and after a reload
   the file's name is on the turn that carried it.
7. **Ask for the export.** The profile button opens a menu with **Settings**;
   **Settings** lists **Data controls**; that page has the **Improve the model for
   everyone** switch and, under **Export data**, an **Export** button. Press it: a
   dialog with **Confirm export**. Press that: a status appears saying the export
   was requested — and the mock's terminal prints the link where an email would
   have arrived.
8. **Fetch the link signed in, and be refused signed out.** Open the printed link in
   this window: a zip downloads, holding `conversations.json` and `user.json` — your
   chats, in the export's shape, the renamed title and the file's name among them.
   Open the same link in a window with no session (`chromium --incognito`, the same
   arguments), or `curl -k https://127.0.0.1:8444/__mock/exports/<token>.zip`: `403`.
   `chatgpt-mock exports` lists the link to anyone.
9. **Read the ledger.** `chatgpt-mock ledger`: one sign-in (the refused one is not
   one), your chats, your messages, one file, one rename, one export requested. Stop
   the mock (Ctrl-C) and it prints the same block on the way out.

A walk that sees every signal proves the mock serves its map. It is not evidence
about chatgpt.com, and it turns no row *observed* (§56).

## What it cannot do yet

Named so that a later slice can claim them (§21, §28, §57, §58). On either site: a
rate limit, a login expiry mid-run, a modal or a JavaScript dialog in the way, a
generation error, a CAPTCHA or security challenge, a code prompt at sign-in; on the
export page, a link that expires, an export already requested and still processing,
a rate limit on asking, and an email — a mock has no clock a link could die on and no
inbox to send to. On the mock chatgpt.com besides: the composer as the site serves it
after its redesign of September 2026, which is the highest-risk *reported* row on its
map; the auth host's real screens and chain; the zip's file name; the confirmation
screen's words; interim assistant messages before the answer; an archive split over
several conversation files, and the members that carry media. And a printed
reachability block for every running mock at once.

## Tests

```sh
uv run --package mocks pytest mock
```

One suite, named by owner: `test_core_*.py` for what the sites share, and
`test_claude_*.py` and `test_chatgpt_*.py` for each site. They cover the behaviour
(each `site.py`) without a socket, each archive with `zipfile` and `json` and nothing
of the tool's, the wire (each `server.py`, a FastAPI application served by uvicorn)
over a real TLS connection to a real port, and the citations against the maps. What
they cannot cover is a real Chrome running a page's own script: that is what a
rehearsal is, and for the mock chatgpt.com, the walk.

## Layout

```text
mock/
├── pyproject.toml          the distribution `mocks`: two commands, one dependency set
├── README.md               this file
├── src/
│   ├── mockcore/           what the sites share: certificate, ledger, reply, sessions,
│   │                       exports, wire, cli — and knows no site
│   ├── claudemock/         the mock claude.ai: site, pages, server, archive, uimap, cli
│   └── chatgptmock/        the mock chatgpt.com: the same six, its own
└── tests/                  one suite, prefixed by owner
```
