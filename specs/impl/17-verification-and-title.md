# 17 — Verification and title

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §2 (verify that the resulting chat exists), §11 (verify response exists), §15 (structural fidelity: titles, history)
**Depends on:** [12](12-import-loop.md)
**Enables:** [19](19-report.md)
**Status:** Built

## Goal

Trust the page, not the agent: after Hermes reports a conversation done, the tool itself
reloads the created chat and checks that every part and every acknowledgement is there.
And give the chat its source title through the UI, as a verified step.

## In scope

- `browser probe --messages [--expect TEXT]... [--expect-title TEXT]` (`08` extension):
  adds `messages`, an ordered list of `{role, chars, contains}` for every message on the
  page, and `title`, `{chars, source, matches}` — a length, which of the two places it
  was read from (`chat` per `docs/claude-ui-map.md`, else `document` for
  `document.title`), and whether it equals `--expect-title` after whitespace
  normalisation. **Not the title itself**, which the first draft of this spec asked for:
  §10's output discipline keeps a chat's name off stdout, `08` had already established
  the pattern that answers it (`--expect` → `contains`, matched in the page), and every
  caller of this flag — the skill's `rename` verification and `verify.py` — knows the
  title it is asking about. Both fields are absent from the printed object unless they
  were asked for, so `08`'s poll loop still gets the object it had.
- Tool-side verification, `dataporter/verify.py`, run by `Importer` after a `completed`
  or `partial` result with a `conversation_id`, and by `hermes-claude-migrate verify`:
  1. navigate the tab to `https://claude.ai/chat/<id>` via CDP (allowed by the safety
     gate; it is this run's id);
  2. `probe --messages --expect "MIGRATION-ACK {short_id} 1/{N}" …
     --expect-title "{title}"`;
  3. checks, all required for `completed`:
     - page kind is `chat` and `conversation_id` matches (chat exists);
     - human messages ≥ `N` and the first contains `Original conversation ID: {uuid}`;
     - for each part `i`, some assistant message contains `MIGRATION-ACK {short_id} i/N`;
     - if `fidelity.rename_title` and the source title is non-empty: `title` equals it
       after whitespace normalisation, else limitation `title_not_set`.
  Outcome written to state: `verified_at` (UTC) when every check passed and `null` when
  one did not — the field says the chat was read back and held everything, which is a
  statement a failed check withdraws — and on failure status `partial` with
  `error.category = verification`, detail naming the first failed check,
  `retry_recommended = true`; `last_step` stays whatever Hermes reported.
  With one exception, added while building: **a verification never overwrites a reason.**
  It writes its error only when the entry has none, which is the case it exists for — a
  run that reported `completed` and was wrong. A run that already said why it stopped
  keeps that reason and that reason's `retry_recommended`, because "ack 2/2 missing" is
  the consequence an operator already knows about rather than the cause, and because a
  verification must not recommend another attempt at something `01` classified as not
  worth retrying (a page outside the migration surface, say). The status is still
  `partial` either way, and `verified_at` is still `null`.
  Run after a `completed` or `partial` *result*: `failed`, `needs_human` and
  `rate_limited` are runs that already said where they got to, or that somebody else
  still owns.
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
  applicable), plus `04`'s rendering limitations — the rendering slugs first, because
  they describe the export, then these, which describe the account. `docs/LIMITATIONS.md`
  (`10`) is updated with observed rather than expected entries.

## Out of scope

- Judging whether Claude *understands* the history — that is semantic fidelity and belongs
  to the pilot (`20`).

## Design notes

- **The probe answers questions about the title; it never reports one.** See *In scope*.
  The same rule reaches the skill (`probe --expect-title`) and this module (the
  `--expect-title` it passes is rendered from `state.json`), so the only process that
  ever holds a chat's name is this one, and the only places it is written down are the
  two §7 already puts it in.
- **The title does reach Hermes**, in the task prompt, and that is this slice's one
  deliberate exception to `11`'s "the prompt names files, never their contents". §15 asks
  for equivalent titles, the rename field is the only way to set one, and it has to be
  typed. One line of metadata, in a prompt that still carries none of the conversation.
  `prompt.py`'s docstring records it as the exception it is.
- Verification reads the page through our CDP probe rather than asking Hermes, so a
  Hermes that over-reports `completed` is caught. It is the "verify response exists"
  of §11 made independent of the agent that produced the response.
- Rename is delegated to Hermes because it is a small, adaptive UI flow (menus differ
  between sidebar and header) and the title is short enough that typing it through the
  model is acceptable; the verify step still compares against the source string.
- A verification failure leaves the status `partial`, not `failed`: a chat exists and may
  well be usable; the report shows the failed check so the operator can look.
- **Two verifications, not one.** The skill's own `verify` step reads the transcript back
  before it reports (`11`), and this module reads it again afterwards. The first is cheap
  and catches a run that would otherwise report `completed` on a page it had not looked
  at; the second is the one that counts, because it does not go through the agent being
  checked. Neither needs a selector this repo has not already got.
- **The `completed → partial` edge is `17`'s alone.** §7's transition table (`06`) had no
  way out of `completed` except `running` under `--force`. A verification that could only
  agree with the agent it exists to check would not be a verification, so the table grew
  that edge and nothing else writes it.

- **Waiting for a chat is not the same as waiting for a page.** `Page.navigate`
  returns before the tab shows what it asked for, so the verification polls — and
  what it polls *for* is the difference between a slow load and a missing chat.
  `Verifier._settled` ends the wait on a page that has landed (this chat, once a
  turn has rendered; or any other chat, immediately) and keeps waiting only on a
  page that is not a chat at all, because `/new` is both what a tab shows in
  transit and where a chat that no longer exists sends you. The live URL is
  re-checked against the migration surface on every poll, as `08`'s
  `await-response` does, so a session that expires mid-verification reads as
  `chat unreadable` rather than as thirty seconds spent on a sign-in page.

## Acceptance criteria

- A static chat fixture with two parts and both acks: `verify` passes and sets
  `verified_at`; remove one ack → `FAILED  ack 2/2 missing`; change the id in the URL
  → `FAILED  chat missing`. (`tests/test_verify.py`, *Acceptance*. The fixture is the
  modelled page `08` and `11` are tested against, with a transcript written out;
  `tests/fixtures/pages/migrated.html` is the same chat as real HTML, which
  `test_browser_probe.py` reads through a real Chrome to prove the selectors separate the
  roles and find the title.)
- A fake Hermes claiming `completed` for a chat the fixture shows with one ack of two:
  state ends `partial`, category `verification`, `retry_recommended == true`. (The flag
  is what the verification writes; `13` then spends it — the conversation is attempted
  again, and the record reads `false` at the end of a run whose budget ran out, which is
  `_exhausted`'s rule and not this slice's.)
- `verify --only <short_id>` runs without launching Hermes (a stub runner asserts no call).
- Real run: a conversation migrated by Hermes shows its source title in the sidebar
  after reload, and `verify` passes. *Outstanding: needs a destination account and a real
  Chrome, like every other real-run criterion in `10`–`16`. `20` is where it is met.*

## What `29` changed

The first rehearsal (`docs/rehearsal-01.md`) found that `_read`'s settle test —
"this chat, and at least one turn" — fires a poll too early on a large
transcript: a two-part conversation whose first message is 47,000 characters
renders progressively, and one turn was on the page before the second. It now
waits for as many human turns as the conversation has parts, and a chat that
really is short is waited out and then reported. `verify_s` is what that costs.

## Risks

- The rename UI may not exist or may be unreliable; `10` question 7 decides whether
  `fidelity.rename_title` defaults to `true`. If it defaults to `false`, "equivalent
  titles" is met only by the seed's header line, and `LIMITATIONS.md` says so.
  It ships as `true`, without the answer, on two grounds: the step is described by
  *affordance* rather than by a selector this repo would have to invent — finding a menu
  is what Hermes is for — and a rename that does not take costs the conversation nothing,
  because the step cannot fail a migration and the title is verified from the page rather
  than from the agent's word. An operator who watches it flail sets the flag to `false`
  and loses one line of metadata per chat.
- The title is the one piece of conversation metadata that passes through a model's
  context (the prompt) and its output tokens (the rename field). It is bounded at
  `fidelity.title_max_chars` and never logged or printed, but it is a widening of the
  surface §10 draws, and it is here rather than in a footnote because that is the trade
  §15 asked for.
