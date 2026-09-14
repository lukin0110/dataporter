# Snapshots are vendor-native

One store will hold data from Claude, ChatGPT and Gemini, and one store invites one
format. We decided that a snapshot holds the vendor's own archive, byte for byte, and
that everything of ours — the stamp, the provenance, the gaps, the counts — sits beside
it in a manifest and never inside it. Normalising is the importer's job, at read time, as
it is today for an export: the importer for a vendor reads that vendor's shape, and a
snapshot of a Claude account migrates exactly as the export inside it would (brief `03`,
§32, §37).

## Considered

- A normalised store: extraction converts each vendor's archive into one dataporter
  format on the way in. Uniform to read, but a backup that has been re-interpreted is
  not a backup — a bug in the conversion is a bug in every snapshot ever taken — and it
  duplicates each vendor's parser at write time.
- Both: the native archive kept as the record, a normalised view derived beside it. Two
  things to keep consistent, and the derived one can be produced from the native one at
  any later time, which is the case for not producing it now.

## Consequences

- A snapshot's fingerprint is the archive's own (`Export.fingerprint`, the SHA-256 of
  `conversations.json`), so a workspace begun from the raw export and one begun from its
  snapshot are the same migration.
- Each source needs its own importer before its snapshots can be restored; a snapshot
  of a source the tool cannot yet import is still a backup.
- A normalised view, if one is ever wanted for tools that are not importers, is a
  derivation from a snapshot and never a replacement for one (brief `03`, §40).

## Amended 2026-09-14: the vendor's archive may be several files

*"The vendor's own archive, byte for byte"* assumed one file, because both sources
shipped one. Claude does not: its emailed link serves a **manifest** naming several
single-use URLs, one per category and part — `light_metadata-000.zip`,
`conversations-000.zip`, and more parts as an account grows.

A snapshot therefore holds the manifest and every part, each byte for byte and under the
name the vendor gave it, with `snapshot.json` gaining a `parts` list so it still accounts
for everything in its own directory. `archive` stays what an importer reads — the part
carrying `conversations.json` — so nothing that knows only `archive` learns anything new.

What was *not* done, and is the point of the amendment: repackaging the parts into one
zip. It would have kept the old shape and every reader untouched, at the cost of filing an
archive the vendor never served — which is the one thing this decision says a snapshot
never contains. A backup that has been re-packed is re-interpreted, and the reasoning
against a normalised store is the reasoning against it here.
