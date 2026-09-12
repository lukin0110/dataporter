# Experiment 02 — the full run

**Kind:** Experiment record — what the complete migration measured, not what was designed.
Produced by [`21`](../specs/impl/21-scale-up.md).
**Answers:** [§19](../specs/01-initial-brief.md)'s success criterion and its six secondary
metrics, with numbers.
**Full run:** none.
**Export:** unknown. **Source conversations:** unknown. **Tool version:** unknown.
**Hermes version:** unknown. **Chrome version:** unknown.

Every number below carries a mark: `*measured on <date>*` when a run produced it,
`*not yet run*` when none has. `tests/test_scale_up_doc.py` enforces that each §19 metric
carries exactly one marked number, that the gate has a row per threshold `21` sets, and
that the status line above stops saying `none` as soon as any number claims a measurement.
It is the rule [`10`](../specs/impl/10-attach-spike.md)'s spike documents and
[`20`](../specs/impl/20-pilot.md)'s pilot write-up already follow, for the same reason: a
question nobody answered has to look different from one answered badly.

Nothing in this file may carry conversation content — not a title, not a message, not an
account identifier (§10). Conversations are named by their eight-character short id.

Every number in this document is produced by a script over the workspace, so that a reader
can reproduce it rather than trust it:

```sh
uv run python spikes/sign_off.py gate    --workspace migration
uv run python spikes/sign_off.py metrics --workspace migration --recoveries <N>
uv run python spikes/sign_off.py drill   --workspace migration
uv run python spikes/sign_off.py safety  --workspace migration --export <export>
```

## The gate

Checked against the **pilot's** workspace ([`experiment-01.md`](experiment-01.md)) before
the full run starts, and recorded here whether it passed or not. Failing the gate sends
the work back to the slice that owns the failure; it is not a reason to run anyway with a
note about it.

| Gate | Threshold | Number | Verdict | Mark |
| --- | --- | --- | --- | --- |
| Pilot question 1 — chats created ÷ attempted | ≥ 90 % | — | — | *not yet run* |
| Pilot question 2 — parts acked, parts < 50 k chars | ≥ 90 % | — | — | *not yet run* |
| Pilot question 3 — semantic probe grades | no `fail` | — | — | *not yet run* |
| Every pilot `Failures` line understood | a reason, not a shrug | — | — | *not yet run* |

**Verdict:** not yet run. *not yet run*

Where a failure line's reason is not obvious from the report, it is written out here —
one line per failure, naming what happened and which slice owns it.

*not yet run*

## The full run

How it was run: `import <export> --all --limit 50`, in sessions of at most
`run.max_conversations × 5`, resumed from state between sessions, every session appended
to `run.json`. Interruptions are expected and recorded rather than avoided.

| | Number | Mark |
| --- | --- | --- |
| Sessions | — | *not yet run* |
| Wall-clock hours, summed over sessions | — | *not yet run* |
| Elapsed days, first session to last | — | *not yet run* |
| Conversations in a terminal status | — | *not yet run* |
| Report reconciles (`Created + Partial + Failed + Pending == Source`) | — | *not yet run* |

The §16 block of the last session goes here verbatim, from `dataporter report`.

*not yet run*

## The metrics (§19)

The primary metric is stated as a percentage **with its numerator and denominator**,
because a rate without its terms is not a result. `Number` is what the script printed;
`Terms` is `numerator ÷ denominator`.

| §19 metric | Measure | Number | Terms | Mark |
| --- | --- | --- | --- | --- |
| Primary: migrated without human intervention | `completed` conversations with `attempts == 1` that appear in no pause record ÷ source conversations | — | — | *not yet run* |
| semantic fidelity | semantic probe pass rate over a random sample of 20 completed conversations (`20`'s probe) | — | — | *not yet run* |
| migration speed | conversations per hour, wall-clock, summed over the sessions in `run.json` | — | — | *not yet run* |
| browser reliability | `Browser actions` ÷ (retries + recovery rows fired) | — | — | *not yet run* |
| recovery rate | conversations that ended `completed` after at least one retry or recovery ÷ conversations that needed one | — | — | *not yet run* |
| attachment coverage | `Attachments migrated` ÷ attachments found, and by class | — | — | *not yet run* |
| manual interventions | `Human interventions`, with the reason each ask carried | — | — | *not yet run* |

Two of these cannot be read out of the workspace alone, and the script says so rather than
reporting the half it has:

- **semantic fidelity** needs the sample graded. `sign_off.py sample` names the twenty
  conversations, `followup --only …` asks each one `20`'s question, and the grades go in
  the table below. `judge` records a model's opinion beside them.
- **browser reliability** needs the in-run recovery rows counted in the transcripts —
  `13`'s table, one row per recovery Hermes attempted — and passed as `--recoveries N`.

### Attachment coverage, by class

| Class | Found | Migrated | Mark |
| --- | --- | --- | --- |
| 1 — inline, in the export's `extracted_content` | — | — | *not yet run* |
| 2 — bytes on disk, uploaded through the composer | — | — | *not yet run* |
| 3 — unsupported, recorded and not sent | — | — | *not yet run* |

### Semantic probe grades

The random sample of 20, graded by hand; the judge's verdict beside it where the `judge`
extra was installed. A disagreement between the two columns is a finding about the judge.

| Conversation | Hand grade | Why | Judge | Mark |
| --- | --- | --- | --- | --- |
| — | — | — | — | *not yet run* |

### Manual interventions, by reason

| Reason | Count | Mark |
| --- | --- | --- |
| — | — | *not yet run* |

## The interruption drill

One SIGKILL, mid-conversation, inside the full run, then `import` again. The claim is that
a killed run costs no conversation and creates no duplicate chat.

| Check | Number | Mark |
| --- | --- | --- |
| Distinct `/chat/<id>` ids in `state.json` | — | *not yet run* |
| `Created + Partial` | — | *not yet run* |
| Conversations lost | — | *not yet run* |
| Entries recovered out of `running` | — | *not yet run* |

**Verdict:** not yet run. *not yet run*

## Safety (§17)

One row per check `sign_off.py safety` prints, in its order, so the block is pasted rather
than aggregated:

| Check | Number | Mark |
| --- | --- | --- |
| `export sha-256 unchanged` — the source export re-digested, against the fingerprint the run recorded | — | *not yet run* |
| `history: migration URLs` — `/new` and `/chat/<id>` this workspace created | — | *not yet run* |
| `history: chats this workspace did not create` — fails the audit | — | *not yet run* |
| `history: other hosts` — fails the audit | — | *not yet run* |
| `history: other claude.ai paths` — `/login` and the like, counted for a person to judge | — | *not yet run* |

The source account was never opened by the tool: it has no credential for it, it reads the
export as a file, and the only browser it drives is the profile inside the workspace.
`sign_off.py safety` is what checks the second half of that claim, over the profile's own
`History` database.

## What was not observed

`21` treats what the run did not meet as untested rather than as working. Anything the
full run never provoked — a rate limit, a CAPTCHA, a login expiry mid-session, the circuit
breaker, an export whose attachment bytes exist, a chat the rename refused — goes here,
with what would have to happen to see it.

*not yet run*

## Was §19's criterion met?

§19 is met if the tool "can take a Claude export and automatically reconstruct a useful
representation of its conversations in another Claude account through the Claude web
interface", and the primary metric is how many conversations made it without a person.
A plain sentence, not a gradient:

**Answer:** not yet run. *not yet run*

## Slice statuses

[`specs/README.md`](../specs/README.md)'s status column is swept at sign-off: every slice
`Done`, or `Done (partial)` with a link to the reason in this file. A slice descoped
during the full run is named here with what was left out and why.

*not yet run*

## Limitations

[`LIMITATIONS.md`](LIMITATIONS.md) is finalised from this run: one heading per limitation
name the report prints, the count from the full run, and whether it is a UI limit, an
export limit or a tool choice. A limitation with no count there is one this run never saw.

*not yet run*
