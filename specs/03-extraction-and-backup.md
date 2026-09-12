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
claude.ai and downloaded. This brief starts one step earlier, at the account itself, and
adds the step the person did by hand. It also stops assuming the account is a Claude one.
The tool will extract from ChatGPT, Gemini and others, and what it writes is shaped so
that a second source is another source and not a second tool.

```text
Account A (Claude, ChatGPT, Gemini, …)
      │
      │ extract
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
reads everything it can, and writes it down. It changes nothing in the account. It knows
nothing about migration, seeds, or a destination.

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

```bash
dataporter extract --source claude --account old-personal

```

Extraction signs in to the source account and reads it through the browser, as a
signed-in user would see it: the list of conversations, each conversation in full, the
projects, the memories, the files, the profile. It reads what the site delivers to that
browser and does not call a backend on its own (§2 applies to extraction as it applies to
import). The vendor's official data export — the emailed archive — is not the mechanism:
a link that arrives in an inbox some time later is a step a person takes, not one the
tool can make reliable or repeat on a schedule.

An official export is still welcome. It is filed into the store as a snapshot, unchanged,
with the moment it was requested as its stamp if that is known and the moment it was filed
if not:

```bash
dataporter extract --source claude --account old-personal --from ./data-2026-09-12.zip

```

Extraction is **complete or it says so**. A conversation it cannot read, a file it cannot
download, a section of the account it does not know how to reach, is written into the
snapshot as a gap with a reason. A snapshot with gaps is a valid snapshot; a snapshot
that is silent about what it lacks is not. The one thing extraction never does is
overwrite: a snapshot in progress is visibly incomplete until it is finished, and a
finished snapshot is never touched again (§33).

Example output:

```text
Claude extraction — old-personal

Conversations:  127 found, 127 read
Projects:         4 found,   4 read
Memories:         1 found,   1 read
Files:           38 found,  36 read, 2 not downloadable

Snapshot: ~/.dataporter/store/claude/old-personal/2026-09-12T20-51-07Z

```

Do not print conversation contents during normal operation.

## 32. The snapshot

A snapshot is the data of one account, from one source, as it stood at one moment.

**It is in the vendor's shape.** What the vendor gave, the snapshot keeps: Claude's shape
for a Claude account, ChatGPT's for ChatGPT. Extraction converts nothing on the way in. A
backup that has been re-interpreted is not a backup, and the importer already owns the
reading of each vendor's shape. Anything of ours — the stamp, the gaps, the count of what
was found — sits beside the vendor's data, never inside it. A normalised view may be
derived from a native snapshot later; the reverse is impossible.

**It is complete on its own.** Every snapshot holds the whole account. None refers to an
earlier one to be read. A store may one day share bytes between snapshots (§40); that is
invisible to the snapshot and to whoever reads it.

**It is written once.** From the moment it is finished, nothing changes it. A second
extraction is a second snapshot with a later stamp. There is no "latest" that moves, no
update, no merge.

**It carries its provenance.** The source, the account label, the stamp, the version of
the tool that wrote it, whether it came from a live extraction or a filed export, and
every gap with its reason.

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
- **Stamp** is the moment extraction began, in UTC, to the second, and it is the only
  ordering the store has.

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
- a source knows how to sign in, what the account holds, and how to read each part of it
  through the browser;
- a source's snapshot is in that vendor's shape, and the importer for that vendor — when
  there is one — reads that shape.

Extraction from a source the tool does not have is refused, not attempted.

## 35. The source session

Extraction signs in to the **source** account. The first brief's session (§8) is the
**destination's**, and one browser profile holds one signed-in identity per site, so the
source gets its own session: its own profile, its own `login`, its own `logout`, named by
the account label it serves.

```bash
dataporter login --account old-personal
dataporter extract --source claude --account old-personal
dataporter session logout --account old-personal

```

The rules of §8 hold for the source exactly as for the destination: interactively the
person signs in themselves in the window the tool opens; non-interactively the operator
may hand the tool the source account's credentials for one invocation, and the tool keeps
them in memory only, writes them nowhere, and never puts them in a snapshot.

## 36. Safety boundaries

Extraction is **read-only**. Signed in to the source account, the tool:

- reads conversations, projects, memories, files and the profile;
- navigates to reach them;

and never:

- sends a message, creates a chat, or renames one;
- deletes anything;
- changes any setting;
- touches billing or security;
- leaves the pages it needs for reading.

The surface (§17, [ADR 0001](../docs/adr/0001-no-door-in-the-wall.md)) grows an
**extraction surface**: the pages of the source site that show a signed-in user their own
data, and nothing else. It is a second list beside the migration surface and the login
surface, refused just as strictly. The destination session never extracts and the source
session never imports.

## 37. Import from a snapshot

```bash
dataporter import ~/.dataporter/store/claude/old-personal/2026-09-12T20-51-07Z

```

`import` accepts a snapshot wherever it accepts an export, and a snapshot of a Claude
account migrates as an export of that account does: the same classification, the same
seeds, the same report. Where a snapshot holds more than an export does — the files an
export never carried (§14) — import uses it. The snapshot is read and never written.

A snapshot with gaps is migrated as far as it goes, and the report says what was not
there to migrate, distinct from what was there and failed.

## 38. What is never printed or written

The rules of §10 and §26 hold. Extraction prints counts and a path, never a title or a
line of a conversation. Logs name the account by its label, never by its email. The
snapshot holds the account's data because that is its purpose; everything the tool
writes *about* the snapshot — the store listing, the logs, the report — holds numbers and
labels only.

## 39. First run

Before the whole account, extract one that is small and known, and answer with numbers:

1. Does every conversation the site lists appear in the snapshot, with every turn?
2. Do the files come down, and do their bytes match what the site serves?
3. Does an import of the snapshot produce the same dry run (§9) as an import of the
   official export of the same account, taken the same day, allowing for what the export
   never carried?
4. What does the site hold that the tool could not reach, and is every such thing a gap
   in the snapshot?
5. Does a second extraction, minutes later, produce a second snapshot and leave the first
   byte-identical?

Only after these are answered does extraction run against an account that matters, and
only after 3 is answered does a snapshot stand in for an export anywhere.

## 40. Later

Named so that a later brief or slice can claim them:

- a cloud store: the same snapshot, written to a bucket, with the disk layout as its
  contract;
- sharing bytes between snapshots in a store, invisible to the snapshot;
- retention: which snapshots a store keeps, and who decides;
- encryption at rest, and who holds the key;
- scheduling inside the tool, if a cron ever proves insufficient;
- ChatGPT, Gemini and Copilot as sources, each its own brief or slice;
- a mock source — the mock claude.ai (§21) showing a signed-in user their own data — so
  extraction can be rehearsed with no account;
- verifying a snapshot by importing it into a throwaway account and comparing;
- a normalised view derived from a native snapshot, for tools that are not importers.
