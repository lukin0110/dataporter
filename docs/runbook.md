# Runbook

**Kind:** Operator's handbook — what to do while a migration is running, and what to do
when it stops. Produced by [`21`](../specs/impl/21-scale-up.md).
**Audience:** whoever is sitting in front of the full run.
**Companion:** [`README.md`](../README.md) is how to get to a first pilot; this is
everything after that.

The full run is days of sessions on a slow, sequential, account-modifying loop, and it is
designed to be interrupted rather than babysat. Nothing below is a recovery procedure for
an unexpected state — all of it is the normal shape of the run.

## The session loop

```sh
hermes-claude-migrate import <export> --all --limit 50     # one session
hermes-claude-migrate report                               # read it before the next
```

`--limit 50` is `run.max_conversations × 5`, the session size [`21`](../specs/impl/21-scale-up.md)
runs the experiment at; `--all` is what lifts the configured ceiling of ten, and without it
a `--limit` above that ceiling is refused rather than quietly honoured. A session ends with
the §16 report on stdout and every conversation it touched in a terminal status. Run the
same command again for the next session: what is already `completed` is not selected
again, so the command is its own resume.

Exit codes are the summary: `0` everything landed, `1` at least one conversation failed or
is partial, `5` the run is paused for a person (see below), `4` there was nothing left to
do — which is how the full run ends.

## Interrupting

Ctrl-C, `kill`, a closed laptop, a power cut: all the same thing. Every workspace file is
written whole and replaced atomically, so an interrupted run leaves either the previous
file or the new one, never half of either.

What is left behind is a conversation recorded as `running` — the status that means "a
process was working on this and did not say how it ended". The next `import` converts it
before selecting anything, counts it in `run.json.interrupted`, and migrates it again from
its last verified step. A chat that was already created is resumed in place rather than
created a second time.

If the killed process held the workspace lock and is gone:

```sh
hermes-claude-migrate import <export> --all --limit 50 --force-unlock
```

`--force-unlock` removes a lock whose owner is not running. It refuses to remove one whose
owner is, which is what stops two runs writing to one account.

## Resuming a pause

Six things stop the run and ask for a person (§12): authentication required, a CAPTCHA, a
security challenge, an ambiguous UI state, an unrecoverable browser error, and a
confirmation the agent will not give itself — which is also how a rate limit too long to
sit out arrives. On a terminal the ask is printed and the run waits:

```text
Human intervention required

Reason:       CAPTCHA
Conversation: 8a02c7d1 (4 of 50)
Last step:    submit
Browser:      the Chrome window is open — complete the step there

Press Enter to resume, or Ctrl-C to stop.
```

Do the thing in the Chrome window the run already has open — solve the CAPTCHA, sign in
again, dismiss the dialog — and press Enter. The conversation continues from its last
successful step; it is never restarted, and nothing is sent twice.

Off a terminal (a cron job, a CI step, a detached session) there is nobody to ask, so the
run writes the pause to `run.json` and exits `5`. Clear whatever it was asking about, then:

```sh
hermes-claude-migrate resume
```

`resume` continues the paused run's own selection with the paused conversation first. It
takes no arguments: the export it was migrating is recorded in `run.json`. An `import`
started while a pause is outstanding says
`paused at 8a02c7d1 — run: hermes-claude-migrate resume` before it does anything else:
answer that first, rather than letting a fresh run pick the paused conversation up on its
own terms.

## Retrying failures

Read the report first. Each failure line carries the last successful step, the category,
the error and a verdict:

```text
Failures and partial migrations:
  3f9c2a1e  failed    step=submit    generation: response never completed    retry=yes
  c41d90aa  failed    step=-         unsupported: empty_conversation         retry=no
```

`retry=yes` means the category is transient and another attempt is worth making;
`retry=no` means it is not, and a second run would fail the same way; `retry=unknown` is
the tool declining to guess — look at the conversation before deciding.

```sh
hermes-claude-migrate import <export> --retry-failed --retry-partial --limit 50
hermes-claude-migrate import <export> --only 3f9c2a1e                  # just this one
```

`--only` names conversations whatever their status, so it needs none of the retry flags —
and so naming one that already `completed` migrates it a second time. A `partial` retry
resumes in the chat that already exists rather than creating another; a conversation that
is migrated again from the start gets a **new** chat, and the old one stays in the account
(§17 forbids deleting it) with its id kept in `run.json.previous_destinations`. `--force`
is the same thing over a wider selection: it widens what counts as unfinished to include
`completed`.

If the run stopped itself with `stopping: 3 consecutive failures (network) — see report`,
that is the circuit breaker: three conversations failed the same way in a row, which is a
condition in the environment rather than in those three conversations. Fix the condition —
signal, session, rate limit — and run the session again.

## The interruption drill

Once inside the full run, on purpose ([`21`](../specs/impl/21-scale-up.md)):

```sh
kill -9 <pid of the import>           # mid-conversation
hermes-claude-migrate import <export> --all --limit 50 --force-unlock
uv run python spikes/sign_off.py drill --workspace migration
```

The drill passes when `state.json` holds one distinct `/chat/<id>` per landed conversation
— no duplicate chat — and every source conversation is still in a terminal status. The
script checks exactly that, and says which ids collided if any did.

## Reading the report

```sh
hermes-claude-migrate report            # the §16 block, the failures, the limitations
hermes-claude-migrate report --json     # the same numbers, for a script
hermes-claude-migrate status            # per conversation, from state.json
```

The report reconciles: `Created + Partial + Failed + Pending == Source conversations`, and
`Pending` is what this run has not reached yet. `Limitations:` counts conversations, not
occurrences, and every name in it is described in [`LIMITATIONS.md`](LIMITATIONS.md).

To check the account itself rather than what the run believes about it:

```sh
hermes-claude-migrate verify                       # every migrated chat, re-read
hermes-claude-migrate verify --only 8a02c7d1
```

`verify` opens the browser and no Hermes at all: it is the second opinion, so it asks the
page rather than the agent that wrote to it.

## Signing the run off

```sh
uv run python spikes/sign_off.py gate    --workspace migration   # before the full run
uv run python spikes/sign_off.py metrics --workspace migration   # §19's table
uv run python spikes/sign_off.py sample  --workspace migration   # the 20 to probe
uv run python spikes/sign_off.py safety  --workspace migration --export <export>
```

The numbers go into [`experiment-02.md`](experiment-02.md), which is what `21` is for. The
gate is checked against the pilot's workspace **before** the full run starts; the rest
after it finishes.

## Cleaning up

The tool deletes nothing at the destination, ever, so clearing the throwaway account is a
manual job:

1. `hermes-claude-migrate status --json` lists every source conversation with the
   destination chat id it landed in; `run.json`'s `previous_destinations` holds the chats
   superseded by a `--force` re-run.
2. Delete those chats in the Claude UI yourself, or delete the throwaway account.
3. `rm -rf migration/` removes the workspace — seeds, attachments, state, the signed-in
   browser profile and the probe replies.
4. `rm -rf ~/.hermes/profiles/dataporter/` removes Hermes's session transcripts, which
   contain page snapshots and therefore conversation content. `setup` prints this path on
   every run for exactly this moment.

`hermes-claude-migrate session logout` removes the browser profile alone, which is the
local half of step 3. It ends no session anywhere else and touches nothing in the account.
