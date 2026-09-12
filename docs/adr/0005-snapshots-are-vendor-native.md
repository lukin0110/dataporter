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
