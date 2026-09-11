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

Recreate **exactly one** conversation from a Claude data export as a chat in
claude.ai, by driving the web UI of a browser you are already attached to. One
run migrates one conversation and then stops.

The division of labour is fixed and is not yours to change:

- **You decide when to act.** Where the page is, whether it is in the state the
  next step needs, whether something unexpected is in the way, and when to stop.
- **The helper commands do the acting whose exactness matters.** Inserting a seed
  byte for byte, uploading a file, waiting for generation to finish. They verify
  their own effect and answer with one JSON object.

A seed must never pass through your output tokens. You never type, retype,
summarise or reconstruct conversation text — not into the composer, not into your
reasoning, not into your answer.

## When to use

Use this skill when a task prompt gives you a `short_id`, a part count, seed file
paths and the acknowledgement lines to expect, and asks you to migrate that one
conversation.

Do not use it for anything else. It is not a way to browse claude.ai, to tidy an
account, to answer a question about a chat, or to migrate several conversations
in one run.

## Inputs

Every field comes from the task prompt. Nothing here is yours to invent, and no
value is a path you may guess at.

| Field | What it is |
| --- | --- |
| `short_id` | Eight characters identifying the source conversation. It appears in every acknowledgement line. Never a title. |
| `parts` | How many seed parts this conversation was split into. `N` below. |
| `seed files` | One absolute path per part, in order: part 1 first. Read only by the helper, never by you. |
| `attachments` | One absolute path per file to upload, or `none`. |
| `expected acknowledgements` | The exact line the chat must reply with for each part, in order. Match them literally. |
| `resume_from` | The step to resume at. `open` on a first attempt. |
| `existing conversation_id` | The chat a retry must continue in, or `none`. |
| `parts already acknowledged` | How many parts are already in that chat, acknowledged. `0` on a first attempt. |
| `helper` | The command prefix for every helper call: `hermes-claude-migrate --workspace <workspace> browser …`. Use it verbatim, with the subcommand appended. |

A prompt that is missing a field, or whose `parts` and list lengths disagree, is
not a prompt to guess at: stop and return `failed` with `error.category`
`hermes`.

## Procedure

Steps run in this order. **Every step acts, then verifies, and only a step whose
verification passed may be reported as reached.** `last_step` in your result is
the last step that passed, never the one you were attempting — and `open` when
nothing passed at all, because the field is never empty.

| Step | Act | Verify before going on |
| --- | --- | --- |
| `open` | `browser_navigate` to `https://claude.ai/new`, or to `https://claude.ai/chat/<existing conversation_id>` when the prompt gives one | `browser probe`: `logged_in` is true and `composer_present` is true. On the login page, or with `logged_in` false → stop, `needs_human`, reason `auth_required` |
| `new_chat` | only when the prompt gives no existing conversation id: if the URL is already `/chat/…`, `browser_navigate` to `https://claude.ai/new` again | `browser probe`: `kind` is `new_chat` and `composer_chars` is `0` |
| `attach` | once per attachment, before the first paste: `<helper> attach --file <path>` | the helper answers `"ok": true` |
| `paste` | `<helper> paste --seed <path of this part>` | the helper answers `"ok": true` — it has already compared a hash of what the composer holds against the seed |
| `submit` | send the message: `browser_press` `Enter` on the composer's ref, or `browser_click` the send control's ref | `browser probe`: `composer_chars` is `0` **and** `last_message.role` is `human` |
| `await` | `<helper> await-response --expect "<this part's acknowledgement line>"` | the helper answers `"ok": true` |
| `ack` | read `last_message.contains` in that same answer | it contains this part's acknowledgement line. If it does not, take one `browser_snapshot` and classify (see *Recovery*) |
| `identify` | `browser probe` | `conversation_id` is a uuid and the URL is `/chat/<that uuid>`. When the prompt gave an existing id, it must be that same id |
| `rename` | not in this version — `17` writes it | — |
| `verify` | not in this version — `17` writes it | — |
| `done` | nothing | the result is emitted |

`paste`, `submit`, `await` and `ack` repeat, in that order, once per part, in the
same chat: part 1, then part 2, and so on to part `N`. Do not start a part before
the previous part's `ack` has passed, and never paste two parts into one message.

`rename` and `verify` are named here because they are steps of the migration and
a later version performs them. Until then, a run that has passed `identify` is
finished: report `last_step` `done`. Do not attempt to rename a chat.

### Resuming

`resume_from` names the step to begin at, `existing conversation_id` names the
chat to begin in, and `parts already acknowledged` says how much of it is already
there. Resuming means: navigate to that chat at `open`, skip `new_chat`, and
start the per-part loop at the part *after* the acknowledged ones — part `k + 1`
when `k` parts are acknowledged.

Check the count before trusting it, with the evidence you already have: a
`<helper> probe --expect "<part k's acknowledgement line>"` must report that line
in `last_message.contains`. If it does not, the chat is not where the prompt says
it is: stop and return `partial` with `error.category` `verification` rather than
pasting into it.

Never re-paste a part whose acknowledgement is already in the transcript. A
duplicated part is worse than a missing one, because nothing downstream can tell
it apart from the original.

### Calling a helper

Every helper call is the prompt's `helper` prefix, the subcommand, and its
arguments, run through your terminal tool. Each one prints exactly one JSON
object on stdout and exits `0` when it worked, `1` when the page or the file was
not as required, and `2` when the call itself was wrong.

```text
<helper prefix> probe
<helper prefix> probe --expect "MIGRATION-ACK ab12cd34 1/2"
<helper prefix> paste --seed /path/to/part-01.txt
<helper prefix> attach --file /path/to/file.pdf
<helper prefix> await-response --expect "MIGRATION-ACK ab12cd34 1/2"
<helper prefix> close-extra-tabs
```

Read the object, not the exit code alone. `{"ok": true, …}` is the only answer
that lets a step pass; `{"ok": false, "error": "…"}` names what went wrong in one
of these words:

`no_claude_tab`, `ambiguous_tab`, `unknown_target`, `outside_migration_surface`,
`composer_missing`, `composer_not_empty`, `text_mismatch`, `seed_not_found`,
`seed_unreadable`, `file_not_found`, `input_not_found`, `upload_rejected`,
`chip_not_found`, `response_timeout`.

## Verification

What a step is allowed to count as proof:

- **A helper's own answer.** `paste` proves itself by hashing the composer's
  text; `attach` by finding the attachment's chip; `await-response` by watching
  the last message stop growing. These are the strongest evidence available, and
  where one disagrees with your reading of a snapshot, the helper is right.
- **A `browser probe` object.** Facts about the page with no content in them:
  `url`, `kind`, `logged_in`, `composer_present`, `composer_chars`, `generating`,
  `send_enabled`, `dialogs`, `conversation_id`, and `last_message` as a role, a
  character count and which of your `--expect` strings were found.
- **A `browser_snapshot`.** Only when you need an element's ref in order to act
  on it, or to classify something you could not otherwise explain. A snapshot of
  claude.ai contains conversation text, so take as few as the work needs.

What never counts: a tool call returning without an error, a page "looking
right", or an assumption that a click did what clicks usually do. If you cannot
verify a step, it did not happen.

Never quote a message, a chat title, or the account's name or email — in your
reasoning, in your output, or in the result object. `short_id`, a conversation
uuid, a step name and a count are the only identifiers this run produces.

## Rules

1. Only `https://claude.ai/new` and `https://claude.ai/chat/<this run's id>` may
   be navigated to. No other page, no settings, no billing, no other chats.
2. Never delete, archive, star, share or rename anything except the `rename` step
   on this run's own chat.
3. Never enter text into the composer except through the helper.
4. If an action outside this list appears necessary, stop and return
   `needs_human` with reason `confirmation_required`.
5. If a page asks for a password, a code, a CAPTCHA or a security challenge, do
   not attempt it; return `needs_human` with the matching reason.

Rule 2 names the `rename` step because a later version performs it. This version
does not, so in this version rule 2 permits nothing at all.

## Recovery

`13` writes this section: the full mapping from every failure the migration can
meet to its detection, its in-run recovery and its retry policy. Until it lands,
the rule is that a step which cannot be verified ends the run rather than being
worked around.

- A helper that answers `"ok": false` may be re-run once, and only when its
  `error` says the page was not ready yet (`composer_not_empty` after a submit
  that may still be settling, `chip_not_found`, `response_timeout` while
  `generating` is true). Anything else stops the run.
- `outside_migration_surface` is never retried: it means the tab left the two
  URLs this run is allowed to touch. Return `failed` with `error.category`
  `safety`.
- A `dialogs` entry in a probe, or a page you cannot classify, is `needs_human`
  with reason `ambiguous_ui`. A page that asks you to sign in is `auth_required`;
  a CAPTCHA or a challenge is `captcha` or `security_challenge`.
- A message saying the account has hit a limit is `rate_limited`; put the number
  of seconds in `retry_after_s` when the page names one, and stop.
- Never restart a conversation from `open` to escape a failure. A chat that
  exists is recorded, retried and continued; a second chat for the same source
  conversation is a duplicate nobody can clean up.

## Result

The last thing you output is exactly one JSON object, and nothing after it. It is
read by the tool that started you, so it is the only part of your output that has
to be exact.

| Field | Meaning |
| --- | --- |
| `outcome` | `completed`, `partial`, `failed`, `needs_human` or `rate_limited` |
| `conversation_id` | the destination chat's uuid, or `null` if none exists yet |
| `last_step` | the last step whose verification passed |
| `chunks_acked` | how many acknowledgement lines you actually saw |
| `error` | `{"category": …, "detail": …}` when something went wrong |
| `needs_human_reason` | `auth_required`, `captcha`, `security_challenge`, `ambiguous_ui`, `browser_error` or `confirmation_required` |
| `retry_after_s` | seconds to wait, when a rate limit named one |
| `actions` | how many browser actions you made |

`error.category` is one of `auth`, `captcha`, `security_challenge`, `rate_limit`,
`generation`, `network`, `navigation`, `dialog`, `ui`, `browser`, `hermes`,
`export`, `unsupported`, `verification` or `safety`. Pick the most specific one
that is true: `auth` for a sign-in page, `dialog` for something modal in the way,
`safety` for a page outside the two URLs this run may touch, `browser` only when
nothing narrower fits.

Every part acknowledged, in a chat with a uuid:

```json
{
  "outcome": "completed",
  "conversation_id": "b6f0a2d4-1c88-4e3a-9a1f-2f0e5d7c8b91",
  "last_step": "done",
  "chunks_acked": 2,
  "actions": 14
}
```

Some parts acknowledged; the chat exists and can be continued:

```json
{
  "outcome": "partial",
  "conversation_id": "b6f0a2d4-1c88-4e3a-9a1f-2f0e5d7c8b91",
  "last_step": "ack",
  "chunks_acked": 1,
  "error": {"category": "browser", "detail": "await-response timed out on part 2"},
  "actions": 9
}
```

Nothing landed:

```json
{
  "outcome": "failed",
  "conversation_id": null,
  "last_step": "new_chat",
  "chunks_acked": 0,
  "error": {"category": "browser", "detail": "paste answered text_mismatch"},
  "actions": 4
}
```

A person has to do something before this can continue:

```json
{
  "outcome": "needs_human",
  "conversation_id": null,
  "last_step": "open",
  "chunks_acked": 0,
  "needs_human_reason": "auth_required",
  "error": {"category": "auth", "detail": "the login page was shown"},
  "actions": 1
}
```

The account has hit a limit:

```json
{
  "outcome": "rate_limited",
  "conversation_id": "b6f0a2d4-1c88-4e3a-9a1f-2f0e5d7c8b91",
  "last_step": "submit",
  "chunks_acked": 1,
  "retry_after_s": 3600,
  "error": {"category": "rate_limit", "detail": "the page reported a usage limit"},
  "actions": 11
}
```

A truthful `failed` is useful; an invented `completed` is worse than no run at
all, because the conversation it claims to have migrated will never be retried.
