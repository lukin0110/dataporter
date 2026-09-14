# 43 — The ChatGPT archive

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 06](../06-chatgpt-extraction.md) §59 (the refusals), §64; brief 03
§32 (the vendor's shape)
**Depends on:** [42](42-source-seam.md), [30](30-store-and-snapshot.md),
[`docs/chatgpt-export-format.md`](../../docs/chatgpt-export-format.md)
**Enables:** [44](44-chatgpt-session-and-ask.md), [45](45-fetch-through-the-session.md)
**Status:** Done

## Goal

The half of ChatGPT that needs no browser: a ChatGPT archive recognised by its members,
counted, its one gap found, filed with `--from` and listed by `snapshots`; and the two
refusals — a Claude archive handed to `--source chatgpt` named for what it is, and a
ChatGPT snapshot or zip refused by `import` and `inspect` with ADR 0005's reason. The
source is registered here; its ask and its fetch answer `not implemented` until `44` and
`45`.

## In scope

- **The reader** (`export/chatgpt.py`, new): `looks_like(names)` — `user.json`, or a
  numbered `conversations-NNN.json` member; `conversation_members(names, display)` —
  `conversations.json`, else the split members in the order their names sort;
  `is_file(name)` — a member whose base name is not `.json` and not `chat.html`;
  `read(view) -> Reading`: every conversation member parsed as a JSON array, or the rare
  object wrapping one under `conversations`, each item an object with a `mapping`
  (`Envelope`, pydantic, `extra="ignore"`, and nothing else modelled); `user.json` an
  object if present; **conversations** counted; **files** the members `is_file` says;
  **missing files** the attachment keys `message.metadata.attachments[].id` names
  (`file-<key>` or `file_<key>`, order-preserving unique) that no file member's name
  holds; the fingerprint the SHA-256 over the conversation members' bytes in name order.
  Every refusal is an `ExportError` with the member and position, in the reader's
  existing wording. `users.json` in the names, or `chat_messages` on a conversation, is
  refused as `the archive looks like a Claude export, not a ChatGPT one: <display>`.
- **The source** (`sources/chatgpt.py`, registered): `chatgpt` / `ChatGPT`, hosts
  `chatgpt.com` and `auth.openai.com`, `login_url` the root, sign-in paths the root,
  `/auth/login` and `/auth/callback`, the export page `/settings/data-controls`, the
  five selectors of §61 and §62 as the tool's re-typing of the map's rows,
  `fetch_needs_session`, `signed_out_at_root`, `unattended_signin="walk"`, the two
  sentences of §60's block, `Conversations: {conversations}     Files: {files}`, and
  the `login` prompt. `store.SOURCES` is `("claude", "chatgpt")`.
- **The manifest** (`store.Counts.files`): `int | None`, written only when set, so a
  Claude manifest is byte-identical to `30`'s; `version` stays `1`.
- **The filing** (`extract.py`): `_read` asks `sources.recognised(names)` before reading
  and refuses an archive that is another source's — `the archive looks like a {looks}
  export, not a {asked} one: {display}`, exit `2`, nothing filed — in both directions;
  `_filing` carries `files`. The block, golden:

  ```text
  ChatGPT extraction — work

  Filed chatgpt-small.zip.
  Conversations: 3     Files: 2
  Gaps: 2 files the export does not carry

  Snapshot: ~/.dataporter/store/chatgpt/work/2026-09-30T18-12-44Z
  ```

  `--from` is the only mode that works for ChatGPT in this slice: the ask and `--link`
  print `not implemented in this build: the ChatGPT ask` / `… a fetch through the ChatGPT
  session` on stderr and exit `69`, `30`'s answer for a mode a later slice builds.
- **The refusals** (`export/source.py`): `IMPORTABLE = {"claude"}`; `read_export`
  refuses names `chatgpt.looks_like` claims, and `_SnapshotSource` refuses a manifest
  whose source is not importable, both with `{what} cannot be imported by this build
  ({display}); a snapshot of a source the tool cannot import is still a backup (ADR
  0005)` — exit `2` through `inspect`, `import`, `import --dry-run`, `seeds`, `resume`.
  `store.read_manifest` is public, since the reader is its second caller.
- **Fixtures** (`tests/fixtures/chatgpt-small/`, `chatgpt-split/`), written by hand from
  the format document and never from the mock's renderer (ADR 0003): three
  conversations, one with two attachments — one carried as `file-aaaa1111.dat`, one not —
  one with a `multimodal_text` part and an archived flag, one with a third missing
  attachment; `user.json`, `chat.html`, `message_feedback.json`,
  `conversation_asset_file_names.json`, `dalle-generations/a.png`. The split fixture has
  two numbered members and three conversations. `conftest.zip_tree` zips a fixture with
  its directories.
- **Tests** (`tests/test_chatgpt_archive.py`, fast): recognised by names; the fixture's
  numbers; `is_file`; the split members counted and hashed in name order however the zip
  lists them; the wrapped shape; a referenced attachment with no member is a gap and a
  carried one is not, under either spelling and under a media directory; an attachment
  without a file id is not counted; `user.json` read only far enough to be an object;
  every refusal's line; the golden `--from` block; the manifest's `counts` and `gaps`;
  a Claude manifest without a `files` key; both wrong-source refusals before anything is
  filed; the `snapshots` row; the two not-yet lines; the ADR line from `load_export` on a
  zip and on a snapshot, and exit `2` through `inspect` and `import --dry-run`.

## Out of scope

- The ask, the session and the fetch: `44`, `45`.
- Modelling messages, content types, branches: a ChatGPT importer's brief (§71).
- What a ChatGPT account holds that no export carries: *unknown*, `LIMITATIONS.md` (`47`).

## Design notes

- **Recognised by names, refused by shape.** Names route — `user.json` against
  `users.json` — and the shape check inside each reader is what names the other source
  honestly when the names lied.
- **The fingerprint over concatenated sorted members.** One rule that collapses to
  Claude's for one member and does not depend on the order a zip lists the split ones.
  Rejected: the SHA-256 of `export_manifest.json`, which is not always present.
- **`Files` counts members, `Gaps` counts ids.** A file member may carry an id nobody
  refers to, and a referred id may be carried under `user-<id>/…`; membership by key
  anywhere in the name is the honest rule until a real export is read.
- **The ADR line lives in `export/source.py`** so every reading command refuses
  identically; `extract` names the source the archive looks like instead, because
  "cannot be imported" is not what an operator filing an archive asked about.
- **Registered before its browser half.** `--from`, `snapshots` and the refusals need the
  name; the ask and the fetch say `not implemented` rather than drive a page with a
  sign-in the tool cannot walk yet. Keyed on the source's own facts —
  `unattended_signin == "walk"`, `fetch_needs_session` — which `44` and `45` take over.
- **`exclude_if` on `Counts.files`** rather than `exclude_none` on the manifest, which
  would also drop `asked_at: null` and change every snapshot filed without an ask.

## Acceptance criteria

- `extract --source chatgpt --account work --from chatgpt-small.zip` exits `0`, prints
  the block above with the fixture's numbers, and the manifest carries
  `counts.files: 2` and one gap of two.
- The split fixture counts three and its fingerprint is `sha256(b001 + b002)`.
- `--source chatgpt --from export-small.zip` and `--source claude --from
  chatgpt-small.zip` exit `2` naming the source each looks like, and the store is empty.
- `inspect` and `import --dry-run` on a ChatGPT snapshot, and `inspect` on the zip, exit
  `2` with the ADR line and write nothing.
- A Claude `snapshot.json` written by this build has no `files` key.
- `extract --source chatgpt --account work` and `… --link <url>` exit `69` with the
  not-yet line.
- *(Live, `46`'s.)* The extraction rehearsal files the mock chatgpt.com's archive
  through this reader; that is what turns this slice `Done`.
  Met on 2026-09-14: the extraction rehearsal (`46`, [`docs/rehearsal-03.md`](../../docs/rehearsal-03.md)) filed the mock chatgpt.com's archive through this reader, twice; `Done`.

## Risks

- **Every shape claim is assumed.** A real export whose `conversations.json` is something
  else fails the recogniser loudly, exit `2`, with the member and position — which is the
  intended first-run surface (§69), not a fallback.
- **A key that is a substring of another.** `file-ab` would be "carried" by
  `file-abc.dat`. Real ids are long and random; the rule is named so a reader of a real
  export can check it.
