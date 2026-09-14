# 59 — Asking Hermes for its configuration

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** nothing new — it corrects [`09`](09-hermes-runner.md)'s reading of
`hermes config show`, which `09` itself named as a guess for a real Hermes to settle
**Depends on:** [09](09-hermes-runner.md)
**Enables:** `nothing yet` — `10`'s spike, which needs a profile it can read
**Status:** Built

## Goal

Stop parsing a screen. `setup` and `doctor` read Hermes's configuration by asking for one
key at a time — `config get <key> --json` — instead of flattening the display that
`config show` prints. Outside the milestone gates, as `22`, `23` and `25` are: it exists
because of how the tool meets a real Hermes, not because a brief asked for it.

## What was wrong

`dataporter setup` reported `no model configured` against a profile that had one. Observed
2026-09-14, Hermes Agent v0.21.2:

```text
┌─────────────────────────────────────────────────────────┐
│              ☤ Hermes Configuration                     │
└─────────────────────────────────────────────────────────┘

◆ Paths
  Config:       ~/.hermes/profiles/dataporter/config.yaml
◆ Model
  Model:        {'default': 'us.anthropic.claude-sonnet-5', 'provider': 'custom:bedrock-mantle'}
```

`config show` is a decorated display and was never YAML. Run the tool's own readers over it:

```text
parse_config keys -> ['Backend','Bell','Config','Discord','Enabled','Install','Max turns',
                      'Model','Personality','Protect first','Protect last','Reasoning',…]
flat['browser.backend'] -> None
configured_model(flat)  -> ''
parse_profile_list(...) -> ['Profile', '───────────────', '◆default', 'dataporter']
```

Not one dotted key. The model was the reported symptom; `doctor` had also been reporting
`browser.backend` and `browser.cdp_url` unset, and `setup` re-setting all twelve keys every
run. `flat['Model']` read `'(auto)'` — a second `Model:` label in a later section wins —
so a case-insensitive lookup would have found the wrong value rather than none.
`parse_profile_list` returned the header, the rule and `◆default` in place of `default`.

## In scope

- **`client.parse_value`** replaces `parse_config` (and `_split_setting`, `_unquote`): one
  `config get --json` value as a string. A bool is `true`, a number is `120`, spelled as
  the config file spells them because `mismatches` compares strings. **Not JSON is `None`**,
  which is how `Config key not set: <key>` is read — Hermes exits `0` for a key it has not
  got. An object or an array is `None` too: `config get model` answers the whole section.
- **`HermesCli.config_get(key)`** and **`config(keys)`**, which reads only what it is asked
  for and omits the unset, so `mismatches` still says `unset`.
- **`config_show_text` stays and is never parsed** — `09`'s idempotence criterion compares
  two runs of it for equality, which is shape-agnostic and still true.
- **`profile.MODEL_KEY = "model.default"`** replaces the five-way `MODEL_KEYS` guess.
- **`parse_profile_list`** learns the real table: `◆` joins the markers, and a rule line
  discards everything above it, which is what keeps the header out of the names.
- **`doctor`** asks for the twelve keys it compares plus the model — thirteen calls,
  ~3.5s against a real Hermes, in a command that runs once.
- **The fakes stop lying.** `tests/fake_hermes.py` and `rehearsal/hermes.py` both answer
  `config get --json`, and both render `config show` as a *display* — capitalised labels,
  the model as a dict repr — so nothing can quietly go back to parsing it.

## Out of scope

- The Hermes-side display bug (a dict repr where a formatted value belongs). It is upstream
  and stops affecting this tool the moment nothing parses the display.
- Reading `config.yaml` directly through `hermes config path`. Considered; it would add the
  YAML dependency `01` declined and would bypass Hermes's own resolution of defaults.
- `10`'s spike. It still owns the attach question; this slice only settles what `09` left
  to it about the configuration.

## Design notes

- **One subprocess a key, deliberately.** The alternative was one call and a parser, which
  is what just failed. `setup` and `doctor` run once; `_preflight` runs once a run, not once
  a conversation.
- **`parse_value` is public** because it is the seam a test should hold, exactly as
  `parse_config` was. `_split_setting` and `_unquote` were private and are gone with it.
- **A section reads as unset rather than as its repr.** A caller that asks for `model`
  rather than `model.default` has asked for the wrong thing, and being told "unset" is
  better than an operator being shown `{'default': …}` as the name of their model — which
  is the bug this slice exists to remove.
- **The rehearsal spells `MODEL_KEY` itself** rather than importing it. It imported
  `MODEL_KEYS[0]` from the tool, so it agreed with the guess by construction and could never
  have caught it. A stand-in that takes its answers from the code it stands in for is not a
  test double.
- **The test that could not fail.** `test_the_model_is_read_from_whichever_key_holds_it`
  looped over `MODEL_KEYS` asserting each was readable — a tautology against the tuple,
  green for as long as every one of the five guesses was wrong. Replaced by one that spells
  the key.

## Acceptance criteria

- Against a real Hermes: `config get model.default --json` reads the model, an unset key
  reads `None`, and `parse_profile_list` returns `['default', 'dataporter']`.
- `HermesCli.config([*profile_config(settings), MODEL_KEY])` resolves 13 of 13 keys on a
  configured profile, and `configured_model` returns the model rather than `""`.
- `make check-all` green on the coverage gate. The macOS-only
  `test_the_child_really_sees_only_that` failure is pre-existing and unrelated.
- No test asserts a machine-readable `config show`; both fakes render a display.

## Risks

- **A second Hermes version spells it differently.** `MODEL_KEY` is one constant, named
  here, and a wrong one now fails loudly — `config get` answers "not set" — where the old
  ladder failed silently by finding nothing under any of five names.
- **Thirteen spawns where there was one.** Measured at ~3.5s against a real Hermes, in
  commands that run once. If a caller ever needs this per conversation, it needs a cache,
  not a parser.
