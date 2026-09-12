# 27 — The scripted agent as a `hermes`

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 02](../02-claude-mock.md) §23 (*Who stands where Hermes
stands*)
**Depends on:** [09](09-hermes-runner.md), [11](11-skill.md),
[24](24-non-interactive.md), [26](26-mock-claude.md)
**Enables:** [29](29-rehearsal.md)
**Status:** Done

## Goal

Package the model-free scripted agent the tool's own tests already have as a
`hermes` executable on the path, so that a rehearsal's subprocess contract is the
real one: the real runner starts a real process with the environment `09` builds,
and that process performs the skill against a real Chrome by calling the real
helpers.

It is not an agent. It cannot decide, and a rehearsal is therefore no evidence
about whether a model can follow the skill (§27).

## In scope

- **`rehearsal/agent.py`** — the three moves `11` leaves to an agent, against a
  real page: `CdpBrowser.navigate` (go, and wait for the document),
  `.submit` (focus the composer with `08`'s own `FOCUS_JS`, press Enter) and
  `.rename` (open the chat's menu, insert the name, press Enter, then wait until
  the page carries it). `CdpSignInBrowser` for `24`'s task: navigate, dismiss one
  banner, and report which of `email`, `password`, `code` and `captcha` is
  showing — the first two by `login_form`'s own selectors, so there is one
  spelling of them. `HelperRunner` invokes
  `dataporter browser …` as a subprocess and reads back the one JSON
  object it prints, which is exactly what Hermes's terminal tool does.
- **`rehearsal/hermes.py`** — the executable. `--version` (`hermes 1.0.0`),
  `profile list`, `profile create`, `config set`, `config show`, and
  `-p … -z <prompt> --toolsets … --usage-file …`. The profile is a JSON file
  whose path arrives in `REHEARSAL_HERMES_STATE`; `config show` prints flat
  dotted keys and adds `agent.model: none/scripted-agent`, because `setup` never
  sets a model and `doctor` fails a profile that has none.
- **Five tasks, dispatched on what the prompt contains**: a migration
  (`short_id:`), `20`'s follow-up probe (`question file:`), `24`'s sign-in
  (`login url:`), and `doctor`'s two — the attach check (`remote debugging on`,
  answered with the nonce *and* the other tab's URL, which requires really
  listing the targets on the tool's debug port) and the helper check
  (`terminal tool to run exactly this command`, answered with the nonce and the
  helper's own `ok`).
- **`tests/fake_agent.py` gains `ScriptedProbe`** — `20`'s probe procedure, the
  third beside `ScriptedAgent` and `ScriptedSignIn`: navigate to the chat, probe
  for the composer and the conversation id, `paste --seed` the question file,
  submit, `await-response`, and report the reply. It belongs to the tool's test
  tree because that is where the other two are and where the skill is what they
  are written against.
- **`write_executable`** generates the `hermes` script — the interpreter that can
  import this package, the paths, and the profile location — the way
  `fake_hermes` is generated and for the same reason.
- **Where the browser comes from**: the CDP url in the profile the tool
  configured, which is how a rehearsal proves `browser.cdp_url` is what an agent
  attaches by. The doctor prompts carry their own, and are read from the prompt.
- **Tests** in `tests/test_rehearsal.py`: the profile round-trip, the version,
  the dispatch, the doctor answers against a fake client, `ScriptedProbe` against
  a stub, and the executable's own shape.

## Out of scope

- The agent's *procedure*, which is `tests/fake_agent.py` and belongs to `11`
  and `13`. This slice packages it; it does not restate it.
- A real Hermes with a real model against the mock. §28 keeps it.
- `judge`: it needs a model.

## Design notes

- **It lives in `rehearsal/`, not in the package.** §22's tool is byte-identical
  to the one that will meet claude.ai, and a module for the rehearsal's agent
  inside `dataporter` would be a change to it. `rehearsal/` is linted and
  type-checked and is in neither the wheel nor the sdist.
- **The three procedures are imported where they are used.** They are in the
  tool's *test* tree, which is not on the path when the executable is written —
  so a top-level import would make writing the executable depend on having it.
- **The rename knows the mock's markup.** `17` asks an agent to find "the chat's
  own menu" by looking, which is judgement; a script has ids instead. The UI
  map's `rename affordance` row records the shape, marked *unknown*, and the
  tool's own code still looks for none of it.
- **A model is named `none/scripted-agent`.** `doctor`'s `hermes model` line
  cannot be blank, and naming a model that is not there would put a falsehood in
  a record. The record prints the line as it comes.

## Acceptance criteria

- `hermes --version` answers, `setup` creates the profile and sets twelve keys,
  and `doctor` reports `hermes on PATH`, `hermes profile`, `hermes model`,
  `hermes config`, `skill installed`, `chrome executable`, `chrome launch + cdp`,
  `hermes attaches to chrome`, `hermes runs helper` and `session` — all `ok`
  against a signed-in mock.
- One `import --only <uuid>` against the mock ends `completed`, with the paste,
  submit, await and verify steps all going through the real helper CLI (the
  records in `logs/actions.jsonl` are written by the helper, not by the agent).
- No credential reaches this process: the sign-in task's prompt carries none, and
  the tool types them itself.

Every criterion above was met on 2026-09-12, against a real headless Chromium and
the mock; [`docs/rehearsal-01.md`](../../docs/rehearsal-01.md) is the record. A
rehearsal needs no real Hermes and no account, which is why `Done` rather than
`Built` is the honest value here.

## Risks

- **It is not Hermes.** Everything it proves is about the deterministic half. The
  record says so in the same words §27 does.
- **It could drift from the skill.** It reads the rendered prompt and nothing
  else, and the tool's own suite drives the same procedure against a fake page —
  so a prompt that stopped carrying what the procedure needs fails in both places.
