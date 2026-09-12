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
  transcript. `17` records this against every chat that lands, as the per-conversation
  limitation `timestamps_not_preserved`, so that `19`'s account of one conversation is
  complete without this file. *by construction*
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
- **Titles.** `17` renames the chat through the UI — Hermes opens the chat's own menu and
  types the source title, capped at `fidelity.title_max_chars` — and then checks the
  displayed title from the page. Whether that affordance exists and is reliable is `10`'s
  Q7, still unanswered, so the step is best effort by design: a chat whose title did not
  take is recorded as `title_not_set` against that conversation and migrated all the same,
  and an operator who finds the rename unreliable sets `fidelity.rename_title = false` and
  gets `title_not_set` for every conversation. Where the title is not set, "equivalent
  titles" is met only by the header line `04` writes into the first seed part, which names
  the source conversation inside the chat's first message. *unknown*
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

## The names `19` prints

Every limitation the report counts is one of these six slugs, recorded against a
conversation in `state.json` and printed by name in the `Limitations:` block. The first
four are `04`'s, written when the seed is rendered and carrying the number of blocks they
stand for (`thinking_omitted:3`); the last two are `17`'s, written against a chat that was
read back. `19` counts conversations rather than occurrences, so the per-conversation
number stays in `state.json` where the conversation it belongs to is.

[`21`](../specs/impl/21-scale-up.md) gives each one a heading of its own, a count from the
full run and a kind:

- **UI limit** — the Claude web interface offers no way to do it. A different tool driving
  the same UI would hit the same wall.
- **export limit** — the export does not carry what would be needed. A richer export could
  lift it.
- **tool choice** — this build decided not to. A later slice could decide otherwise, and
  the entry says what that would cost.

A count is a measurement, so it carries the experiment marks — `*not yet run*` until the
full run produces it, `*measured on <date>*` after — rather than the three marks the
observations above use. `tests/test_scale_up_doc.py` checks that every name the code can
print has a heading here, and that each heading carries a count and a kind.

### `branches_dropped`

The export's off-path messages, left out of the seed. A conversation that was edited and
re-answered is migrated as the path the export marks current; the other branches are
counted and not rendered. Replaying them would mean editing a message in the destination
chat and answering it again, which is a second migration of the same conversation.

| Conversations in the full run | Kind | Mark |
| --- | --- | --- |
| — | tool choice | *not yet run* |

### `thinking_omitted`

Extended-thinking blocks. They are not part of what the person saw, and nothing in the
composer can produce one.

| Conversations in the full run | Kind | Mark |
| --- | --- | --- |
| — | UI limit | *not yet run* |

### `tool_calls_summarised`

A tool call the seed renders as `[Tool call: name]`. The call itself cannot be replayed
into a new chat: the destination would have to run the tool, which is a different action
in a different account.

| Conversations in the full run | Kind | Mark |
| --- | --- | --- |
| — | UI limit | *not yet run* |

### `unknown_blocks`

A content block this build has no rendering for, kept as `[Unsupported content: type]` so
that a reader of the migrated chat knows something was there. What the block held is in
the export; what to do with it is `02`'s to decide, one block type at a time.

| Conversations in the full run | Kind | Mark |
| --- | --- | --- |
| — | tool choice | *not yet run* |

### `timestamps_not_preserved`

*Original message timestamps*, above, recorded against every chat that lands. The composer
offers no way to set a send time, so every migrated message is stamped when it was pasted.
Expected against every completed conversation; a count below that is a finding about `17`
rather than about the UI.

| Conversations in the full run | Kind | Mark |
| --- | --- | --- |
| — | UI limit | *not yet run* |

### `title_not_set`

*Titles*, above: the chat kept the destination's own title because the rename did not take,
or because `fidelity.rename_title` is off. A UI limit in the first case and a tool choice
in the second, and the count does not distinguish them — the configuration that produced
the run does.

| Conversations in the full run | Kind | Mark |
| --- | --- | --- |
| — | UI limit | *not yet run* |

## Semantic fidelity (§15)

Not a limitation list — the target. `20` measures it with the six §18 questions and,
optionally, the `judge` extra. Anything it finds that the UI cannot be made to do lands
here.

## How to add to this file

One bullet, one mark, and the slice that found it. A limitation discovered without a mark
is an impression; `tests/test_spike_docs.py` fails the build for an unmarked entry.

A limitation the *report* can print is not a bullet but a heading of its own under
*The names `19` prints*, with a count and a kind, because `21`'s sign-off quotes it by
name: add the slug to the code and `tests/test_scale_up_doc.py` fails until the heading
exists.
