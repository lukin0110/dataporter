# ChatGPT data export — format

**Export inspected:** none.
**Export date:** unknown.
**Status:** no real export has been read. Every factual claim below is *assumed*.

Brief `05` §55 makes this the one place the shape of a ChatGPT export is written down: the
mock chatgpt.com renders its archive from what this document says, and the tool's ChatGPT
half, when it is written, reads what this document says. OpenAI publishes no description
of the format — the fullest third-party account of it, the format notes of the
`nexus-ai-chat-importer` project (*Sources*, below), opens with "OpenAI does not
document this format publicly … It can change without notice" — so everything below is
what independent readers of real exports agree on, read on 2026-09-13 from the sources
listed at the end, and the section before them says how to confirm it.

## How to read this document

Every factual claim carries one of:

- ***observed*** — read in a real archive, the one named at the top.
- ***assumed*** — expected, derived from several independent third-party parsers of real
  exports. Nothing here has confirmed it.
- ***decided in brief `05`*** — our rule, not the export's. It cannot be wrong about the
  export; it can only be a bad choice. The slice that builds the archive may narrow it.

## Claims

### Archive layout

- The export is a `.zip` whose members sit at the archive root. *assumed*
- `conversations.json` is present and is a JSON array of conversation objects; it has
  been seen, rarely, as an object with a `conversations` key. *assumed*
- A large export splits the conversations over numbered files, `conversations-NNN.json`,
  instead of one. *assumed* — OpenAI's own transfer article says "Larger exports may
  contain numbered conversation JSON files instead", which is documentation and not yet
  an observation of one.
- The other members two independent 2026 inventories report, which disagree at the
  edges — the layout changed during 2026, and the second is the later one:

  | Member | First inventory (2026-02) | Second inventory (2026-08) | Purpose |
  | --- | --- | --- | --- |
  | `user.json` | yes | yes | the account |
  | `chat.html` | yes | yes | a rendering for a person |
  | `message_feedback.json` | yes | — | thumbs up and down |
  | `shared_conversations.json` | yes | — | shared links |
  | `model_comparisons.json` | optional | — | side-by-side answers |
  | `user_settings.json` | — | yes | settings |
  | `export_manifest.json` | — | yes | every member with its size |
  | `conversation_asset_file_names.json` | — | yes | attachment id → original name |
  | `library_files.json` | — | yes | uploads, canvases, generated images |
  | `file_<id>.dat`, `file-<id>.dat` | root-level `file-*` | yes | attachment bytes, no name, no extension |
  | `dalle-generations/`, `user-<id>/`, `textdocs/` | yes | — | media and canvases, by path |

  *assumed*, all of it.
- The mock chatgpt.com writes `conversations.json` and `user.json` and nothing else: an
  empty member would claim a feature the mock does not have. *decided in brief `05`*

### Attachment bytes

- A 2026 export **carries attachment bytes**, as `file_<id>.dat` members without a name or
  an extension, with `conversation_asset_file_names.json` mapping each id to its original
  name; earlier exports carried media under `dalle-generations/` and `user-<id>/`, and
  that path survives as a value in the name index. *assumed*

  This is the opposite of the Claude export's one gap
  ([`export-format.md`](export-format.md)), and it decides whether a ChatGPT snapshot has
  a gap for files at all. Confirming it is the first thing reading a real export settles.
- The mock carries no bytes and names an accepted file on the message that carried it,
  which is the mock's one gap and not the export's. *decided in brief `05`*

### Timestamps

- `create_time` and `update_time` are numbers: seconds since the epoch, UTC, with a
  fraction (`1704067240.0`, `1704067200.123`). *assumed*
- On a message either may be `null`. *assumed*
- The mock dates a chat by its own creation and its messages one second apart, so that
  the same chats render the same bytes. *decided in brief `05`*

### The conversation

| Field | What | Mark |
| --- | --- | --- |
| `title` | the title | *assumed* |
| `create_time`, `update_time` | as above | *assumed* |
| `mapping` | an object of node id → node (below) | *assumed* |
| `current_node` | the id of the leaf of the branch the page shows | *assumed* |
| `conversation_id`, `id` | the conversation's UUID, the same value in both | *assumed* |
| `is_archived` | boolean | *assumed* |
| `default_model_slug` | the model, e.g. `auto`, `gpt-5` | *assumed* |
| `gizmo_id`, `gizmo_type`, `conversation_template_id` | non-null when the conversation belongs to a custom GPT or a project | *assumed* |
| `moderation_results`, `plugin_ids`, `safe_urls`, `blocked_urls`, `disabled_tool_ids` | lists, or `null` | *assumed* |
| `conversation_origin`, `voice`, `async_status`, `owner`, `sugar_item_id`, `sugar_item_visible` | `null` or false in ordinary chats | *assumed* |
| `is_starred`, `is_study_mode`, `is_do_not_remember`, `is_read_only`, `pinned_time`, `memory_scope` (`global_enabled`), `context_scopes` | newer, seen in 2026 exports | *assumed* |

- Any field not listed survives whole and is counted, never dropped; that is the later
  importer's rule to make and is not decided here.

### The node

- `{ "id", "message", "parent", "children" }`: `message` is a message object or `null`,
  `parent` a node id or `null`, `children` a list of node ids. *assumed*
- The root node has `parent: null` and, often but not always, `message: null`; the first
  real messages may be a `system` message with empty parts and then the user's. *assumed*
- The mock writes one root node with `message: null` and `parent: null`, then the turns
  chained one under the other, `current_node` the last of them. *decided in brief `05`*

### The message

| Field | What | Mark |
| --- | --- | --- |
| `id` | the message's id, equal to its node's | *assumed* |
| `author` | `{ "role", "name", "metadata" }`; `role` is `system`, `user`, `assistant` or `tool`; `name` carries a tool's identity (`browser`, `python`, `dalle.text2im`, `bio`, `canmore.*`) and is otherwise `null` | *assumed* |
| `create_time`, `update_time` | as above, nullable | *assumed* |
| `content` | `{ "content_type", … }`, the payload key depending on the type (below) | *assumed* |
| `status` | `in_progress`, `finished_successfully`, `aborted`, `error` | *assumed* |
| `end_turn` | `true` on the message that ends a turn; `null` or `false` otherwise | *assumed* |
| `weight` | a number, `1.0` for ordinary messages | *assumed* |
| `metadata` | an object; carries `model_slug`, `attachments` and much else | *assumed* |
| `recipient` | `all` for a message a person sees; a tool's name for a message addressed to a tool — the hidden-message rule is "an assistant message whose recipient is not `all`" | *assumed* |
| `channel` | `null` in ordinary chats | *assumed* |

### Content types

Only `text` and `multimodal_text` carry `parts`; the others carry their payload under
another key, and a reader that expects `parts` everywhere is wrong.

| `content_type` | Payload | Example (redacted) | Mark |
| --- | --- | --- | --- |
| `text` | `parts`, a list of strings | `{"content_type": "text", "parts": ["…"]}` | *assumed* |
| `multimodal_text` | `parts`, strings and asset pointers | `{"content_type": "multimodal_text", "parts": [{"content_type": "image_asset_pointer", "asset_pointer": "sediment://file_…"}, "…"]}` | *assumed* |
| `code` | `text`, `language` | `{"content_type": "code", "language": "python", "text": "…"}` | *assumed* |
| `execution_output` | `text` | `{"content_type": "execution_output", "text": "…"}` | *assumed* |
| `tether_quote` | `text`, `title`, `url`, `domain` | — | *assumed* |
| `tether_browsing_display` | `result`, `summary` | — | *assumed* |
| `tether_browsing_code` | — | — | *assumed* |
| `system_error` | `text` | a tool's failure, e.g. a page that refused | *assumed* |
| `thoughts` | `thoughts`, a list of `{summary, content, chunks, finished}` | — | *assumed* |
| `reasoning_recap` | `content` | — | *assumed* |
| `user_editable_context` | `user_profile`, `user_instructions` | custom instructions | *assumed* |
| `model_editable_context` | `model_set_context` | memory | *assumed* |
| `sonic_webpage` | `url`, `domain`, `title`, `text`, `snippet`, `pub_timestamp` | a page fetched by web search, new in 2026 | *assumed* |

- Asset pointer parts carry their own `content_type`: `image_asset_pointer`,
  `audio_asset_pointer`, `audio_transcription`,
  `real_time_user_audio_video_asset_pointer`. *assumed*
- The mock writes `text` only. *decided in brief `05`*

### Attachments on a message

- A file is referenced two ways: `message.metadata.attachments[]`, each
  `{ "id", "name", "mime_type", "size", "source", "library_file_id" }`, and an asset
  pointer part whose `asset_pointer` is `sediment://file_<id>`; "in current exports every
  attachment reference sits on a user message". *assumed*
- The mock names an accepted file in `metadata.attachments` on the user message that
  carried it, with no bytes behind the id. *decided in brief `05`*

### Branching

- An edit or a regeneration is a sibling node under the same `parent`; `children` lists
  every branch, and `current_node` names the leaf of the one the page shows. *assumed*
- The active path — walk `parent` from `current_node` to the root — is the reading three
  parsers use. Whether the later importer takes it, and how it orders and counts what is
  off the path, is that brief's to decide, as `02` decided it for Claude. Not decided here.

### `user.json`

- One object: `{ "id", "email", "chatgpt_plus_user", "phone_number" }`, the `id` beginning
  `user-`. *assumed*
- The mock writes `id` and `email`, the id derived from the configured email so that the
  same account renders the same bytes. *decided in brief `05`*

## Refreshing this document

Read one real export, from a throwaway or a consenting account, and record its shape and
nothing of its content:

1. List the members with their sizes — `export_manifest.json`, if present, is that list.
2. For `conversations.json`: whether it is an array or an object; whether the export is
   split; the set of conversation fields; the set of message fields; the set of
   `content_type` values and, for each, its payload key; the roles; whether the root node
   has a message; the type of `create_time`.
3. For the attachments: whether `file_<id>.dat` members exist and how many, and whether
   `conversation_asset_file_names.json` names them.
4. Set **Export inspected** and **Export date** at the top and drop the status paragraph.
5. Change every line the reading confirms from *assumed* to *observed*, and correct the
   ones it refutes.
6. Open the slice that builds the mock's archive and change what it renders to match;
   then, when there is one, the tool's ChatGPT export model.

## Sources

Read on 2026-09-13. All but the last are parsers or readers of real exports, and the
claims above are what they agree on; the last is OpenAI's own, cited for the one thing
it says about the archive — that a large export is split over numbered files.

| Short name | What | Address | Date |
| --- | --- | --- | --- |
| nexus-ai-chat-importer | "ChatGPT export format (2026)", the August 2026 member inventory, the `.dat` assets and the name index; the quoted opening line | <https://github.com/Superkikim/nexus-ai-chat-importer/blob/main/docs/architecture/providers/chatgpt-export-format.md> | 2026 |
| convoviz | `docs/dev/chatgpt-spec.md` v3.0, the February 2026 member inventory, a schema of `conversations.json`, the hidden-message rule | <https://github.com/mohamed-chs/convoviz/blob/main/docs/dev/chatgpt-spec.md> | 2026-02-05 |
| chatgpt-exporter | `src/api.ts`, the `content_type` union and the author roles | <https://github.com/pionxzh/chatgpt-exporter/blob/master/src/api.ts> | read 2026-09-13 |
| obsidian-weaver | `src/interfaces/IConversation.ts`, typed conversation, node and message | <https://github.com/vasilecampeanu/obsidian-weaver/blob/master/src/interfaces/IConversation.ts> | read 2026-09-13 |
| open-chat-memory | a redacted sample `conversations.json`, the root node and a finished assistant node | <https://github.com/ndamulelonemakh/open-chat-memory/blob/main/docs/examples/openai-export-sample/conversations.json> | read 2026-09-13 |
| ChatGPT-Wrapped | `docs/export-data-schema.md`, the directory layout and `export_manifest.json` | <https://github.com/Systina12/ChatGPT-Wrapped/blob/main/docs/export-data-schema.md> | read 2026-09-13 |
| OpenAI 9106926 | "Transfer exported conversations between ChatGPT accounts": numbered conversation files in large exports | <https://help.openai.com/en/articles/9106926-transfer-exported-conversations-between-chatgpt-accounts> | read 2026-09-13 |
