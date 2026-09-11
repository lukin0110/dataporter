# Seed limits

**Kind:** Spike record — what was observed, not what was designed. Produced by
[`10`](../specs/impl/10-attach-spike.md).
**Answers:** Q3 (what the composer accepts, and how).
**Spike run:** none.
**Hermes version:** unknown. **Chrome version:** unknown.

This file owns two values: `seed.max_chars` in
[`config.py`](../src/dataporter/config.py) and the default `--method` of
[`08`](../specs/impl/08-browser-helpers.md)'s `browser paste`. Both currently hold the
number and the choice that `03`–`08` guessed; neither has been measured.

## Answers

- **Q3 — On the real composer, does `paste --method insert_text` land the text verbatim,
  does the UI convert it to a "pasted text" attachment, at what size does anything break,
  and does `08`'s block-per-line reading round-trip what the editor holds?**
  unknown. Not attempted: needs a signed-in throwaway destination account in a headed
  Chrome. `spikes/paste_ladder.py` runs the ladder — 5 k, 20 k, 50 k, 100 k and 200 k
  characters against both methods — and writes the table below.
  *unknown*

## The ladder

One row per size and method. `verbatim` is `browser paste` reporting `ok` — it compares
sha256 digests of the normalised seed and the normalised composer, so a `no` there means
the text changed, not that it looked different. `chip` is whether the UI turned the insert
into a "pasted text" attachment instead of leaving it in the composer, which a human reads
off the screen.

| Chars | Method | Verbatim | Composer chars read back | Elapsed ms | Chip | Mark |
| ----- | ------ | -------- | ------------------------ | ---------- | ---- | ---- |
| 5 000 | `insert_text` | not run | — | — | — | *unknown* |
| 20 000 | `insert_text` | not run | — | — | — | *unknown* |
| 50 000 | `insert_text` | not run | — | — | — | *unknown* |
| 100 000 | `insert_text` | not run | — | — | — | *unknown* |
| 200 000 | `insert_text` | not run | — | — | — | *unknown* |
| 5 000 | `exec_command` | not run | — | — | — | *unknown* |
| 20 000 | `exec_command` | not run | — | — | — | *unknown* |
| 50 000 | `exec_command` | not run | — | — | — | *unknown* |
| 100 000 | `exec_command` | not run | — | — | — | *unknown* |
| 200 000 | `exec_command` | not run | — | — | — | *unknown* |

## The round trip

`probe.PRELUDE_JS`'s `blockText` reads the composer one block element per line rather than
as `innerText`, because a rich-text editor is worth two line breaks at a paragraph
boundary. It was measured against Chromium 141 driving the checked-in page fixtures, never
against claude.ai. Two shapes decide whether that reading is right:

| Shape | Expected | Observed | Mark |
| ----- | -------- | -------- | ---- |
| an empty composer | `composer_chars` is `0` | not yet looked at | *unknown* |
| a seed with one blank line in it | one `\n\n`, not `\n\n\n` | not yet looked at | *unknown* |
| a seed with a leading space on a line | the non-breaking space `normalise` folds back | not yet looked at | *unknown* |

## The values this file sets

| Setting | Value today | Where it came from | Mark |
| ------- | ----------- | ------------------ | ---- |
| `seed.max_chars` | `50000` | a guess in `03`, never measured | *unknown* |
| `seed.hard_max_chars` | `400000` | a guess in `03`, never measured | *unknown* |
| `browser paste --method` default | `insert_text` | `08`'s reasoning that CDP input bypasses the paste handler | *unknown* |
| `timeouts.response_s` | `300.0` | a guess in `07`, never measured | *unknown* |

**`seed.max_chars` reason:** none recorded yet. `10`'s acceptance criteria are not met
until this line names a measured number and the row it came from.
