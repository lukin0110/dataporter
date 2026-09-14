# Extraction from ChatGPT

**Brief 06.** Section numbers continue from [`05-chatgpt-mock.md`](05-chatgpt-mock.md),
which ends at §58, so that `§N` names exactly one section anywhere in this repository. The
words used here are defined in [`CONTEXT.md`](../CONTEXT.md).

## 59. Goal

Give the tool its **ChatGPT half**, as extraction only: a second source beside Claude that
signs in to a ChatGPT account, asks on its export page, fetches the archive the way the
vendor requires — signed in — and files a snapshot in ChatGPT's own shape into the same
store, listed by the same command. Brief 03 said a second source is another source and not
a second tool (§29, §34); this brief is where that is made true, and the making of it is
one object per vendor that the store, the commands and the trace know nothing of.

```text
ChatGPT account
      │
      │ extract: ask, on chatgpt.com          ─┐
      ▼                                        │ the source session:
   an email ──── the person ──── a link        │ one browser profile,
      │                                        │ two host names
      │ extract: fetch, signed in, and file   ─┘
      ▼
  Snapshot ──────────► Store  (<store>/chatgpt/<account>/<stamp>/)

```

Nothing migrates. A ChatGPT snapshot is a backup and not yet a restore: `import` and
`inspect` refuse it with the reason, because each source needs its own importer before its
snapshots can be restored, and a snapshot of a source the tool cannot import is still a
backup ([ADR 0005](../docs/adr/0005-snapshots-are-vendor-native.md)). A ChatGPT importer,
and ChatGPT as a destination, are each a later brief (§71).

The half is built against the mock chatgpt.com (§52) from its first slice and rehearsed
against it before any account is touched, which is what brief 05 built the mock for. It
claims §58's first item, §40's "ChatGPT … as sources", and §51's "ChatGPT and Gemini: their
sites, their selectors, and the trace unchanged"; its first tool-driven run is what turns
slices `39`–`41` `Done` under §56.

## 60. The ChatGPT source

§34 says what a source knows: how to sign in, where the vendor lets a user ask for their
data, what the archive that comes back looks like, and what the account holds that the
archive does not. This brief makes that one object per vendor — its name and how it is
spelled in a block, the hosts its session touches, its sign-in page and the shape of its
sign-in, its export page and the two clicks that ask on it, whether its link can be fetched
without a session, the sentences its ask block prints, and how its archive is recognised,
counted and found wanting. Claude moves onto the same object and prints every byte it
printed before; ChatGPT is a second object beside it, and Gemini will be a third. The
store, the manifest, `snapshots`, `login` and `extract` do not change when a source lands.

The ask is §31's, unchanged in shape:

```bash
dataporter login --source chatgpt --account work
dataporter extract --source chatgpt --account work

```

```text
ChatGPT extraction — work

Export requested 2026-09-30 18:12 UTC.
ChatGPT will email or text a download link to the account's address.
It can take up to 7 days. When it arrives:

  dataporter extract --source chatgpt --account work --link <url>

```

The two sentences in the middle are the vendor's own: OpenAI documents that the link
arrives by email or text message and that an export can take up to seven days (help
article 7260999), and a person reading the block should know what they are waiting for.
Claude's block keeps its one sentence. The block is golden (`specs/README.md`), as brief
03's blocks are.

## 61. The sign-in on two hosts

Signing in to chatgpt.com passes through `auth.openai.com` (§54, help article 7426629).
The source session's profile holds both hosts, the surface admits both, and a trace of a
sign-in shows the second host in its observations (§67).

Interactively the tool opens the window and waits for the person, as it does for Claude
(§35). Unattended it signs in **itself, deterministically, with no model**: the landing
page's **Log in** control, the auth host's email step and its **Continue**, the password
step and its **Continue**, the return to the site signed in. A page that is not the shape
expected — a code prompt, a challenge, a CAPTCHA, a landing page with no **Log in** — stops
the run with exit `3` and the `login` instruction, which is §12's answer for a step only a
person can take. No Hermes is on this path: a backup is a cron job, and a cron job that
needs an agent and an API key is a backup people stop running. Claude's unattended sign-in
keeps `24`'s shape; whether it should take this one is a later question.

Every control the tool looks for is the tool's own spelling of a row of
[`docs/chatgpt-ui-map.md`](../docs/chatgpt-ui-map.md), typed on the tool's side of
[ADR 0003](../docs/adr/0003-the-mock-is-a-separate-project.md)'s line and never imported
from the mock. The auth host's real screens are *unknown*; the shape above is the mock's,
which is the documented shape and the simplest one, and the first real sign-in is what
corrects it.

## 62. The export page and the ask

The tool navigates straight to the Data controls page at a path spelled once in the
source — the mock serves it at `/settings/data-controls`, and the real path is *unknown* —
presses **Export**, presses **Confirm export** in the dialog that opens, and waits for the
page to say the export was requested (help article 7260999). Then `ask.json`, then the
block. One ask is open per account at a time, as §31 says, and the stamp is the moment of
the press, as §33 says. The documented route — the profile menu, **Settings**, **Data
controls** — is not walked: it is three more controls nobody has observed, and a wrong path
is one string to correct the day a trace shows the real one (§71).

## 63. The fetch through the session

Brief 03 §35 says the fetch needs no session, and that is true of Claude and false of
ChatGPT: the download must be made signed in to the account that asked for it (help
article 7260999, §54). **§35 is amended by this section**: it holds for a source whose
vendor allows the download, and a source whose vendor requires the session fetches through
it. The Claude fetch is unchanged. The one that follows is ChatGPT's.

```bash
dataporter extract --source chatgpt --account work --link 'https://…'

```

The tool opens the source session, makes sure it is signed in — interactively the window
and the wait, unattended the credentials and the sign-in of §61, exactly as the ask does —
and then **points the tab at the link**. The browser makes the download, the tool catches
it as it lands, and from there the fetch is §31's: the bytes are checked to be an export
of this source, filed as a snapshot, and the block printed. The session's cookie never
leaves the browser: the tool does not read the profile's cookie jar, does not carry a
cookie into a request of its own, and never learns what the cookie is. Rejected: lifting
the cookie out of the profile for a browserless download, which would make the tool hold a
credential §32 says a snapshot must never contain and §35 says the tool never sees.

```text
ChatGPT extraction — work

Downloaded 12.4 MB.
Conversations: 88     Files: 12
Gaps: 3 files the export does not carry

Snapshot: ~/.dataporter/store/chatgpt/work/2026-09-30T18-12-44Z

```

A link that is refused, that leads to a page instead of an archive — which is what a
signed-out download looks like — or that stalls, is refused with the reason and the ask
stays open, as §31 says. Unattended, the credentials are required before the browser
starts, as the ask requires them (`31`): a fetch that would stop at a sign-in form after
following the link has spent a link that may be single-use.

## 64. The archive, counts and gaps

The tool **recognises and counts** a ChatGPT archive and does not model it. What it reads
is what [`docs/chatgpt-export-format.md`](../docs/chatgpt-export-format.md) says, every
line of which is *assumed*: `user.json`, an object; `conversations.json`, an array of
conversation objects each with a `mapping`, or the numbered `conversations-NNN.json` files
a large export is split into. The fourteen content types, the branches and the hidden
messages are the importer's to read, in the brief that reads them. Reading less is the
point: a reader that pinned fourteen assumed payload shapes before anyone had opened a real
export would be fourteen guesses a snapshot depended on.

The block's count line is the source's own. Claude counts conversations, projects and
memories; ChatGPT counts conversations and **files**, the members the archive carries that
are not JSON documents and not the rendering for a person — the attachment bytes a 2026
export is reported to ship, which Claude's does not.

**Gaps.** One kind: an attachment a message refers to whose bytes no member carries, with
§31's reason. Nothing else is claimed missing, because nobody has looked at what a ChatGPT
account holds beyond its chats; `docs/LIMITATIONS.md` says so. The mock chatgpt.com carries
no bytes at all (§55), so a snapshot of it has a gap for every file a chat accepted, which
is the mock's gap and not the export's.

A Claude archive handed to `--source chatgpt` is refused naming what it looks like, and the
reverse: two sources with the same member name and different shapes are told apart by
shape, before anything is filed.

The snapshot's fingerprint is the SHA-256 over the conversation members in name order — one
member, one hash, which is Claude's rule; several, one hash over all of them in the order
their names sort.

## 65. Safety boundaries

§36 holds word for word. The **ChatGPT extraction surface** is: on `chatgpt.com`, the root
`/`, the sign-in's own paths, and the export page; on `auth.openai.com`, every path,
because that host serves nothing but the sign-in and its real paths are unknown. Nothing
else on either host, and no other host. `/settings` alone and every `/c/<id>` are outside
it.

The root is admitted because it has to be: a signed-out request for any page lands there,
the sign-in's return lands there, and `login` opens there. It is the site's new-chat page,
and admitting it does not contradict §36: a chat is created by a submit, and nothing on
this surface ever makes one. The only synthesized inputs on the whole of it are the
credential fields on the auth host and three clicks — **Log in**, **Export**, **Confirm
export**.

The fetch has a wall of its own: the link the person handed over, and wherever the vendor
redirects it, every hop recorded (§66). The tool navigates to the string it was given and
clicks nothing; "is this a ChatGPT export" is asked of the bytes after they have landed, as
it is for Claude. Rejected: admitting only the site's own hosts, which would refuse the
first real fetch the moment the vendor served its archive from a storage host nobody here
has seen, for a reason only a trace could show.

## 66. The trace and the link

The link is a credential to the archive while it lives (§32), and §46 keeps it out of the
run log by name. A fetch that drives a tab leaves a trace (§43), and the watch records
every navigation with its URL — which for a download link is the credential itself, in the
path. So, beside §46: **while a fetch is in progress, a trace carries hosts and never
paths**. The navigation to the link, every redirect hop and every request the page makes
are recorded as the host and a marker for the rest — never the path, never the query — and
the writer refuses a path written by anyone while the fetch runs, under the same guard that
refuses the link in a log record. The download itself is recorded, as a move of the
tool's own: the host it came from, its size, and the length and suffix of the name the
vendor gave it, never the name, which may carry the account's address.

## 67. Tracing parity

A ChatGPT `login`, ask and fetch leave **the same trace a Claude run does** — the header,
the moves, the sketches before and after each, the watch's observations, the certificate,
and the account home's `actions.jsonl` — in the shape brief 04 gives every source (§50).
The header names the source `chatgpt` and the host `chatgpt.com`; a navigation to or a
request on the auth host names that host; each host's certificate is recorded once. This is
a requirement and not a consequence, because those traces are the evidence: the first real
run's trace is what turns a row of `docs/chatgpt-ui-map.md` *observed* (§49), and the
diff between what the mock served and what the site showed is what corrects the mock.

## 68. The rehearsal

Nothing rehearses extraction today, for either source; slice `32` was walked by hand. This
brief adds an **extraction protocol** to the rehearsal (§22, §26), parametrised by source
and run by the shipped tool against each site's mock: the runner seeds the mock's account
through the mock's own chat API — a few chats, one upload — then `login`, an ask, the link
read from the mock's listing where the inbox would be, the fetch, a second ask and a second
fetch, `snapshots`; then the reconciliation of the tool's numbers with the ledger's
(`Exports requested`, the chats, the files), the traces gathered from the account home, and
a record. The pass criteria are §39's questions where a mock can answer them: two snapshots
from two asks, the first byte-identical after the second, the counts the ledger's, the
link in no file the run left. No scripted agent is needed, because §61's sign-in needs no
agent. The glossary's **rehearsal** widens to say so: a protocol, the full run's or an
extraction's.

The run against the mock chatgpt.com is what §56 lends `39`–`41` for their live criterion,
and the run against the mock claude.ai is the first `30` and `31` have had.

## 69. First run

Before an account that matters, a throwaway ChatGPT account, and §39's six questions asked
of it — plus the ones this source adds, each answered with a number or an observation in
`docs/extraction-02.md`, in `docs/extraction-01.md`'s discipline:

7. Does the real link need the session — would a browserless fetch have been refused?
8. What is the redirect chain from the emailed link to the bytes, host by host?
9. What is the zip's file name, by length and suffix?
10. Where is the Data controls page — a path, a dialog, a hash route — and is it the shape
    the mock serves?
11. What does the auth host show, step by step, and does §61's walk get through it?
12. How long did the export take to arrive, against the documented "up to 7 days"?
13. What does the site show when an export is already requested, and when a link has
    expired?

Only after these are answered does extraction run against a ChatGPT account that matters,
and only then do the rows of `docs/chatgpt-ui-map.md` this brief stands on turn *observed*.

## 70. What is never printed or written

The rules of §10, §26 and §38 hold. The link is in no trace under any field (§66). The auth
host's pages are sketched by role and label, never by what a field holds. A credential
typed into the auth host is a CDP parameter and never part of an expression, as `24` made
it. Nothing the tool writes about a ChatGPT account carries an email address, a title or a
line of a conversation; the archive carries them because that is its purpose.

## 71. Later

Named so that a later brief or slice can claim them:

- the documented route to the export page — the profile menu, **Settings**, **Data
  controls** — the day a trace shows the direct path is not one;
- reading the inbox, for an extraction that needs no person at all (§40);
- a ChatGPT importer: reading the archive's shape into the migration, the active path and
  what is off it, the fourteen content types;
- ChatGPT as a destination (§58);
- Claude's unattended sign-in in §61's shape, without an agent;
- the mock gemini.google.com and the tool's Gemini half;
- the 24-hour expiry and the "already requested" state, in the mock and in the tool;
- a fetch that lifts the session's cookie for a browserless download — rejected in §63 and
  named here so that nobody reopens it silently;
- a normalised view derived from a ChatGPT snapshot (§40).
