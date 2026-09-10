# 21 — Scale-up and sign-off

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §19 (success criteria and metrics), §15 (fidelity write-up)
**Depends on:** [20](20-pilot.md)
**Enables:** nothing — this is the last slice
**Status:** Not started

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

## Acceptance criteria

- The full run finishes with every conversation in a terminal status and a report that
  reconciles (`19`).
- The interruption drill shows zero duplicates and zero lost conversations.
- Every §19 metric has a number in `docs/experiment-02.md`, and the primary metric is
  stated as a percentage with its numerator and denominator.
- `docs/LIMITATIONS.md` names only limitations that actually appeared in the report, with
  counts.
- A reader who has never seen the project can run `login`, `import --dry-run` and
  `import --pilot` from `README.md` alone.
- The source export's SHA-256 is unchanged after the full run; the source account was
  never opened by the tool (the browser profile's history contains only `claude.ai/new`
  and `claude.ai/chat/<id>` URLs created by this workspace — checked by a script over the
  profile's `History` database).

## Risks

- The full run may take days at the §13 pace. That is acceptable; the state file is
  built for it, and the write-up records the elapsed time as the speed metric.
