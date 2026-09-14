# Rehearsal 03 — extraction

**Kind:** Rehearsal record — what a rehearsal measured, not what was designed.
Produced by [`46`](../specs/impl/46-extraction-rehearsal.md).
**Answers:** [§68](../specs/06-chatgpt-extraction.md)'s protocol against both mocks,
with numbers, and [§39](../specs/03-extraction-and-backup.md)'s questions 3 and 6 where
a mock can answer them.
**Rehearsal run:** 2026-09-14. **Mode:** `non-interactive`.
**Tool:** dataporter 0.1.0. **Scripted agent:** scripted agent 1.0.0. **Chrome:** Chrome/152.0.7977.84.
**Mock claude.ai:** 0.2.0. **Mock chatgpt.com:** 0.2.0.

An extraction rehearsal is §68's protocol run by the shipped tool against each
site's mock: the account seeded through the mock's own routes, then `login`, an
ask, the link read from the listing that stands in for the inbox, the fetch, a
second ask and a second fetch, `snapshots`, `session status`, `session logout`.
It is **not evidence about either site**: every `*unknown*` and `*reported*` row
of [`claude-ui-map.md`](claude-ui-map.md) and
[`chatgpt-ui-map.md`](chatgpt-ui-map.md) is what it was after it (§56). The
mock claude.ai's link is fetched without a browser, the mock chatgpt.com's
through the session (§63).

Nothing here carries conversation content or a link: the link is a credential
to the archive while it lives, and every place the runner wrote one it wrote
`<link>` (§66).

## The mock claude.ai

| | |
| --- | --- |
| Seeded | 3 chats, 1 file |
| Chrome extra arguments | `--host-resolver-rules=MAP claude.ai 127.0.0.1:8443`, `--ignore-certificate-errors-spki-list=thRpuSHnmbYOZd5VP0ng+E4/yArsC2yq5vpK+yjdmD8=`, `--no-proxy-server`, `--no-sandbox`, `--disable-gpu`, `--disable-dev-shm-usage` |

### The protocol

| Step | Exit | Seconds | Note |
| --- | --- | --- | --- |
| `setup` | 0 | 4.3 |  |
| `login` | 0 | 4.3 |  |
| `extract (ask 1)` | 0 | 3.1 |  |
| `extract --link (fetch 1)` | 0 | 0.3 |  |
| `extract (ask 2)` | 0 | 2.4 |  |
| `extract --link (fetch 2)` | 0 | 0.3 |  |
| `session status` | 0 | 2.4 |  |
| `session logout` | 0 | 0.3 |  |
| `snapshots` | 0 | 0.3 |  |

### The traces

| Step | Trace | Lines | Certificate | Agent |
| --- | --- | --- | --- | --- |
| `setup` | — | — | — | — |
| `login` | `traces/02-login.jsonl` | 22 | `claude.ai` | `hermes 1.0.0 (scripted agent)` |
| `extract (ask 1)` | `traces/03-extract--ask-1.jsonl` | 10 | `claude.ai` | `hermes 1.0.0 (scripted agent)` |
| `extract --link (fetch 1)` | — | — | — | — |
| `extract (ask 2)` | `traces/05-extract--ask-2.jsonl` | 10 | `claude.ai` | `hermes 1.0.0 (scripted agent)` |
| `extract --link (fetch 2)` | — | — | — | — |
| `session status` | — | — | — | — |
| `session logout` | — | — | — | — |
| `snapshots` | — | — | — | — |

### The blocks, and the ledger beside them

```text
Claude extraction — rehearsal

Export requested 2026-09-14 08:16 UTC.
Claude will email a download link to the account's address.
When it arrives:

  dataporter extract --source claude --account rehearsal --link <url>
```

```text
Claude extraction — rehearsal

Downloaded 0.0 MB.
Conversations: 3     Projects: 0     Memories: 0
Gaps: 2 files the export does not carry

Snapshot: /tmp/r3/store/claude/rehearsal/2026-09-14T08-16-54Z
```

```text
Claude extraction — rehearsal

Downloaded 0.0 MB.
Conversations: 3     Projects: 0     Memories: 0
Gaps: 2 files the export does not carry

Snapshot: /tmp/r3/store/claude/rehearsal/2026-09-14T08-16-56Z
```

```text
Mock claude.ai — ledger

Sign-ins:                      2
Chats created:                 3
Messages received:             3
Files accepted:                1
Renames:                       0
Exports requested:             2
```

### Pass criteria

| Criterion | Number | Verdict | Mark |
| --- | --- | --- | --- |
| login signs the source account in | exit 0 | pass | *measured on 2026-09-14* |
| both asks are taken and print the block | 2/2 asks | pass | *measured on 2026-09-14* |
| the mock minted one link per ask | 2 links listed, exports requested: 2 | pass | *measured on 2026-09-14* |
| both fetches file a complete snapshot | 2/2 fetches, 2 complete snapshots | pass | *measured on 2026-09-14* |
| the second stamp sorts after the first | 2026-09-14T08-16-54Z < 2026-09-14T08-16-56Z | pass | *measured on 2026-09-14* |
| ledger: conversations == chats created | [3, 3] == 3 (seeded 3) | pass | *measured on 2026-09-14* |
| ledger: the gap is the files the mock accepted, none of them carried | gaps [2, 2] == 1 × 2, files carried [None, None] | pass | *measured on 2026-09-14* |
| the first snapshot is unchanged by the second | archive and manifest hashes equal | pass | *measured on 2026-09-14* |
| snapshots lists both rows | 2 rows | pass | *measured on 2026-09-14* |
| the link is in no file the run left | none | pass | *measured on 2026-09-14* |
| one trace per step that drove a tab, each naming the source | [1, 1, 1] for 3 steps | pass | *measured on 2026-09-14* |
| ledger: sign-ins == the seeding's + the tool's password steps | 2 == 1 + 1 | pass | *measured on 2026-09-14* |

## The mock chatgpt.com

| | |
| --- | --- |
| Seeded | 3 chats, 1 file |
| Chrome extra arguments | `--host-resolver-rules=MAP chatgpt.com 127.0.0.1:8444, MAP auth.openai.com 127.0.0.1:8444`, `--ignore-certificate-errors-spki-list=4gLhR7kiVTf38ZwhdJ2MAXjYTWe21p8Gnq+zcz/e/9Q=`, `--no-proxy-server`, `--no-sandbox`, `--disable-gpu`, `--disable-dev-shm-usage` |

### The protocol

| Step | Exit | Seconds | Note |
| --- | --- | --- | --- |
| `login` | 0 | 3.2 |  |
| `extract (ask 1)` | 0 | 3.3 |  |
| `extract --link (fetch 1)` | 0 | 2.8 |  |
| `extract (ask 2)` | 0 | 2.5 |  |
| `extract --link (fetch 2)` | 0 | 2.3 |  |
| `session status` | 0 | 2.3 |  |
| `session logout` | 0 | 0.3 |  |
| `snapshots` | 0 | 0.3 |  |

### The traces

| Step | Trace | Lines | Certificate | Agent |
| --- | --- | --- | --- | --- |
| `login` | `traces/01-login.jsonl` | 26 | `chatgpt.com` | `hermes 1.0.0 (scripted agent)` |
| `extract (ask 1)` | `traces/02-extract--ask-1.jsonl` | 10 | `chatgpt.com` | `hermes 1.0.0 (scripted agent)` |
| `extract --link (fetch 1)` | `traces/03-extract---link--fetch-1.jsonl` | 6 | `chatgpt.com` | `hermes 1.0.0 (scripted agent)` |
| `extract (ask 2)` | `traces/04-extract--ask-2.jsonl` | 7 | — | `hermes 1.0.0 (scripted agent)` |
| `extract --link (fetch 2)` | `traces/05-extract---link--fetch-2.jsonl` | 6 | `chatgpt.com` | `hermes 1.0.0 (scripted agent)` |
| `session status` | — | — | — | — |
| `session logout` | — | — | — | — |
| `snapshots` | — | — | — | — |

### The blocks, and the ledger beside them

```text
ChatGPT extraction — rehearsal

Export requested 2026-09-14 08:17 UTC.
ChatGPT will email or text a download link to the account's address.
It can take up to 7 days. When it arrives:

  dataporter extract --source chatgpt --account rehearsal --link <url>
```

```text
ChatGPT extraction — rehearsal

Downloaded 0.0 MB.
Conversations: 3     Files: 0
Gaps: 1 file the export does not carry

Snapshot: /tmp/r3/store/chatgpt/rehearsal/2026-09-14T08-17-06Z
```

```text
ChatGPT extraction — rehearsal

Downloaded 0.0 MB.
Conversations: 3     Files: 0
Gaps: 1 file the export does not carry

Snapshot: /tmp/r3/store/chatgpt/rehearsal/2026-09-14T08-17-12Z
```

```text
Mock chatgpt.com — ledger

Sign-ins:                      2
Chats created:                 3
Messages received:             3
Files accepted:                1
Renames:                       0
Exports requested:             2
```

### Pass criteria

| Criterion | Number | Verdict | Mark |
| --- | --- | --- | --- |
| login signs the source account in | exit 0 | pass | *measured on 2026-09-14* |
| both asks are taken and print the block | 2/2 asks | pass | *measured on 2026-09-14* |
| the mock minted one link per ask | 2 links listed, exports requested: 2 | pass | *measured on 2026-09-14* |
| both fetches file a complete snapshot | 2/2 fetches, 2 complete snapshots | pass | *measured on 2026-09-14* |
| the second stamp sorts after the first | 2026-09-14T08-17-06Z < 2026-09-14T08-17-12Z | pass | *measured on 2026-09-14* |
| ledger: conversations == chats created | [3, 3] == 3 (seeded 3) | pass | *measured on 2026-09-14* |
| ledger: the gap is the files the mock accepted, none of them carried | gaps [1, 1] == 1 × 1, files carried [0, 0] | pass | *measured on 2026-09-14* |
| the first snapshot is unchanged by the second | archive and manifest hashes equal | pass | *measured on 2026-09-14* |
| snapshots lists both rows | 2 rows | pass | *measured on 2026-09-14* |
| the link is in no file the run left | none | pass | *measured on 2026-09-14* |
| one trace per step that drove a tab, each naming the source | [1, 1, 1, 1, 1] for 5 steps | pass | *measured on 2026-09-14* |
| ledger: sign-ins == the seeding's + the tool's password steps | 2 == 1 + 1 | pass | *measured on 2026-09-14* |
| the sign-in crossed to the auth host and both hosts were certified | crossed: True, certified: ['auth.openai.com', 'chatgpt.com'] | pass | *measured on 2026-09-14* |


**Verdict:** passed. *measured on 2026-09-14*

## What it found

- The seeding signs in to the mock through its own routes before the tool starts, and the mock counts that sign-in; the reconciliation of sign-ins reads `1 + the tool's password steps` rather than subtracting it silently.
- A file the mock claude.ai accepted is two gaps in the snapshot, because the Claude export names a file under both `files` and `files_v2` and `30` counts every reference; the mock chatgpt.com's is one. Neither carries bytes, which is the mocks' gap and not the exports'.
- The mock claude.ai's link is fetched with the mock's certificate trusted through `SSL_CERT_FILE`, written by the runner from the certificate the mock served; the mock chatgpt.com's is fetched through the session, and the tool is told to trust nothing.

## What it could not exercise

- Anything about claude.ai or chatgpt.com. A mock is a consequence of its UI
  map, never evidence about it (§56).
- An email: the mock lists its links where the inbox would be, and the runner
  reads the listing where a person would read a message.
- The 24-hour expiry of a link, an export already requested and still
  processing, a rate limit on asking: the mocks have no clock (§58).
- The auth host's real screens and the real Data controls path: the walk and
  the path are the mock's, and the first real run is what corrects them (§69).
- Whether the real ChatGPT link needs the session at all: the mock mirrors the
  documentation, and only a real link answers (§69).

