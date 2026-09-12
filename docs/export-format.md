# Claude data export — format

**Export inspected:** none.
**Export date:** unknown.
**Status:** no real export has been read. Every factual claim below is *assumed*.

`02`'s prerequisite is that a real export from the operator's source account is
inspected before the parser is written, and that this file records what is actually in
it. That has not happened yet, so this file is the parser's stated model of the export
rather than a report of one, and `02` stays *In progress* until it is confirmed. The
last section says exactly how to confirm it.

## How to read this document

Every factual claim carries one of:

- ***observed*** — read in a real archive, the one named at the top.
- ***assumed*** — expected, derived from several independent third-party parsers.
  Nothing here has confirmed it.
- ***decided in `02`*** — our rule, not the export's. It cannot be wrong about the
  export; it can only be a bad choice.

## Claims

### Archive layout

- The export is a `.zip` whose members sit at the archive root. *assumed*
- `conversations.json` is present and is a JSON array of conversation objects. *assumed*
- `users.json`, `projects.json` and `memories.json` may be present. *assumed*
- No other member is expected. An unexpected one is recorded as `unknown_file` and the
  parse continues. *decided in `02`*
- An archive whose members sit under one wrapping directory is accepted, and so is an
  extracted directory. *decided in `02`*

### Attachment bytes

- The archive carries **no attachment bytes** — only `attachments[].extracted_content`,
  `file_name`, `file_size`, `file_type`, and the `files[]` / `files_v2[]` references.
  *assumed*

  This is the open question in `specs/README.md`. It decides whether `03`'s attachment
  class 2 (reproducible by upload) can exist at all without an operator-supplied
  `--attachments-dir`. If bytes do turn out to be in the archive, `02` gains a way to
  read them and `16` changes with it.

### Timestamps

- ISO 8601, UTC, trailing `Z`, microsecond precision. *assumed*
- Every timestamp is normalised to a tz-aware UTC `datetime` on parse; a naive value is
  assumed UTC and logged. *decided in `02`* — `04` renders
  `{created_at as YYYY-MM-DD HH:MM UTC}` into a byte-compared golden string, so an
  offset left unnormalised would print the wrong hour with the word `UTC` beside it.

### Content blocks

A message carries `content`, a list of typed blocks. `text` on the message is a
fallback: `content` is authoritative when present, because exports have been seen with
an empty `text` and a populated `content`. *assumed*

| `type` | Fields | Example (redacted) | Mark |
| --- | --- | --- | --- |
| `text` | `text` | `{"type": "text", "text": "…"}` | *assumed* |
| `tool_use` | `name`, `input` | `{"type": "tool_use", "name": "artifacts", "input": {"title": "…", "language": "python"}}` | *assumed* |
| `tool_result` | `content` | `{"type": "tool_result", "content": [{"type": "text", "text": "…"}]}` | *assumed* |
| `thinking` | `thinking` | `{"type": "thinking", "thinking": "…"}` | *assumed* |
| `token_budget` | — | `{"type": "token_budget"}` | *assumed* |

- Any other tag survives whole as `UnknownBlock.raw`, is counted as
  `unknown_block_type:<tag>`, and `04` renders it `[Unsupported content: {type}]`.
  *decided in `02`*
- A *known* tag whose payload will not validate is also kept whole, counted as
  `malformed_block:<tag>`. *decided in `02`*

### Optional fields

- `index` on messages: present. *assumed*
- `current_leaf_message_uuid` on conversations: present. *assumed*
- `files_v2` on messages: present alongside `files`. *assumed*
- `sender` is `human` or `assistant`. Anything else is dropped and counted as
  `unknown_sender:<value>`, because it cannot be represented. *assumed*

### Branching

- Edits and regenerations create sibling messages sharing a `parent_message_uuid`, and
  siblings may carry the same `index`. *assumed*

## The active path *decided in `02`*

The messages a conversation migrates are one lineage, chosen like this:

1. The leaf is `current_leaf_message_uuid` when it names a message that exists. A
   dangling pointer is not an error: it falls back to step 2 and logs
   `export leaf not found`.
2. Otherwise the leaf is the message with the latest `created_at` that no other message
   names as its parent, ties broken by the later position in `chat_messages`.
3. Walk `parent_message_uuid` to the root. A repeat (a cycle) or a parent that is not in
   the conversation stops the walk; both are logged.
4. Everything else is `off_path()`: counted, reported by `19` as a limitation, never
   dropped.

## The ordering rule *decided in `02`*

Within the active path: by `index` when every message on the path has one **and they are
all distinct**; otherwise by `created_at`, ties broken by position in `chat_messages`.

Uniqueness is evaluated across the path, not the whole conversation. A regenerated
sibling legitimately carries the same `index` as the message it replaces, so a
conversation-wide check would disqualify `index` exactly when branches exist — which is
when ordering matters most.

The parent walk decides *membership*; this rule decides *order*. Where the two disagree,
this rule wins.

## Refreshing this document

Run the parser against a real export with the run log on, and read one record:

```bash
dataporter --verbose inspect /path/to/export.zip
```

The `export shape` record reports the file list, `with_index`, `with_leaf`,
`with_files`, `with_files_v2`, `block_types`, the counts and the fingerprint — that is
one line per export and it answers most of the table above. Then:

1. Set **Export inspected** and **Export date** at the top and drop the status paragraph.
2. Change every line the record confirms from *assumed* to *observed*.
3. Add any block type in `block_types` that is not in the table, with a redacted example.
4. Open `specs/impl/02-export-model.md` and mark it `Done` if nothing had to change; if
   something did, write it into *Resolved while building* first.
