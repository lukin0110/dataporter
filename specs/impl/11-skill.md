# 11 — Skill and step protocol

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §4 (Hermes capabilities), §5 (selectors, verify after each action), §11 (agent verification), §17 (safety)
**Depends on:** [10](10-attach-spike.md)
**Enables:** [12](12-import-loop.md), [13](13-recovery.md)
**Status:** Not started

## Goal

The `claude-migrate` skill Hermes loads for every conversation, and the task prompt that
invokes it: a fixed sequence of steps where every step acts, then verifies, then records
the step name that `state.json` and the report use.

## In scope

- Repository file `skills/claude-migrate/SKILL.md`, installed by `setup` (`09`).
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
  *Recovery* (filled by `13`), *Result*. Selectors and labels quoted from
  `docs/claude-ui-map.md`, never invented.
- Step names, in order, exact — these strings are what `last_step` holds:

  | Step | Act | Verify (must pass before the next step) |
  | --- | --- | --- |
  | `open` | `browser_navigate` to `https://claude.ai/new` | `browser_snapshot` shows the composer; if the login page → result `needs_human` / `auth_required` |
  | `new_chat` | if the URL is `/chat/…`, navigate to `/new` again | URL is `/new` and the composer is empty (`browser probe` → `composer_chars == 0`) |
  | `attach` (per file, `16`) | `terminal: hermes-claude-migrate browser attach --file …` | helper `ok: true` |
  | `paste` (per part) | `terminal: hermes-claude-migrate browser paste --seed …` | helper `ok: true` (hash match) |
  | `submit` (per part) | `browser_press("Enter")` on the composer ref, or `browser_click` on the Send button ref | `browser probe`: composer empty **and** last message role `human` |
  | `await` (per part) | `terminal: hermes-claude-migrate browser await-response --expect "MIGRATION-ACK …"` | helper `ok: true` |
  | `ack` (per part) | read `last_message.contains` | contains the expected ack line; if not, `browser_snapshot` and classify (`13`) |
  | `identify` | `browser probe` | `conversation_id` is a uuid; URL is `/chat/<uuid>` |
  | `rename` (`17`) | rename flow from the UI map | title element shows the source title |
  | `verify` (`17`) | reload `/chat/<uuid>` | user message count ≥ parts, every ack present |
  | `done` | — | result emitted |

  Parts after the first repeat `paste → submit → await → ack` in the same chat.
- Task prompt template `dataporter/hermes/prompt.py`, rendered per conversation:

  ```text
  Use the skill `claude-migrate` (load it with skill_view before acting). Migrate exactly one
  conversation into the claude.ai tab already open in the attached browser.

  short_id: {short_id}
  parts: {N}
  seed files: {paths, one per line}
  attachments: {paths, one per line, or "none"}
  expected acknowledgements: MIGRATION-ACK {short_id} 1/{N} … {N}/{N}
  resume_from: {step or "open"}
  existing conversation_id: {uuid or "none"}
  helper: hermes-claude-migrate --workspace {workspace} browser …

  Follow the skill's procedure. After every action verify it as the skill says. Never type
  the seed yourself; only the helper inserts it. When finished, or when you cannot safely
  continue, print the result JSON described in the skill as the last thing you output.
  ```

  The prompt contains paths and ids, never seed text.
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

## Acceptance criteria

- `SKILL.md` frontmatter validates against the fields Hermes documents; `hermes -p
  dataporter skills list` shows `claude-migrate` after `setup`.
- A rendered prompt for the fixture's two-part conversation contains both ack lines, both
  seed paths and no seed text (test greps for a fixture-only phrase).
- A dry Hermes run with a stub browser page (static HTML from `07`'s fixtures) reaches
  `identify` and returns `completed` with the stubbed uuid.
- Every step name in the table appears in `dataporter/steps.py` as a `StrEnum` member,
  and `state.last_step` only accepts those.

## Risks

- Hermes may skip steps or self-verify loosely. `13` adds the classification rules, and
  `20` measures how often the transcript shows a step without its verification.
