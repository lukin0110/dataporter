# dataporter

A tool that migrates a Claude data export into another Claude account by driving the
claude.ai web interface, and the experiment that measures whether that works. The words
below are the ones the briefs, slices and documents use; where two words exist for one
thing, the first is the one to use.

## Language

### Documents

**Brief**:
A document that states intent — what is being built and why. Its section numbers are
permanent identifiers, cited as §N, and continue across briefs.
_Avoid_: spec, PRD, requirements document

**Slice**:
One implementation spec, cited as `NN`, sized to be built, tested and reviewed in one
sitting.
_Avoid_: task, subtask, ticket, story

**Spike**:
A time-boxed observation of claude.ai, whose findings are each marked *observed* or
*unknown*.
_Avoid_: proof of concept, PoC

**Experiment**:
The pilot and the full run of the migration against a real destination account.
_Avoid_: trial, rehearsal

**UI map**:
The record of claude.ai's states and the signal each one shows, every row marked
*observed* or *unknown*.
_Avoid_: selectors document

**Report**:
The tool's account of a finished migration: the end-of-migration block (§16) and its
machine-readable twin.
_Avoid_: summary, results

**Rehearsal record**:
The document a complete rehearsal leaves.
_Avoid_: report, write-up, log

### Migration

**Seed**:
The rendered transcript of one source conversation, pasted into a new chat in the
destination account.
_Avoid_: prompt, dump, transcript

**Part**:
One piece of a seed, sent as one message and acknowledged on its own.
_Avoid_: chunk, page

**Acknowledgement token**:
The identifier a part carries so that its acknowledgement can be told from any other
line. The **ack line** is the one-line reply that carries it back.
_Avoid_: ack, confirmation

**Workspace**:
The directory that holds everything one migration writes, beside the export and never
inside it.
_Avoid_: state directory, output directory

**Pause**:
The record a run leaves when a page only a person can clear has stopped it. A pause is
resumed, never restarted.
_Avoid_: halt, block

**Human intervention**:
A pause a person cleared, counted in the report.
_Avoid_: manual step

### Browser and agent

**Helper**:
A deterministic move of the tool's own that the agent invokes where exactness matters:
probing, pasting, attaching, awaiting a reply.
_Avoid_: tool, primitive, command

**Probe**:
The helper that reports a page's state without its content.
_Avoid_: snapshot, inspect

**Surface**:
The set of URLs a helper will drive. The migration surface is a new chat and a
conversation on claude.ai; the login surface adds the sign-in page, for the sign-in alone.
_Avoid_: allowlist, whitelist, scope

**Scripted agent**:
The model-free agent that performs the skill's procedure from a rendered prompt exactly
as written, standing where Hermes and its model stand.
_Avoid_: fake agent, mock Hermes, fake Hermes

### Test doubles

**Fake world**:
The arrangement that runs the real importer against a fake Chrome, a fake page and a
fake `hermes`, in process.
_Avoid_: harness, sandbox

**Live tier**:
The tests that drive a real Chrome against served fixture pages.
_Avoid_: end-to-end tests, e2e, integration tests, browser tests

**Mock**:
The served stand-in for the whole of claude.ai that behaves on its own, statefully, for a
real Chrome. There is one, and it is a separate project. Every other test double is a
*fake*, scripted by the test that uses it.
_Avoid_: fake site, simulator, emulator, stub server

**Rehearsal**:
The full run's protocol, run by the shipped tool against the mock with the scripted agent
standing where Hermes stands. No model, no account.
_Avoid_: dry run, test run, smoke test, e2e

**Rehearsal export**:
The synthetic export a rehearsal migrates.
_Avoid_: fixture export, sample export

**Ledger**:
The mock's own count of what it was asked to do — sign-ins, chats created, messages
received, files accepted, renames.
_Avoid_: log, stats, metrics
