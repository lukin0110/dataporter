# Spike evidence

What [`10`](../../specs/impl/10-attach-spike.md) produces while it runs, as opposed to
what it concludes. The conclusions are in [`hermes-attach.md`](../hermes-attach.md),
[`claude-ui-map.md`](../claude-ui-map.md), [`seed-limits.md`](../seed-limits.md) and
[`LIMITATIONS.md`](../LIMITATIONS.md); this directory is the working out.

| File | Written by | Holds |
| ---- | ---------- | ----- |
| `notes.jsonl` | `spikes/spike.py note` | one JSON object per observation: the question, the note, a UTC timestamp, the Hermes version and the Chrome version |
| `paste-ladder.json` | `spikes/paste_ladder.py` | one object per (size, method) of Q3's ladder, and the markdown table to paste into `seed-limits.md` |
| `*.png` | a human | screenshots, with every piece of personal data cropped out before the file is saved |
| `pilot/` | `20` | the pilot run's Hermes sessions, redacted by a human — [`pilot/README.md`](pilot/README.md) says what is stripped |

Two rules, both from §10 and §17:

- **No content.** Not a message, not a title, not an account identifier, not an email
  address, not a chat URL's uuid beyond what a note genuinely needs. The helpers only ever
  emit lengths and digests; a hand-written note is the one place a human can leak
  something, so read it back before committing it.
- **The throwaway account only.** Nothing here may come from the source account or the
  operator's own account.

Every file here is committed once it holds something. They are evidence: `11`–`17` are
corrected against them, `20` reads its numbers off them, and `21` cites them.
