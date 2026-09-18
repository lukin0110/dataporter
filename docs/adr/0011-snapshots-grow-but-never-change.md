# Snapshots grow but never change

A Claude export does not carry the account's skills, so `extract-skills` (brief 09) files
them itself. Where they go ran straight into §33: the store never overwrites, a stamp that
already exists is an error, and a snapshot is written as files that are created once and
never renamed, moved or appended to, with a marker that lands last. Two commands writing
one snapshot breaks the sentence as written — and one snapshot is what an operator wants,
because the skills and the conversations of one account at one moment belong in one place.

So **a snapshot may gain files it did not have, and may never change a file it has**
(brief 09 §91). `extract-skills --stamp` writes into an existing snapshot; it adds
`skills/` and the files under it, refuses rather than replace if a target is already there,
and touches neither the archive, nor its parts, nor the fingerprint. The one thing that is
written twice is `snapshot.json`, because a snapshot holding a file its manifest does not
name is precisely what §32 exists to prevent. `COMPLETE` is re-written after it, in the same
order `file_archive` uses, so a reader that sees the marker still has every byte the
manifest claims.

§33's reason for forbidding appends is the object store it is shaped for — "an object store
has no rename; the disk layout does not use one either". That reason survives intact.
Nothing here renames, nothing moves, and no file is appended to in the byte sense; a
manifest rewritten in full is a `PUT` to the same key, which is the one write an object
store does best. What the rule was protecting is not what this gives up.

What it does give up is the promise that a snapshot read twice reads the same. A reader
that saw a snapshot before its skills arrived and cached the manifest now holds a stale one.
That is accepted because the store has exactly one reader today — `Store.rows()`, which
re-walks the directory every time `snapshots` runs — and because the alternative was worse
in a way that compounds.

## Considered

**A sidecar manifest**, `skills/skills.json`, leaving `snapshot.json` untouched. It keeps
§33 literally true, and the append becomes a new directory rather than a modification —
genuinely the cleaner invariant. Rejected because `snapshots` then reports on one manifest
while the directory holds two, so either the listing goes blind to skills or it learns to
read both and the "one manifest per snapshot" rule dies a quieter death instead of a
documented one.

**A skills snapshot of its own**, stamped separately. The store's rules survive untouched
and the command needs no `--stamp` at all. Rejected because the two halves of one account at
one moment then sit in directories stamped minutes apart, and nothing in the store says they
belong together — the operator has to know, which is the kind of thing a store exists to
stop being true.

**Folding skills into `extract`** so one command writes one snapshot and seals it once. It
keeps every invariant. Rejected in brief 09 §88 for a reason outside the store entirely: an
ask waits hours on an email and may be open once at a time, while skills come back in
seconds, so coupling them means asking the vendor for a fresh export to get a current copy
of a skill.

**Letting `COMPLETE` mean "complete for now"** — relaxing the marker rather than the file
rules. Rejected because the marker is the only thing a reader has to distinguish a snapshot
in progress from a finished one, and a marker that means two things means nothing. It still
means every byte the manifest names is present; that is why it is re-written last rather
than left alone.
