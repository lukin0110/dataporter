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

## The four export rows (`31`)

The rows `10` answers all live in a destination account, which is the account the spike
has. Brief `03`'s four — `export page`, `export button`, `export confirmation` and
`export requested` — live in a **source** account, so they are observed on their own
trip, with a throwaway account that has something in it:

1. `dataporter login --account spike` — sign in to the throwaway source account, in the
   window the tool opens. The profile lands in its own account home, not the
   destination's.
2. Find where claude.ai lets that account ask for its data, by hand, and write the path
   down. If it is not `/settings/data-privacy-controls`, correct
   `export_page.EXPORT_PAGE_PATH` — the extraction surface and the fixture page follow
   it.
3. With the page open, read the three selectors off it — the control that asks, whatever
   confirmation it opens, and whatever appears once the request is accepted — and correct
   `export_page.py`'s `_SELECTORS`.
4. `dataporter extract --account spike` and watch it. Note whether one press was enough,
   whether a dialog followed, how long the page took to admit the request, and whether
   the email arrived — brief §39's questions 1, 2 and 5, which
   [`extraction-01.md`](../extraction-01.md) is waiting for.
5. Turn the four rows of [`claude-ui-map.md`](../claude-ui-map.md) to
   `*observed on <date>*`, and note anything the page did that the code does not expect.

A second ask against the same account is what answers "is there a rate limit on asking",
and it costs nothing but the wait.

Two rules, both from §10 and §17:

- **No content.** Not a message, not a title, not an account identifier, not an email
  address, not a chat URL's uuid beyond what a note genuinely needs. The helpers only ever
  emit lengths and digests; a hand-written note is the one place a human can leak
  something, so read it back before committing it.
- **The throwaway account only.** Nothing here may come from the source account or the
  operator's own account.

Every file here is committed once it holds something. They are evidence: `11`–`17` are
corrected against them, `20` reads its numbers off them, and `21` cites them.
