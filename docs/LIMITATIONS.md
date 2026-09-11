# Limitations

**Kind:** Running record of what this migration cannot reproduce. Seeded by
[`10`](../specs/impl/10-attach-spike.md), added to by every slice that finds another one,
and quoted by [`21`](../specs/impl/21-scale-up.md)'s sign-off.
**Spike run:** none.

[§15](../specs/01-initial-brief.md) sets two fidelity targets and says which one wins:
semantic usability over "perfect reproduction of internal Claude metadata that cannot be
controlled through the UI". This file is the list of that metadata — everything §15 asks
for that the destination account will not hold after a migration, and what the operator
gets instead.

Every entry carries a mark:

- *by construction* — it follows from the approach itself (a conversation is replayed as
  one or more human messages pasted into a new chat), not from anything about the UI. No
  observation can change it; only a different approach could.
- *observed on `<date>`* — a human watched the UI refuse or ignore it.
- *unknown* — expected to be a limitation, not yet confirmed. `10` confirms these.

## Structural fidelity (§15)

### Message-level metadata

- **Original message timestamps.** Every migrated message is timestamped when it is
  pasted, not when it was written. The composer offers no way to set a send time. The
  original times survive only inside the seed text, where `04` renders them as part of the
  transcript. *by construction*
- **Message identifiers.** The destination account mints its own message ids. The source
  export's ids are not carried over and cannot be referenced from the destination.
  *by construction*
- **Per-message boundaries.** A source conversation of forty turns becomes one human
  message per seed part, not forty messages. `state.json` records how many parts a
  conversation became; the turn structure itself lives in the rendered text.
  *by construction*
- **Message roles.** Every migrated turn is inside a human message regardless of who said
  it in the source. The seed labels each turn, so the roles are readable but not
  structural. *by construction*
- **The model that produced each assistant turn.** The export records a model per
  conversation at best; the UI has no way to attribute a pasted turn to a model, and the
  acknowledgement Claude writes back comes from whatever model the destination account is
  set to. *by construction*

### Conversation-level metadata

- **Conversation creation and update times.** A migrated chat is created now. Whether the
  UI exposes any way to influence either is unknown until `10` looks. *unknown*
- **Conversation identifiers.** The destination mints a new `/chat/<uuid>`; `06`'s
  `state.json` maps source id to destination id, which is the only place the two are tied
  together. *by construction*
- **Titles.** Whether a chat can be renamed through the UI reliably enough to be a
  verified step is `10`'s Q7 and `17`'s whole subject. If the answer is no, "equivalent
  titles" moves from `17` into this file. *unknown*
- **Chronological order between conversations.** Conversations are migrated in the order
  `12` picks, so the destination's sidebar order reflects the migration, not the source
  history. *by construction*
- **Stars, archive state, folders and projects.** Not part of `02`'s export model and not
  set by any slice. *unknown*

### Content

- **Attachments whose bytes the export does not carry.** `03` classifies these; `16`
  uploads the ones we have and records the rest. Whether the real export archive contains
  bytes at all is an open question in [`specs/README.md`](../specs/README.md). *unknown*
- **Which message an uploaded attachment hangs off.** An attachment chip belongs to the
  message being composed, so every file `16` uploads is attached to the first message of
  the migrated chat rather than to the message that carried it in the source. The seed's
  `[File: … — attached to this chat]` line, written where the original message was, is
  what ties the two back together. *by construction*
- **Rendered artifacts, tool calls and code execution results.** What the export holds for
  these, and what survives being pasted as text, is not yet known. *unknown*

## Semantic fidelity (§15)

Not a limitation list — the target. `20` measures it with the six §18 questions and,
optionally, the `judge` extra. Anything it finds that the UI cannot be made to do lands
here.

## How to add to this file

One bullet, one mark, and the slice that found it. A limitation discovered without a mark
is an impression; `tests/test_spike_docs.py` fails the build for an unmarked entry.
