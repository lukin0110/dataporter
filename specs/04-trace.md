# The trace

**Brief 04.** Section numbers continue from
[`03-extraction-and-backup.md`](03-extraction-and-backup.md), which ends at §40, so that
`§N` names exactly one section anywhere in this repository. The words used here are
defined in [`CONTEXT.md`](../CONTEXT.md).

## 41. Goal

Make every run that drives a browser **leave a trace**: a file that says, in order, what
the tool and the agent did in the tab and what the page did and showed in return — so
that the mock claude.ai (§21) can be corrected against the real site, and a second
source's mock against that source, from evidence rather than from guesses.

Today the tool is built out of guesses. Every row of
[`docs/claude-ui-map.md`](../docs/claude-ui-map.md) is *unknown*, the mock cites those
rows and invents nothing beyond them (§21), and [`docs/spike/`](../docs/spike/) holds no
observation of any kind: no run against a real site has ever been recorded in a form
anyone could read back. The channel from reality into the map and the mock exists on
paper — a person watches claude.ai and marks a row *observed on \<date\>* — and nothing
feeds it.

A trace is that feed. A person reads one and marks rows; Claude Code reads one and edits
the mock's pages; a rehearsal leaves one too, in the same shape, and the difference
between the two is the mock's to-do list.

```text
        a real run                          a rehearsal
   ┌────────────────┐                   ┌────────────────┐
   │ tool + Hermes  │                   │ tool + scripted│
   │ against the    │                   │ agent against  │
   │ real site      │                   │ the mock       │
   └───────┬────────┘                   └───────┬────────┘
           │ leaves                             │ leaves
           ▼                                    ▼
      a trace ──────────── compared ──────── a trace
           │
           │ read by a person, or by Claude Code
           ▼
   the UI map's rows turn *observed*; the mock's pages change

```

A trace is not a transcript: it never carries a message, a title or an address. It is
not the ledger (§21), which is the mock's own count and exists only on the mock's side.
It is not the report (§16), which says what a migration achieved. It is what the browser
went through, in outline, and nothing else.

## 42. What leaves a trace

**Every command that drives a tab leaves one.** Today that is `login`, `import`, `resume`,
`verify`, `followup`, `doctor`, and `extract` when it asks. A command that opens no
browser — a dry run, a fetch, a listing, a report — leaves none. There is no flag: a
trace is not a diagnostic a person turns on when something went wrong, it is the record
a run leaves so that the next run against the mock is closer to this one. A rehearsal
leaves traces for the same reason and by the same rule, since the tool cannot tell a
rehearsal from a real run ([ADR 0001](../docs/adr/0001-no-door-in-the-wall.md)).

**One file per run**, beside the run log, with the run log's stamp:

```text
<workspace>/logs/run-20260913T100000Z.jsonl      a migration's run log
<workspace>/logs/trace-20260913T100000Z.jsonl    its trace

<account home>/logs/trace-20260913T203000Z.jsonl an extraction's, or a source login's

```

The trace lives where the run's other records live: the workspace for a migration and
the destination's session, the account home for an extraction and a source session.
Never in the store, never in the export, never in a snapshot.

**One shape, four kinds of line.** A trace is JSON lines. The first line is the header;
every other line is a move, an observation or a sketch, in the order they happened.
Illustrative in its values, normative in its keys and their order:

```text
{"trace":1,"kind":"header","ts":"2026-09-13T10:00:00.000Z","command":"import","flags":["--pilot"],"source":"claude","host":"claude.ai","account":null,"export_fingerprint":"1f844dc5…","tool":"dataporter 0.1.0","chrome":"Chromium 141.0.7390.37","agent":"hermes 1.0.0 (scripted agent)","chrome_arguments":["--host-resolver-rules=MAP claude.ai 127.0.0.1:8443","--ignore-certificate-errors-spki-list=…"],"root":"/home/me/export/migration"}
{"kind":"observation","ts":"…","t_ms":412,"what":"certificate","host":"claude.ai","issuer":"claude.ai","subject":"claude.ai"}
{"kind":"observation","ts":"…","t_ms":415,"what":"navigation","path":"/new","query":[]}
{"kind":"sketch","ts":"…","t_ms":640,"hash":"3f9c2a1b7e04","path":"/new","query":[],"title_chars":8,"controls":[{"role":"textbox","label":"Write your prompt to Claude","chars":0},{"role":"button","label":"Send message","disabled":true},{"role":"link","count":12,"chars":231}],"selectors":{"COMPOSER_SELECTOR":1,"MESSAGE_SELECTOR":0,"TITLE_SELECTOR":0,"FILE_INPUT_SELECTOR":1},"dialogs":[]}
{"kind":"move","ts":"…","t_ms":650,"helper":"probe","ok":true,"elapsed_ms":38,"conversation_id":null,"before":"3f9c2a1b7e04","after":"3f9c2a1b7e04","result":{"kind":"new_chat","logged_in":true,"composer_present":true,"composer_chars":0,"generating":false,"send_enabled":false,"tab_count":1}}
{"kind":"observation","ts":"…","t_ms":3120,"what":"request","id":"r7","method":"POST","path":"/api/chats","query":[],"type":"fetch"}
{"kind":"observation","ts":"…","t_ms":3402,"what":"response","id":"r7","status":200,"content_type":"application/json","bytes":211,"elapsed_ms":282}
{"kind":"observation","ts":"…","t_ms":3410,"what":"url_changed","path":"/chat/2b1f…","query":[]}
{"kind":"observation","ts":"…","t_ms":51300,"what":"end","exit":0}

```

Every line after the header carries two clocks: `ts`, the wall clock to the millisecond
in UTC, which is how a move is found again in `logs/actions.jsonl`; and `t_ms`, the
milliseconds since the trace began, which is how a real run and a rehearsal are laid
side by side without the wall clock in the way.

The header names the command and its flags — the names of the flags, never their
values, because `--email` is one — the source and the host, the account by its label or
`null`, the export's fingerprint when there is one, the versions of the tool, the browser
and the agent as each reports itself, the browser's extra arguments as configured, and
the directory the trace is in. The last line, when the run ended on its own, says so and
how; a run that was killed leaves no last line, which is itself the record of it.

## 43. The move

A move is one helper call as it happened. The helpers are the deterministic half of the
division of labour (§5): probe, paste, attach, await, and the rest. Hermes calls them
through the terminal, and the tool's own extraction presses its two buttons through the
same path; either way, the line that counts a browser action for the report (§16) is
written by one function of the tool's, and that function now writes the move as well:
which helper, whether it succeeded, how long it took, the conversation it concerned, what
the helper printed — minus anything §46 forbids — and the sketch of the page before and
after (§45).

The move is not what the agent believes it did. Slice `19` decided that the count of
browser actions is the count of the tool's own records and not the agent's claim, and the
trace keeps that line: a move is written by the code that made it. What the agent does
in the tab on its own — opening a chat, pressing send, renaming — is not a move, because
the tool did not make it. It is what the watch is for.

## 44. The watch and its observations

**The tool keeps its own eyes on the tab for the length of a run.** Hermes drives the
browser directly for the adaptive moves (§5, `11`): it navigates, it presses send, it
finds the chat's menu. The tool sees none of that through its helpers, and a trace that
only held moves would have a hole where every adaptive action was. So the tool opens a
second session on the same tab, beside the agent's, and records what the page does,
whoever caused it.

An **observation** is one such thing, with its moment. The watch records:

- a **navigation**: the page moved to a new document, at what path;
- a **URL change** within a document, the kind a page makes for itself after a chat is
  created, at what path;
- a **dialog** opening and closing — the browser's own dialogs — by their type and never
  their message;
- a **request** the page made to its own host, and the **response**: method, path,
  status, content type, size, how long it took. Static assets and other hosts are not
  recorded: the mock is a page, not a content delivery network;
- the **certificate** the browser was shown for the host, once: its issuer and its
  subject (§47);
- a **tab** appearing or closing;
- the watch **losing** its session, which never stops the run (below);
- the **end** of the run, and how it ended.

A navigation and a dialog each take a sketch (§45), so that a trace shows not only that
the page moved but what it looked like when it arrived.

**The watch is a witness, not a hand.** It sends no input and drives nothing. It enables
what it must to hear the page and nothing more, so that a run watched and a run unwatched
are the same run. If the watch cannot start, or its session drops, the trace says so and
the run goes on: the trace is evidence and the migration is the product, and no
migration is failed for want of its record.

## 45. The sketch

A probe reports the page as booleans: composer present, generating, send enabled. That is
the right report for an agent deciding its next step, and the wrong one for a person
deciding why the composer was not found: "false" says nothing about what *was* there. A
sketch does.

**A sketch is the page in outline.** Its path; its controls, by role and by label, where
the label is what a person would read on it — `Send message`, `Write your prompt to
Claude`, `Accept all`; and everything else by role and shape alone — how many links, how
long a heading, whether a dialog is open. Which of the tool's own selectors matched, by
name, and how many elements each found. Whether any dialog is pending.

**Labels are kept for controls and for nothing else.** A control is what a person presses,
types into, or is told by: buttons, text boxes, checkboxes, menu items, tabs, dialogs,
alerts, status regions. Their labels are the site's chrome, the same for every account,
and they are what the mock needs to reproduce. Everything else — headings, links, list
items, images, regions — is recorded as its role, its count and the length of its text,
never the text. A link in the sidebar is a conversation's title; a heading is one too; a
list item is a message. A sketch that kept those would be a transcript with the words
moved around.

**A sketch is taken at every move's start and end and at every navigation and dialog**,
and the same page costs one line: a sketch is named by a hash of its content, written in
full the first time that hash is seen in a trace and named by the hash after. A run that
polls a page for a minute leaves one sketch and sixty moves that point at it.

## 46. What a trace never carries

The rules of §10, §26 and §38 hold, and a trace adds its own:

- **No content.** No message, no title, no seed, no reply, no name of a file the account
  holds. The names the run log forbids as fields — `text`, `seed`, `title`, `content`,
  `snapshot`, `stdout`, `email`, `secret`, `credentials`, `link` — a trace forbids at
  every depth of every line, under the same strict switch, so that a mistake fails the
  build and never reaches a file in an operator's hands.
- **No query values.** A URL in a trace is its host, its path and the names of its query
  keys. A query value is a credential more often than not — a sign-in code, an emailed
  token — and a fragment is a value too.
- **No dialog messages, no headers, no bodies.** A dialog is recorded by type; a request
  by method, path and shape; a response by status, type and size. A cookie is a header,
  and a body is content.
- **No label outside a control's.** §45.

What a trace does carry is exactly what the mock is made of: paths, roles, labels of
controls, the shape of traffic, timing. None of it is personal, and all of it is the
same for every account on the site — which is why a trace of a real run can be read, cited
and committed (§49).

## 47. Marks, not a verdict

A trace of the mock mistaken for a trace of the real site would correct the mock against
itself. So a reader has to be able to tell the two apart — and the tool cannot: it has no
setting that names the mock, by [ADR 0001](../docs/adr/0001-no-door-in-the-wall.md), and
that is not going to change for the sake of a label.

**A trace records what it saw and lets the reader judge**
([ADR 0006](../docs/adr/0006-a-trace-says-what-it-saw.md)). Three marks, none of them a
verdict:

- the browser's extra arguments, as configured — the resolver rule that points the host
  at the mock is one of them, and it is in the header because it was in the
  configuration;
- the agent's version line, verbatim, as `hermes --version` printed it. The scripted
  agent (§23) says `(scripted agent)` in its line, so that it is a mark too;
- the certificate the browser was shown for the host: its issuer and its subject. The
  mock's is signed by itself, so its issuer is its own name; the real site's issuer is
  a public authority's. *(Amended by `36`: this section first said the mock's certificate
  names `claude-mock`. The mock writes that organisation into it, but a browser reports
  an issuer by its common name, so what a trace shows for the mock is an issuer equal to
  its subject — which is the mark of a certificate signed by itself, and enough.)*

A reader sees the mock's certificate and the scripted agent and knows it is reading a
rehearsal; the mock's certificate and a real Hermes, a run against the mock; a public
certificate, the real world. The filename says nothing of this, because the file is made
before the page is seen and a record is never renamed.

## 48. The rehearsal's traces

A rehearsal (§22) is the full run's protocol against the mock, and every step of it that
drives a tab now leaves a trace. The rehearsal runner, which knows what it is running,
gathers them:

```text
<root>/traces/03-login.jsonl
<root>/traces/06-import-pilot.jsonl
<root>/traces/09-import-all-again.jsonl
…

```

and the rehearsal record (§26) lists them — step, file, how many lines, what the
certificate said, what the agent said — so that a record names its evidence and a
reader can go from a pass criterion to the trace that would show it failing.

A rehearsal's traces are the **baseline**. They show what the mock does today, in the
same shape a real run's traces show what the site does. Laying the two side by side is
how the mock's next change is chosen, and it is the reason the shape is one shape and
the timing is recorded from the trace's own start rather than the wall clock.

## 49. Traces as evidence

§21 says a mock run never turns an *unknown* into an *observed on \<date\>*: only a
person watching claude.ai does that. This brief widens the sentence by one clause and
keeps its meaning: **a person who has read a trace of a run against claude.ai may mark
a row *observed on \<date\>*, citing the trace by file and line.** The trace is the
watching, kept; the person is still the one who marks.

A trace cited that way is committed, under `docs/spike/traces/`, beside the spike's other
evidence, once the person citing it has read it end to end. A trace carries no content
by construction (§46), so the reading is a check and not a redaction; a trace that turns
out to carry something it should not is a bug in the tool, fixed there, and the trace is
not committed until it is.

The mock's citations (§21) may then name a trace where they name a row: "this page does
what `docs/spike/traces/login-2026-09-20.jsonl` line 14 showed", in the mock's own words
and with nothing imported across the line
([ADR 0003](../docs/adr/0003-the-mock-is-a-separate-project.md)).

## 50. One shape for every source and every mock

Claude is the first site a trace is taken of and the only one this brief requires. The
tool will extract from ChatGPT and Gemini (§34), each will get a mock of its own the day
its extraction is rehearsed, and a trace of a ChatGPT extraction has to be what a ChatGPT
mock is corrected against. So:

- **the trace, the watch and the sketch know no site.** They are told a source's name,
  the host to watch, and the names of the selectors the source drives its pages with,
  and that is all they are told. A second source adds its own three and changes nothing
  in the shape;
- **the header names the source and the host**, so that a trace of a ChatGPT extraction
  and a trace of a Claude migration are the same kind of file, read by the same reader,
  and never confused;
- **a mock reads a trace, it does not import one.** What the four kinds of line mean is
  written here, once, and a mock project reads this brief and the files, not the tool's
  code (ADR 0003).

A migration is always into a Claude account (§1), so a migration's trace is always of
claude.ai; an extraction's trace is of whichever source was asked.

## 51. Later

Named so that a later brief or slice can claim them:

- a renderer: `dataporter trace <file>`, the outline of a trace for a person, when a
  person wants one — today the reader is Claude Code, and JSON lines are what it reads;
- a comparison: two traces in, the differences out, so that the mock's to-do list is
  computed rather than read off;
- a mock that reads traces directly, to serve the paths and controls a trace showed
  rather than the ones a person typed in from it — with the stateful, self-behaving
  mock of §21 kept, since a trace replayed is a fake and not a mock;
- screenshots beside a sketch, cropped by the person who commits them, where an outline
  is not enough;
- ChatGPT and Gemini: their sites, their selectors, their mocks, each its own slice, and
  the trace unchanged.
