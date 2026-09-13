# The mock chatgpt.com

**Brief 05.** Section numbers continue from [`04-trace.md`](04-trace.md), which ends at
§51, so that `§N` names exactly one section anywhere in this repository. The words used
here are defined in [`CONTEXT.md`](../CONTEXT.md).

## 52. Goal

Build a **mock chatgpt.com** — a served stand-in for the whole of that site, as the mock
claude.ai (§21) is for its own — so that the tool's ChatGPT half, when it is written, is
built against a stateful site from its first slice and rehearsed against it before any
real account is touched.

The tool has no ChatGPT half today. Extraction from ChatGPT, and later migration into a
ChatGPT account, are each a brief of their own and not yet written (§34, §40, §51). This
brief comes first, on purpose. The mock claude.ai was built *after* the tool it stands in
for, out of the guesses the tool had already made about a site nobody had watched, and a
rehearsal against it can only prove the tool agrees with itself. The mock chatgpt.com is
built *ahead* of its driver, out of what OpenAI documents and what others have reported,
so that the driver's first slice meets a sign-in on two host names, a composer that turns
a long paste into an attachment, and a download that wants a session — before it meets
the real ones.

```text
the tool's ChatGPT half (later)             scripted agent (later)
        │                                            │
        └───────────────── Chrome ───────────────────┘
                              │
                              │  https://chatgpt.com      →  127.0.0.1
                              │  https://auth.openai.com  →  127.0.0.1
                              ▼
                      the mock chatgpt.com
                              │
                              ▼
                           ledger

```

It is the whole site: sign-in, chats, a reply, a rename, an upload, the export page, a
link and an archive. It stands ready as a **source** — the site an extraction asks — and
as a **destination** — the site a migration pastes into — although no brief migrates into
ChatGPT yet: §1 and §50 say a migration's destination is a Claude account, and this brief
does not change that. It serves the destination surface ahead of any brief that uses it,
because the chat surface is the half the mock claude.ai already has, and a mock that was
only an export page would be re-founded the day ChatGPT becomes a destination.

It is not evidence about chatgpt.com — §27 applies word for word — it involves no model
and no account, and it changes nothing in the tool: `--source chatgpt` is refused today
and is refused after this brief.

## 53. One project, many mocks

The mock claude.ai is a separate project (ADR
[0003](../docs/adr/0003-the-mock-is-a-separate-project.md)): its own project file,
dependencies, tests and README, inside this repository for now, importing nothing from
the tool. The mock chatgpt.com is not a second such project beside it. It is a second
**site** in the same project, and the project becomes the home of every mock — Gemini's
after this one.

What the two share is more than what divides them: a certificate minted for a host name
and a key Chrome is told to trust; a session that survives the browser closing; the
witness routes the tool never drives; the ledger and its block; the reachability block
that tells the operator how to reach it; the obedient reply that finds the one line a
seed asks for and answers with exactly it, in steps; a link minted instead of an email.
That half becomes a **core** neither site owns, and each site is a package of its own
beside it: its pages, its paths, its selectors, its archive, its citations of its UI map.
One project file, one test run, one distribution — renamed, since it is no longer
Claude's alone — and one command per site:

```sh
claude-mock serve
chatgpt-mock serve

```

ADR 0003 stands: the project imports nothing from the tool, the tool imports nothing from
it, and moving it to its own repository is still one directory move — the mocks leave
together. What changes is that a helper wanted by two mocks is promoted to the core
rather than duplicated, which is the ADR's own consequence.
*(ADR [0007](../docs/adr/0007-the-mocks-are-one-project.md).)*

## 54. The mock chatgpt.com

The mock stands in for the whole of chatgpt.com and behaves on its own. It is not
scripted per run, and there is no model behind it.

### Obedient

As §21: a seed asks for exactly one line, the mock finds that line and replies with
exactly it, after a configurable non-zero delay and growing in at least two steps; a
message that asks for no line gets one canned sentence. The seed is the tool's own, and a
seed written for a ChatGPT destination will ask the same way, so the reply is the core's
and not this site's.

### Governed by its UI map

Every state the mock can show is a row of
[`docs/chatgpt-ui-map.md`](../docs/chatgpt-ui-map.md), and the mock cites the row. It
invents nothing. Unlike the Claude map, whose rows were the tool's own guesses, this
map's rows come from what OpenAI documents about its site and what others have reported
of it, and the marks say which. A row is marked one of three ways:

- ***observed on \<date\>*** — a person watched the site do it, or read it in a trace of a
  run against the site and cites the trace (§49);
- ***reported (source, \<date\>)*** — OpenAI's own documentation, or a third party who
  looked, cited by address and dated. Better than a guess and not an observation;
- ***unknown*** — nobody has looked, and the mock takes the simplest behaviour and says
  so.

A mock run never turns a *reported* or an *unknown* row *observed*. A behaviour the mock
needs and the map has no row for is added to the map first, marked *reported* if a source
says so and *unknown* if none does.

### Sign-in

OpenAI documents that signing in passes through `auth.openai.com` as well as
`chatgpt.com` (help article 7426629). The mock answers both names: one resolver rule
sends both to it, its certificate names both, and the sign-in pages are served under the
auth host, at paths the slice picks and the map marks *unknown*, because what those pages
look like has not been observed by anyone whose account of it can be cited.

The shape is the one the unattended sign-in (§8, `24`) was written to get past: a landing
page with a **Log in** control; then the email step and the password step, each with a
**Continue** control; **Continue with Google**, **Microsoft** and **Apple** controls that
lead nowhere useful. Exactly one configured email and password pair signs in; any other is
refused, so a wrong credential fails a run rather than passing it. There is no banner to
dismiss, because no source reports one and the mock invents nothing.

### Chats

A submit creates a chat with its own id and URL, and reloading that URL shows every turn.
The site's reported shape, which the map records with its sources:

- one control sends a message and, while the reply is being written, stops it — one
  element that changes what it is called, not two;
- every turn carries its author's role, and a copy control appears on a turn that is
  finished, so that "the reply stopped growing" is not the only signal a tool has;
- the rename affordance is in the chat's own entry in the sidebar: an options menu with a
  rename item, then a titled field that takes the new name and confirms on Enter. The
  renamed title survives a reload;
- a file control accepts a file and shows it by name.

**A long paste becomes an attachment.** OpenAI documents (release notes of 2026-06-22 and
2026-08-04, help article 6825453) that more than 10,000 characters pasted into the
composer become an attachment, with a **Show in text field** control that puts the text
back, on every plan. A seed is several times that. The mock applies the rule to *any*
insertion that takes the composer past the threshold, serves the attachment and the
control, and the map marks the threshold *reported* and the trigger — a paste, or text the
browser protocol inserts — *unknown*. Stricter than the site can be and never laxer: a
tool that handles the attachment here handles either outcome there, and a mock that hid
the rule would let a seed step ship untested against the one documented behaviour that
breaks it.

### The export page

OpenAI documents the ask (help article 7260999): the profile menu, **Settings**, **Data
controls**, and under **Export data** an **Export** control; a confirmation screen with a
**Confirm export** control; then an email or text message carrying a **Download data
export** link, which expires 24 hours after it is received and must be opened signed in to
the same account. The mock serves that page and that flow — the control, the confirmation,
a status that appears only once the ask has been counted — and, having no inbox, prints
the link in its own terminal and lists it, as the mock claude.ai does (§40, `32`).

**The download wants a session.** Brief 03 §35 says the fetch needs no session, and that
is true of Claude. OpenAI's documentation says it is not true of ChatGPT. The mock mirrors
the documentation: the archive is served to the signed-in session and refused to anyone
else, while the listing of links stays open — it stands in for the inbox, and the inbox is
not the account. The tool's fetch, which downloads without a browser, cannot fetch it.
That is the fact the later brief has to meet, and it meets it here first. Brief 03 is not
amended by this one.

One ask mints one link, at once, and a second ask adds a second link, so that two
extractions can file two snapshots (§39). The site's own states around an ask — an export
already requested and still processing, a link that has expired — need a clock the mock
does not have, and are named in §58.

### The ledger

The same six counts as the mock claude.ai's, under a heading that names the site:

```text
Mock chatgpt.com — ledger

Sign-ins:                      2
Chats created:                 8
Messages received:            11
Files accepted:                2
Renames:                       8
Exports requested:             1

```

The ledger is the witness a rehearsal record reconciles against (§25), and it is this
site's alone: two mocks running at once keep two ledgers.

### Reachability

As §21: on start the mock prints the exact lines an operator adds to the workspace's
browser configuration, and those lines send both host names to the mock and trust the
mock's own key and no other. It listens on a port of its own beside the mock claude.ai's,
keeps a certificate of its own, and serves its ledger and its links at the same witness
paths on its own host and port. The marks of §47 hold unchanged: a trace of a run against
this mock shows both names in the resolver rule and a certificate that signed itself.

**Two mocks at once.** A rehearsal that extracts from one site and migrates into another
needs both mocks up in one Chrome. Chrome keeps one value per argument, so the two
reachability blocks cannot be pasted side by side: the operator merges them into one rule
and one list of keys. Each mock prints its own block, the project's README says how the
two are merged, and a printed merged block is left for a later slice (§58) — the day a
rehearsal needs it is the day the later brief runs one.

### Lifetime

A separate process the operator starts, as Chrome is. State lives in memory for as long as
the process runs; restarting it resets it.

## 55. The archive

The archive the link serves is in ChatGPT's own shape (§32, ADR
[0005](../docs/adr/0005-snapshots-are-vendor-native.md)), rendered from the mock's chats
at the moment of the fetch, so that a run can migrate into the mock and then extract what
it migrated.

OpenAI publishes no description of that shape. What is known of it is what independent
readers of real exports agree on, and every claim about it is *assumed* until a real
export has been read.
[`docs/chatgpt-export-format.md`](../docs/chatgpt-export-format.md), in the discipline of
[`docs/export-format.md`](../docs/export-format.md), is the one place the shape is
written down, and the mock's archive is rendered from what it says. The day a real export
is read, that document changes first and the mock follows.

The archive holds the two members the shape cannot do without — the conversations, and
the account they belong to — and nothing else: an empty member would claim a feature the
mock does not have. The rest of the reported inventory is listed in the format document,
assumed and unwritten. A file a chat accepted is named on the message that carried it and
its bytes are carried nowhere, which is the one gap this archive has (§31). Finished
turns only, never the prefix of a reply still being revealed; the same chats render the
same bytes.

## 56. Built ahead of its driver

None of this mock exists today: the brief is intent, and its slices are carved after it.
And nothing in the tool drives chatgpt.com, so no rehearsal can run against the mock
until the later brief's slices exist. Until then the mock is proven by two things:

- its own suite — the behaviour without a socket, the wire over a real TLS connection to
  a real port, the archive read back with nothing of the tool's;
- a person with a Chrome, following a walk the project's README writes down: point Chrome
  at it, sign in and be refused with a wrong password, create a chat and watch the reply
  grow, paste past the threshold and put the text back, rename, upload, ask for the
  export, fetch the link signed in and be refused signed out, read the ledger.

A slice of this brief reaches `Built` when its suite passes. It reaches `Done` when the
first tool-driven run has walked it — which is the later brief's to make, and is said so
in the slice rather than left implied. The mock is not evidence about chatgpt.com, and a
walk of it turns no row of its map *observed*.

The rules of §10, §26 and §38 hold. The credentials are invented and configured into the
mock. No real account is signed in to, no real export is read, and nothing the mock prints
carries a message, a title or an address.

## 57. What is sure and what is not

What this brief's slices are to build, and on what ground. None of it exists yet: the
brief is intent, and its slices are carved after it.

| Behaviour | Ground | Who builds it |
| --- | --- | --- |
| The core and the project shape (§53) | the mock claude.ai, `26`–`32` | a slice of this brief |
| Sign-in on two host names | documented (7426629) | a slice of this brief |
| The sign-in screens and their fields | *unknown* | a slice of this brief, in the simplest shape |
| A new chat at the root, a conversation at its own URL | reported | a slice of this brief |
| A composer with a stable id, one send-and-stop control, turns by role, a copy control on a finished turn | reported | a slice of this brief |
| A paste over 10,000 characters becomes an attachment, with **Show in text field** | documented (6825453) | a slice of this brief |
| Rename through the sidebar entry's options menu into a titled field | reported | a slice of this brief |
| Upload through a file control, shown by name | reported | a slice of this brief |
| The export page and its flow: **Export**, **Confirm export**, a status | documented (7260999) | a slice of this brief |
| A link instead of an email; the archive behind a session | documented (7260999) | a slice of this brief |
| The archive's shape | assumed (`docs/chatgpt-export-format.md`) | a slice of this brief |
| The ledger, reachability, lifetime | §21 | a slice of this brief |

What this brief names and builds nothing for, because nobody has looked or the mock has
no clock — each an *unknown* or a *reported* row served by nothing, and each on §58's
list: the composer's shape after the site's redesign of September 2026, which is the
highest-risk *reported* row on the map; the auth host's screens and fields; the file name
of the zip; the confirmation screen's words; the "already requested" state; the 24-hour
expiry; a rate limit; interim assistant messages before the answer; an export split over
several conversation files; the members that carry media.

## 58. Later

Named so that a later brief or slice can claim them:

- the tool's ChatGPT half — a source, its sign-in, its ask and a fetch that carries a
  session (§34, §40) — and, after it, ChatGPT as a destination: each its own brief;
- a rehearsal against this mock, and the record it leaves (§26);
- the composer as the site now serves it, the day a trace of a run against chatgpt.com
  shows it (§49);
- the sign-in screens on the auth host, the same way;
- an export already requested and still processing; a link that expires; a rate limit;
  a generation error; a modal or a JavaScript dialog in the way; a CAPTCHA or a security
  challenge; a code prompt at sign-in — the failure states on cue, as §28 names them for
  the other mock;
- interim assistant messages before the answer, so that "the reply stopped growing" can
  be wrong for the reason it is wrong on the site;
- an archive split over several conversation files, and the members that carry media;
- a printed reachability block for every running mock at once;
- reading a real ChatGPT export, so that the format document's claims turn *observed*;
- the mock gemini.google.com, a third site in the same project;
- anything the map has no row for.
