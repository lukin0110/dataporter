# 29 — The rehearsal

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 02](../02-claude-mock.md) §22, §23, §25, §26, §27
**Depends on:** [26](26-mock-claude.md), [27](27-scripted-hermes.md),
[28](28-rehearsal-export.md), and everything the protocol invokes
**Enables:** a passed rehearsal, which is the precondition for spending the
throwaway account on [10](10-attach-spike.md)
**Status:** Done

## Goal

One command that runs the shipped tool through the full run's protocol against
the mock, checks §25's pass criteria — including the reconciliation against the
mock's ledger — and, when asked, leaves §26's record.

The tool it runs is the tool that ships. It is invoked as a black-box process,
with flags an operator may type and a `config.toml` an operator may write. There
is no flag, environment variable or host setting anywhere in it that names the
mock (ADR [0001](../../docs/adr/0001-no-door-in-the-wall.md)).

## In scope

- **`rehearsal/run.py`**, and `python -m rehearsal.run --root <dir>
  [--mode non-interactive|interactive] [--chrome PATH] [--record docs/rehearsal-NN.md]`.
- **Preparation**: `28`'s export; a `config.toml` carrying the two arguments the
  mock printed (`--host-resolver-rules`, `--ignore-certificate-errors-spki-list`)
  plus whatever this machine needs to run a browser at all; `27`'s `hermes` on a
  `PATH` the steps inherit; the credentials in the environment, never in the
  file the tool refuses to read them from.
- **The pin is computed, not pasted**: `spki_pin` reads the certificate the mock
  is actually serving and hashes its SubjectPublicKeyInfo, which is the same
  string the mock printed. It keeps the runner independent of the mock's files —
  and pins the rehearsal to the key of the process it is really talking to.
- **A fresh mock is required.** §25 reconciles the report against the *whole* of
  the ledger, so a mock that has already counted something is refused with a
  sentence saying to restart it.
- **The protocol** (§23), in §23's order, each step's exit code, duration and
  output recorded (`<root>/protocol/NN-step.{out,err}`; nothing is printed,
  because a step's output is the tool's and a transcript may carry a title):
  `setup`, `doctor`, `login`, `doctor` again, `import --dry-run`,
  `import --pilot` and `report`, `import --all` interrupted by one `SIGKILL`
  mid-conversation, `import --all` again, `verify`, `report`, `followup`,
  `status`, `session status`, `session logout`, then the sign-off instruments
  (`gate`, `drill`, `safety`). `judge` is not part of it: it needs a model.
- **The drill kills on the mock's evidence**: the run is killed the moment the
  *ledger* shows a message received, which is a conversation in flight said by
  the only party that is not the tool describing itself.
- **§25's criteria**, computed: completion at the first attempt over `28`'s
  `MIGRATABLE`, no pause, the report's reconciliation, `verify`, titles, the
  drill, the safety audit, and the five ledger identities. The ledger is read
  after `verify` and **before** `followup`, because a probe sends one more
  message per chat and §25 reconciles the migration's messages.
- **The drill's own share is measured**: the ledger is read immediately before
  the killed run starts and immediately after it dies, and that delta is carried
  on the ledger's side of each identity — the chat it created and never learned
  the id of, and the part it sent into it. A rehearsal still reconciles to the
  character, with what the kill cost written out rather than waved at.
- **`render`** writes §26's record: the versions of the tool, the scripted agent,
  Chrome and the mock; the mode and the pacing; the protocol table; the report's
  §16 block and the ledger block side by side; the criteria with
  `*measured on <date>*` on every number; what it found; and what it could not
  exercise. Exit `0` when every criterion passed, `1` when one did not.

## Out of scope

- Starting the mock or a browser. The mock is a process the operator starts, as
  Chrome is; the tool launches Chrome itself.
- Continuous integration. §23 neither requires nor forbids it, and the decision
  belongs to the slice that would add it.
- `judge`, a real Hermes, and the failure states §21 lists. §28 keeps them.

## Design notes

- **Interactive mode signs in unattended.** §23 wants both modes and §25 wants no
  person to have helped, and interactive `login` is the one step that waits for
  one. The runner's interactive mode is therefore interactive everywhere except
  the sign-in, and the record says so under *what it could not exercise*. A
  headless-but-attended run is `browser.headless = true` with the mode left
  interactive, which is the switch `24` already provides.
- **`doctor` is run twice.** §23 puts it before `login`, and there it fails:
  `hermes attaches to chrome` asks the agent to report the URL of the other tab,
  and a signed-out tab has redirected to `/login`. That is true of claude.ai too,
  so it is recorded as a finding rather than worked around, and `doctor` is run
  again afterwards where it can pass.
- **The record is rendered from numbers, not from prose.** Everything in it is
  something this run measured; the only hand-written part is the list of what a
  rehearsal cannot be evidence of, which is §27 and does not vary.

## Acceptance criteria

- Against a freshly started mock, `python -m rehearsal.run --root <dir>` exits
  `0` and every §25 criterion reads `pass`.
- The record it writes names four versions, both blocks, and carries a mark on
  every number.
- No file it writes and nothing it prints carries a message, a title or an
  account identifier.
- Run twice against the same fresh mock, it refuses the second time.

## Risks

- **A rehearsal can only find what the mock can show.** The failure states §21
  lists are exactly the ones a migration is most likely to meet on the real site.
- **The drill leaves an orphan chat, by construction.** A one-shot agent reports
  the chat's id when it returns, so a run killed before it returns leaves a chat
  the tool never learned about and the retry starts another. The ledger is what
  makes that visible — the tool's own drill instrument cannot see it — and the
  record names it. It is a property of the design rather than a defect in it, and
  it belongs in `LIMITATIONS.md` at sign-off.
- **Three defects it has already found** are `24`'s sign-in reading a page
  mid-navigation as a challenge, `07`'s first probe reading a tab that has not
  rendered as a session that expired, and `17`'s verification reading a large
  transcript after its first turn. All three are races that a fake page cannot
  have, which is the argument for the mock existing.
