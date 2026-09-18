# 68 — The facade: five commands, one object

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** nothing in the brief — tooling, like [22](22-test-performance.md),
[23](23-library-operations.md) and [25](25-distribution.md). No command, flag, golden
string or exit code moves.
**Depends on:** [23](23-library-operations.md), [25](25-distribution.md),
[30](30-store-and-snapshot.md), [31](31-source-session-and-ask.md), [63](63-everything-but-the-logs.md),
[66](66-extract-skills.md)
**Enables:** any host project that installs this package
**Status:** Done

## Goal

Give a Python caller one object for the five commands a host project actually reaches
for — `login`, `logout`, `extract`, `extract-skills` and `doctor` — so that using
`dataporter` as a library is an import and a call rather than a reading of
[23](23-library-operations.md)'s operations table.

`23` made every command's body a library function in the module that owns its domain, and
that table is still the whole API. What it does not carry is the two things every one of
those calls needs first: a `Settings`, and the source and account the command is *about*.
Today a caller who wants `extract-skills` has to know `load_settings`, `with_store_dir`,
`with_account` and which module holds the operation before writing a line. `Dataporter` is
that plumbing and nothing else.

It is not a change of behaviour and not a second implementation. Every method layers
settings the way `cli.py` layers them and calls the one operation `23` already wrote,
returning that operation's own frozen outcome unchanged.

## In scope

- **`dataporter/api.py`** — the module. `Dataporter`, the message `SETTINGS_ALONE` that its
  constructor refuses with, and two module-private helpers: `_values_given`, which asks
  whether anything was passed beside a `Settings`, and `_with_source`, which applies and
  checks a constructor's vendor.

  ```python
  Dataporter(workspace=None, store=None, source=None,
             mock=False, non_interactive=False, settings=None)
  Dataporter.from_config(workspace=None, store=None, source=None,
                         mock=False, non_interactive=False)
  ```

  Nine methods, each taking `sink: Sink = DISCARD` and returning the operation's outcome:

  | Method | Operation | Outcome |
  | --- | --- | --- |
  | `login(account=None, *, source=None)` | `browser.session.login` | `LoginOutcome` |
  | `spend_link(link, *, account=None, source=None)` | `browser.session.login(link=…)` | `LoginOutcome` |
  | `logout(account, *, source=None)` | `browser.session.logout` | `LogoutOutcome` |
  | `ask(account, *, source=None)` | `extract.ask` | `ExtractOutcome` |
  | `fetch(account, link, *, source=None, quiet=False)` | `extract.fetch` | `ExtractOutcome` |
  | `file(account, path, *, source=None)` | `extract.file` | `ExtractOutcome` |
  | `abandon(account, *, source=None)` | `extract.abandon` | `ExtractOutcome` |
  | `extract_skills(account, *, source=None, stamp=None, quiet=False)` | `extract_skills.extract_skills_command` | `SkillsOutcome` |
  | `doctor()` | `hermes.doctor.run_doctor` | `DoctorOutcome` |

  A `settings` property reads back what was resolved. `_for(account, source)` is the
  private method every account-scoped method starts with, and it is `with_account`.
- **`from dataporter import Dataporter`** — `__init__.py` gains a module `__getattr__` that
  fetches the class on first use and raises `AttributeError` for every other name, plus a
  `TYPE_CHECKING` import so the name is real to a type checker. Lazy because `api` imports
  the extraction, browser and Hermes modules, and importing them eagerly would make every
  `from dataporter.config import …` in the tool pay for Chrome.
- **`config.settings_without_config_file(workspace=, non_interactive=, mock=)`** — the
  constructor's builder. `load_settings` minus the config file: the contextvar
  `settings_customise_sources` reads is left unset, so no `config.toml` is discovered and
  none is read. The environment still fills in what nobody named, because `init` comes
  first in the ladder and cannot be outranked by it. Wraps a validation failure in
  `ConfigError` with the words `load_settings` uses.
- **`config.mock_overrides`** — `_mock_overrides` made public, so the rule that moves the
  default workspace to `./migration-mock` has one implementation and both doors call it.
- **`config.validate_source`** — the source half of `with_account`'s validation, split out
  and called by both, so the facade can check a constructor's `source` where it is named.
- **The README** — a *Five commands, one object* subsection opening *From another project*,
  with the operations table kept below it as the complete surface.

## Out of scope

- **Every other command.** `import`, `resume`, `seeds`, `inspect`, `verify`, `followup`,
  `judge`, `report`, `status`, `snapshots`, `setup` and the `browser` helpers have no
  facade method and are reached through `23`'s table. The five here are the ones a host
  project reaches for; a sixth is a line in this file when somebody wants one.
- **`session status`.** Considered and left out. A caller who wants the answer before an
  extraction has `doctor`, and `AuthError` is what a signed-out session raises.
- **Credentials.** `24`'s email and password are not parameters. They reach an unattended
  ChatGPT extraction through `settings=load_settings(email=…, password_file=…)`, which
  keeps the one place that reads a password file where it already was.
- **Any change to an operation.** No signature, outcome, message or exit code moves. The
  facade passes no `flags`, so a trace's header records none.

## Design notes

- **A second door, and `23`'s rule.** `23`'s design notes and the package docstring both
  say a re-export is a second spelling of where a thing lives, and that is why the
  operations are reached at the module that holds them. `Dataporter` is named at the top
  level anyway, and the distinction being relied on is that it is not a re-export: it is a
  class of its own, holding configuration the operations do not hold. The convenience
  bought is the whole point of the slice, and the cost is one name that exists in two
  places. `23`'s Status carries the amendment note, and so does the shared-decisions bullet
  in `specs/README.md` that made the same promise for `25`.
- **No `config.toml`, on purpose.** A library runs in somebody else's process, in somebody
  else's working directory. A `./migration/config.toml` found there was written for an
  operator's shell, and obeying it silently is how a host application ends up configured by
  a file it does not know about. The environment is a different case: `init` outranks it, so
  it only fills in fields the caller left unsaid, and suppressing it would mean a second
  construction path through the module every command depends on. `from_config` is the door
  for a caller who *does* want the operator's file, and it says so by name.
- **`mock` moves the workspace.** The `mock` field's own docstring says the flag changes the
  origin "and … the *defaults* for where state is kept", and the second half lived inside
  `load_settings`. A facade that built `Settings` directly and forgot would talk to the mock
  while writing to `./migration`, which is the collision ADR 0010 exists to prevent. Making
  `_mock_overrides` public was cheaper than describing the rule twice.
- **Four methods for `extract`, two for `login`.** A command line has one entry per command
  and needs flags to choose a mode; Python does not. `ask`, `fetch`, `file` and `abandon`
  are what `extract_command` dispatches to, so the combinations it refuses — a link beside
  a path, `--abandon` beside either — cannot be spelled here at all. `login` splits for a
  different reason: §73's two commands run in two terminals, which in Python is two calls,
  and `spend_link` naming the second one is more honest than a `link=` keyword on a method
  that otherwise blocks for ten minutes.
- **`extract_skills` keeps the command's name.** `ask` and `fetch` earned theirs by being
  separate words in `CONTEXT.md` with separate meanings. Skills extraction has one route and
  one command, so matching the command name is what makes it findable by a reader of the
  README's command table.
- **The source is checked in the constructor, the label at the call.** A facade holds a
  vendor across calls, so a typo in it should raise on the line that holds it rather than
  inside the first extraction; a label belongs to one call and is checked there, by
  `with_account`, as it always was. The cost is that a `Dataporter` built as a module-level
  constant can fail at import time, on a value that was wrong the whole time.
- **`settings=` is refused beside a value.** Merging them would mean deciding which wins,
  and a caller who passes both believes both are doing something. Refused for the reason
  `12` refused `--pilot` beside a selection flag.
- **No logging configuration.** `cli.main` calls `log.configure_logging`; this does not,
  because a library that reconfigures handlers fights whatever its host set up. The
  operations still call `log.enable_run_log`, so run logs are written under the workspace or
  the account home either way — which the README says, because it is the surprising half.
- **Not a glossary word.** `CONTEXT.md` is untouched. A facade is a convenience door into
  the tool, not a thing in the domain the tool is about.

## Acceptance criteria

- `tests/test_api.py::test_every_operation_is_plumbing`: no method named in `OPERATIONS`
  contains a `for`, `while`, `try`, `with` or `if`. `__init__` and `from_config` are
  excluded, because choosing between a handed `Settings` and a built one is the branch they
  exist to make.
- `tests/test_api.py::test_every_operation_returns_the_operations_own_outcome`: every
  method's return annotation names the module that owns the outcome. No facade result type
  exists.
- `tests/test_api.py::test_it_reads_no_config_file`: one `config.toml`, two doors. The
  constructor ignores it and `from_config` obeys it.
- `tests/test_api.py::test_mock_moves_the_workspace_as_the_flag_does`: `Dataporter(mock=True)`
  resolves `./migration-mock`, and an explicit workspace still wins.
- `tests/test_api.py::test_logout_is_the_operation`, `…::test_file_is_the_operation`,
  `…::test_abandon_is_the_operation`, `…::test_the_ask_is_the_operation`,
  `…::test_fetch_is_the_operation`, `…::test_extract_skills_is_the_operation`: each produces
  the outcome and the bytes the operation produces when handed the settings the CLI would
  have layered. `fetch` fills `30`'s opener and clock seams once and sends both sides
  through the same filling, because neither is part of the surface this slice offers.
- `tests/test_api.py::test_the_hook_refuses_every_other_name`: `from dataporter import console`
  still resolves, because the hook raises `AttributeError` for everything but `Dataporter`.
- `tests/test_api.py::test_nothing_prints_unless_a_sink_is_given`.
- `tests/test_api.py::test_login_means_the_destination_unless_a_label_says_otherwise`,
  `…::test_spend_link_is_the_same_operation_carrying_the_link`,
  `…::test_fetch_forwards_the_link_and_the_quiet`,
  `…::test_doctor_is_about_the_environment_and_takes_no_label`: the three that cannot be run
  twice and compared — each blocks on a person, a second process or a Hermes subprocess —
  stand their operation in for itself and assert what it was handed. `fetch` has one of
  these as well as its byte equality, because the arguments it forwards include `quiet`,
  which the equality test cannot see.
- `tests/test_api.py::test_no_operation_is_told_which_flags_were_typed`: `flags` is empty,
  so a trace's header records no option nobody gave.
- `tests/test_api.py::test_a_value_no_settings_would_accept_is_a_config_error`: both
  branches, in the words `load_settings` uses for the same failure.
- Every test written before this slice passes unchanged. `make check-all` passes with the
  coverage gate unchanged, `api.py` at 100%.

Nothing here needs a real Hermes, a real Chrome or a real account, which is why this slice
is `Done` rather than `Built`. What it does not prove is `login`, `spend_link` and `doctor`
end to end: each blocks on a person, a second process or a Hermes subprocess, so they are
covered by delegation rather than by the byte equality the other six get. A rehearsal is
what would exercise them whole.

## Risks

- **Two places describe how to call the tool.** The README's facade subsection and `23`'s
  operations table can drift, and the facade can fall behind an outcome that gains a field.
  The shape test catches logic appearing here; nothing catches a method that should have
  been added. The mitigation is that the facade returns the operations' own types, so a new
  field arrives at the caller without this file changing.
- **The lazy `__getattr__` is subtle.** It works because `from package import name` asks for
  the attribute before trying the submodule, and a hook that answered for `console` would
  shadow the module. `test_the_hook_refuses_every_other_name` is what keeps that true.
- **`settings_without_config_file` is a second way to build `Settings`.** It is deliberately
  a near-copy of `load_settings`'s body minus one source. If a third override joins the
  ladder, both need it, and only `load_settings` has a test that would notice.
