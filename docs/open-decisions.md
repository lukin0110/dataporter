# Open decisions

**Kind:** Running record of decisions nobody has made yet. Not a backlog of work — a
list of questions where more than one answer is defensible and picking one is somebody's
call rather than a slice's.

Each entry says what is at stake, what the options are, what happens while nobody
decides, and **what settles it**: an ADR, an amendment to a brief, an edit to
[`CONTEXT.md`](../CONTEXT.md), or a line in an implementation spec. An entry leaves this
file when one of those lands, and the entry says which.

Entries are cited by their identifier (`D1`), the way
[`orval-candidates.md`](orval-candidates.md)'s are, so a code comment or a spec line can
point at the question it is waiting on.

Everything below was read off the files named, at `e8606bf`. A line number is where it
was; the claim is what it said.

**Where these came from.** `D1`–`D4` came out of `/code-review` of `30`–`31`.
`D5`–`D8` came out of a sweep of all 46 pull requests — their descriptions and every
review thread on them — looking for questions that were raised, answered by nobody, and
then merged past. The sweep's own findings about what is *no longer* open are in *Findings assessed
and closed*, below, so that the next sweep does not re-open them. What the sweep could
not read is said there too.

| | Question | Raised by | Blocking? |
| --- | --- | --- | --- |
| [D2](#d2--what-timeoutsask_s-covers) | Does `timeouts.ask_s` bound the poll, or the whole ask? | `/code-review` of `31` | no |
| [D3](#d3--33s-workspace-beside-the-snapshot) | §33 says a snapshot's import writes its workspace beside it; `30` refuses to | `/code-review` of `30` | no |
| [D5](#d5--list-or-tuple-in-the-export-model) | The export model is called immutable and `frozen=True` is shallow | review of `02` (PR #2) | no |
| [D6](#d6--attribute-docstrings-on-constants) | A string after an assignment: this repo's convention, or dead code? | reviews of `06` and `10` (PRs #11, #17) | no |
| [D7](#d7--how-the-wall-is-described) | ADR `0001` and §22 describe a wall narrower and wider than the one that ships | review of brief `02` (PR #35) | no |
| [D8](#d8--the-vendored-skills-broken-references) | Vendored skills cite skills this repo does not have | review of the skills install (PR #23) | no |

None of the eight blocks a merge: each is a question about words, budgets, conventions or
paperwork, and the code does something defensible today. They are here so that
"defensible today" does not quietly become "decided".

## D2 — What `timeouts.ask_s` covers

`31`'s spec, step 5: "poll `EXPORT_PAGE_JS` for `requested` up to `timeouts.ask_s`". The
code sets one deadline at `export_page.py:254`, before `_bring_to_export_page`, so
arriving at the page and waiting for the page's answer share one budget: a slow
navigation shortens the poll.

That was deliberate — one number for "how long an ask may take" is easier to reason about
than two, and a navigation that never lands is not a case the poll should still be paying
for — but it is not what the spec says, and nothing wrote the reason down until this
file.

**Options.**

1. **Amend `31`.** One sentence in *In scope* saying the deadline covers the whole of
   `request_export`, navigation included. No code changes.
2. **Split the budget.** A separate, shorter wait for the navigation (the page load is a
   page load; `timeouts.verify_s` is the existing precedent at 30 s), leaving `ask_s` for
   the poll alone, as the spec reads. Two numbers, and the spec stands.

**Settled by:** a line in [`specs/impl/31-source-session-and-ask.md`](../specs/impl/31-source-session-and-ask.md),
with or without the code change.

## D3 — §33's "workspace beside the snapshot"

Brief `03` §33: "An import from a snapshot writes its workspace beside the snapshot, as
it does beside an export today." `30` does the opposite — `store.refuse_workspace_inside`
(`store.py:558`, called from `importer.py:2116` and `seed.py:273`) refuses a workspace
*inside* a snapshot, because a snapshot is finished by definition and `state.json` and a
signed-in browser profile are exactly what must never appear in one.

The reasoning is in `30`'s design notes and is convincing. The problem is procedural: the
working rule says a slice "may not quietly contradict the brief; that requires an
amendment", and the brief is unamended. §33 still tells a reader something the tool
refuses to do.

**Options.**

1. **Amend §33** to say a snapshot's import writes its workspace anywhere but inside the
   snapshot, naming `30` as the slice that found it. The brief is stable, not immutable —
   amending it explicitly is the rule, not the exception.
2. **Drop the guard** and let §33 stand as written. Nobody has argued for this.

**Settled by:** an amendment to [`specs/03-extraction-and-backup.md`](../specs/03-extraction-and-backup.md) §33.

## D5 — `list` or `tuple` in the export model

`src/dataporter/export/model.py` says the models are immutable and sets `frozen=True`,
which is shallow: `conversation.chat_messages.append(...)` still works, and so does
`message.content.append(...)` (`model.py:231`, `:236`–`:238`, `:254`, `:367`–`:370`).
The review of `02` asked for tuples, or validators coercing to them; `02`'s author
declined **because the slice could not decide it**: the spec's normative type block
spells `list[...]` (`specs/impl/02-export-model.md:38`–`:62`), and the working rule says
a slice may resolve what a spec leaves open but may not contradict it. The question was
left for a human and nobody has answered it since — the fields are still `list[...]` in
both documents at `e8606bf`.

Two things make the shallowness cost less than it looks, and both are still true:
`03`'s planner and `04`'s rendering are specified as pure and have determinism tests, and
the shallowness is written down in `ExportModel`'s own docstring rather than implied.
What is not true is that nothing would notice: the models are the package's public
surface, so an importer of `dataporter.export` gets a type whose immutability is a
convention.

**Options.**

1. **Amend `02`** to spell the containers `tuple[...]` and sweep the annotations, the
   parser's construction sites and any caller that indexes or extends one. One move,
   across `export/model.py`, `plan.py`, `render.py` and their tests; the public type of
   every field changes, which is exactly why it is an amendment and not a refactor.
2. **Say the convention is the promise.** One line in `02` — the containers are not
   mutated by anything in this tool, and a caller who mutates one is on their own —
   and drop the word "immutable" from the module docstring for something narrower.

**Settled by:** an amendment to [`specs/impl/02-export-model.md`](../specs/impl/02-export-model.md),
with the code sweep if option 1.

## D6 — Attribute docstrings on constants

A string literal after a module-level assignment is used 150-odd times across `src/` and
`tests/` to document the name above it. Two reviews called it dead code (PR #11 on
`tests/test_summary.py:118`, PR #17 on `tests/test_spike_docs.py:57`); both times the
answer was that it is PEP 257's attribute-docstring form, that pydantic reads exactly
this form for field descriptions (`use_attribute_docstrings`), and that changing the five
in one test module would make that module the only one in the repo that differs. Both
times the answer ended by inviting a human to overrule it, and said the change would be
repo-wide and its own PR. Neither thread was resolved.

So the convention is established by practice, contested by a reviewer, and written down
nowhere: `specs/README.md`'s *Shared decisions* does not mention it, which is why the
same finding arrived twice and will arrive again.

**Options.**

1. **Write the convention down** in `specs/README.md`'s *Shared decisions* — attribute
   docstrings document constants, `#` comments explain code — and the next review's
   finding has a line to be answered with.
2. **Drop it** for `#` comments in one repo-wide slice, and lose the pydantic field
   descriptions that depend on the form (`use_attribute_docstrings` is on).

**Settled by:** a line in [`specs/README.md`](../specs/README.md)'s *Shared decisions*
(option 1), or a slice (option 2).

## D7 — How the wall is described

The helpers' wall is a host *and* a path: `^https://claude\.ai/(new|chat/[0-9a-f-]{36})(\?.*)?$`,
and since `31` there is a second one — the extraction surface, which is the sign-in page
and the export page and nothing else. Two documents describe it as something else:

| Where | What it says | What ships |
| --- | --- | --- |
| [`adr/0001`](adr/0001-no-door-in-the-wall.md), first sentence | refuses every URL that is not `https://claude.ai/new` or `https://claude.ai/chat/<id>` | a query string is allowed, `<id>` is a uuid, and `31` added a surface the sentence does not mention |
| [`specs/02-claude-mock.md`](../specs/02-claude-mock.md) §22 | "The helpers' refusal of every URL that is not on `claude.ai`" | the host is the smaller half of the check; a `claude.ai/settings/profile` is refused too |

Both were raised in the review of brief `02` and neither was answered. §22's sentence is
the one that matters: it is the argument for the mock being reached by operator
configuration rather than by a setting, and it understates the property it rests on.

**Options.**

1. **Amend both.** A sentence in the ADR that names the pattern and says there are now
   two surfaces, and an amendment to §22 saying host *and* path. The ADR is ours to
   correct; §22 is a brief, so it is an amendment rather than an edit in passing.
2. **Amend §22 only**, and let the ADR keep a simplification that was true when it was
   written. Cheaper, and it leaves a document that a reader of `08` will find wrong.

**Settled by:** an amendment to [`specs/02-claude-mock.md`](../specs/02-claude-mock.md) §22,
and an edit to `adr/0001`.

## D8 — The vendored skills' broken references

[`skills-lock.json`](../skills-lock.json) pins skills copied into `.agents/skills/`
(with `.claude/skills` linked to them). Four references in them point at skills this
repository does not have, and one is a typo:

| Where | What it cites |
| --- | --- |
| `.agents/skills/implement/SKILL.md:9` | "Use /tdd where possible" — there is no `tdd` skill |
| `.agents/skills/wayfinder/SKILL.md:65`, `:78` | ticket types `research` and `prototype`, invoked as Skills; neither is installed or pinned |
| `.agents/skills/grill-with-docs/SKILL.md:3` | "ADR's" |

Raised six times in the review of PR #23 and never answered. The question is not what is
wrong — it is whose file it is. A local fix is overwritten by the next refresh from
upstream (`eb5a00a` refreshed them once already), and the lock file exists precisely to
make these copies reproducible rather than edited.

**Options.**

1. **Upstream.** Report or fix it at `mattpocock/skills`, which is where
   `npx skills check` re-fetches them from, and take the next refresh. The only fix that
   survives.
2. **Patch locally and record the deviation**, the way `docs/graft.md` records the three
   deviations from generated output, so a refresh does not silently restore them.
3. **Write down that vendored skills are upstream's**, findings included, and stop
   reviewing them here.

**Settled by:** an upstream change (option 1), a note beside `skills-lock.json` (option
2), or a line in [`specs/README.md`](../specs/README.md)'s *Repo tooling* (option 3).

## Review findings not acted on

Not decisions so much as judgement calls with nobody assigned. From the same
`/code-review`, against `67b5613...79746c8`; each is a smell, not a defect, and none
changes behaviour. All seven were re-read at `e8606bf` and all seven still stand; the
line numbers below are the current ones.

| Finding | Where |
| --- | --- |
| Three spellings of one `O_EXCL` open: `extract.py:254` and `:531` against `store.py:508` `_open_exclusive`, with `0o600` written twice beside `store.py:496` `SNAPSHOT_MODE` | `30`, `31` |
| `extract.py:616` `_digest` re-implements the chunked hash inside `store.py:475` `_copy`, and imports `store.COPY_CHUNK` to do it | `30` |
| `extract.py:656` `_display` re-joins `root / source / account / stamp`, which is `Store.directory` (`store.py:318`) | `30` |
| `export_page.py:397` `_wait_until` is a third deadline-and-poll loop beside `session.py:118` and `helpers.py:638` | `31` |
| `store.py:610` `list_command` is the only operation not named after its command (`snapshots`) | `30` |
| `cli.py:461` `Account` and `:469` `AccountOption` differ only in whether the option is required, and neither name says so | `31` |
| `(source, account, stamp)` travel together through `Store.directory`, `Filing`, `Snapshot`, `SnapshotRow` and `_display` — a type wanting to be born | `30` |

The first three are the same shape: `extract` re-derives what `store` already knows. If
any of these is worth doing, it is one tidying slice and not seven edits.

## Findings assessed and closed

What the sweep of the 46 pull requests checked and found settled. Kept so that a thread
still open on GitHub is not mistaken for work still open here.

| Finding, and where it was raised | What is true at `e8606bf` |
| --- | --- |
| D1, the glossary against the code: `archive`, `snapshot` and `URL` (`/code-review` of `30`–`31`) | Settled by brief `06` (`47`): `CONTEXT.md` gained **Archive** — the export as a file, which a snapshot keeps byte for byte — and **Fetch**, and `archive` left the `_Avoid_` lists of **Export** and **Store**. The `snapshot` and `URL` identifiers stay: the lists govern prose, and the glossary now says which word is which thing. |
| D4, whether brief `03`'s blocks are golden (`/code-review` of `30`–`31`) | Settled by brief `06` (`47`): the Examples row of `specs/README.md` says brief `03`'s (§31, §33) and brief `06`'s (§60, §63) are golden, which is what `tests/test_extract.py`, `test_ask.py`, `test_store.py`, `test_chatgpt_ask.py` and `test_chatgpt_fetch.py` compare bytes against. |
| `_click` on the export page could press a sign-in page, because the extraction surface admits `/login` (PR #44) | Fixed in `c3219cb`: `export_page.py:314` refuses anything but the export page itself, with `NOT_THE_EXPORT_PAGE`. The GitHub thread is still open; the code is not. |
| A dead `LOGGED_OUT` constant in `tests/test_source_session.py` (PR #44) | Fixed in the same commit. The constant that remains is `tests/test_browser_session.py:159`, which is used four times. |
| `--host-resolver-rules=MAP claude.ai 127.0.0.1:8443` cannot carry a port, so §21's line would not route to the mock (PR #35) | Wrong, and disproved by a run rather than by argument: [`rehearsal-01.md`](rehearsal-01.md) records a complete rehearsal on 2026-09-12 against Chromium 141 with exactly that flag. `MAP` takes `host:port`. |
| `tests/fake_agent.py` used `PurePosixPath`, so a Windows path would yield the whole string as its name (PR #25) | Fixed: `fake_agent.py:41` imports `PurePath`, and `:550` records why. |
| The PR description and brief `03` arrived in one pull request and should be split (PR #40) | The author's call, made: the description was widened to cover both. Nothing outstanding. |
| A tense mixed in `specs/impl/05-dry-run.md:73`'s parenthetical (PR #37) | Cosmetic, in a document about a block that is pinned by bytes. Not worth an amendment; recorded here so the next sweep skips it. |

## What this sweep could not read

The sessions that produced these pull requests are enumerable — 45 of them, titled
`Spec NN`, `Brief 02`, `Reload skills` and so on, between 2026-09-10 and 2026-09-13 —
but their transcripts are not readable from a session other than their own. What each
one decided is therefore taken from what it wrote down: its pull request description,
its commits, the review threads on it, and the *Design notes* and *Resolved while
building* sections it left in the slice. A decision made in a session and never written
into one of those four places is not in this file, and nothing here can find it.
