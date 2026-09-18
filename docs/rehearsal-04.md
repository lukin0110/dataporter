# Rehearsal 04 — extraction

**Kind:** Rehearsal record — what a rehearsal measured, not what was designed.
Produced by [`46`](../specs/impl/46-extraction-rehearsal.md).
**Answers:** [§68](../specs/06-chatgpt-extraction.md)'s protocol against both mocks,
with numbers, and [§39](../specs/03-extraction-and-backup.md)'s questions 3 and 6 where
a mock can answer them.
**Rehearsal run:** 2026-09-18. **Mode:** `non-interactive`.
**Tool:** dataporter 0.1.0. **Scripted agent:** scripted agent 1.0.0. **Chrome:** Chrome/153.0.8010.48.
**Mock claude.ai:** 0.2.0. **Mock chatgpt.com:** 0.2.0.

An extraction rehearsal is §68's protocol run by the shipped tool against each
site's mock: the account seeded through the mock's own routes, then `login`, an
ask, the link read from the listing that stands in for the inbox, the fetch —
and, on the mock claude.ai, `extract-skills` into that snapshot, into it again,
and into one of its own (`67`) — a second ask and a second fetch, `snapshots`,
`session status`, `logout`.
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
| Chrome extra arguments | `--no-proxy-server`, `--no-sandbox`, `--disable-gpu`, `--disable-dev-shm-usage` |

### The protocol

| Step | Exit | Seconds | Note |
| --- | --- | --- | --- |
| `login` | 0 | 9.7 |  |
| `login --link` | 0 | 1.1 |  |
| `extract (ask 1)` | 0 | 1.3 |  |
| `extract --link (fetch 1)` | 0 | 2 |  |
| `extract-skills (into the first snapshot)` | 0 | 2.2 |  |
| `extract-skills (again)` | 2 | 2.8 | refused: the files are already there |
| `extract-skills (a snapshot of its own)` | 0 | 2.5 |  |
| `extract (ask 2)` | 0 | 1.4 |  |
| `extract --link (fetch 2)` | 0 | 2.2 |  |
| `session status` | 0 | 1 |  |
| `logout` | 0 | 0.4 |  |
| `snapshots` | 0 | 0.3 |  |

### The traces

| Step | Trace | Lines | Certificate | Agent |
| --- | --- | --- | --- | --- |
| `login` | `traces/02-login.jsonl` | 13 | — | `hermes 1.0.0 (scripted agent)` |
| `login --link` | `traces/01-login---link.jsonl` | 14 | — | `hermes 1.0.0 (scripted agent)` |
| `extract (ask 1)` | `traces/03-extract--ask-1.jsonl` | 8 | — | `hermes 1.0.0 (scripted agent)` |
| `extract --link (fetch 1)` | `traces/04-extract---link--fetch-1.jsonl` | 11 | — | `hermes 1.0.0 (scripted agent)` |
| `extract-skills (into the first snapshot)` | `traces/05-extract-skills--into-the-first-snapshot.jsonl` | 23 | — | `hermes 1.0.0 (scripted agent)` |
| `extract-skills (again)` | `traces/06-extract-skills--again.jsonl` | 23 | — | `hermes 1.0.0 (scripted agent)` |
| `extract-skills (a snapshot of its own)` | `traces/07-extract-skills--a-snapshot-of-its-own.jsonl` | 23 | — | `hermes 1.0.0 (scripted agent)` |
| `extract (ask 2)` | `traces/08-extract--ask-2.jsonl` | 8 | — | `hermes 1.0.0 (scripted agent)` |
| `extract --link (fetch 2)` | `traces/09-extract---link--fetch-2.jsonl` | 11 | — | `hermes 1.0.0 (scripted agent)` |
| `session status` | — | — | — | — |
| `logout` | — | — | — | — |
| `snapshots` | — | — | — | — |

### The blocks, and the ledger beside them

```text
Claude extraction — rehearsal

Export requested 2026-09-18 08:52 UTC.
Claude will email a download link to the account's address.
When it arrives:

  dataporter extract --source claude --account rehearsal --link <url>
```

```text
downloaded  manifest.json  647.0 B
downloaded  light_metadata-000.zip  245.0 B
downloaded  conversations-000.zip  938.0 B
Claude extraction — rehearsal

Downloaded 0.0 MB in 2s.
Conversations: 3     Projects: 0     Memories: 0
Gaps: 2 files the export does not carry

Snapshot: /tmp/r4/store/claude/rehearsal/2026-09-18T08-52-50Z
```

```text
downloaded  research-helper.skill  231.0 B
downloaded  standup-notes.skill  226.0 B
downloaded  plugin-helper.skill  228.0 B
Claude skills — rehearsal

Downloaded 3 skills in 2s.
3 skills.
Gaps: 1 skill could not be downloaded

Snapshot: /tmp/r4/store/claude/rehearsal/2026-09-18T08-52-50Z/skills
```

```text
downloaded  research-helper.skill  231.0 B
downloaded  standup-notes.skill  226.0 B
downloaded  plugin-helper.skill  228.0 B
Claude skills — rehearsal

Downloaded 3 skills in 2s.
3 skills.
Gaps: 1 skill could not be downloaded

Snapshot: /tmp/r4/store/claude/rehearsal/2026-09-18T08-52-58Z/skills
```

```text
downloaded  manifest.json  647.0 B
downloaded  light_metadata-000.zip  245.0 B
downloaded  conversations-000.zip  938.0 B
Claude extraction — rehearsal

Downloaded 0.0 MB in 2s.
Conversations: 3     Projects: 0     Memories: 0
Gaps: 2 files the export does not carry

Snapshot: /tmp/r4/store/claude/rehearsal/2026-09-18T08-53-01Z
```


```text
Mock claude.ai — ledger

Sign-ins:                      2
Chats created:                 3
Messages received:             3
Files accepted:                1
Renames:                       0
Exports requested:             2
Sign-in links minted:          2
Skill lists read:              3
Skills served:                 9
```

### Pass criteria

| Criterion | Number | Verdict | Mark |
| --- | --- | --- | --- |
| login signs the source account in | exit 0, login --link exit 0 | pass | *measured on 2026-09-18* |
| both asks are taken and print the block | 2/2 asks | pass | *measured on 2026-09-18* |
| the mock minted one link per ask | 2 links listed, exports requested: 2 | pass | *measured on 2026-09-18* |
| both fetches file a complete snapshot | 2/2 fetches, 2 complete snapshots | pass | *measured on 2026-09-18* |
| the second stamp sorts after the first | 2026-09-18T08-52-50Z < 2026-09-18T08-53-01Z | pass | *measured on 2026-09-18* |
| ledger: conversations == chats created | [3, 3] == 3 (seeded 3) | pass | *measured on 2026-09-18* |
| ledger: the gap is the files the mock accepted, none of them carried | gaps [2, 2] == 1 × 2, files carried [None, None] | pass | *measured on 2026-09-18* |
| the first snapshot is unchanged by the second | archive and manifest hashes equal | pass | *measured on 2026-09-18* |
| snapshots lists every row | 3 rows, 3 expected | pass | *measured on 2026-09-18* |
| the link is in no file the run left | none | pass | *measured on 2026-09-18* |
| one trace per step that drove a tab, each naming the source | [1, 1, 1, 1, 1, 1, 1, 1, 1] for 9 steps | pass | *measured on 2026-09-18* |
| ledger: sign-ins == the seeding's + the tool's | 2 == 1 + 1 (a link spent) | pass | *measured on 2026-09-18* |
| login saw the link sent and said so | the line is in its stdout | pass | *measured on 2026-09-18* |
| ledger: sign-in links minted == the seeding's + the tool's | 2 == 1 + 1 | pass | *measured on 2026-09-18* |
| extract-skills files the account's own skills beside the archive | ['plugin-helper', 'research-helper', 'standup-notes'] == ['plugin-helper', 'research-helper', 'standup-notes'], counts.skills 3 | pass | *measured on 2026-09-18* |
| the append left the archive untouched | archive hash equal | pass | *measured on 2026-09-18* |
| a second extract-skills into the same stamp is refused | exit 2 | pass | *measured on 2026-09-18* |
| a snapshot of the skills alone is complete and listed | 1 skills-only snapshot(s), ['plugin-helper', 'research-helper', 'standup-notes'], listed as skills: True | pass | *measured on 2026-09-18* |
| the gap is the one skill the mock refused | gaps [1, 1] == 1 refused (broken-skill) | pass | *measured on 2026-09-18* |
| ledger: the mock served only the skills the account wrote, once per run | lists read 3 == 3, served 9 == 3 × 3 | pass | *measured on 2026-09-18* |
| no skill's name is in a trace | none | pass | *measured on 2026-09-18* |

## The mock chatgpt.com

| | |
| --- | --- |
| Seeded | 3 chats, 1 file |
| Chrome extra arguments | `--no-proxy-server`, `--no-sandbox`, `--disable-gpu`, `--disable-dev-shm-usage` |

### The protocol

| Step | Exit | Seconds | Note |
| --- | --- | --- | --- |
| `login` | 0 | 2.3 |  |
| `extract (ask 1)` | 0 | 2.2 |  |
| `extract --link (fetch 1)` | 0 | 1.4 |  |
| `extract (ask 2)` | 0 | 1.1 |  |
| `extract --link (fetch 2)` | 0 | 1.3 |  |
| `session status` | 0 | 1.1 |  |
| `logout` | 0 | 0.3 |  |
| `snapshots` | 0 | 0.3 |  |

### The traces

| Step | Trace | Lines | Certificate | Agent |
| --- | --- | --- | --- | --- |
| `login` | `traces/01-login.jsonl` | 24 | — | `hermes 1.0.0 (scripted agent)` |
| `extract (ask 1)` | `traces/02-extract--ask-1.jsonl` | 7 | — | `hermes 1.0.0 (scripted agent)` |
| `extract --link (fetch 1)` | `traces/03-extract---link--fetch-1.jsonl` | 5 | — | `hermes 1.0.0 (scripted agent)` |
| `extract (ask 2)` | `traces/04-extract--ask-2.jsonl` | 7 | — | `hermes 1.0.0 (scripted agent)` |
| `extract --link (fetch 2)` | `traces/05-extract---link--fetch-2.jsonl` | 5 | — | `hermes 1.0.0 (scripted agent)` |
| `session status` | — | — | — | — |
| `logout` | — | — | — | — |
| `snapshots` | — | — | — | — |

### The blocks, and the ledger beside them

```text
ChatGPT extraction — rehearsal

Export requested 2026-09-18 08:53 UTC.
ChatGPT will email or text a download link to the account's address.
It can take up to 7 days. When it arrives:

  dataporter extract --source chatgpt --account rehearsal --link <url>
```

```text
downloaded  export.zip  1.5 KB
ChatGPT extraction — rehearsal

Downloaded 0.0 MB in 1s.
Conversations: 3     Files: 0
Gaps: 1 file the export does not carry

Snapshot: /tmp/r4/store/chatgpt/rehearsal/2026-09-18T08-53-09Z
```

```text
downloaded  export.zip  1.5 KB
ChatGPT extraction — rehearsal

Downloaded 0.0 MB in 1s.
Conversations: 3     Files: 0
Gaps: 1 file the export does not carry

Snapshot: /tmp/r4/store/chatgpt/rehearsal/2026-09-18T08-53-12Z
```


```text
Mock chatgpt.com — ledger

Sign-ins:                      2
Chats created:                 3
Messages received:             3
Files accepted:                1
Renames:                       0
Exports requested:             2
Sign-in links minted:          0
Skill lists read:              0
Skills served:                 0
```

### Pass criteria

| Criterion | Number | Verdict | Mark |
| --- | --- | --- | --- |
| login signs the source account in | exit 0 | pass | *measured on 2026-09-18* |
| both asks are taken and print the block | 2/2 asks | pass | *measured on 2026-09-18* |
| the mock minted one link per ask | 2 links listed, exports requested: 2 | pass | *measured on 2026-09-18* |
| both fetches file a complete snapshot | 2/2 fetches, 2 complete snapshots | pass | *measured on 2026-09-18* |
| the second stamp sorts after the first | 2026-09-18T08-53-09Z < 2026-09-18T08-53-12Z | pass | *measured on 2026-09-18* |
| ledger: conversations == chats created | [3, 3] == 3 (seeded 3) | pass | *measured on 2026-09-18* |
| ledger: the gap is the files the mock accepted, none of them carried | gaps [1, 1] == 1 × 1, files carried [0, 0] | pass | *measured on 2026-09-18* |
| the first snapshot is unchanged by the second | archive and manifest hashes equal | pass | *measured on 2026-09-18* |
| snapshots lists every row | 2 rows, 2 expected | pass | *measured on 2026-09-18* |
| the link is in no file the run left | none | pass | *measured on 2026-09-18* |
| one trace per step that drove a tab, each naming the source | [1, 1, 1, 1, 1] for 5 steps | pass | *measured on 2026-09-18* |
| ledger: sign-ins == the seeding's + the tool's | 2 == 1 + 1 (password steps) | pass | *measured on 2026-09-18* |
| the sign-in crossed to the auth origin | /log-in seen 10x | pass | *measured on 2026-09-18* |


**Verdict:** passed. *measured on 2026-09-18*

## What it found

- The seeding signs in to the mock through its own routes before the tool starts, and the mock counts that sign-in; the reconciliation of sign-ins reads `1 + the tool's` — a password typed on the mock chatgpt.com, a link spent on the mock claude.ai — rather than subtracting it silently.
- The mock claude.ai's sign-in is brief 07's two commands: `login` runs in the background, the runner enters the address at its window as a person would, and `login --link` spends the link the mock minted where an email would go. Both steps leave a trace, told apart by the header's `flags`.
- A file the mock claude.ai accepted is two gaps in the snapshot, because the Claude export names a file under both `files` and `files_v2` and `30` counts every reference; the mock chatgpt.com's is one. Neither carries bytes, which is the mocks' gap and not the exports'.
- Both mocks' links are fetched through the source session's own browser, pointed at the mock by `--mock` and by nothing else: the mocks serve plain HTTP on loopback and there is no certificate anywhere (`65`). The mock claude.ai's link is an index naming a zip per category, and each of those may be taken once — so a fetch that is retried against the same link fails here exactly as it does on the real site.
- The mock claude.ai's account holds six skills seeded as a mix — four the account wrote, one of Anthropic's, one with a `creator_type` the tool does not know — and one of the four answers `500`. `extract-skills` runs three times: the store takes the first, refuses the second, and files the third on its own; the witness says only the account's own were ever served, once per run, and the refused one is one gap in each snapshot (`67`).

## What it could not exercise

- Anything about claude.ai or chatgpt.com. A mock is a consequence of its UI
  map, never evidence about it (§56).
- An email: the mock lists its links where the inbox would be, and the runner
  reads the listing where a person would read a message.
- The 24-hour expiry of a link, an export already requested and still
  processing, a rate limit on asking: the mocks have no clock (§58).
- Whether claude.ai's `list-skills` and `download-dot-skill-file` answer as the
  mock's do: the rows they stand on were read once on a personal account and are
  `*unknown*` in the map (`66`), and only a run against a throwaway account with a
  committed trace turns them.
- The auth host's real screens and the real Data controls path: the walk and
  the path are the mock's, and the first real run is what corrects them (§69).
- Whether the real ChatGPT link needs the session at all: the mock mirrors the
  documentation, and only a real link answers (§69).

