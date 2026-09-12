# The mock claude.ai and the rehearsal

**Brief 02.** Section numbers continue from [`01-initial-brief.md`](01-initial-brief.md),
which ends at §19, so that `§N` names exactly one section anywhere in this repository. The
words used here are defined in [`CONTEXT.md`](../CONTEXT.md).

## 20. Goal

Build a **mock claude.ai** — a served stand-in for the whole site — and use it to
**rehearse** the migration: the shipped tool, unchanged, run through the whole protocol
against the mock, on any machine with Chrome, with no Claude account and no model.

The tool has two halves. The agent's half — Hermes reading the skill with a model behind
it — is what the pilot (§18) and the full run (§19) measure. The other half is
deterministic: the browser session, the sign-in form, the helpers, the seeds, the import
loop, the state, verification, the report, resume, the interruption drill and the sign-off
instruments. That half has never met a real browser showing a real, stateful site, because
until now the only such site was claude.ai itself. The mock is where that half is
developed and proven, so that claude.ai is touched only by the spike (`10`) and the
experiments.

```text
hermes-claude-migrate            scripted agent (no model)
        │                                 │
        └──────────── Chrome ─────────────┘
                        │
                        │  https://claude.ai  →  127.0.0.1
                        ▼
                    the mock
                        │
                        ▼
                     ledger

```

A rehearsal exercises what the in-process fakes stop short of:

- a real DOM in a real Chrome, reached under the real host name;
- the sign-in form, filled from credentials, in two steps;
- seeds of every size the export produces, pasted and read back;
- a chat that comes into being on submit, has a URL, and survives a reload;
- a reply that takes time and then stops;
- a rename and an upload;
- the loop across many conversations, in sessions, interrupted and resumed;
- verification, the report and the sign-off instruments over the result;
- the subprocess contract between the tool and whatever stands where Hermes stands.

A rehearsal is not evidence about claude.ai. It cannot answer one of `10`'s questions, and
every `*unknown*` in [`docs/claude-ui-map.md`](../docs/claude-ui-map.md) is still
`*unknown*` after it. Nor is it evidence about the agent's half: whether a model can
follow the skill is the pilot's question (§18, questions 4 and 5), and a rehearsal
involves no model at all.

## 21. The mock

The mock stands in for the whole of claude.ai and behaves on its own. It is not scripted
per run, and there is no model behind it.

### A separate project

The mock is its own project — its own project file, dependencies, tests and README —
listed as a member of this repository's workspace for now. It imports nothing from the
tool, and the tool imports nothing from it. Moving it to its own repository is a directory
move. *(ADR [0003](../docs/adr/0003-the-mock-is-a-separate-project.md).)*

### Obedient

A seed asks Claude to reply with exactly one line. The mock reads each message it
receives, finds that line, and replies with exactly it — after a configurable, non-zero
delay, and growing in at least two steps, so that "the reply stopped growing" is something
a rehearsal really waits for. A follow-up question gets one canned sentence.

### Governed by the UI map

Every state the mock can show is a row of the UI map's middle column, and the mock cites
the row. It invents nothing. Where the map says *unknown*, the mock takes the simplest
behaviour the code already accepts, and says that it did. A behaviour the mock needs and
the map has no row for is added to the map first, marked *unknown*. A mock run never turns
an *unknown* into an *observed on <date>*: only a person watching claude.ai does that.

### Sign-in

The login page carries what the unattended sign-in (§8, `24`) was written to get past: a
banner to dismiss once, sign-in buttons for other providers, a passkey option, and then
the email path in two steps — email, then password. Exactly one configured email and
password pair signs in. Any other is refused, so a wrong credential fails a rehearsal
rather than passing it.

### Chats

A submit creates a chat with its own id and URL. Reloading that URL shows every turn. A
rename affordance exists, and a renamed title survives a reload. A file input accepts a
file and shows it by name.

### The ledger

The mock counts what it was asked to do — sign-ins, chats created, messages received,
files accepted, renames — and prints the count on request:

```text
Mock claude.ai — ledger

Sign-ins:                      2
Chats created:                 8
Messages received:            11
Files accepted:                2
Renames:                       8

```

The ledger is the witness a rehearsal record reconciles against (§25). Nothing in the tool
can tell a rehearsal from a real run (§22), so the mock is the only party that can.

### Reachability

The mock tells the operator how to reach it; nobody composes a resolver rule by hand. On
start it prints:

```text
Mock claude.ai listening on https://127.0.0.1:8443

Add to <workspace>/config.toml before running the tool:

[browser]
extra_args = [
  "--host-resolver-rules=MAP claude.ai 127.0.0.1:8443",
  "--ignore-certificate-errors-spki-list=AbCdEf0123456789AbCdEf0123456789AbCdEf0123456789=",
]

```

Trust is scoped to the mock's own key, never to every certificate. Which mechanism
establishes that trust is an implementation detail; the shape of what is printed is not.

### Lifetime

A separate process the operator starts, as Chrome is. State lives in memory for as long as
the process runs, so a rehearsal in several sessions sees the same chats throughout.
Restarting it resets it.

### What it cannot do yet

Named here so that a later brief or slice can claim them (§28):

- a rate limit;
- a login expiry in the middle of a run;
- a modal or a JavaScript dialog in the way;
- a generation error;
- a CAPTCHA or a security challenge;
- a code prompt at sign-in.

## 22. The tool under rehearsal

The tool under rehearsal is byte-identical to the tool that will meet claude.ai, and it
runs as a black-box process. It has no host setting, no flag and no environment variable
that names the mock. The helpers' refusal of every URL that is not on `claude.ai` (§17)
stays exactly as it ships.

The mock is reached through configuration an operator may already write: the browser's
extra arguments, in the rehearsal's own workspace, map the host to the mock and trust its
key. Whatever stands where Hermes stands attaches to that Chrome, so its navigation lands
on the mock too.

A rehearsal proves the code that ships, or it proves nothing.
*(ADR [0001](../docs/adr/0001-no-door-in-the-wall.md).)*

## 23. The rehearsal

A rehearsal is the full run's protocol
([`docs/experiment-02.md`](../docs/experiment-02.md)), run against the mock:

```text
setup
doctor
login
import <rehearsal export> --dry-run
import <rehearsal export> --pilot          then: report
import <rehearsal export> --all --limit N  in sessions; one SIGKILL mid-conversation,
                                           then import again
verify
report
followup
status, session status, session logout
the sign-off instruments: gate, drill, safety

```

`judge` is not part of it: it needs a model, and against the mock it would grade noise.

### Who stands where Hermes stands

The **scripted agent**: the model-free procedure the tool's own tests already have, which
performs the skill exactly as written. For a rehearsal it is packaged as a `hermes`
executable on the path, which answers the version, profile and configuration commands and
performs every one-shot task — the attach check, the sign-in task, a migration, a
follow-up — by driving the same Chrome and calling the real helpers. It belongs to the
tool's test tree, not to the mock.

The hand-driven conversation in [`spikes/README.md`](../spikes/README.md) — the helpers
called one at a time by a person — is the developer's inner loop, and works against the
mock unchanged.

A real Hermes with a real model may be pointed at the mock. That is not what a rehearsal
is for, and it is listed under §28.

### One run, one mode

One run is one mode: interactive, with a window, or `--non-interactive`, without. A
complete rehearsal covers both.

### Pacing

Pacing (§13) may be lowered through the workspace's configuration, exactly as an operator
may lower it. The rehearsal record states the values used. The tool's defaults are never
changed for the mock's sake.

### Where it runs

On any machine with Chrome, with or without a display, with no API key and no Claude
account. Whether continuous integration runs it is a decision for the slice that would add
it; this brief neither requires nor forbids it.

### What it never touches

The credentials are invented and configured into the mock. No real account is signed in
to, and no real export is read. Ever.

## 24. The rehearsal export

A rehearsal migrates a purpose-built export that contains no real conversation. It covers
the five kinds §18 names — a short conversation, a long one, one with code, one with
attachments, one with many turns — and as many of the pilot's selection categories (`20`)
as can be built, including:

- a conversation whose seed needs at least two parts at the tool's default size;
- attachments of all three classes (§14), with the class 2 bytes beside the export;
- one conversation the tool classifies as unsupported.

It is sized so that a complete run in one mode takes minutes at rehearsal pacing.

## 25. Pass criteria

A rehearsal run passes when all of the following hold, and no person helped:

- every migratable conversation of the rehearsal export ends `completed` at its first
  attempt, with no pause recorded — **100 %**. The mock is obedient and the agent is
  deterministic, so anything less is a defect in the tool;
- the report reconciles: `Created + Partial + Failed + Pending == Source`;
- `verify` finds, in every chat, the source line and each part's ack line;
- every conversation ends with its title set;
- the interruption drill loses no conversation and creates no duplicate chat;
- the safety audit (§17) finds no host but `claude.ai`, and no chat the workspace did not
  create;
- the report's numbers reconcile with the ledger:

```text
chats created      == distinct chat ids in the state
messages received  == parts sent
files accepted     == attachments migrated by upload
renames            == titles set
sign-ins           == logins + automatic sign-ins

```

A record whose numbers do not reconcile is not a rehearsal.

## 26. The rehearsal record

A developer's run leaves nothing but the terminal.

A *complete* rehearsal that gates something — before the spike, before the pilot, before a
release — leaves one document, `docs/rehearsal-NN.md`, in the discipline the experiment
documents follow:

- every number carries a mark, `*measured on <date>*`;
- the versions of the tool, the scripted agent, Chrome and the mock;
- the mode and the pacing used;
- the report's §16 block and the ledger block, side by side;
- what it found, and what it could not exercise;
- no conversation content, no title, no account identifier (§10).

A claim without a number is not a record.

## 27. What a rehearsal is not evidence of

- Anything about claude.ai. Every `*unknown*` in the UI map is still unknown.
- Whether a model can follow the skill. That is the pilot's questions 4 and 5 (§18).
- Semantic fidelity (§15, §19) and the pilot's question 3. Against the mock these are
  *not applicable* — never "passed".
- Any realism the UI map does not record.

A passed rehearsal is the precondition for spending the throwaway account on `10`. It is
not a substitute for it.

## 28. Later

Named so that a later brief or slice can claim them:

- failure states on cue — the list in §21;
- a real Hermes with a real model against the mock;
- running a rehearsal in continuous integration;
- serving the live tier's fixture pages from the mock, which needs failure pages the mock
  cannot yet produce;
- a mock whose state survives its own restart;
- extraction of the mock to its own repository;
- anything the UI map has no row for.
