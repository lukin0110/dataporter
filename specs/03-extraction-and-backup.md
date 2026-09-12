# Extraction and backup

**Brief 03.** Section numbers continue from [`02-claude-mock.md`](02-claude-mock.md),
which ends at §28, so that `§N` names exactly one section anywhere in this repository. The
words used here are defined in [`CONTEXT.md`](../CONTEXT.md).

## 29. Goal

Make the tool able to **take data out** of an account as well as put it in, and make what
it takes out a **backup**: a record of an account as it stood at one moment, kept where it
can never be overwritten, and from which the account can be rebuilt with the migration
the first brief describes.

The first brief starts at a file: the export a person has already requested from
claude.ai, waited for, and downloaded. This brief starts one step earlier, at the account
itself, and takes over the steps around the one a person still has to do: the tool asks
the vendor for the export, the vendor emails the person a link, the person hands the link
to the tool, and the tool downloads it and files it where it can never be overwritten. It
also stops assuming the account is a Claude one. The tool will extract from ChatGPT,
Gemini and others, and what it writes is shaped so that a second source is another source
and not a second tool.

```text
Account A (Claude, ChatGPT, Gemini, …)
      │
      │ extract: ask the vendor
      ▼
   an email ──── the person ──── a link
                                   │
      ┌────────────────────────────┘
      │ extract: fetch and file
      ▼
  Snapshot ──────────► Store  (disk today, cloud later)
      │
      │ import
      ▼
Account B (Claude)

```

Two verbs, two commands, no path between them that runs both. `extract` writes a
snapshot and stops. `import` reads a snapshot, or an export, and migrates it. A person who
only wants a backup never migrates; a person who only wants to migrate never extracts.
Nothing happens "in one go".

## 30. Two concerns, kept apart

**Extraction** answers: *what is in this account right now?* It signs in to an account,
asks the vendor for the account's export, and files what comes back. It changes nothing
in the account beyond that one request. It knows nothing about migration, seeds, or a
destination.

**Import** answers: *how does this get into that account?* It is what the first brief
describes, unchanged. It reads a snapshot the way it reads an export today, and it does
not care which extraction produced it or when.

The two share one thing: the shape of what one writes and the other reads. That shape is
the vendor's own (§32), so the boundary between them is the vendor's data and nothing of
ours.

A backup system is the two of them and a clock. The tool provides `extract`, a store
that never overwrites, and `import` as the restore. The clock is the operator's: a cron,
a launchd job, a habit. The tool does not schedule itself, does not prune, does not
encrypt. Each of those is a later decision (§40), not a missing feature.

## 31. Extract

The vendor's own data export is the mechanism. It is the artefact the vendor stands
behind, the one `import` already reads, and the one whose shape a second source also
has: ChatGPT and Gemini each email a link to an archive too. The tool does not read the
account through its pages or call a backend of its own; §2 applies to extraction as it
applies to import.

The export arrives in two moves with a person between them, because the vendor puts an
inbox there. The tool automates the two moves and not the inbox.

### The ask

```bash
dataporter extract --source claude --account old-personal

```

The tool signs in to the source account (§35), goes to where the vendor lets a user ask
for their data, and asks. That is the only thing it does in the account. It then says
what it did and what happens next:

```text
Claude extraction — old-personal

Export requested 2026-09-12 20:51 UTC.
Claude will email a download link to the account's address.
When it arrives:

  dataporter extract --source claude --account old-personal --link <url>

```

This works in both modes. Interactively the window is open and the person may watch or
help; unattended (`24`) the tool does it alone, with the source account's credentials
held as §8 holds the destination's. Whether the tool's own helpers press the vendor's
button or the agent does is the slice's to decide, as it is for every page (§5).

The tool remembers that it asked, and when, so that the link that comes back is filed
under the moment the account was as the export describes it. One ask is open per account
at a time; asking again while one is open is refused, and the open ask says how to
abandon it.

### The fetch

```bash
dataporter extract --source claude --account old-personal --link 'https://…'

```

The person reads the vendor's email and hands the link to the tool. The tool downloads
the archive, checks that it is an export of this source and not something else, and
files it as a snapshot (§32) into the store (§33), unchanged. A link that has expired,
or that does not lead to an archive this source recognises, is refused with the reason,
and the ask stays open so the person can try again.

```text
Claude extraction — old-personal

Downloaded 41.3 MB.
Conversations: 127     Projects: 4     Memories: 1
Gaps: 38 files the export does not carry

Snapshot: ~/.dataporter/store/claude/old-personal/2026-09-12T20-51-07Z

```

An archive the person already has — asked for by hand, or downloaded before the tool
existed — is filed the same way, with no ask behind it:

```bash
dataporter extract --source claude --account old-personal --from ./data-2026-09-12.zip

```

### Complete or it says so

An export carries what the vendor chose to put in it and not what the account holds.
Everything the account has that the archive does not — the bytes of the files, today —
is written into the snapshot as a gap with a reason. A snapshot with gaps is a valid
snapshot; a snapshot that is silent about what it lacks is not.

The one thing extraction never does is overwrite: a snapshot in progress is visibly
incomplete until it is finished, and a finished snapshot is never touched again (§33).

Do not print conversation contents during normal operation.

## 32. The snapshot

A snapshot is the data of one account, from one source, as it stood at one moment.

**It is in the vendor's shape.** What the vendor gave, the snapshot keeps: Claude's shape
for a Claude account, ChatGPT's for ChatGPT. Extraction converts nothing on the way in. A
backup that has been re-interpreted is not a backup, and the importer already owns the
reading of each vendor's shape. Anything of ours — the stamp, the gaps, the count of what
was found — sits beside the vendor's data, never inside it. A normalised view may be
derived from a native snapshot later; the reverse is impossible.

**It is complete on its own.** Every snapshot holds everything its export carried, and
names what it did not. None refers to an earlier one to be read. A store may one day
share bytes between snapshots (§40); that is invisible to the snapshot and to whoever
reads it.

**It is written once.** From the moment it is finished, nothing changes it. A second
extraction is a second snapshot with a later stamp. There is no "latest" that moves, no
update, no merge.

**It carries its provenance.** The source, the account label, the stamp, the version of
the tool that wrote it, whether the tool asked for the export or a person handed it over,
when it was asked for and when it was fetched, and every gap with its reason. The link
itself is not kept: it expires, and it is a credential to the archive while it lasts.

**It has no secrets in it.** No credential, no session cookie, no token — nothing the
source session held (§35).

## 33. The store

The store is where snapshots go. Today it is a directory on disk. Later it is also a
bucket somewhere, and nothing about a snapshot changes when it is.

A snapshot is addressed by source, account and moment:

```text
<store>/<source>/<account>/<stamp>/

<store>/claude/old-personal/2026-09-12T20-51-07Z/
<store>/claude/old-personal/2026-10-01T03-00-00Z/
<store>/chatgpt/work/2026-09-30T18-12-44Z/

```

- **Source** is the vendor: `claude`, `chatgpt`, `gemini`.
- **Account** is a label the operator chooses, not the login. Emails change and ids are
  the vendor's; a label is the operator's and stays put.
- **Stamp** is the moment the export was asked for, in UTC, to the second, because that
  is the moment the account was as the archive describes it. An archive with no ask
  behind it is stamped with the moment it was filed. The stamp is the only ordering the
  store has.

The store **never overwrites**. A stamp that already exists is an error; the tool does
not merge into it, replace it, or pick a new stamp on its own. A store that lost a
snapshot to a later run would have failed at the one thing a store is for.

The store is shaped for the cloud it does not yet reach: a snapshot is written as files
that are created once and never renamed, moved or appended to, and a snapshot in progress
is told from a finished one by a marker that lands last. An object store has no rename;
the disk layout does not use one either, so the second backend is a second writer of the
same files and not a migration of the first.

The store is not the workspace. The workspace (§7) is what one migration writes, beside
whatever it migrates. The store is long-lived, spans accounts and sources, and holds
nothing a migration writes. An import from a snapshot writes its workspace beside the
snapshot, as it does beside an export today, and the snapshot itself stays untouched.

```bash
dataporter snapshots

```

```text
claude/old-personal   2026-09-12T20-51-07Z   127 conversations   complete
claude/old-personal   2026-10-01T03-00-00Z   131 conversations   complete
chatgpt/work          2026-09-30T18-12-44Z    88 conversations   2 gaps

```

## 34. Sources

Claude is the first source and the only one this brief requires. The brief is written so
that ChatGPT, Gemini and the rest are each a source beside it, and the store, the
snapshot's provenance and the commands do not change when one lands:

- a source is named for the vendor, never for the program
  ([ADR 0004](../docs/adr/0004-the-command-is-dataporter.md));
- a source knows how to sign in, where the vendor lets a user ask for their data, what
  the archive that comes back looks like, and what the account holds that the archive
  does not;
- a source's snapshot is in that vendor's shape, and the importer for that vendor — when
  there is one — reads that shape.

Extraction from a source the tool does not have is refused, not attempted.

## 35. The source session

The ask signs in to the **source** account. The first brief's session (§8) is the
**destination's**, and one browser profile holds one signed-in identity per site, so the
source gets its own session: its own profile, its own `login`, its own `logout`, named by
the account label it serves. The fetch needs no session: the link is the vendor's leave
to download, and the tool downloads without a browser.

```bash
dataporter login --account old-personal
dataporter extract --source claude --account old-personal
dataporter session logout --account old-personal

```

`login`, `session status` and `session logout` do not take an account today: they mean
the destination, and they go on meaning it when the option is absent. Naming an account
is what this brief adds to them; how the option is spelled and where the source
profile lives are the slice's to decide.

The rules of §8 hold for the source exactly as for the destination: interactively the
person signs in themselves in the window the tool opens; non-interactively the operator
may hand the tool the source account's credentials for one invocation, and the tool keeps
them in memory only, writes them nowhere, and never puts them in a snapshot.

## 36. Safety boundaries

Extraction takes **one action** in the source account: it asks for the export. Signed in
there, the tool:

- navigates to where the vendor lets a user ask for their data;
- asks;

and never:

- sends a message, creates a chat, or renames one;
- deletes anything;
- changes any setting other than by that ask;
- touches billing or security;
- leaves the pages the ask needs.

The ask is an account-level action in §17's sense, and it is the one such action this
brief permits without stopping for a person: it is what the command exists to do, the
person asked for it by running the command, and it is not destructive. Anything else on
that page stops.

The surface (§17, [ADR 0001](../docs/adr/0001-no-door-in-the-wall.md)) grows an
**extraction surface**: the sign-in page and the page where the export is asked for, and
nothing else. It is a second list beside the migration surface and the login surface,
refused just as strictly. The destination session never extracts and the source session
never imports. The fetch downloads from the link the vendor sent and from nowhere else.

## 37. Import from a snapshot

```bash
dataporter import ~/.dataporter/store/claude/old-personal/2026-09-12T20-51-07Z

```

`import` accepts a snapshot wherever it accepts an export, and a snapshot of a Claude
account migrates exactly as the export inside it does: the same classification, the same
seeds, the same report. The snapshot is read and never written. Should a snapshot one
day hold more than the export does (§40), import uses it.

A snapshot with gaps is migrated as far as it goes, and the report says what was not
there to migrate, distinct from what was there and failed.

## 38. What is never printed or written

The rules of §10 and §26 hold. Extraction prints counts and a path, never a title or a
line of a conversation. Logs name the account by its label, never by its email. The
snapshot holds the account's data because that is its purpose; everything the tool
writes *about* the snapshot — the store listing, the logs, the report — holds numbers and
labels only.

## 39. First run

Before an account that matters, extract one that is small and known, and answer with
numbers:

1. Does the ask work, in each mode, and does an email arrive?
2. Does the archive the tool fetches match, byte for byte, the one a person downloads
   from the same link?
3. Does an import of the snapshot produce the same dry run (§9) as an import of that
   archive given to it directly?
4. What does the account hold that the archive does not, and is every such thing a gap
   in the snapshot?
5. How long does the link live, and what does the tool say when it has died?
6. Does a second extraction produce a second snapshot and leave the first byte-identical?

Only after these are answered does extraction run against an account that matters, and
only after 3 is answered does a snapshot stand in for an export anywhere.

## 40. Later

Named so that a later brief or slice can claim them:

- the inbox: reading the vendor's email and taking the link from it, so that an
  extraction needs no person at all;
- reading the account through its pages, for what the export does not carry — the
  files — and for a snapshot that does not wait on an email;
- a cloud store: the same snapshot, written to a bucket, with the disk layout as its
  contract;
- sharing bytes between snapshots in a store, invisible to the snapshot;
- retention: which snapshots a store keeps, and who decides;
- encryption at rest, and who holds the key;
- scheduling inside the tool, if a cron ever proves insufficient;
- ChatGPT, Gemini and Copilot as sources, each its own brief or slice;
- a mock source — the mock claude.ai (§21) with a page to ask for an export, and a link
  it prints instead of an email — so extraction can be rehearsed with no account;
- verifying a snapshot by importing it into a throwaway account and comparing;
- a normalised view derived from a native snapshot, for tools that are not importers.
