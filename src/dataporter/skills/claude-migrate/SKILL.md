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

# claude-migrate

**This skill is not finished. Do not migrate anything with it.**

`hermes-claude-migrate setup` installs this file so that the Hermes profile is
complete and `hermes-claude-migrate doctor` can prove the chain works end to end
(slice `09`). The procedure itself — the step sequence, the per-step verification
protocol and the recovery rules — is written by slice `11`, after slice `10` has
observed the real claude.ai and recorded what each step can actually check.

Until then this file carries the final frontmatter and nothing else, so that a
profile which claims to have the skill installed is not quietly running a guess
at one.

## When to use

Never, in this version. If a task asks you to use this skill, stop immediately.

## Procedure

1. Do not navigate, type, paste, upload or submit anything.
2. Report the result object below and end the run.

```json
{
  "outcome": "failed",
  "conversation_id": null,
  "last_step": "open",
  "chunks_acked": 0,
  "error": {
    "category": "hermes",
    "detail": "the claude-migrate skill is a placeholder; slice 11 writes the procedure"
  }
}
```

## Inputs

Filled in by `11`.

## Verification

Filled in by `11`. Every step acts, then verifies, then records its name; no step
reports success because a call returned.

## Rules

- Stay on `https://claude.ai/new` and `https://claude.ai/chat/<uuid>`. Nothing
  else on the account is yours to touch, and nothing is ever deleted (§17).
- Insertion of conversation text is done by `hermes-claude-migrate browser paste`,
  never by typing or by reproducing the text yourself: a seed must not pass
  through a model's output tokens.

## Recovery

Filled in by `13`.

## Result

End every run with one JSON object in the shape above. `09`'s runner reads the
last such object from your output and validates it.
