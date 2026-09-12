# 11 — Skill and step protocol

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §4 (Hermes capabilities), §5 (selectors, verify after each action), §11 (agent verification), §17 (safety)
**Depends on:** [10](10-attach-spike.md)
**Enables:** [12](12-import-loop.md), [13](13-recovery.md)
**Status:** Done

## Goal

The `claude-migrate` skill Hermes loads for every conversation, and the task prompt that
invokes it: a fixed sequence of steps where every step acts, then verifies, then records
the step name that `state.json` and the report use.

## In scope

- Packaged file `src/dataporter/skills/claude-migrate/SKILL.md`, installed by `setup`
  (`09`). Inside the package, not at the repository root, because `setup` copies it out
  of the installed tool and only files under the package directory reach the wheel —
  `09` shipped it with the frontmatter below and a placeholder body that refuses to act.
  Frontmatter, exact:

  ```yaml
  ---
  name: claude-migrate
  description: Recreate one migrated conversation in claude.ai via the web UI
  version: 0.1.0
  platforms: [macos, linux]
  metadata:
    hermes:
      tags: [browser, migration, claude]
      category: dataporter
      requires_toolsets: [browser, terminal]
  ---
  ```

- Skill body sections: *When to use*, *Inputs*, *Procedure*, *Verification*, *Rules*,
  *Recovery* (`13` replaces it; until then it says that an unverifiable step ends the
  run, names the one re-runnable class of helper failure, and forbids restarting a
  conversation from `open`), *Result*. Selectors and labels quoted from
  `docs/claude-ui-map.md`, never invented — which is why the skill decides from `probe`
  objects and helper answers, and reaches for a `browser_snapshot` only when it needs a
  ref to act on.
- Step names, in order, exact — these strings are what `last_step` holds:

  | Step | Act | Verify (must pass before the next step) |
  | --- | --- | --- |
  | `open` | `browser_navigate` to `https://claude.ai/new`, or to `/chat/<existing conversation_id>` when the prompt gives one | `browser probe`: `logged_in` and `composer_present`; if not → result `needs_human` / `auth_required` |
  | `new_chat` | only on a first attempt: if the URL is `/chat/…`, navigate to `/new` again | URL is `/new` and the composer is empty (`browser probe` → `composer_chars == 0`) |
  | `attach` (per file, `16`) | `terminal: hermes-claude-migrate browser attach --file …` | helper `ok: true` |
  | `paste` (per part) | `terminal: hermes-claude-migrate browser paste --seed …` | helper `ok: true` (hash match) |
  | `submit` (per part) | `browser_press("Enter")` on the composer ref, or `browser_click` on the Send button ref | `browser probe`: composer empty **and** last message role `human` |
  | `await` (per part) | `terminal: hermes-claude-migrate browser await-response --expect "MIGRATION-ACK …"` | helper `ok: true` |
  | `ack` (per part) | read `last_message.contains` | contains the expected ack line; if not, `browser_snapshot` and classify (`13`) |
  | `identify` | `browser probe` | `conversation_id` is a uuid; URL is `/chat/<uuid>` |
  | `rename` (`17`) | only when the prompt gives a `title`: the chat's own menu, its rename affordance, the title typed through `browser_type` | `browser probe --expect-title "<title>"` → `title.matches` is `true`; a rename that does not take leaves `last_step` at `identify` and stops nothing (`17`) |
  | `verify` (`17`) | `browser probe --messages --expect "<each ack line>"` | every part's ack line is in some message's `contains`; if one is not, classify it as a generation failure for that part (`13`) |
  | `done` | — | result emitted |

  Parts after the first repeat `paste → submit → await → ack` in the same chat.
  `last_step` is the last step whose verification passed, and `open` when none did —
  the field is required by `09`'s contract, so it is never empty.
  The names live in `dataporter/steps.py` as `Step`, `state.last_step` is typed as one,
  and `HermesResult.step` is the raw string read back as one (or `None`).
- Task prompt template `dataporter/hermes/prompt.py`, rendered per conversation:

  ```text
  Use the skill `claude-migrate` (load it with skill_view before acting). Migrate exactly one
  conversation into the claude.ai tab already open in the attached browser.

  short_id: {short_id}
  parts: {N}
  seed files:
  {one path per line}
  attachments: none
  expected acknowledgements:
  {one line per part: MIGRATION-ACK {short_id} k/{N}}
  resume_from: {step or "open"}
  existing conversation_id: {uuid or "none"}
  parts already acknowledged: {k, or 0}
  helper: hermes-claude-migrate --workspace {workspace} browser …

  Follow the skill's procedure. After every action verify it as the skill says. Never type
  the seed yourself; only the helper inserts it. When finished, or when you cannot safely
  continue, print the result JSON described in the skill as the last thing you output.
  ```

  Two departures from the sketch above, both in *Design notes*: every list is written out
  one value per line under its key (the `…` elision is not something an agent can expand
  safely), and `parts already acknowledged` was added. `attachments` is `none` or the same
  block shape. The prompt contains paths and ids, never seed text; `render` refuses a
  prompt whose parts, seed files and ack lines disagree.
- *Rules* section (§17), verbatim in the skill:
  1. Only `https://claude.ai/new` and `https://claude.ai/chat/<this run's id>` may be
     navigated to. No other page, no settings, no billing, no other chats.
  2. Never delete, archive, star, share or rename anything except the `rename` step on
     this run's own chat.
  3. Never enter text into the composer except through the helper.
  4. If an action outside this list appears necessary, stop and return
     `needs_human` with reason `confirmation_required`.
  5. If a page asks for a password, a code, a CAPTCHA or a security challenge, do not
     attempt it; return `needs_human` with the matching reason.

  Two tasks are not migrations and each earns one paragraph after the rules, not a
  sixth rule: `20`'s follow-up probe, and `24`'s **sign-in**. The sign-in task asks the
  agent to bring the tab to `https://claude.ai/login` until an email or password input
  is visible and then stop — rule 1 admits `/login` for that task only; rules 2–5 hold in
  full, and the agent types nothing, submits nothing and holds no credentials. Its result
  object is `{"outcome": "form_ready", "fields": [...], "url": ...}` or `needs_human` /
  `failed`; the tool that started it types the credentials itself, in its own process,
  after the agent has stopped (`signin.py`, `browser/login_form.py`).
- *Result* section: the `HermesResult` JSON schema from `09`, with one example per
  outcome, and the instruction that it is the last thing printed.

## Out of scope

- Reacting to failures (`13`), the pause/resume handshake (`14`), attachments (`16`),
  rename and post-hoc verification (`17`).

## Design notes

- The step list mirrors §5's diagram one to one so the report's "last successful step"
  (§16) is a name a reader can find in the brief.
- Submission is left to Hermes (Enter or Send) on purpose: it is the one action where an
  agent reading the page beats a fixed keystroke, and its verification (`composer empty`
  and a new human message) is cheap and exact.
- The prompt names files, not content, so a Hermes transcript of the prompt itself never
  contains conversation text; snapshots taken later will, and that is documented in
  `README.md` (shared decisions).
- **`parts already acknowledged` was added to the prompt.** A resumed run has to know
  which part to paste next. Without the number, an agent would have to read the
  transcript to find out — which means snapshots, which means conversation text in its
  context, to rediscover a count `state.json` already holds (`06`). Sending it costs a
  line and makes the resume rule checkable, so the skill also requires one
  `probe --expect "<part k's ack>"` before continuing: the prompt says where the chat
  should be, the page says where it is, and a disagreement is `partial` /
  `verification`, never a paste.
- **Every list in the prompt is written out in full**, one value per line. The sketch
  elided the ack lines with `…`; these strings are matched literally by
  `await-response --expect`, and a list the agent has to reconstruct is a list it can
  reconstruct wrongly.
- **`rename` and `verify` were named and not performed, and `17` wrote them.** This
  slice shipped both steps as placeholders because `docs/claude-ui-map.md` had — and
  still has — no observed rename affordance, and this slice's rule is that selectors and
  labels are quoted from that document, never invented. `17` performs them anyway, and
  says why in its own design notes: the rename is described by *affordance* rather than
  by selector ("the chat's own menu, its rename affordance"), which is a thing Hermes
  finds by looking rather than a string we would be inventing, and a rename that does
  not take costs the conversation nothing. The `verify` step needs no selector at all —
  it is one `probe --messages` against ack lines we wrote ourselves.
- **`open` navigates to the existing chat when there is one.** The sketch had it always
  go to `/new`, which on a retry would create a second chat for the same conversation —
  the one failure §17 has no cleanup for, since nothing may be deleted.
- **`HermesResult.last_step` stays a plain string**, with `HermesResult.step` reading it
  back as a `Step` or `None`. The agent is the producer: a run that did the work and then
  named its step in its own words has still reported the outcome, the id and the count,
  and losing all three to a validation error would be the strictness `extra="ignore"`
  exists to avoid. `state.last_step` is where the vocabulary is enforced, because that is
  the file `19` reports from.
- **`16` filled the `attach` step in.** The row above was written and not performed: this
  version's prompt said `attachments: none`, so nothing exercised it. `16` is what gives
  the step files to attach, a chip-count check to verify them with
  (`browser attachments`), and the two result fields — `attachments_uploaded` and
  `attachments_failed` — that let a run report a file it could not put in the chat without
  losing the conversation it did migrate. The step is still `attach`, and `last_step` is
  unchanged; `16`'s design notes hold the rest.
- **The dry run is a scripted agent, not a stub.** `tests/fake_agent.py` reads the
  rendered prompt and performs the procedure through the real CLI against `08`'s page
  model. It proves the prompt is sufficient and the helpers compose; it proves nothing
  about Hermes's judgement, which only `10`'s throwaway prompts and `20` can measure.
- **One sentence was added to *Rules* by [`20`](20-pilot.md).** The pilot's semantic
  probe sends one follow-up question into a chat this tool created and reports the reply,
  which is a message quoted in a result object — the one thing the *Verification* section
  otherwise forbids outright. The permission is written as a single sentence, scoped to a
  task prompt that asks for a probe and to the one chat that prompt names, and the
  question itself still reaches the composer through `paste` rather than through the
  agent's own typing, so rule 3 is untouched. `followup.py` holds the rest of the
  reasoning; nothing about a migration changed.

## Acceptance criteria

- `SKILL.md` frontmatter validates against the fields Hermes documents
  (`test_hermes_skill.py`); `hermes -p dataporter skills list` shows `claude-migrate`
  after `setup` — **unverified**: it needs an installed Hermes, like `09`'s first
  criterion, and `10` is where it gets checked.
- A rendered prompt for the fixture's two-part conversation contains both ack lines, both
  seed paths and no seed text (test greps for a fixture-only phrase) —
  `test_hermes_prompt.py`.
- A dry Hermes run with a stub browser page reaches `identify` and returns `completed`
  with the stubbed uuid — `test_skill_dry_run.py`. The stub is `08`'s modelled page
  rather than `07`'s static HTML: the criterion needs a page that *changes* when a
  message is submitted, and a static document cannot acquire a `/chat/<uuid>` URL or
  answer with an acknowledgement.
- Every step name in the table appears in `dataporter/steps.py` as a `StrEnum` member,
  and `state.last_step` only accepts those — `test_steps.py` reads this document's table
  and `test_state.py` refuses a name that is not one.
- Every `error` string `08` can print is named in the skill, and every result example in
  it validates as a `HermesResult` — `test_hermes_skill.py`.

## Risks

- Hermes may skip steps or self-verify loosely. `13` adds the classification rules, and
  `20` measures how often the transcript shows a step without its verification.
- The skill describes a page nobody has watched. Every signal it relies on comes from
  `probe`, and every row of `docs/claude-ui-map.md` is still `*unknown*`; if the real
  composer, Send button or message elements differ, the helpers are what change, and the
  skill changes only where it names a state.
- A scripted agent cannot misread an instruction; a real one can. The prose that matters
  most — never retype a seed, never open a second chat, stop rather than work around —
  is unmeasured until `20`.
