# Hermes attach

**Kind:** Spike record — what was observed, not what was designed. Produced by
[`10`](../specs/impl/10-attach-spike.md).
**Answers:** Q1 (does `-z` attach), Q2 (tab reuse), Q9 (usage file and session export).
**Spike run:** none.
**Hermes version:** unknown. **Chrome version:** unknown.

Every answer below carries a mark: `*observed on <date>*` when a human watched it happen,
`*unknown*` when it has not been tried. `tests/test_spike_docs.py` enforces that each of
`10`'s ten questions has exactly one marked answer line across this file,
[`claude-ui-map.md`](claude-ui-map.md) and [`seed-limits.md`](seed-limits.md), and that the
status line above stops saying `none` as soon as any answer claims an observation.

## Answers

- **Q1 — Does a `-z` run in the `dataporter` profile attach to our Chrome via
  `browser.cdp_url`, and if not, which rung of the fallback ladder works?**
  unknown. Not attempted: the spike needs an installed Hermes, a headed Chrome and a
  throwaway destination account, and none of the three exists where this document was
  written. Run `spikes/prompts/attach-probe.md` through the three invocations in
  [`spikes/README.md`](../spikes/README.md) and stop at the first that answers.
  *unknown*
- **Q2 — When attached, does `browser_navigate` reuse the existing claude.ai tab or open a
  new one?**
  unknown. Not attempted. The same `attach-probe.md` run answers it: the prompt ends by
  reporting the target list twice, before and after its navigation, so a second tab shows
  up as a second entry rather than as an impression. Decides whether `12` runs
  `browser close-extra-tabs` before every conversation.
  *unknown*
- **Q9 — What is in `--usage-file`, and does `hermes sessions export` give the run's tool
  calls?**
  unknown. Not attempted. `hermes.runner.HermesUsage` currently guesses at three numbers
  by name at any depth; the real shape replaces that guess. Until it does, `19` reports a
  cost of zero as "not recorded".
  *unknown*

## The rung that was chosen

**Rung:** unknown — no rung has been tried.

The ladder, ordered by how much of [`07`](../specs/impl/07-browser-session.md) survives:

| Rung | What it is | What it costs |
| ---- | ---------- | ------------- |
| a | `browser.cdp_url` honoured in one-shot mode | nothing; `07`–`09` stand as built |
| b | a long-lived `hermes serve` or ACP session, `/browser connect` issued once | keeps our profile, adds a long-lived process for `09` to own |
| c | Hermes's own headed Chromium (`browser.headed: true`, `inactivity_timeout` raised), login done inside it | gives up the dedicated profile of `07`; `07` needs amending |

## The profile configuration that worked

Pasted verbatim from `hermes -p dataporter config show`, so that the keys `setup` writes
can be compared against the keys Hermes really holds.

```text
not yet captured
```

## Notes

Timestamped observations land in [`spike/notes.jsonl`](spike/), one JSON object per line,
written by `spikes/spike.py`. Screenshots go in [`spike/`](spike/) with personal data
cropped.
