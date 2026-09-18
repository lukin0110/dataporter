# 67 — The mock grows skills

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 09](../09-skills.md) §90, §91, §93, §94
**Depends on:** [66](66-extract-skills.md), [64](64-the-mock-catches-up.md),
[65](65-the-mock-is-reached-by-a-flag.md)
**Enables:** `nothing yet`
**Status:** Done

## Goal

Teach the mock claude.ai to serve a skills list and a `.skill` file, and extend the
extraction rehearsal to run `extract-skills` against it and reconcile what was filed with
the mock's ledger. This is the slice that turns [`66`](66-extract-skills.md)'s
criterion 13 from *unverified* into a test.

## In scope

- **New rows first.** The six skills rows already in
  [`claude-ui-map.md`](../../docs/claude-ui-map.md) are `*unknown*`, which is what the mock
  is allowed to build from: `26`'s rule is that a behaviour the mock needs with no row is
  added to the map first, marked *unknown*, and **a mock run never turns an *unknown* into
  an *observed***. Nothing in this slice marks anything.
- **`mock/src/claudemock/uimap.py`** — `ROWS` entries citing `skills list`,
  `skill authorship`, `skill download` and `skill name`, and `WHAT_THE_MOCK_DOES` saying
  what was chosen where the row is silent. The existing test that a mock behaviour without a
  row is a failure covers the new pages.
- **`mock/src/claudemock/server.py`** — three addresses on the mock's own origin, re-typed on
  its side of ADR 0003's line and not imported from `dataporter`:
  - `GET /api/organizations` → one organisation with a uuid the mock mints.
  - `GET /api/organizations/{org}/skills/list-skills` → `{"skills": [...]}`, each entry
    carrying `id`, `name`, `creator_type`, `enabled` and `backing_plugin_id`, seeded to hold
    **a mix**: at least two `user`, one `anthropic`, one `user` that is disabled, one `user`
    inside a plugin, and one whose `creator_type` is a value the tool does not know.
  - `GET /api/organizations/{org}/skills/download-dot-skill-file?skill_id=…` → a real zip
    with `Content-Disposition: attachment`, so the capture in `45` behaves as it does for an
    archive part.
- **One skill that will not come back**, so §93's gap is exercised end to end: a
  `skill_id` whose download answers `500`. Not a hang — a route that never answers holds a
  worker for the length of the tool's idle budget, and what §93 asks is that *a* failure be
  a gap, not that every failure be. The tool files the rest, records one `Gap`, and exits `0`.
- **No page.** `66` as built never navigates to the page the skills are listed on — its
  controls carry the skills' names and a sketch keeps a control's label (§46) — so the mock
  serves none, and `/customize/skills/mine` is *not found* signed in, as any path the mock
  does not have is.
- **The ledger** (`CONTEXT.md`) gains two counts — `skills_listed`, how many times the list
  was read, and `skills_served`, how many files went out — and the witness gains
  `/__mock/skills.json`, which says how often each skill was served, so the rehearsal can
  reconcile which ids went out rather than trust a total. `mockcore.Ledger` is every site's
  (ADR 0007), so the mock chatgpt.com prints two zeros there, as it prints one for links.
- **`rehearsal/extraction.py`** — after the first fetch, three `extract-skills` runs on the
  mock claude.ai's half (`Mock.has_skills`): into the snapshot the fetch filed, into it
  again — recorded as deliberate, because the store refusing it is the point — and into a
  snapshot of its own. Seven criteria read the witness and the manifests: the account's own
  skills filed beside the archive, the archive's hash unchanged by the append, the second
  run refused, the skills-only snapshot complete and listed as skills, the refused skill one
  gap in each, the mock having served only the account's own once per run, and no skill's
  name in any trace. `digest_of` is taken *after* the skills joined the first snapshot, so
  §39's "the first snapshot is unchanged by the second" still holds of the second fetch.
- **The record** renders whatever blocks a half produced rather than three fixed slots, so
  the mock claude.ai's half shows five and the mock chatgpt.com's three.
- **`mock/tests/`** for the three addresses, and `tests/test_rehearsal_extraction.py` for the
  protocol.

## Out of scope

- Marking any UI-map row *observed*. Only a person watching claude.ai, or a committed trace,
  does that (`04` §49) — and the spike's reading was on a personal account, so
  [`spike/README.md`](../../docs/spike/README.md)'s throwaway-account rule kept it out.
- The real-account criteria in [`66`](66-extract-skills.md). A rehearsal is not evidence
  about the vendor (ADR 0006).

## Design notes

**Why the seeded list is a mix.** The filter is the whole of `66`'s scope decision, and a
list of only-ours proves nothing about it. The unknown `creator_type` is there to pin
`66`'s criterion 5 against a served response rather than a fake's.

**Why the organisations address is cited under `skills list`.** The tool reads
`/api/organizations` first because every other skills address hangs under the uuid it
answers; the map's `skills list` row says so since this slice, and the mock cites that row
for both reads rather than inventing a row for a request that is half of one read.

**Why the gap is a served failure rather than a fake's.** `45`'s capture has a stop reason
for each way a download can fail, and §93 turns exactly one of them into a gap. A mock that
can produce that failure is what tells us the seam is wired, rather than that a fake was
told to return it.

## Acceptance criteria

1. `mock/tests` pass, including one per address.
2. Every new mock behaviour cites a row of `claude-ui-map.md`; the existing check that an
   uncited behaviour fails still passes.
3. No row of `claude-ui-map.md` changes its mark in this slice.
4. The extraction rehearsal's criteria, as `tests/test_rehearsal_extraction.py` pins them
   against a modelled half: 21 for the mock claude.ai (14 and `67`'s seven), 13 for the
   mock chatgpt.com, and each of the seven fails on the modelled fault it exists for.
5. `python -m rehearsal.run --protocol extraction` against fresh mocks passes every
   criterion, including the seven, and its record shows `Skills served: 9` under the mock
   claude.ai's ledger.
6. A second `extract-skills` into the same stamp refuses, exits non-zero, and leaves every
   filed byte unchanged.
7. The skills-only snapshot is listed as `3 skills` and complete.
8. The refused skill is one gap in each snapshot, and the runs exit `0`.
9. [`66`](66-extract-skills.md)'s criterion 13 is met on that run.

Run on 2026-09-18, headless, Chrome 153: every criterion passed against both mocks — 21
on the mock claude.ai, 13 on the mock chatgpt.com — and the record is
[`docs/rehearsal-04.md`](../../docs/rehearsal-04.md); `Done`.

## Risks

- **The mock is built from `*unknown*` rows**, so it can only be as right as the reading
  behind them. A rehearsal that passes says the tool and the mock agree, never that either
  matches claude.ai (ADR 0006). The real-account criteria stay open.
- **The seeded shape may be wrong in a way the tool tolerates** — a field the real listing
  spells differently, for instance — and a green rehearsal would not show it. What would is
  the throwaway-account run that closes `66`'s last criterion.
