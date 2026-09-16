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

What the two share — the wire they are served on, a session that survives the
browser closing, the witness routes the tool never drives, the ledger and its
block, the reachability block, the obedient reply, a link minted instead of an
email — is `mockcore`, a package
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

Each prints where it is. Reaching it is a flag on the tool and nothing else:

```text
Mock claude.ai listening on http://127.0.0.1:8443

Run the tool with --mock to reach it: dataporter --mock login --account <label>

```

```text
Mock chatgpt.com listening on http://127.0.0.1:8444

Run the tool with --mock to reach it: dataporter --mock login --account <label>

```

**Plain HTTP on loopback, and no certificate anywhere.** Until `65` a mock served
TLS *as* the site it stands in for, because the tool refused every URL that was not
`https://` on the real host and had to be steered from outside — a resolver rule
mapping the name, an SPKI pin trusting one key, and a `[browser] extra_args` table
an operator pasted into a `config.toml`
([ADR 0001](../docs/adr/0001-no-door-in-the-wall.md)). `--mock` replaces all of it
([ADR 0010](../docs/adr/0010-the-mock-is-reached-by-a-flag.md)): it changes the
tool's **origin** and nothing else, and Chrome treats `http://127.0.0.1` as a
trustworthy origin, so no page behaves differently for the loss.

The mock chatgpt.com answers on **two ports**: `8444` for the site and `8445` for
the auth origin, because OpenAI documents that signing in passes through
`auth.openai.com` as well as `chatgpt.com`. It used to be one socket told apart by
the `Host` header the resolver rule supplied; with no rule there is no name to
route on, so the second origin is a second socket. Only the first is printed — a
sign-in reaches the other by a redirect and nothing else.

The tool is pointed at a mock by `--mock` and by nothing else: not
`DATAPORTER_MOCK`, not `config.toml`. The two walls are disjoint, so a command that
forgot the flag refuses the mock and one that was given it by mistake refuses the
real site; and what a mock run writes goes to `~/.dataporter/mock/` and
`./migration-mock`, apart from anything real.

The credentials are invented and configured here. Both mocks default to
`rehearsal@example.invalid` and `rehearsal-not-a-real-password`; `--email` and
`--password` change them. On the mock chatgpt.com exactly that pair signs in, and
any other is refused, so a wrong credential fails a run rather than passing it.
The mock claude.ai takes the address alone and ignores `--password`: claude.ai has
no password sign-in (the tool's brief `07`), and neither does its mock.

## Sign in to the mock claude.ai

The mock claude.ai signs people in by link (`49`, brief `07` §79), as the real site
does. The address step mints a sign-in link — `http://127.0.0.1:8443/magic-link#<token>:…`,
the token in the fragment, as the real one is — and, having no inbox to send it to,
prints it in its own terminal and lists it for any other:

```sh
uv run --package mocks claude-mock sign-in-links    # one link per line, oldest first
```

After the address the page shows the controls the real one showed on 2026-09-15
(`docs/spike/claude-sign-in-link-sent.html`): a code field, a **Verify email
address** button, **Try sending it again** and **Change email address**. The link,
opened in the browser that gave the address, signs it in once and lands on `/new`;
opened anywhere else, or twice, it signs nobody in and leaves that browser at the
code page — the one shape the tool recognises for *a link opened elsewhere*. No
code is ever minted: the code door is deferred (§80). The tool's two commands, end
to end, with no account and no `--non-interactive` — a Claude sign-in has none:

```sh
dataporter login --account mock &                   # the window; it waits for the link
LINK=$(uv run --package mocks claude-mock sign-in-links | tail -n 1)
dataporter login --account mock --link "$LINK"      # spends it in that window
wait                                                # the first command ends signed in
```

The pending sign-in survives the browser closing: its cookie lives an hour, so a
`login --link` run after the window has gone still finds the sign-in it finishes.

### Two mocks at once

Nothing to merge since `65`. Start both; each is on its own port and the tool finds
whichever its `--source` names:

```sh
uv run --package mocks claude-mock serve      # 8443
uv run --package mocks chatgpt-mock serve     # 8444, and 8445 for the auth origin
```

This used to be the awkward part. Chrome keeps **one value per argument**, so two
`--host-resolver-rules` in one `extra_args` list meant the second silently won, and
an operator running both mocks had to merge every `MAP` into one rule and both SPKI
pins into one list by hand. There is no rule and no pin now.

## Ask it for an export

Both mocks serve the page where the site lets a user ask for their data, and, having
no inbox to email, print the link in their own terminal and list it for any other:

```sh
uv run --package mocks claude-mock exports       # one link per line, oldest first
uv run --package mocks chatgpt-mock exports
```

What a link serves is the mock's own chats, rendered in the site's own export shape
at the moment of the fetch — so a run can migrate into a mock and then extract what
it migrated. One ask mints one link, at once; a second ask adds a second link, so
two extractions file two snapshots. A link lives until the process stops, and a link
nobody asked for is `404`.

**Both links want the session.** OpenAI documents that a ChatGPT export must be
downloaded "while you are signed in to the same account that requested it", and a
real Claude link, minutes old and well inside its day, answered `403` to a request
without one. So each link is on its own site's host — where the browser's cookie is
— and the tool points the source session's tab at it. Open a link in the signed-in
Chrome and the file downloads; open it where there is no session and it is the
sign-in page. The *listing* of links stays open: it stands in for the inbox, and the
inbox is not the account.

Where the two sites part is what the link serves.

- **The mock chatgpt.com's link is the archive.** One zip at
  `http://127.0.0.1:8444/__mock/exports/<token>.zip`, fetched as often as you like.

- **The mock claude.ai's link is an index.** `http://127.0.0.1:8443/__mock/exports/<token>`
  serves a `manifest.json` in the vendor's shape — `instructions`, `created_at`,
  `total_files`, `data_files[]`, `version` — naming one zip per *category*:

  ```text
  light_metadata-000.zip    users.json
  conversations-000.zip     conversations.json      ← the one an importer reads
  ```

  Each is at an address of its own, under the account rather than under the index,
  and **may be fetched once**: the second time is `404`. The manifest says so about
  its own files, in its own words, on every real export — so a fetch retried against
  the same link fails here exactly as it does on the real site.

Both moves of an extraction, end to end, with no account:

```sh
#   the source session: the two sign-in commands above, first
dataporter --non-interactive extract --account mock   # the ask; the mock prints the link
LINK=$(uv run --package mocks claude-mock exports | tail -n 1)
dataporter extract --account mock --link "$LINK"      # the fetch; a snapshot is filed
dataporter snapshots
```

The sign-in itself is never unattended (brief `07` §76): `login` opens the window and
waits, and `login --link` spends the link in it. A rehearsal has no person at that
window, so `rehearsal/` plays one — it enters the address over the debug port and
reads the link where the inbox would be.

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
Sign-in links minted:          0

```

This is the witness. The tool can tell a rehearsal from a real run since `65` — it
was given `--mock` — but it still only knows what it *tried* to do, so the mock
remains the only party that can say what really happened on the other side of the
wire — and a rehearsal record whose numbers do not reconcile with these is not a
rehearsal (§25). The same seven counts for every site, under a heading that names
it, because two mocks running at once keep two ledgers; the seventh is a sign-in
link minted where an email would go, which only the mock claude.ai does. The
numbers are printed when the process is stopped, and served as JSON at
`/__mock/ledger.json` on each mock's own host and port.

## Reading a trace

Every run of the tool that drives a tab leaves a **trace**, `logs/trace-<ts>.jsonl`
beside its run log (the tool's brief `04`), and a trace of a run against a real site is
what its mock is corrected against. A mock reads one the way a person does — as a file,
in the shape the brief describes — and imports nothing from the tool that wrote it (ADR
0003). Four kinds of line:

- **`header`**, the first line: the command, the source and host, the tool, browser and
  agent versions, and the browser's arguments. A trace of a *mock* names `127.0.0.1`
  as its host, which is the point: it says so by its own contents, so it can never be
  mistaken for evidence about the real site. There is no `certificate` line at all,
  because there is no TLS (`65`); a trace of
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
  method, path, status, type, size and timing, a tab appearing. The
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
- **An export page.** A control, a confirmation, and an answer that appears only
  once the ask has been counted and a link minted.
- **In memory.** State lives for as long as the process does, so a run in several
  sessions sees the same chats throughout. Restarting resets it.

### `claude-mock`

- **Sign-in by link.** A banner that hides the form until it is dismissed once,
  buttons for other providers and a passkey that lead nowhere, then the email step
  — and no password step, because claude.ai has none. The address mints a link,
  printed and listed instead of mailed; the page then shows the real site's
  link-sent controls, the one row of the Claude map that is *observed*; the link
  signs in the browser that asked, once, at `/magic-link`, whose own script reads
  the token off the fragment and posts it back.
- **The chat's own menu** carries the title and renames it.
- **The settings panel**, not a page: claude.ai asks for an export from a dialog
  over the app, at `/new#settings/data-privacy-controls`. A fragment never reaches a
  server, so the panel is markup on the chat page and the page's own script opens it
  on the address, with the composer and the file input behind it. Six rows offer a
  button and the Export row is the first *visible* one — the first of the six is
  there and not shown, so that a click helper which did not filter by visibility
  would press the wrong thing. The Export row moves the address to
  `…/export-data` and a second screen replaces the first, carrying the confirmation
  and a `Conversations from` period the ask never touches. Confirming answers `202`
  and raises a toast reading exactly `Export started`. Every one of those rows is
  still *unknown*: they are a person's reading of one account on one day.
- **A session that can lapse.** `POST /__mock/expire-session` throws every session
  away; the browser keeps its cookie and the site stops knowing it, so the next page
  it asks for answers `/logout?involuntary&returnTo=…` and then the sign-in page —
  the two hops a real account took, in
  [`docs/spike/traces/login-2026-09-15.jsonl`](../docs/spike/traces/login-2026-09-15.jsonl).
  Nothing the tool drives can ask for it, because an expiry is something that
  happens *to* a run.

### `chatgpt-mock`

- **Sign-in on two hosts.** A landing page at the root with a **Log in** control
  and a **Sign up** that leads nowhere useful; **Log in** goes to
  `http://127.0.0.1:8445/log-in`, where the email step and the password step each
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
how the mock was proven before the tool could drive it (§56). Start it and point a
Chrome at its address — a throwaway profile is enough, and nothing else is needed
since `65`:

```sh
uv run --package mocks chatgpt-mock serve
chromium --user-data-dir=/tmp/walk http://127.0.0.1:8444/
```

and walk it, checking each signal against [the map](../docs/chatgpt-ui-map.md):

1. **Land.** `http://127.0.0.1:8444/` is a page with a **Log in** button and a **Sign
   up** button. Any other address — `http://127.0.0.1:8444/c/anything` — comes back
   here.
2. **Sign in, and be refused.** **Log in** takes you to
   `http://127.0.0.1:8445/log-in`: an email field and **Continue**, and the three
   providers. Enter `rehearsal@example.invalid`, then a wrong password: you are back
   at the email step with an alert. Enter the right pair: you are on
   `http://127.0.0.1:8444/` with a composer, a sidebar, a **New chat** link and a
   profile button.
3. **Create a chat and watch the reply grow.** Type a line and press Enter. The
   address becomes `http://127.0.0.1:8444/c/<uuid>`, your turn is on the page as a
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

Named so that a later slice can claim them (§21, §28, §57, §58). `64` claimed one of
them: the mock claude.ai can now show a login expiry mid-run, on request. What is
left, on either site: a rate limit, a modal or a JavaScript dialog in the way, a
generation error, a CAPTCHA or security challenge, a code prompt at sign-in; on the
export page, a link that expires, an export already requested and still processing,
a rate limit on asking, and an email — a mock has no clock a link could die on and no
inbox to send to. Nor does either panel render *late*: a real one was measured
appearing about 2.9 s after the navigation and the mock's is there at once, so the
wait `62` built is not exercised here. On the mock chatgpt.com besides: the composer as the site serves it
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
│   ├── mockcore/           what the sites share: ledger, reply, sessions, exports,
│   │                       wire, cli — and knows no site
│   ├── claudemock/         the mock claude.ai: site, pages, server, archive, uimap, cli
│   └── chatgptmock/        the mock chatgpt.com: the same six, its own
└── tests/                  one suite, prefixed by owner
```
