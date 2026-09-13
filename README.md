# dataporter

Migrate a Claude data export into **another** Claude account, by driving the Claude web
interface with the [Hermes](https://github.com/NousResearch) agent. The tool reconstructs
each source conversation as a *migration seed* — a rendered transcript — and pastes it into
a new chat in the destination account, one conversation at a time, through the same UI a
person would use. Claude's internal database and undocumented backend APIs are
deliberately left alone (§2); this is the experiment that asks whether the normal user
interface is enough.

It is an experiment, and it says so in its files: [`specs/01-initial-brief.md`](specs/01-initial-brief.md)
is what it is for, [`specs/`](specs/) is how it is built, and
[`docs/experiment-02.md`](docs/experiment-02.md) is where what it turned out to be able to
do is written down. The success criterion is one number — how many conversations migrate
without a person having to intervene — and until a full run has produced it, the write-up
says so.

**Status:** the tool is built and tested; the experiment has not been run. No real export
has been read end to end, `10`'s spike has not been conducted against a live Claude, and
neither the pilot (`20`) nor the full run (`21`) has produced a number —
`docs/experiment-01.md` and `docs/experiment-02.md` carry `*not yet run*` where each one
belongs. Extraction is the same: `31`'s ask is built against a placeholder path and three
guessed selectors, no real account has been asked, and `docs/extraction-01.md` says so.
[`specs/README.md`](specs/README.md) is the per-slice state.

## What you end up with

A destination account whose chats each contain one conversation from the export, rendered
as text and acknowledged by Claude, with the original title where the UI allowed a rename.
What cannot survive the trip — timestamps, message ids, branches, thinking blocks — is
listed in [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) and counted in the report. Read that
file before you run anything: it is the honest description of the result.

## What it will never do (§17)

The destination account is touched only for the migration. The tool and the agent it
drives will not:

- delete source conversations — the export is opened read-only and never written to, and
  the source account is never signed in to at all;
- modify unrelated destination conversations, or send a message to one;
- change account settings, billing or security settings;
- act outside the migration workflow — a helper refuses any page that is not
  `claude.ai/new` or `claude.ai/chat/<id>`, and Hermes is told to stop and ask rather than
  click anything destructive.

It also never deletes anything at the destination. A conversation migrated twice leaves
two chats, and the old one's id is kept in `run.json` rather than tidied away.

Interactively the tool never sees your Claude password (§8): you sign in yourself, in a
browser window it opens. Unattended (`--non-interactive`, `24`) you hand it the
destination account's email and password for one run, through the environment or a file;
it keeps them in memory, types them into the sign-in form itself, and never writes them
to a file, a log, a prompt or the agent. It never reads the API key Hermes uses; that is
Hermes's own `.env`.

## Requirements

- Python ≥ 3.12. [`uv`](https://docs.astral.sh/uv/) to develop on this repository;
  a project that only *depends* on the package needs whatever installer it already uses.
- Google Chrome, Chromium, Brave or Edge, installed locally.
- Hermes, installed with its official installer, on `PATH`, with a model configured and an
  API key in its `.env`. `doctor` checks the version, the profile, the model and the
  config, and tells you which of them is missing. Hermes is a subprocess and never an
  import, so it constrains nothing about a host project's dependencies or its Python
  version — it only has to be on the `PATH` the process inherits.
- A **throwaway destination account**. Not the source account, and not an account whose
  contents you would miss: this is an experiment that writes to it.
- Your Claude data export, as the `.zip` you were sent or a directory you unpacked it to.

## Install

There is no release on PyPI — `25` shaped the package to be installable and deliberately
left publishing alone — so the install is a git URL or a path.

**Into another project**, which is what makes it a library rather than a checkout:

```sh
uv add git+https://github.com/lukin0110/dataporter   # or: uv add ../dataporter
uv add dataporter[judge] --no-sources                # `20`'s optional model judge
```

`pip install git+https://github.com/lukin0110/dataporter` does the same thing for a
project that uses pip. Either way you get the `dataporter` command in that
project's environment, `python -m dataporter` as the same command under another name, and
the library described in [From another project](#from-another-project) below.

**For just the command**, with no project to put it in:

```sh
uv tool install git+https://github.com/lukin0110/dataporter
```

**To develop on it:**

```sh
git clone <this repository> && cd dataporter
make install                      # uv sync
uv run dataporter --version
```

Everything below is written as `dataporter …`; prefix it with `uv run` when you
have not installed the package into your own environment.

## Run it

```sh
# 1. The Hermes profile and the migration skill. Idempotent; run it again any time.
dataporter setup

# 2. Hermes, Chrome, the profile, the skill, the pacing — every check, in order.
dataporter doctor

# 3. Sign in to the *destination* account, by hand, in the window this opens.
dataporter login

# 4. What would be migrated, and what cannot be. Touches no account.
dataporter import <export> --dry-run

# 5. The pilot: five to ten conversations chosen by category (20). Start here.
dataporter import <export> --pilot
dataporter report

# 6. The full export, in sessions. Resume by running it again.
dataporter import <export> --all --limit 50
```

Steps 1–5 are the whole of the first sitting, and step 4 is safe to run on anything: it
parses the export, classifies every conversation and prints what a migration would do,
without opening a browser or writing to an account.

Step 6 is days of work for a large export, and it is meant to be interrupted. State lives
in the workspace, every session ends with a report, and `import` again continues where the
last one stopped. [`docs/runbook.md`](docs/runbook.md) is the operator's half of this:
interrupting, resuming, retrying failures, clearing a pause, reading the report.

## The commands

| Command | What it does |
| --- | --- |
| `setup` | Create the Hermes profile and install the migration skill. |
| `doctor` | Check Hermes, Chrome and the configuration. Exits `6` at the first failure. |
| `login` | Open the dedicated browser profile and wait for you to sign in. `--account LABEL` (and `--source`) signs in to a *source* account instead of the destination. |
| `session status` / `session logout` | Whether that profile is signed in; remove it locally. Same two options, same meaning. |
| `extract` | Ask a source for an account's export, then file what comes back as a snapshot. `--source`, `--account`, `--link`, `--from`, `--abandon`, `--store`. |
| `snapshots` | What the store holds: source, account, stamp, conversations, state. `--json`. |
| `inspect <export>` | What the export contains, and what is migratable. A snapshot works wherever an export does. |
| `seeds <export>` | Write the migration seeds without touching a browser. |
| `import <export>` | Migrate. `--dry-run`, `--pilot`, `--all`, `--limit`, `--only`, `--retry-failed`, `--retry-partial`, `--force`, `--skip-attachments`. |
| `status` | What the workspace records, per conversation. |
| `resume` | Continue a run that paused for a person. |
| `verify` | Re-read migrated chats in the account and check they hold what was sent. |
| `report` | The end-of-migration report: counters, failures, limitations. |
| `followup` / `judge` | The pilot's semantic probe, and the optional model grade for it. |

Global options go before the subcommand: `--workspace PATH`, `--verbose`, `--quiet`,
`--version`, and `24`'s `--non-interactive`, `--email EMAIL`, `--password-file PATH`.
Configuration is `<workspace>/config.toml`, `DATAPORTER_…` environment variables and flags, in
that order of precedence, ending at the flags — except the mode and the credentials, which
`config.toml` may not carry.

## Backing an account up

`extract` takes data *out* of an account and files it where it can never be
overwritten; `import` is the restore. The two never run in one go — a person who only
wants a backup never migrates — and a person stands between them, because the vendor
puts an inbox there:

```sh
# 0. Sign in to the source account, in its own browser profile.
dataporter login --account old-personal

# 1. Ask Claude for the account's export. The tool presses the button itself.
dataporter extract --source claude --account old-personal      # the ask

# 2. Claude emails a link. Hand it over; the tool downloads, checks and files it.
dataporter extract --source claude --account old-personal --link 'https://…'

# An archive you already have is filed the same way, with no ask behind it:
dataporter extract --source claude --account old-personal --from ./data-2026-09-12.zip

dataporter snapshots                                           # what the store holds
dataporter import ~/.dataporter/store/claude/old-personal/2026-09-12T20-51-07Z
```

A snapshot is the vendor's own archive, byte for byte, with everything of ours beside it
— the stamp, the provenance, the counts, and every gap with its reason. It is written
once and never touched again: a second extraction is a second snapshot with a later
stamp, and a stamp that already exists is an error rather than a merge.

| Where | What is in it |
| --- | --- |
| `~/.dataporter/store/<source>/<account>/<stamp>/` | The snapshots: `export.zip`, `snapshot.json`, `COMPLETE`. `--store DIR` or `[store] dir` moves it. |
| `~/.dataporter/accounts/<source>/<account>/` | What is *not* a snapshot: the open ask, the logs, and (`31`) the source session's browser profile. `[accounts] dir` moves it. |

`--account` is your label for the account, not its login: emails change and ids are the
vendor's. The link is used once and never written down — not in the snapshot, not in a
log — because it expires and is a credential to the archive while it lasts.
[`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) has what to know before relying on a store,
and what one press on the vendor's page does not promise.

The source account gets its own browser session, because one browser profile holds one
signed-in identity per site: `login --account old-personal` signs it in, `session status
--account old-personal` says whether it still is, and `session logout --account
old-personal` throws it away. Without `--account` all three mean the destination, exactly
as before. **One at a time**: every session shares `browser.cdp_port`, so a Chrome still
running for one account makes the next command exit `2` — close it and run again.

The ask itself never uses a model: the tool goes to the page, presses the button, and
records that it did. Unattended (`--non-interactive`) it is the same one press, and it
needs Hermes only when the source session has expired and somebody has to be signed in
first — which is `24`'s agent half, and the one part of a backup a cron job cannot do
without a model.

## Running unattended

```sh
export DATAPORTER_NON_INTERACTIVE=1 DATAPORTER_AUTH__EMAIL=you@example.com DATAPORTER_AUTH__PASSWORD=…
dataporter login                                  # signs in, closes Chrome
dataporter import <export> --all --limit 50       # signs in again if it must
```

In this mode Chrome runs without a window, `login` and `import` sign in from the
credentials — Hermes brings the page to the form, and the tool types into it from its own
process, so the agent never holds the password — and nothing waits for a keypress: a page
only a person can clear is recorded as a pause and the run exits `5`, for `resume` to pick
up. Missing credentials are exit `2` before a browser starts. An account whose sign-in is
an emailed code, a CAPTCHA or a challenge cannot be signed in unattended; the run says so
and stops. [`docs/runbook.md`](docs/runbook.md) has the exit codes and the details.

## From another project

Everything the CLI does is a library call (`23`). Each command's body is a function in the
module that owns it — `importer.import_command`, `browser.session.login`,
`verify.verify_all` — that takes `Settings`, writes its lines to a `console.Sink` and
returns a frozen outcome with an `exit_code`. A Python caller gets the same words and the
same codes, and never imports `typer`:

```python
from pathlib import Path

from dataporter import console, importer
from dataporter.config import load_settings

settings = load_settings(workspace=Path("var/claude-migration"))
sink = console.Collected()
outcome = importer.import_command(
    settings,
    importer.ImportRequest(export="./claude-export", dry_run=True),
    sink=sink,
)
print(sink.stdout, outcome.exit_code)
```

The operations table in [`specs/impl/23-library-operations.md`](specs/impl/23-library-operations.md)
is the API: one row per command, naming the function, its options and the outcome it
returns. They are reached where they live rather than re-exported from the top level,
because a re-export is a second spelling of where a thing lives. The package ships
`py.typed`, so a host project's type checker reads the real signatures instead of `Any`.

Four things are worth knowing before the first call:

- **Pass `workspace=` explicitly.** The default is `./migration`, relative to the working
  directory of whatever process is calling — which for a library is the host
  application's, not an operator's shell. The example above names one rather than
  discovering one.
- **Nothing prints unless you ask.** The default sink is `console.DISCARD`; pass
  `console.Collected()` to read the lines back, or `console.Terminal()` to let them
  through to stdout and stderr.
- **Errors raise, results return.** An outcome's `exit_code` carries "nothing to do" or
  "a conversation did not make it" (`exit_codes.ExitCode`); anything an operator could fix
  is an `errors.MigrationError` subclass, or `errors.UsageError` for a contradiction in
  what was asked.
- **Hermes and Chrome are still required.** A dry run, `inspect` and `seeds` touch neither
  and work anywhere the package is installed. Everything else needs `hermes` on the
  `PATH` of the calling process and a browser on the machine — run `doctor` (or
  `hermes.doctor.run_doctor`) once from the host project to find out which is missing.

`python -m dataporter <command>` runs the CLI without the console script being on `PATH`,
which is the easier spelling from inside another project's environment.

## Where your conversations end up

Three places, all local, and each one is purged by deleting a directory:

| Where | What is in it | How to purge |
| --- | --- | --- |
| `<export>` | Your export, opened read-only. The tool never writes to it. | Yours; keep it. |
| `migration/` (the workspace, `--workspace` to move it) | `state.json`, `run.json`, `plan.json`, `report.json`, `seeds/` (the rendered transcripts), `attachments/`, `pilot/probes.json` (replies Claude wrote), `browser-profile/` (a signed-in Chrome profile) and `logs/`. | `rm -rf migration/` |
| `~/.hermes/profiles/dataporter/` | Hermes's own session transcripts, which contain page snapshots and therefore conversation content. | `rm -rf ~/.hermes/profiles/dataporter/` — `setup` prints the path on every run. |
| `~/.dataporter/store/` (`30`, `--store` to move it) | The snapshots `extract` files: one vendor archive each, and a manifest beside it. Holds conversations because that is what a backup is for. | `rm -rf ~/.dataporter/store/` — the tool never deletes from the store itself. |
| `~/.dataporter/accounts/` (`[accounts] dir` to move it) | Per source account, and never a snapshot: the open ask and the run logs. | `rm -rf ~/.dataporter/accounts/` |

The workspace holds content by design: a seed *is* a conversation. What does not hold
content is the terminal and the run logs — no title and no message is printed or logged at
any verbosity (§10), which is what makes a log safe to paste into an issue.

`session logout` removes the browser profile only. It does not sign the destination
account out anywhere else, and it deletes nothing in the account.

## Developing

```sh
make check        # lint, types, and the fast half of the suite — what CI runs on a PR
make check-all    # everything, with the coverage gate — what CI runs on main
make fmt
```

[From another project](#from-another-project) is the library half of this, and `23` is
where the shape came from: `cli.py` parses flags and exits, and every command's body is a
function in the module that owns the domain.

`make check` also runs the mock's own tests, which are a second on top of its four;
`make check-all` is about twenty-five; the second one
runs the suite across every core. The `check`/`check-all` line is the `slow` marker —
anything that spawns a subprocess, binds a socket or launches a browser — so a pull
request is never gated on a browser. The tests that drive a *real* one are skipped unless
there is one to drive: `DATAPORTER_TEST_BROWSER=/path/to/chrome uv run pytest -m live`
runs those eighteen against whatever Chrome or Chromium you point it at.

### Rehearsing it

You do not need a Claude account to run the whole tool end to end. `mock/` is a served
stand-in for claude.ai — its own project, one dependency, no model behind it — and
`rehearsal/` runs the full run's protocol against it with a model-free agent standing
where Hermes stands:

```sh
uv run --package claude-mock claude-mock serve        # in one terminal
uv run python -m rehearsal.run --root /tmp/rehearsal  # in another
```

The mock prints the two Chrome arguments that point a browser at it; the tool itself has
no setting that names it, so a rehearsal proves the code that ships or it proves nothing.
What comes out is §25's pass criteria, reconciled against the mock's own count of what it
was asked to do, and — with `--record docs/rehearsal-NN.md` — a record like
[`docs/rehearsal-01.md`](docs/rehearsal-01.md). It is **not** evidence about claude.ai:
see [`specs/02-claude-mock.md`](specs/02-claude-mock.md) §27 and
[`mock/README.md`](mock/README.md).

[`specs/README.md`](specs/README.md) is the map: what each slice is, what is `Done`, and
which brief section it satisfies. Start there rather than here.
