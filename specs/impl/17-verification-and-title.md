# 17 — Verification and title

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §2 (verify that the resulting chat exists), §11 (verify response exists), §15 (structural fidelity: titles, history)
**Depends on:** [12](12-import-loop.md)
**Enables:** [19](19-report.md)
**Status:** Not started

## Goal

Trust the page, not the agent: after Hermes reports a conversation done, the tool itself
reloads the created chat and checks that every part and every acknowledgement is there.
And give the chat its source title through the UI, as a verified step.

## In scope

- `browser probe --messages [--expect TEXT]...` (`08` extension): adds `messages`, an
  ordered list of `{role, chars, contains}` for every message on the page, and `title`
  (the chat's displayed title per `docs/claude-ui-map.md`, else `document.title`).
- Tool-side verification, `dataporter/verify.py`, run by `Importer` after a `completed`
  or `partial` result with a `conversation_id`, and by `hermes-claude-migrate verify`:
  1. navigate the tab to `https://claude.ai/chat/<id>` via CDP (allowed by the safety
     gate; it is this run's id);
  2. `probe --messages --expect "MIGRATION-ACK {short_id} 1/{N}" …`;
  3. checks, all required for `completed`:
     - page kind is `chat` and `conversation_id` matches (chat exists);
     - human messages ≥ `N` and the first contains `Original conversation ID: {uuid}`;
     - for each part `i`, some assistant message contains `MIGRATION-ACK {short_id} i/N`;
     - if `fidelity.rename_title` and the source title is non-empty: `title` equals it
       after whitespace normalisation, else limitation `title_not_set`.
  Outcome written to state: `verified_at` (UTC), and on failure status `partial` with
  `error.category = verification`, detail naming the first failed check,
  `retry_recommended = true`; `last_step` stays whatever Hermes reported.
- `hermes-claude-migrate verify [--only UUID]...`: re-verifies every `completed` and
  `partial` entry with an id, without Hermes, and prints one line per conversation:
  `{short_id}  verified` or `{short_id}  FAILED  {check}`; exit `0` if all verified, `1`
  otherwise. Never repairs anything.
- Title (§15 "equivalent titles"): the `rename` step in the skill (`11`), after
  `identify` and before `verify`: open the chat's menu, choose the rename affordance,
  enter the source title (short enough to type through `browser_type` — titles are
  capped at `fidelity.title_max_chars`, default `200`, truncated with `…`), confirm, and
  verify the displayed title changed. Config `fidelity.rename_title` (default `true`;
  `false` skips the step and records `title_not_set` for every conversation).
- Limitations recorded per conversation for everything the UI cannot set (§15 semantic
  over structural): `timestamps_not_preserved` (always), `title_not_set` (when
  applicable), plus `04`'s rendering limitations. `docs/LIMITATIONS.md` (`10`) is updated
  with observed rather than expected entries.

## Out of scope

- Judging whether Claude *understands* the history — that is semantic fidelity and belongs
  to the pilot (`20`).

## Design notes

- Verification reads the page through our CDP probe rather than asking Hermes, so a
  Hermes that over-reports `completed` is caught. It is the "verify response exists"
  of §11 made independent of the agent that produced the response.
- Rename is delegated to Hermes because it is a small, adaptive UI flow (menus differ
  between sidebar and header) and the title is short enough that typing it through the
  model is acceptable; the verify step still compares against the source string.
- A verification failure leaves the status `partial`, not `failed`: a chat exists and may
  well be usable; the report shows the failed check so the operator can look.

## Acceptance criteria

- A static chat fixture with two parts and both acks: `verify` passes and sets
  `verified_at`; remove one ack → `FAILED  ack 2/2 missing`; change the id in the URL
  → `FAILED  chat missing`.
- A fake Hermes claiming `completed` for a chat the fixture shows with one ack of two:
  state ends `partial`, category `verification`, `retry_recommended == true`.
- `verify --only <short_id>` runs without launching Hermes (a stub runner asserts no call).
- Real run: a conversation migrated by Hermes shows its source title in the sidebar
  after reload, and `verify` passes.

## Risks

- The rename UI may not exist or may be unreliable; `10` question 7 decides whether
  `fidelity.rename_title` defaults to `true`. If it defaults to `false`, "equivalent
  titles" is met only by the seed's header line, and `LIMITATIONS.md` says so.
