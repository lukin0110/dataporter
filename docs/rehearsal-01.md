# Rehearsal 01 — non-interactive

**Kind:** Rehearsal record — what a rehearsal measured, not what was designed.
Produced by [`29`](../specs/impl/29-rehearsal.md).
**Answers:** [§25](../specs/02-claude-mock.md)'s pass criteria, with numbers.
**Rehearsal run:** 2026-09-12. **Mode:** `non-interactive`.
**Tool:** hermes-claude-migrate 0.1.0. **Scripted agent:** scripted agent 1.0.0. **Chrome:** Chromium 141.0.7390.37.
**Mock:** 0.1.0.

A rehearsal is the full run's protocol
([`experiment-02.md`](experiment-02.md)) run by the shipped tool against the
mock, with the scripted agent standing where Hermes stands. It is **not evidence
about claude.ai**: every `*unknown*` in [`claude-ui-map.md`](claude-ui-map.md) is
still `*unknown*` after it, semantic fidelity is *not applicable* rather than
passed, and whether a model can follow the skill is the pilot's question (§27).

Nothing here carries conversation content: conversations are named by their
eight-character short id (§10).

## How it was run

| | |
| --- | --- |
| Mode | `non-interactive` |
| Pacing | 0s between conversations, 0s between parts |
| Response timeout | 120 s |
| Browser | headless: true |
| Chrome extra arguments | `--host-resolver-rules=MAP claude.ai 127.0.0.1:8443`, `--ignore-certificate-errors-spki-list=e3+5wzOchmkg/grrkObhsjI1CSMwW+f6XnBzLNyXgl4=`, `--no-proxy-server`, `--no-sandbox`, `--disable-gpu`, `--disable-dev-shm-usage` |

The two arguments the mock printed are the whole of how the tool reaches it. The
rest are what this machine needs to run any browser at all. The tool itself has
no setting that names the mock (§22).

## The protocol

| Step | Exit | Seconds | Note |
| --- | --- | --- | --- |
| `setup` | 0 | 4.9 |  |
| `doctor (before login)` | 6 | 2 | a signed-out tab has redirected to /login |
| `login` | 0 | 2.5 |  |
| `doctor (after login)` | 0 | 2.7 |  |
| `import --dry-run` | 0 | 0.4 |  |
| `import --pilot` | 0 | 51.3 |  |
| `report (after pilot)` | 0 | 0.3 |  |
| `import --all (interrupted)` | -9 | 3 | SIGKILL mid-conversation |
| `import --all (again)` | 0 | 23 |  |
| `verify` | 0 | 3 |  |
| `report` | 0 | 0.4 |  |
| `followup` | 0 | 52 |  |
| `status` | 0 | 0.4 |  |
| `session status` | 0 | 0.9 |  |
| `sign_off.py gate` | 1 | 0.4 | its last rows are for a person to judge |
| `sign_off.py drill` | 0 | 0.3 |  |
| `sign_off.py safety` | 1 | 0.3 | its last rows are for a person to judge |
| `session logout` | 0 | 0.4 |  |

## The report, and the ledger beside it

The tool's own §16 block, and what the mock counted while it was produced. The
ledger is read after `verify` and before `followup`, because a follow-up probe
sends one more message per chat and §25 reconciles the migration's messages.

```text
Claude migration complete

Source conversations:         10
Created:                       9
Partial:                       0
Failed:                        1

Messages represented:         98
Attachments migrated:          2

Browser actions:              72
Retries:                       1
Human interventions:           0

Failures and partial migrations:
  f6000006  failed    step=-         unsupported: empty_conversation    retry=no

Limitations:
  timestamps_not_preserved      9
```

```text
Mock claude.ai — ledger

Sign-ins:                      1
Chats created:                10
Messages received:            11
Files accepted:                1
Renames:                       9
```

## Pass criteria (§25)

| Criterion | Number | Verdict | Mark |
| --- | --- | --- | --- |
| every migratable conversation completed at its first attempt | 9/9, drill interrupted 1 | pass | *measured on 2026-09-12* |
| no pause recorded | human interventions: 0 | pass | *measured on 2026-09-12* |
| the report reconciles | 9 + 0 + 1 + 0 == 10 | pass | *measured on 2026-09-12* |
| verify finds the source line and every ack line | exit 0 | pass | *measured on 2026-09-12* |
| every conversation ends with its title set | 9/9 titles set | pass | *measured on 2026-09-12* |
| the drill loses no conversation and creates no duplicate chat | Interruption drill | pass | *measured on 2026-09-12* |
| the safety audit finds no host but claude.ai | other hosts: 0, chats this workspace did not create: 0 (other claude.ai paths: 1, for a person to judge) | pass | *measured on 2026-09-12* |
| ledger: chats created == distinct chat ids in the state | 10 == 9 + 1 (the chat the killed run created and never recorded) | pass | *measured on 2026-09-12* |
| ledger: messages received == parts sent | 11 == 10 + 1 (the part the killed run had sent) | pass | *measured on 2026-09-12* |
| ledger: files accepted == attachments migrated by upload | 1 == 1 | pass | *measured on 2026-09-12* |
| ledger: renames == titles set | 9 == 9 | pass | *measured on 2026-09-12* |
| ledger: sign-ins == logins + automatic sign-ins | 1 == 1 + 0 | pass | *measured on 2026-09-12* |

**Verdict:** passed. *measured on 2026-09-12*

## What it found

- `doctor` before `login` fails `hermes attaches to chrome`: the check asks the agent for the URL of the other tab, and a signed-out tab has redirected to `/login`. True of claude.ai too, so it is recorded rather than worked around; `doctor` is run again after `login`, where it passes.
- The sign-off instruments are run before `session logout` rather than after it, as §23's order has them: the safety audit reads the browser profile's own History database, and `logout` deletes the profile.
- `sign_off.py gate` and `sign_off.py safety` both exit 1, and neither is a failed criterion: the gate's third question needs hand-graded semantic probes, which against the mock are *not applicable* (§27), and its fourth asks a person to explain the one failure line (the unsupported conversation); the audit counts the run's own `/login` visit as an `other claude.ai path` for a person to judge. §25's two safety rows — no other host, and no chat this workspace did not create — are read off the audit's table above.
- The interruption drill leaves a chat the tool never learned the id of, because a one-shot agent reports the id when it returns. The retry starts another chat, and the mock counts both. The tool's own drill instrument cannot see it; the ledger can, and the reconciliation above carries it.

## What it could not exercise

- Anything about claude.ai. The mock is a consequence of the UI map, never
  evidence about it.
- Whether a model can follow the skill (§18, questions 4 and 5): a rehearsal
  involves no model.
- Semantic fidelity (§15, §19): *not applicable* against a stand-in that replies
  with the line it was asked for.
- The failure states the mock cannot yet produce (§21): a rate limit, a login
  expiry mid-run, a modal or JavaScript dialog, a generation error, a CAPTCHA or
  security challenge, a code prompt at sign-in.
- `judge`: it needs a model, and against the mock it would grade noise.

