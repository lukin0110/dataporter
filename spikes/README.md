# Spike scripts

Scripts that are not product code. [`10`](../specs/impl/10-attach-spike.md) is a
time-boxed spike and this is the tree it was allowed to leave behind — prompts that are
not skills, and scripts that drive a page by hand — and
[`21`](../specs/impl/21-scale-up.md) added one more, for the same reason rather than the
same purpose: `sign_off.py` reads a finished workspace and prints the gate, the §19
metrics, the drill check and the §17 audit, and a migration needs none of it.
`pyproject.toml` excludes `spikes/` from the sdist and the wheel packages only
`src/dataporter`, so nothing here is installed with the tool. `make check` does lint and
type-check it, because a script nobody can run after the next refactor cannot repeat the
spike, and repeating the spike after a claude.ai change is the reason to keep it.

What the spike *concludes* goes in [`docs/`](../docs/). This file is how to conduct it.

`21`'s script is documented where it is used: [`docs/runbook.md`](../docs/runbook.md) for
the operator, [`docs/experiment-02.md`](../docs/experiment-02.md) for the numbers it
produced. Everything below is `10`'s.

## Before anything

- **A throwaway destination account.** Never the source account, never the operator's own.
  Everything below writes to it.
- `hermes-claude-migrate setup` has run and `hermes-claude-migrate doctor` reports every
  line, or has told you exactly which one it stops at.
- `hermes-claude-migrate login` has left a headed Chrome signed in to the throwaway
  account, on one claude.ai tab.
- `uv run python spikes/spike.py context` prints a Hermes version and a Chrome version
  rather than `unknown` for both. If it does not, fix that first: an observation without
  the two versions is an observation nobody can reproduce.

## Order

Not the order the questions are numbered in. Cheap and safe first; the ones that cost
quota or risk a challenge last.

| Step | Questions | How | Answers go to |
| ---- | --------- | --- | ------------- |
| 1 | Q1 rung a | `hermes-claude-migrate doctor` | `docs/hermes-attach.md` |
| 2 | Q1 rungs b, c | `prompts/attach-probe.md`, invoked as below | `docs/hermes-attach.md` |
| 3 | Q2 | the same prompt, on whichever rung worked | `docs/hermes-attach.md` |
| 4 | Q3 | `uv run python spikes/paste_ladder.py` | `docs/seed-limits.md` |
| 5 | Q8 | `browser attach --file` on `/new` before typing | `docs/claude-ui-map.md` |
| 6 | Q4, Q5 | the hand-driven conversation below | `docs/claude-ui-map.md` |
| 7 | Q7 | rename that conversation, reload, look | `docs/claude-ui-map.md` |
| 8 | Q9 | read the run's `--usage-file`; `hermes sessions export` | `docs/hermes-attach.md` |
| 9 | Q10 | `session logout`, then `login` again on a fresh profile | `docs/claude-ui-map.md` |
| 10 | Q6 | provoke what can be provoked. **The rate limit last.** | `docs/claude-ui-map.md` |

Everything §15 turns out not to be settable through the UI goes to
[`docs/LIMITATIONS.md`](../docs/LIMITATIONS.md) as it is found, not at the end.

## Q1 — the three invocations

The prompt is the same on every rung; only the invocation changes. Stop at the first rung
that works, because the ladder is ordered by how much of `07` survives it.

```sh
# rung a — one-shot, our Chrome, `browser.cdp_url` from the profile.
# `doctor` already does exactly this and checks the answer names our tab.
hermes-claude-migrate doctor

# rung b — a long-lived session, `/browser connect` issued once by hand.
hermes -p dataporter serve            # then, in the session:
#   /browser connect http://127.0.0.1:9222
#   <paste prompts/attach-probe.md>

# rung c — Hermes's own headed Chromium, logged in inside it.
hermes -p dataporter config set browser.headed true
hermes -p dataporter config set browser.inactivity_timeout 86400
hermes -p dataporter -z "$(cat spikes/prompts/attach-probe.md)"
```

Rung c loses the dedicated profile `07` is built around, so reaching it is not a
configuration detail — it is a finding that sends `07` back for an amendment. Record it as
one.

Whichever rung answers, paste `hermes -p dataporter config show` verbatim into
`docs/hermes-attach.md`. The keys `setup` writes and the keys Hermes holds are not the same
claim.

## The hand-driven conversation

`10`'s second acceptance criterion, and the half of the spike that isolates "does the page
accept this" from "does the agent do the right thing". No Hermes at all:

```sh
hermes-claude-migrate seeds --export <export> --only <id> --out /tmp/spike-seeds
hermes-claude-migrate browser close-extra-tabs
hermes-claude-migrate browser probe
hermes-claude-migrate browser paste --seed /tmp/spike-seeds/<id>/part-01.txt
#   press Enter in the window yourself, then:
hermes-claude-migrate browser probe
hermes-claude-migrate browser await-response --expect <the part-01 token>
hermes-claude-migrate browser paste --seed /tmp/spike-seeds/<id>/part-02.txt
#   press Enter again, then:
hermes-claude-migrate browser await-response --expect <the part-02 token>
```

Then reload `/chat/<uuid>` and check both parts and both acknowledgements are there. While
this runs, watch the DOM for Q4 and the address bar for Q5 — that is what those two
questions are, and there is no cheaper moment to see them.

## The Hermes conversation

`10`'s third acceptance criterion. Only after the hand-driven one has worked:

```sh
hermes -p dataporter -z "$(cat spikes/prompts/one-conversation.md)" \
  --toolsets browser,terminal --usage-file /tmp/spike-usage.json
```

The run passes when its last JSON object validates as a `HermesResult` — a truthful
`"outcome": "failed"` counts, an invented `"completed"` does not. Then read
`/tmp/spike-usage.json` for Q9.

## Recording

```sh
uv run python spikes/spike.py note Q4 "Stop control is a button, aria-label 'Stop response'"
```

One line into `docs/spike/notes.jsonl`, stamped with a UTC timestamp and both versions, so
that neither can be forgotten. Screenshots go beside it in `docs/spike/`, cropped.

**No content, ever** (§10, §17): not a message, not a title, not the account's name or
email. The helpers only ever print lengths and digests; a hand-written note is the one
place a human can leak something.

## The time box

Two working days. A question still open at the end is written into its document as
`unknown` **with what was tried** — that is a finding too, and it is what stops `11` from
being built on a guess that nobody ever labelled as one. `tests/test_spike_docs.py` fails
the build if a question has no answer line at all, so "we ran out of time" and "we forgot"
cannot look the same.
