# 46 — The extraction rehearsal

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 06](../06-chatgpt-extraction.md) §68; brief 04 §48 (traces from
the account home); brief 05 §56 (what turns `39`–`41` `Done`)
**Depends on:** [45](45-fetch-through-the-session.md), [29](29-rehearsal.md),
[36](36-rehearsal-traces.md), [32](32-mock-export-page.md), [40](40-chatgpt-export-and-archive.md)
**Enables:** [47](47-paperwork.md)
**Status:** Done

## Goal

An extraction protocol in the rehearsal runner, run by the shipped tool against each
site's mock: seed the account, `login`, ask, fetch, ask and fetch again, list, reconcile
with the ledger, gather the traces from the account home, and leave a record. The run
against the mock chatgpt.com is the first tool-driven walk of `39`–`41`; the run against
the mock claude.ai is the first `30` and `31` have had.

## In scope

- **The protocol** (`rehearsal/extraction.py`, new; `rehearsal/run.py --protocol
  extraction`, `--chatgpt-port`): for each mock, in order — the account seeded through
  the mock's own routes (its two-step sign-in with the redirect's `Location` read and not
  followed, three chats, one upload on the last), then `login --source X --account
  rehearsal`, `extract` (ask 1), the newest link read from `/__mock/exports.json`,
  `extract --link` (fetch 1), the first snapshot's archive and manifest hashed, ask 2,
  fetch 2, the ledger read, `session status`, `logout`; then, once both halves
  have filed, `snapshots` for each, so the listing shows both rows. One `Settings`, one
  workspace and one accounts directory per mock under `<root>/<source>/`; one store
  under `<root>/store/`. `config.toml` carries `[browser]`, `[hermes] home`,
  `[accounts] dir` and `[store] dir`; the environment carries the credentials,
  `SSL_CERT_FILE` (the mock's certificate, written from what it served) and `no_proxy`.
  Both mocks must be fresh.
- **The runner's additions** (`run.py`): `chrome_args(…, hosts=…)` builds one
  comma-separated resolver rule for a mock that answers two host names;
  `Runner.run(…, secrets=…)` records the argv with `<link>` where a link was;
  `_gather_traces` looks in `<accounts>/*/*/logs/` as well as the workspace
  (the TODO at the old `run.py:347`); `captured` is public.
- **The criteria** (`extraction.criteria`), each a number and a verdict: `login` signs in;
  both asks are taken and print the block; the mock minted one link per ask and
  `Exports requested` is 2; both fetches file a complete snapshot; the second stamp sorts
  after the first; `conversations == chats created` in every manifest; the gap is
  `files accepted × the site's references per file` (2 for Claude, `files` and
  `files_v2`; 1 for ChatGPT) with no bytes carried; the first snapshot's archive and
  manifest are byte-identical after the second fetch (§39, question 6); `snapshots`
  lists both rows; the link is in no file the run left (every file under the mock's root
  and the store's manifests, archives skipped); one trace per step that drove a tab
  (`login`, both asks; both fetches too for a session-bound source), each header naming
  the source and its host; `sign-ins == 1 + the tool's password steps` (the seeding's
  own sign-in, and every `password-step` move across the traces); and, for the mock
  chatgpt.com, the login trace crossed to the auth host and both hosts were certified.
- **The record** (`docs/rehearsal-03.md`): kind, produced by, answers; the versions of the
  tool, the agent, Chrome and both mocks; per mock: what was seeded, the Chrome
  arguments, the protocol table, the traces table (`36`'s, read off the files), the first
  ask block and both fetch blocks as printed, the six-row ledger block under the site's
  heading, the criteria table; the verdict; findings (a failed step, a failed criterion,
  two traces for one step, and three standing findings: the seeding's sign-in, Claude's
  two references per file, the certificate trusted for the browserless fetch); what it
  could not exercise. Every number marked `*measured on <date>*`.
- **Tests** (`tests/test_rehearsal_extraction.py`, fast): the argv mask; the two-host
  rule; a trace gathered from an account home; the six-row ledger block; a clean half
  passes all thirteen criteria (twelve for Claude, whose gap detail reads `[2, 2] == 1 × 2`);
  a changed first snapshot, a link left in a file, a ledger that does not reconcile, and
  one link for two asks each fail their criterion and no other; the record carries both
  halves, a mark on every number and no link; a failed criterion is a finding;
  `digest_of` reads the oldest snapshot.

## Out of scope

- Running both mocks in one Chrome: each half gets its own Chrome and profile.
- The migration protocol: unchanged, and still the default.
- A rehearsal that migrates into one mock and extracts from the other (§40).

## Design notes

- **One invocation, both mocks, one record.** The brief asks for the ChatGPT half
  rehearsed and for `30`/`31`'s first tool-driven extraction; one record with two halves
  is what a reader compares. Rejected: two records for the same protocol.
- **Seeding by HTTP, not by the walk.** The mock's chat routes are its own witness paths
  and import nothing across ADR 0003's line; the extraction is what is being rehearsed,
  not the chats. The redirect the mock chatgpt.com answers its password step with names
  `chatgpt.com`, a host the mock does not listen on, so the runner reads the code off it
  and asks for the callback at the mock's own address — what the resolver rule does for
  Chrome.
- **Sign-ins reconciled as `1 + password steps`** rather than `logins + auto sign-ins`:
  `extract` keeps no counter of the sign-ins it made, and `44` made every typed step a
  move, so the traces are the count — and the rule is the same for both sources.
- **The link masked in the runner too.** §66 is the tool's rule; the runner hands the
  link to the tool on a command line and records the step, so it writes `<link>` there,
  and the last criterion greps everything it left for the token.
- **The certificate for the browserless fetch is written by the runner** from the served
  certificate, the same source of truth as the pin; no path into `~/.cache/` to spell.

## Acceptance criteria

- `uv run python -m rehearsal.run --protocol extraction --root /tmp/r3 --record
  docs/rehearsal-03.md --number 3` against fresh `claude-mock` and `chatgpt-mock`
  exits `0`, prints every criterion `pass`, leaves one trace per browser step under
  `/tmp/r3/<source>/traces/` and none under any account home, and writes the record.
- `docs/rehearsal-03.md` renders two ledgers with `Exports requested: 2` and carries no
  link.
- The unit tests above pass; `make check` is green.
- On that run: `39`, `40`, `41` → `Done`; `42`–`45` → `Done`; `30`, `31` gain a line
  naming the record and stay `Built` until a real account.
  Run on 2026-09-14: every criterion passed against both mocks, and the record is
  [`docs/rehearsal-03.md`](../../docs/rehearsal-03.md); `Done`.

*Amended by [`67`](67-the-mock-grows-skills.md):* the mock claude.ai's half runs
`extract-skills` three times after the first fetch and reconciles seven more criteria
against the mock's skills witness; its ledger has nine rows, and the record renders a
half's blocks generically rather than three fixed ones.

## Risks

- **The mock claude.ai's unattended `login` still needs the scripted `hermes`** on the
  path (`24`'s shape); the runner writes one, as `29` does.
- **Two Chromes in sequence on two free ports**: `cdp_port = 0` finds one per half; a
  Chrome an earlier run left behind is on neither.
- **`chats created` counts the seeding's chats only** because the tool creates none; a
  future rehearsal that migrates first would have to add the migration's to the
  expectation.
