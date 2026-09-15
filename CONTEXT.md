# dataporter

A tool that migrates a Claude data export into another Claude account by driving the
claude.ai web interface, and the experiment that measures whether that works. The same
tool extracts an account's data — a Claude account's, or a ChatGPT account's — as a
snapshot and keeps it in a store. The words below
are the ones the briefs, slices and documents use; where two words exist for one thing,
the first is the one to use.

## Language

### Documents

**Brief**:
A document that states intent — what is being built and why. Its section numbers are
permanent identifiers, cited as §N, and continue across briefs.
_Avoid_: spec, PRD, requirements document

**Slice**:
One implementation spec, cited as `NN`, sized to be built, tested and reviewed in one
sitting.
_Avoid_: task, subtask, ticket, story

**Spike**:
A time-boxed observation of claude.ai, whose findings are each marked *observed* or
*unknown*.
_Avoid_: proof of concept, PoC

**Experiment**:
The pilot and the full run of the migration against a real destination account.
_Avoid_: trial, rehearsal

**UI map**:
The record of a site's states and the signal each one shows, one map per site, every
row marked *observed on a date* (a person watched, or a trace is cited), *reported*
(documentation or a third party, cited and dated) or *unknown* (nobody looked).
_Avoid_: selectors document

**Report**:
The tool's account of a finished migration: the end-of-migration block (§16) and its
machine-readable twin.
_Avoid_: summary, results

**Rehearsal record**:
The document a complete rehearsal leaves.
_Avoid_: report, write-up, log

### Migration

**Seed**:
The rendered transcript of one source conversation, pasted into a new chat in the
destination account.
_Avoid_: prompt, dump, transcript

**Part**:
One piece of a seed, sent as one message and acknowledged on its own.
_Avoid_: chunk, page

**Acknowledgement token**:
The identifier a part carries so that its acknowledgement can be told from any other
line. The **ack line** is the one-line reply that carries it back.
_Avoid_: ack, confirmation

**Workspace**:
The directory that holds everything one migration writes, beside the export and never
inside it.
_Avoid_: state directory, output directory

**Pause**:
The record a run leaves when a page only a person can clear has stopped it. A pause is
resumed, never restarted.
_Avoid_: halt, block

**Human intervention**:
A pause a person cleared, counted in the report.
_Avoid_: manual step

### Extraction and backup

**Source**:
The vendor an account belongs to — Claude, ChatGPT, Gemini — and the part of the tool
that knows how to read one. The **source account** is the account being read; the
**destination account** is the Claude account being migrated into.
_Avoid_: provider, platform, origin

**Export**:
The vendor's own data export, as the vendor ships it and a person downloads it. The tool
reads one and files one; it never produces one.
_Avoid_: dump, takeout

**Archive**:
The export as a file: the zip the link serves, which a snapshot keeps byte for byte and
the tool reads without unpacking. An export is what the vendor produced; the archive is
the file it came as.
_Avoid_: dump, bundle, the zip

**Extraction**:
Asking a source for an account's export, fetching it from the link the vendor sends, and
filing it as a snapshot. Changes nothing in the account beyond the ask.
_Avoid_: scrape, crawl, pull, sync, download

**Ask**:
The request the tool makes of a vendor for an account's export, remembered until the link
comes back. One is open per account at a time.
_Avoid_: export request, job, ticket

**Fetch**:
Downloading the archive from the link and handing it to the store: without a browser
where the vendor allows it, through the source session where the vendor requires the
download to be made signed in.
_Avoid_: download, pull, grab

**Export page**:
The page where a vendor lets a signed-in user ask for their data. The one page an
extraction acts on, and the one place the tool clicks anything in a source account.
_Avoid_: settings page, data controls, privacy page

**Attestation**:
What a vendor's site requires of a browser to prove it is one — a challenge cleared, a
token its page computed — and which nothing the tool builds can produce. A step behind one
is a step only a person can take.
_Avoid_: CAPTCHA, bot check, proof of work

**Link**:
The single-use address the vendor emails, which a person hands to the tool. Never kept.
The **export link** downloads the archive after an ask; the **sign-in link** — the
vendor's own word is *magic link* — signs the account in, and the tool spends it by
driving the source session to it rather than by fetching it.
_Avoid_: URL, token, download link

**Pending sign-in**:
The state a session is in between the address being given and the sign-in link being
spent: the vendor has been told who is signing in, and the link is on its way.
_Avoid_: half-finished sign-in, login in progress

**Sign-in code**:
The digits the vendor shows when a sign-in link is opened where the pending sign-in is
not, and which finish that sign-in when typed where it is. The second way to spend a
sign-in link.
_Avoid_: code on its own, OTP, verification code, one-time code

**Snapshot**:
The data of one account, from one source, as it stood at one moment, in the vendor's own
shape. Written once, complete on its own, never changed afterwards.
_Avoid_: backup, dump, copy, version

**Gap**:
Something the account holds that the snapshot does not, recorded in the snapshot with the
reason. A snapshot with gaps is complete about its gaps.
_Avoid_: missing item, error, skip

**Stamp**:
The moment an extraction began, which names its snapshot and orders it among the others.
_Avoid_: timestamp, date, version

**Store**:
Where snapshots are kept: a directory on disk today, a bucket later. Never overwrites.
Not the workspace.
_Avoid_: vault, backup directory, repository

**Backup**:
The practice: extracting on a schedule into a store, and importing to restore. Not a thing
the tool writes — what it writes is a snapshot.
_Avoid_: using it for the snapshot itself

**Source session**:
The browser session signed in to a source account, kept apart from the destination's.
_Avoid_: extraction session, second profile

**Account home**:
The directory that holds what the tool keeps about one source account that is not a
snapshot: its session, its open ask, its logs. Never in the store.
_Avoid_: profile directory, session directory

### Browser and agent

**Helper**:
A deterministic move of the tool's own that the agent invokes where exactness matters:
probing, pasting, attaching, awaiting a reply.
_Avoid_: tool, primitive, command

**Probe**:
The helper that reports a page's state without its content.
_Avoid_: snapshot, inspect

**Surface**:
The set of URLs a helper will drive. The migration surface is a new chat and a
conversation on claude.ai; the login surface adds the sign-in page, for the sign-in alone;
the extraction surface is a source site's sign-in page — on every host the sign-in passes
through — and the page where its export is asked for, for the ask alone.
_Avoid_: allowlist, whitelist, scope

**Scripted agent**:
The model-free agent that performs the skill's procedure from a rendered prompt exactly
as written, standing where Hermes and its model stand.
_Avoid_: fake agent, mock Hermes, fake Hermes

### Trace

**Trace**:
The file a run that drives a tab leaves: every move made and every observation the watch
recorded, in order, with what the page showed in outline and never its content. One per
run.
_Avoid_: log, recording, transcript

**Move**:
One helper call as it happened, with the sketch before and after it.
_Avoid_: step, action

**Watch**:
The tool's own session on the tab for the length of a run, recording what the page did
whoever caused it.
_Avoid_: listener, spy, witness

**Observation**:
One thing the page did or showed, recorded by the watch with its moment: a navigation, a
dialog, a request, a certificate. The evidence that turns a UI-map row *observed on
\<date\>*.
_Avoid_: event, entry

**Sketch**:
A page in outline: its URL, its controls by role and label, the shape of everything else.
Never a message, a title or an address.
_Avoid_: snapshot, DOM dump, view

### Test doubles

**Fake world**:
The arrangement that runs the real importer against a fake Chrome, a fake page and a
fake `hermes`, in process.
_Avoid_: harness, sandbox

**Live tier**:
The tests that drive a real Chrome against served fixture pages.
_Avoid_: end-to-end tests, e2e, integration tests, browser tests

**Mock**:
The served stand-in for the whole of a site that behaves on its own, statefully, for a
real Chrome. One per site, named by the site — the mock claude.ai, the mock chatgpt.com —
and all of them one separate project. Every other test double is a *fake*, scripted by
the test that uses it.
_Avoid_: fake site, simulator, emulator, stub server, the Claude mock, the ChatGPT mock

**Rehearsal**:
A protocol — the full run's, or an extraction's — run by the shipped tool against a site's
mock, with the scripted agent standing where Hermes stands wherever the protocol needs
one. No model, no account.
_Avoid_: dry run, test run, smoke test, e2e

**Rehearsal export**:
The synthetic export a rehearsal migrates.
_Avoid_: fixture export, sample export

**Ledger**:
The mock's own count of what it was asked to do — sign-ins, chats created, messages
received, files accepted, renames, exports requested.
_Avoid_: log, stats, metrics
