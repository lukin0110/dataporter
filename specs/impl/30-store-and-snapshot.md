# 30 — The store and the snapshot

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 03](../03-extraction-and-backup.md) §30, §31 (the fetch and the
filing; the ask is `31`'s), §32, §33, §37, §38
**Depends on:** [02](02-export-model.md), [23](23-library-operations.md)
**Enables:** [31](31-source-session-and-ask.md)
**Status:** Not started

## Goal

Everything of brief 03 that runs with no browser: a store on disk that never overwrites,
a snapshot filed from an archive the person already has or from the link the vendor
emailed, `snapshots` to list what the store holds, and `import`, `inspect` and `seeds`
reading a snapshot exactly as they read an export. The ask — signing in and pressing the
vendor's button — is `31`; here `extract` with no mode flag reports itself unbuilt.

## In scope

- **Configuration** (`config.py`):
  - `StoreSettings`: `dir: Path | None = None` (`[store] dir`, `DATAPORTER_STORE__DIR`)
    and `max_download_bytes: int = 5_000_000_000` (`ge=1`). `Settings.store_dir` is
    `dir` expanded and made absolute, else `~/.dataporter/store`.
  - `AccountsSettings`: `dir: Path | None = None` (`[accounts] dir`,
    `DATAPORTER_ACCOUNTS__DIR`). `Settings.accounts_dir` defaults to
    `~/.dataporter/accounts`.
  - `Settings.source: str = "claude"` and `Settings.account: str | None = None`, set for
    one invocation by `with_account(settings, source, account)` — a `model_copy` override
    in the `with_attachments_dir` family. Both join `NOT_IN_CONFIG_FILE` beside `auth`: a
    label in `config.toml` would silently redirect `login`. A source must match
    `^[a-z][a-z0-9-]*$` and be one of `store.SOURCES = ("claude",)`, else `ConfigError`
    `no such source: <token>`; a label must match `^[a-z0-9][a-z0-9._-]{0,63}$` and not
    be dots alone, else `ConfigError` `account label must be letters, digits, dots,
    dashes or underscores: <token>`.
  - `Settings.account_home`: `accounts_dir / source / account`, or `None` with no
    account. `Settings.logs_dir`: `account_home / "logs"` when an account is set, else
    the workspace. `log.enable_run_log` takes whichever it is given.
  - `TimeoutSettings.download_idle_s: float = 120.0` (`gt=0`). `urllib`'s timeout is per
    read, not per download, and the name says so.
  - `with_store_dir(settings, directory)` for `--store DIR`.
- **The store** (`store.py`, new): `<store>/<source>/<account>/<stamp>/`. `stamp_of(instant)`
  renders `YYYY-MM-DDTHH-MM-SSZ` in UTC to the second; `parse_stamp` reads it back. A
  snapshot is three files, created in this order, each with
  `os.open(path, O_CREAT | O_EXCL | O_WRONLY)` and never renamed, moved or appended to:
  `export.zip`, `snapshot.json`, `COMPLETE` (zero bytes). `export.zip` and
  `snapshot.json` are fsynced, then the directory, before `COMPLETE` is created: a marker
  that lands before the bytes are durable is a marker that lies after a power loss.
  `state.write_atomically` is not reused — it renames. The stamp directory is
  `mkdir(parents=True)`; one that exists raises `StoreError` `snapshot already exists:
  <path>` and nothing is written.
- **The manifest** (`store.Snapshot`, pydantic, `snapshot.json`): `version: 1`, `source`,
  `account`, `stamp`, `origin: "ask" | "link" | "file"`, `asked_at: datetime | None`,
  `filed_at`, `tool_version`, `archive: {name: "export.zip", bytes, sha256}`,
  `export_fingerprint` (the SHA-256 of `conversations.json`, the same number as
  `Export.fingerprint`), `counts: {conversations, projects, memories}` and
  `gaps: [{kind, count, reason}]`. The one gap kind today is `plan.BYTES_NOT_IN_EXPORT`,
  with count = every `attachments`, `files` and `files_v2` entry across all messages (the
  number `export.source._log_shape` already computes as `attachments`) and reason
  `the export does not carry file bytes`. No references, no gap.
- **The ask record** (`store.Ask`, `<account home>/ask.json`): `{asked_at, source,
  account, tool_version}`. `extract.py` owns it, not `Store`: it is operational,
  abandonable state, and a cloud store must never receive it. `31` writes it (`O_EXCL`);
  the fetch reads it and deletes it once `COMPLETE` has landed; `--abandon` deletes it.
- **Errors** (`errors.py`): `StoreError(UsageError)`, exit `2` — stamp exists, ask open,
  no ask to abandon, label or source invalid, store unwritable, snapshot incomplete.
  `FetchError(UsageError)`, exit `2` — link not `https`, an HTTP status (`link refused:
  HTTP 403 — the link may have expired; ask again with: dataporter extract --source claude
  --account <label>`), not a zip, no `conversations.json`, byte cap exceeded, SHA-256
  mismatch after the copy. `NetworkError` (exists, unmapped) for a `URLError`: `cli._RootGroup`
  gains the clause mapping it to `ENVIRONMENT` (`6`) — today it would exit `70`. A detail
  never carries `str(exc)` of an `HTTPError` or `URLError`, which can carry the URL; it
  carries `.code` or `.reason` only.
- **Output discipline** (`log.py`): `link` joins `FORBIDDEN_FIELDS`. Nothing is logged
  under `snapshot` (already forbidden: Hermes page snapshots). Records carry `stamp`,
  `source`, `account`, `bytes`, `origin`.
- **The fetch** (`extract.py`, new): `fetch(settings, link, *, open_url=urllib.request.urlopen,
  sink=DISCARD)`. The opener is the default one — proxies honoured, unlike
  `cdp._NO_PROXY`, which is right for a local browser and wrong for the internet. The
  link must be `https`; that is checked before any request. The body streams to
  `<account home>/tmp/<uuid4>.zip` while a SHA-256 runs, `max_download_bytes` is enforced
  on the stream, and `download_idle_s` is the socket timeout. The temp file is verified
  in place — `zipfile.is_zipfile`, then `ExportSource.open` and `read_export`, which
  yield the counts, the fingerprint and the gap count in one parse — and only then filed
  by `Store.file_archive`, which copies it into a fresh stamp directory and re-hashes the
  copy before writing the manifest. The temp file is unlinked in a `finally`. Stamp and
  origin: `ask.json` present → its `asked_at`, origin `ask`; absent → now, origin `link`,
  and the block gains the line `Filed without an ask on record.` `ask.json` is deleted
  after `COMPLETE`.
- **Filing a file**: `file(settings, path, *, sink)`. `.zip` only: a directory is refused
  with `--from takes the vendor's archive (.zip); a directory is not one` — the vendor's
  shape is the archive, and a tree has no `archive.sha256`. Same verification, origin
  `file`, stamp now.
- **Abandoning**: `abandon(settings, *, sink)` deletes `ask.json`; none there → `no ask
  is open for <source>/<account>`, exit `2`.
- **`extract`** (`cli.py`, one call, no control flow): `dataporter extract --source SRC
  --account LABEL [--link URL | --from PATH | --abandon] [--store DIR]`. `--source`
  defaults to `claude`; `--account` is required. The body is
  `extract.extract_command(settings, ExtractRequest(link, from_path, abandon), sink)`;
  the library picks the mode and refuses `--link` with `--from`, or `--abandon` with
  either, with `UsageError`, as `import_command` does for `--pilot`. No mode flag →
  `sink.note("not implemented in this build: extract (the ask)")` and
  `ExitCode.NOT_IMPLEMENTED`, until `31` fills it. Golden fetch block, brief §31:

  ```text
  Claude extraction — old-personal

  Downloaded 41.3 MB.
  Conversations: 127     Projects: 4     Memories: 1
  Gaps: 38 files the export does not carry

  Snapshot: ~/.dataporter/store/claude/old-personal/2026-09-12T20-51-07Z

  ```

  `Downloaded` is base-10 megabytes to one decimal; the `Gaps:` line is omitted at zero;
  `Filed without an ask on record.` follows `Downloaded` when there was no ask; `--from`
  prints `Filed <name>.` in place of `Downloaded …`. The path is printed as configured,
  `~` unexpanded when the default was used. Constants live beside the function that
  prints them.
- **`snapshots`** (`cli.py` → `store.list_command(settings, *, json_output, sink)`):
  `dataporter snapshots [--json] [--store DIR]`. Walks `<source>/<account>/<stamp>` and
  nothing else; a stamp directory without `COMPLETE` is `incomplete`, one whose manifest
  will not parse is `unreadable`. Golden block, brief §33, label column padded to the
  longest label, count right-aligned:

  ```text
  claude/old-personal   2026-09-12T20-51-07Z   127 conversations   complete
  claude/old-personal   2026-10-01T03-00-00Z   131 conversations   complete
  chatgpt/work          2026-09-30T18-12-44Z    88 conversations   2 gaps

  ```

  An empty store prints `No snapshots in <store>.` and exits `0`: nothing there is an
  answer, as `status` on an empty workspace is. `--json` emits a list of `SnapshotRow`.
- **Import from a snapshot** (`export/source.py`): `ExportSource.open` gains a first
  branch — a directory holding `snapshot.json` is a `_SnapshotSource`, which refuses a
  missing `COMPLETE` with `ExportError` `snapshot is incomplete: <display>` and delegates
  `names`, `read` and `is_archive` to a `_ZipSource` over `export.zip`. `read_export` is
  untouched, so `names()`, `unsupported` and `fingerprint` are the inner archive's.
  `export.model.Export` gains `projects: int = 0` and `memories: int = 0`, counts only,
  set in `read_export` from what `_optional_list` already reads, so the manifest comes
  from one parse. `inspect`, `seeds`, `import --dry-run`, `import` and `resume` take a
  snapshot path wherever they take an export path.
- **The workspace guard** (`importer.import_command`, `seed.write_seeds`): a workspace
  inside the snapshot directory is refused with `UsageError` `the workspace cannot be
  inside a snapshot: <path>`. `ensure_gitignore` and `state` would otherwise write into a
  finished snapshot.
- **Documentation**: `README.md` gains the two commands and the store's location;
  `docs/LIMITATIONS.md` gains the two limits under *Risks*.
- **Tests**:
  - `tests/test_store.py` — the layout; stamps round-trip; the write order and the
    marker; an existing stamp refused with nothing written; listing with `complete`,
    `<n> gaps`, `incomplete` and `unreadable` rows; the golden block on the brief's three
    rows; never a rename, proven by a monkeypatched `os.replace` and `os.rename` that
    raise for the duration of a filing.
  - `tests/test_extract.py` — the fetch with an injected `open_url`: a `BytesIO` body
    files a snapshot; an `HTTPError(403)` and a `URLError` take their exits and create
    nothing; `http://` is refused before `open_url` is called; a body one byte over a
    tiny `max_download_bytes` exits `2` and leaves no temp file; a body that is not a zip
    or has no `conversations.json` likewise; an open `ask.json` sets the stamp and is
    gone afterwards; no ask prints the `Filed without an ask` line; `--from` with a zip,
    and refused with a directory; `--abandon` with and without an ask; the two flag
    combinations refused; the link appears in no stdout line, no stderr line and no run
    log record; `export.zip` is byte-identical to the input.
  - `tests/test_export_source.py` — a snapshot and its archive parse to identical
    `model_dump_json()`; `snapshot.json` and `COMPLETE` are never `unknown_file`; a
    snapshot without `COMPLETE` is refused; `projects` and `memories` are counted.
  - `tests/test_operations.py` — parity for `extract --from`, `extract --abandon`,
    `snapshots` and `snapshots --json`.
  - `tests/test_cli.py` — `COMMANDS` gains `extract` and `snapshots`; the interface test
    still passes.
  - `tests/test_config.py` — the new keys and their environment spellings; `source` and
    `account` refused in `config.toml`; label and source validation.
  - `tests/test_log.py` — `link` is a forbidden field.
  - One `slow` test serves the fixture zip from a local HTTP server and fetches it
    through the real `urlopen`, for the streaming path.

## Out of scope

- The ask — signing in to the source account and pressing the vendor's button —
  and everything about a browser: [31](31-source-session-and-ask.md).
- A cloud store, sharing bytes between snapshots, retention, encryption, the inbox, and
  reading the account through its pages: brief §40.
- Attachment bytes in a snapshot. A Claude export carries none, so the snapshot records
  the gap; `16`'s `--attachments-dir` still works beside a snapshot as beside an export.

## Design notes

- **Vendor-native, never normalised.** The archive is kept byte for byte and everything
  of ours sits beside it. ADR [0005](../../docs/adr/0005-snapshots-are-vendor-native.md).
- **Download to a temp file, verify, then copy.** Brief §33 forbids renames in the store
  so that an object store can be a second writer of the same layout. Streaming straight
  into the stamp directory would turn every refused link — an expired one, a wrong one —
  into an incomplete snapshot, which §31's "the ask stays open so the person can try
  again" argues against. The temp file lives under the account home, outside the store,
  so unlinking it is not a store operation, and the copy is a fresh `O_EXCL` create.
  Cost: twice the disk for the duration of one filing. Accepted.
- **`ask.json` lives in the account home, not the store.** §31 says the tool remembers
  the ask; §33 does not say where. The store's contract — created once, marker last,
  never deleted — fits an abandonable record badly, and cookies, logs and open asks are
  exactly what a cloud store must never receive. The account home is that operational
  place, and `31` puts the source session's profile beside it.
- **`_SnapshotSource` wraps rather than `KNOWN_FILES` widening.** Adding `snapshot.json`
  and `COMPLETE` to the known members would make them part of the export and change
  `unsupported`; wrapping keeps `names()`, `read()` and therefore the fingerprint the
  archive's own, which is what makes §39's question 3 — the same dry run as the archive
  given directly — true by construction rather than by test.
- **Exit `2` for a dead link.** An expired or wrong link is the operator's to fix by
  asking again; `ENVIRONMENT` means the machine is missing something, and `_RootGroup`
  points the operator at `doctor` for it. Only "no network at all" is `6`.
- **`--from` takes a zip and nothing else.** An extracted directory is accepted by
  `import` because a person may have unpacked one; a snapshot is the vendor's archive
  and a tree has no bytes to hash.
- **The workspace guard, not a workspace beside the snapshot.** Brief §33 and
  `CONTEXT.md` say a migration's workspace is "beside" what it migrates; the code's
  default is `./migration` relative to the current directory and the export path never
  reaches workspace resolution. Deriving the workspace from the export would need the
  export path in the config bootstrap pass, which reads `config.toml` from the workspace
  it is deriving. What §33 actually requires is that the store holds nothing a
  migration writes, and a guard enforces exactly that.
- **`resume` needs no change.** `run.json` records the resolved snapshot path and the
  fingerprint is the inner archive's, so a workspace begun from the raw export accepts
  its snapshot on `resume`, and the reverse. That is a feature: the two are the same
  export.
- **An incomplete stamp is the operator's to remove.** A copy that fails midway leaves
  the stamp directory without `COMPLETE`; the next fetch under the same ask computes the
  same stamp and is refused. The tool never deletes from the store, so the refusal names
  the directory and says to remove it by hand. Rare, visible, and recorded in
  `LIMITATIONS.md`.

## Acceptance criteria

- `dataporter extract --source claude --account a --from export-small.zip` into an empty
  store exits `0`, prints the fetch block byte for byte with the fixture's numbers, and
  leaves exactly `export.zip`, `snapshot.json` and `COMPLETE` under
  `<store>/claude/a/<stamp>/`, with `export.zip` byte-identical to the input and the
  manifest's `sha256` equal to it.
- The same command a second time within the same stamp exits `2` with `snapshot already
  exists: <path>` and changes nothing under the store.
- `--link` with an injected opener answering `403` exits `2` with the `link refused` line,
  creates nothing under the store and leaves `ask.json` in place. With a good body and an
  open ask, the stamp equals `asked_at` to the second, the manifest says `origin: ask`,
  and `ask.json` is gone afterwards. With no ask, the manifest says `origin: link` and
  the block carries `Filed without an ask on record.`
- `--link http://…` exits `2` and the injected opener was never called.
- A body larger than `max_download_bytes` exits `2` and leaves nothing under the account
  home's `tmp/`.
- `snapshots` over the brief's three example snapshots renders the §33 block byte for
  byte; over an empty store prints `No snapshots in <store>.` and exits `0`; `--json`
  round-trips through `SnapshotRow.model_validate_json`.
- `inspect <snapshot>` and `inspect <archive>` print identical blocks and identical
  `--json`; `import --dry-run` likewise; a snapshot without `COMPLETE` exits `2` with
  `snapshot is incomplete`.
- `import <snapshot> --workspace <snapshot>/migration` exits `2` and writes nothing.
- `extract --source claude --account a` with no mode flag exits `69` with the
  not-implemented note; `--source chatgpt` exits `2` with `no such source: chatgpt`;
  `--account 'Old Personal'` exits `2` with the label message.
- No run-log record, no stdout line and no stderr line carries the link, an email, a
  title or any message content, under the suite's strict content guard.
- Every `extract` mode and `snapshots` reproduce the CLI's stdout, stderr and exit code
  when called as library operations.

## Risks

- **The real export's shape is still assumed.** `02` is `In progress` and
  `docs/export-format.md` has read no real archive. If the real zip wraps its members in
  a directory, `_ZipSource` already strips it; if it is not a zip at all, the fetch's
  verification refuses it and this slice learns that on the first real link.
- **The link's host is not pinned.** A vendor's download link may be a signed URL on a
  storage host, so the fetch checks the scheme and the content, not the host. A wrong
  link that leads to a valid export of somebody else's account would be filed. The
  `--account` label is the operator's word for whose it is.
- **Large archives.** Twice the bytes on disk for one filing, and a SHA-256 over them
  twice. A multi-gigabyte export is minutes, not hours; the byte cap is the ceiling.
