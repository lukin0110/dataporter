# 21 — Scale-up and sign-off

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §19 (success criteria and metrics), §15 (fidelity write-up)
**Depends on:** [20](20-pilot.md)
**Enables:** nothing — this is the last slice
**Status:** In progress — the instruments and the documents are built and tested; the full
run has not happened. `spikes/sign_off.py` computes the gate, the §19 metrics, the drill
and the §17 audit from a workspace; `README.md`, `docs/runbook.md` and
`docs/experiment-02.md` exist, and `tests/test_scale_up_doc.py` keeps the write-up saying
`*not yet run*` until a run replaces a mark. `20` is the gate on the rest, and `20` has
not been run either.

## Goal

Migrate the complete export, measure the result against §19, and write down what the
experiment showed — including what it could not do.

## In scope

- Go / no-go gate, checked before the full run and recorded in `docs/experiment-02.md`:
  pilot question 1 ≥ 90 %, question 2 ≥ 90 % for parts under 50 k characters, question 3
  no `fail`, and every pilot `Failures` line understood (a reason, not a shrug).
- Full run: `import <export> --all`, in sessions of at most `run.max_conversations × 5`
  with `--limit`, resumed across sessions from state (`06`), with `run.json` carrying every
  session. Interruptions are expected and recorded, not avoided.
- An interruption drill inside the full run: kill the process (SIGKILL) mid-conversation
  once, run `import` again, and confirm no duplicate chat (count of `/chat/<uuid>` ids in
  state equals `Created + Partial`) and no lost conversation.
- Metrics, each a number in `docs/experiment-02.md`:

  | §19 metric | Measure |
  | --- | --- |
  | **Primary:** conversations migrated without human intervention | `completed` conversations whose `attempts == 1` and which appear in no `paused` record ÷ source conversations |
  | semantic fidelity | semantic probe pass rate on a random sample of 20 completed conversations (`20`'s probe) |
  | migration speed | conversations per hour, wall-clock, from `run.json` |
  | browser reliability | `Browser actions` ÷ (retries + recovery rows fired) |
  | recovery rate | conversations that ended `completed` after at least one retry or recovery ÷ conversations that needed one |
  | attachment coverage | `Attachments migrated` ÷ attachments found, and by class |
  | manual interventions | `Human interventions`, with reasons |

- Documentation:
  - `README.md` — what the tool does, the install steps (Hermes installer, `setup`,
    `doctor`, `login`, `import --dry-run`, `import --pilot`, `import --all`), what it will
    never do (§17), and where content ends up (workspace, Hermes profile) and how to purge
    it;
  - `docs/LIMITATIONS.md` finalised from observation: one heading per limitation name in
    the report, with the count from the full run and whether it is a UI limit, an export
    limit or a tool choice;
  - `docs/runbook.md` — interrupting, resuming, retrying failures, handling an
    intervention, reading the report, cleaning up the throwaway account if needed (by
    hand — the tool never deletes at the destination);
  - `docs/experiment-02.md` — the metrics, the drill result, what was not observed, and a
    plain statement of whether §19's success criterion was met.
- Every slice's **Status** in `specs/README.md` set to `Done` or, if something was
  descoped, to `Done (partial)` with a link to the reason in `experiment-02.md`.

## Out of scope

- Improving the numbers. Anything the write-up suggests becomes a new slice.

## Design notes

- The gate thresholds are the pilot's numbers, not aspirations: a full run on a tool
  that failed one chat in ten would produce a report nobody can act on. Failing the gate
  sends the work back to the slice that owns the failure, not to a bigger run.
- Sessions of bounded size, resumed from state, are how a days-long run stays
  observable: each session ends with a report the operator can read before starting the
  next.

Resolved while building:

- **The instruments are a script, not a command.** `21` adds nothing to `01`'s command
  surface: the gate, the metrics, the drill check and the §17 audit read a finished
  workspace and are of no use to a migration, so they live in `spikes/sign_off.py` beside
  `10`'s scripts, which `make check` lints and type-checks and the wheel does not ship.
  The alternative — a `metrics` command — would have put a number nobody migrates with
  into the tool's `--help` forever.
- **Every number in the write-up is printed by that script.** A sign-off whose numerators
  were counted by hand is a sign-off nobody can reproduce; `sign_off.py metrics` prints
  the §19 table as Markdown, to be pasted, with `numerator ÷ denominator` beside every
  rate. Where a term is not in the workspace at all it prints `—` and says what to supply,
  rather than reporting the half it has: the in-run recovery rows `13` leaves only in a
  transcript (`--recoveries N`), and the probe grades a person writes down.
- **"In no `paused` record" is read out of the run log.** `run.json` holds the pause
  nobody has cleared yet and forgets it on `resume`, so the primary metric would otherwise
  count a conversation a person rescued as unattended. `12` logs
  `human intervention required` with the conversation's short id, and the logs are the
  per-conversation record the metric needs. The open pause in `run.json` is added to it.
- **Question 2's bucket is per conversation, not per part.** `state.json` counts
  acknowledgements per conversation (`chunks_acked` against `chunks_total`), so a
  conversation with one part over 50 k characters is left out of both terms of the gate
  and named separately, rather than having its acks split across buckets by a script that
  cannot know which part was refused.
- **The history audit fails on another host and reports another claude.ai path.** The
  criterion says the profile's history holds only `/new` and `/chat/<id>`; a `login` that
  really happened also visits `/login`. A foreign host or a chat id this workspace never
  created is a finding the script asserts; another claude.ai path is one it counts and
  prints for a person to judge. It selects the `url` column and never `title`, because a
  claude.ai page title is somebody's conversation (§10).
- **The write-up exists before the experiment does, and is marked.** `20`'s rule, inherited
  wholesale: `docs/experiment-02.md` carries `*not yet run*` against every number, and
  `tests/test_scale_up_doc.py` refuses a document that claims a measurement while its
  status line still says none. It is why this slice can be `In progress` with everything
  built — the instruments are testable here, the numbers are not.
- **The status sweep is the one deliverable that cannot be prepared.** Setting every slice
  to `Done` before the run that would justify it is exactly the claim this slice exists to
  make honestly, so `specs/README.md` still says what is true today and
  `docs/experiment-02.md` holds the section the sweep is recorded in.

## Acceptance criteria

- The full run finishes with every conversation in a terminal status and a report that
  reconciles (`19`).
  *Not met:* the run has not happened. The reconciliation itself is `19`'s criterion and
  its tests hold it for any workspace; `sign_off.py drill` checks it again at sign-off.
- The interruption drill shows zero duplicates and zero lost conversations.
  *Prepared:* `sign_off.py drill` counts distinct `/chat/<id>` ids against
  `Created + Partial`, names any id two entries share, and refuses a workspace with
  anything left pending. `tests/test_sign_off.py` drives both the passing and the
  duplicated case.
- Every §19 metric has a number in `docs/experiment-02.md`, and the primary metric is
  stated as a percentage with its numerator and denominator.
  *Prepared:* every metric has a row, a measure and one mark, and the rows are
  `sign_off.py metrics`'s own labels — `tests/test_scale_up_doc.py` compares the two, so a
  metric renamed on one side fails the build.
- `docs/LIMITATIONS.md` names only limitations that actually appeared in the report, with
  counts.
  *Prepared:* every name the code can print has a heading, a count and a kind (UI limit,
  export limit or tool choice); the counts are marked `*not yet run*`, and a name whose
  count stays empty after the run is one the run never saw.
- A reader who has never seen the project can run `login`, `import --dry-run` and
  `import --pilot` from `README.md` alone.
  *Met:* `README.md` is the install, the six commands in order, the §17 boundary and the
  three places content ends up with the command that purges each. A test checks the steps
  are there and that every command it names exists.
- The source export's SHA-256 is unchanged after the full run; the source account was
  never opened by the tool (the browser profile's history contains only `claude.ai/new`
  and `claude.ai/chat/<id>` URLs created by this workspace — checked by a script over the
  profile's `History` database).
  *Prepared:* `sign_off.py safety` re-digests `conversations.json` against the fingerprint
  the run recorded, and reads the profile's `History` — the `url` column only — into four
  buckets, failing on a foreign host or a chat this workspace did not create.

## Risks

- The full run may take days at the §13 pace. That is acceptable; the state file is
  built for it, and the write-up records the elapsed time as the speed metric.
