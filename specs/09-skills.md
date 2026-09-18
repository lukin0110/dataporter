# Skills

**Brief 09.** Section numbers continue from [`08-signing-out.md`](08-signing-out.md),
which ends at §87, so that `§N` names exactly one section anywhere in this repository. The
words used here are defined in [`CONTEXT.md`](../CONTEXT.md).

## 88. Goal

A Claude data export does not carry the account's **skills**. Every Claude snapshot this
tool has filed is therefore missing something the account holds, and says nothing about
it — which is the one thing §32 does not allow a snapshot to do. A person who restores
from a snapshot gets their conversations back and loses every skill they wrote.

This brief closes that gap. It adds a second way to extract a Claude account:

```bash
dataporter extract-skills --source claude --account work

```

It is a separate command and not a flag on `extract`, because the two have nothing in
common but their destination. An ask waits hours for an email and can be made once at a
time; skills come back in seconds and can be re-read as often as you like. Tying them
together would mean asking the vendor for a fresh export every time you wanted a current
copy of a skill.

Nothing about the ask, the link, the fetch or the archive changes.

## 89. The command

`--account` is required, as `extract`'s and `logout`'s are, and `--source` defaults to
`claude` through `Settings.source`. There is no destination form of this command.

`--stamp` is optional and names the snapshot the skills are filed under:

```bash
dataporter extract-skills --source claude --account work --stamp 2026-09-18T09-14-02Z

```

Given, the skills join that snapshot — the one the morning's `extract` wrote, so that one
moment of an account is one directory. Omitted, they get a snapshot of their own, stamped
at the moment the extraction began, as §33 stamps an archive with no ask behind it. The
value is a stamp and nothing else: it is a directory name, and a store that sorts by
anything but time is a store with no ordering at all (§33).

It runs in a real browser, like the ask, and needs a display for the same reason: the page
it signs in through is behind the vendor's bot management, which nothing this tool builds
will clear (ADR 0008).

## 90. Which skills

**The ones the account wrote.** Not the ones Anthropic ships with it, not the ones it
discovered and switched on: those are somebody else's to keep, they are not lost when the
account is, and a backup of them is a backup of a link.

Whether a skill is switched on, and whether it belongs to a plugin, decide nothing. A
skill you wrote and turned off is still a skill you wrote, and the account is still the
only place it exists. Both facts are recorded beside the skill rather than used to filter
it.

An account that wrote none is not a failure. The extraction succeeds, files nothing, and
says so.

## 91. Where they land

In a snapshot, beside the archive, in a directory of their own:

```text
<store>/claude/work/2026-09-18T09-14-02Z/
├── export.zip          the archive, when an ask put one here
├── snapshot.json       the manifest
├── COMPLETE            the marker that lands last
└── skills/
    └── <name>.skill    one file per skill, as the vendor served it

```

Each file is what the vendor served, byte for byte, unopened (ADR 0005). The tool does not
unpack a skill, read it, or check that it is what it claims to be; a snapshot holds the
vendor's bytes and our account of them, and nothing in between.

**This amends §32 and §33.**

§32 says a snapshot holds everything its export carried. It now holds everything **its
extractions** carried: an archive, skills, or both. A snapshot with skills and no archive
is a whole snapshot of the skills of an account at a moment, and says so.

§33 says the store never overwrites and that a stamp that already exists is an error. That
stands for an archive: an ask still refuses a stamp it finds. It does not stand for skills.
`extract-skills --stamp` may add to a snapshot that exists, and **only add** — it writes
files that are not there, never a byte over one that is, and refuses rather than replace.
The manifest is rewritten to describe what arrived, because a snapshot that holds a file
its manifest does not name is worse than one whose manifest was written twice. §33's reason
for never appending is the object store it is shaped for, and an object store replaces a
key perfectly well; what it cannot do is rename, and nothing here renames. This is
ADR 0011.

## 92. What the tool does in the account

§36 gives extraction **one action** in a source account: the ask. A skills extraction takes
**none**. It reads a list, and it fetches one address per skill. It presses nothing, opens
no menu, and changes nothing about the account — not a setting, not a skill, not which
skills are switched on.

**This amends §36** by widening where extraction may go and narrowing what it may do there.
The pages the ask needs are joined by the addresses the skills need; the list of things
extraction never does is unchanged and now has one fewer exception to carve out for.

The reads happen in the browser, on the page, on the vendor's own origin — the same rule
ADR 0008 set for the sign-in. The tool holds no token and constructs no authenticated
request; the browser makes them, as it makes every other request that page makes, and the
cookie never leaves it. What comes back is a list of skills and a file each. §46 is
unchanged: a trace records that a read happened and how many things came back, never a
value from one.

## 93. Gaps

A skill that is listed and will not come back is a **gap** (§31): recorded in the snapshot
with the reason, counted in the listing, and not fatal. The extraction finishes, files what
it got, and says what it did not. That is §31's rule — complete, or it says so — applied to
the one thing that can go wrong per file.

Failing to read the list at all is not a gap but an error, and the extraction exits
non-zero having filed nothing. A snapshot cannot be honest about what it is missing if it
never learned what there was.

## 94. The blocks

Golden, as brief 03's, brief 06's, brief 07's and brief 08's are. One line per skill as it
lands, then the block:

```text
downloaded  research-helper.skill  4.1 KB
downloaded  standup-notes.skill  2.7 KB
Claude skills — work

Downloaded 2 skills in 4s.
2 skills.

Snapshot: ~/.dataporter/store/claude/work/2026-09-18T09-14-02Z/skills

```

The per-file lines are `extract`'s (§60's `downloaded`), unchanged — they run straight
into the block, as they do after a fetch — and `--quiet` drops them as it drops those. The
block counts skills rather than megabytes, because a skill is a few kilobytes and every
line would otherwise read `0.0 MB`. With gaps, the `Gaps:` line appears as it does after an
ask, and is omitted entirely when there are none.

An account that wrote no skills:

```text
Claude skills — work

No skills of your own to extract.

```

Exit `0`, nothing filed, no snapshot created. There is no empty snapshot: a directory that
records the absence of something the account never had is not evidence of anything.

## 95. What this does not do

- **It does not restore.** Putting a skill back into an account is a later brief; the site
  takes a `.skill` file by hand today, which is what makes keeping one worth doing now.
- **It does not read a skill.** Not its instructions, not its files, not its description
  beyond what the listing gives for the manifest.
- **It does not extract another vendor's.** ChatGPT and Gemini have no equivalent here, and
  nothing in this brief assumes one.
- **It does not run unattended against claude.ai.** The same display the ask needs
  (`docs/LIMITATIONS.md`), for the same reason.
