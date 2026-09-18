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

# 3. Sign in to the *destination* account: a window opens, you enter the address, Claude
#    emails a link, and a second terminal spends it in that same window (brief 07).
dataporter login
dataporter login --link 'https://…'

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
| `logout` | Sign out of a source account: remove its session, its open ask and its staged downloads, keeping its logs. `--source`, `--account` (required). |
| `session status` | Whether a source account's profile is signed in. `--source`, `--account` (required). |
| `extract` | Ask a source for an account's export, then file what comes back as a snapshot. `--source`, `--account`, `--link`, `--from`, `--abandon`, `--store`. |
| `extract-skills` | Collect the skills the account wrote and file them into a snapshot beside the archive. An export does not carry them. `--source`, `--account`, `--stamp`, `--store`. |
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
`--version`, `24`'s `--non-interactive`, `--email EMAIL`, `--password-file PATH`, and
`--mock` — which points every command at a local stand-in for the site instead of the real
one ([below](#working-with-the-mock)).

Configuration is `<workspace>/config.toml`, `DATAPORTER_…` environment variables and flags, in
that order of precedence, ending at the flags — except the mode, the credentials and
`--mock`, which `config.toml` may not carry. `--mock` is stricter still: it is the flag or
nothing, because the question it answers is "did I mean this run to be real".

## Backing an account up

`extract` takes data *out* of an account and files it where it can never be
overwritten; `import` is the restore. The two never run in one go — a person who only
wants a backup never migrates — and a person stands between them, because the vendor
puts an inbox there:

```sh
# 0. Sign in to the source account, in its own browser profile: the window, the address,
#    then the emailed link spent in that window from a second terminal.
dataporter login --account old-personal
dataporter login --account old-personal --link 'https://…'

# 1. Ask Claude for the account's export. The tool presses the button itself.
dataporter extract --source claude --account old-personal      # the ask

# 2. Claude emails a link. Hand it over; the tool downloads, checks and files it.
dataporter extract --source claude --account old-personal --link 'https://…'

# An archive you already have is filed the same way, with no ask behind it:
dataporter extract --source claude --account old-personal --from ./data-2026-09-12.zip

# 3. The export does not carry the skills the account wrote. Collect them into the same
#    snapshot — no ask, no link, nothing clicked — or, without --stamp, into one of their own:
dataporter extract-skills --source claude --account old-personal --stamp 2026-09-12T20-51-07Z

dataporter snapshots                                           # what the store holds
dataporter import ~/.dataporter/store/claude/old-personal/2026-09-12T20-51-07Z
```

A ChatGPT account is the same two moves (brief `06`). Its sign-in passes through
`auth.openai.com`, and its link is served only to the signed-in session, so the fetch
opens the source session's browser and catches the download rather than fetching
without one:

```sh
dataporter login --source chatgpt --account work
dataporter extract --source chatgpt --account work             # the ask; email or text
dataporter extract --source chatgpt --account work --link 'https://…'   # the fetch, in the browser
```

Unattended, the sign-in is a walk the tool makes itself — no agent on the path — and a
cron job needs the credentials in its environment for the case the session has expired.
A ChatGPT snapshot is a backup and not yet a restore: `import` refuses it with the reason,
because each source needs its own importer before its snapshots can be restored
([ADR 0005](docs/adr/0005-snapshots-are-vendor-native.md)).

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
--account old-personal` says whether it still is, and `logout --account old-personal`
throws it away. The last two name an account always; only `login` still means the
destination when you leave `--account` out. **One at a time**: every session shares
`browser.cdp_port`, so a Chrome still running for one account makes the next command
exit `2` — close it and run again.

The ask itself never uses a model: the tool goes to the page, presses the button, and
records that it did. Unattended (`--non-interactive`) it is the same one press, on a
profile a person signed in; a Claude session that has expired stops the run with exit `3`
and `login` as the remedy, because Claude's sign-in is a link behind an attestation and no
credential can make it (brief 07). An account that was never signed in at all stops with
the same line and the same code *before a browser opens*: there is no session on disk to
reuse, and that is answerable without asking the vendor.

**Both moves work with no account at all.** `mock/` is a served stand-in for the site —
its settings panel, its sign-in, its export link — and `--mock` is what points the tool
there:

```sh
uv run --package mocks claude-mock serve     # in one terminal
dataporter --mock extract --account eddie    # in another: the same command, a local site
```

It keeps what it writes in `~/.dataporter/mock/`, so nothing a mock run files can be
mistaken for a backup of the account it names. [Working with the
mock](#working-with-the-mock) is the whole loop; [`mock/README.md`](mock/README.md) is the
site itself.

## Running unattended

```sh
dataporter login                                  # once, by hand: the window and the link
dataporter login --link 'https://…'
export DATAPORTER_NON_INTERACTIVE=1
dataporter import <export> --all --limit 50       # while the session lasts
```

In this mode Chrome runs without a window and nothing waits for a keypress: a page only a
person can clear is recorded as a pause and the run exits `5`, for `resume` to pick up.
What the mode cannot do is sign a Claude account in. Claude's sign-in is an emailed link
behind an attestation (brief 07, ADR 0008), so `login --non-interactive` is refused with
exit `2` and the command a person runs instead, and a run whose session has expired stops
with exit `3` and names `login`. The credentials `DATAPORTER_AUTH__EMAIL` and
`DATAPORTER_AUTH__PASSWORD` are ChatGPT's alone, for the walk its unattended extraction makes
when its session has expired. [`docs/runbook.md`](docs/runbook.md) has the exit codes and
the details.

## From another project

### Five commands, one object

`Dataporter` (`68`) is the short way in. It covers the five commands a host project
reaches for — signing in and out of a source account, asking for and filing an export, the
skills an export leaves out, and checking the environment — and it holds the configuration
those calls would otherwise repeat:

```python
from pathlib import Path

from dataporter import Dataporter

dp = Dataporter(store=Path("~/backups").expanduser())

dp.login("work")                        # blocks: a window opens, you sign in
dp.ask("work")                          # ask Claude for the export; the link is emailed
dp.fetch("work", "https://…")           # file what the link serves as a snapshot
dp.extract_skills("work")               # the skills an export does not carry
```

| Method | What it does |
| --- | --- |
| `login(account=None)` | Open the sign-in page in the account's own profile and **block** until it is signed in. No account means the destination. |
| `spend_link(link)` | Spend a sign-in link in the window a blocked `login` is holding. Run it from another process. |
| `logout(account)` | Remove the account's session, its open ask and its staged downloads. Keeps the logs. |
| `ask(account)` | Ask the vendor for the export. One ask is open per account, and the answer arrives by email, possibly hours later. |
| `fetch(account, link)` | Download what the emailed link serves and file it as a snapshot. |
| `file(account, path)` | File an archive you already have, with no ask behind it. |
| `abandon(account)` | Give up the open ask, so another can be made. |
| `extract_skills(account, stamp=None)` | Collect the skills the account wrote. `stamp` files them beside an existing snapshot. |
| `doctor()` | Check Hermes, Chrome, the profile and the pacing. `exit_code` is `6` when a check failed. |

Every method takes `sink=` to say where the lines go. Every method above `doctor` also
takes `source=` to name the vendor (`claude` unless you say otherwise); `doctor` is about
the environment rather than an account, so it takes neither that nor a label. Each returns
the same frozen outcome the command line acts on, with an `exit_code` and the facts the
command printed. Five things are worth knowing before the first call:

- **Pass `workspace=` or `store=` if the defaults are wrong for you.** They are `./migration`
  and `~/.dataporter/store`, relative to whatever process is calling.
- **No `config.toml` is read.** The constructor configures itself from what you hand it, and
  the environment fills in what you do not. `Dataporter.from_config(…)` is the door to the
  ladder the command line uses, for a host running on a machine somebody set up for the CLI.
- **Nothing prints.** Pass `sink=console.Collected()` to read the lines back, or
  `console.Terminal()` to let them through. Run logs are still written under the workspace
  or the account home, because the operations write them.
- **Errors raise, results return.** An outcome's `exit_code` carries "nothing to do" or "not
  signed in"; anything an operator could fix is an `errors.MigrationError` subclass, or
  `errors.UsageError` for a contradiction in what was asked.
- **`login` waits for a person, and cannot be made not to.** Claude signs in by emailed link
  behind a bot check (ADR 0008), so the call blocks with the window open until `spend_link`
  spends the link from another process. Unattended sign-in to Claude is refused, by design.

`import`, `resume`, `seeds`, `inspect`, `verify`, `report` and the rest have no method
here. They are reached the way everything was reached before `68`, which is next.

### Every command, where it lives

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
is the full API: one row per command, naming the function, its options and the outcome it
returns. They are reached where they live rather than re-exported from the top level,
because a re-export is a second spelling of where a thing lives. `Dataporter` is the one
name at the top, and it is a class holding configuration rather than an operation under a
second name. The package ships `py.typed`, so a host project's type checker reads the real
signatures instead of `Any`.

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
| `~/.dataporter/store/` (`30`, `--store` to move it) | The snapshots `extract` files: one vendor archive each, a manifest beside it, and — since `66` — the account's own skills under `skills/`, as the vendor served them. Holds conversations because that is what a backup is for. | `rm -rf ~/.dataporter/store/` — the tool never deletes from the store itself. |
| `~/.dataporter/accounts/` (`[accounts] dir` to move it) | Per source account, and never a snapshot: the open ask and the run logs. | `rm -rf ~/.dataporter/accounts/` |

Every command that drives a browser tab — `login`, `import`, `resume`, `verify`,
`followup`, `doctor`, `extract-skills`, and `extract` when it asks — also leaves a **trace**,
`logs/trace-<ts>.jsonl` beside its run log: one line per helper call, with what the
page showed in outline, so that a run against the real site can be read back and the
mock claude.ai corrected against it (brief `04`). A trace carries paths, the labels of
controls, and timings; never a message, a title, an address, a query value or a
credential, and the same guard that protects the run log refuses any line that would.
What the page showed is a **sketch**: its controls by role and label — a button, a text
box, a dialog — and everything else by role and shape, a heading or a sidebar link as a
length and a hash and never a word of it, plus how many elements each of the tool's own
selectors found. Beside the moves, a **watch** — the tool's own session on the tab —
records what the page did whoever caused it, Hermes included: navigations, URL changes,
dialogs by type, the page's own requests in outline, and the certificate the browser was
shown. A watch that is lost is a line in the trace and a warning in the run log, never a
failed run. A trace of a run against the real site may be committed under
`docs/spike/traces/` once a person has read it end to end, and cited by file and line
where a row of the UI map turns *observed*.

The workspace holds content by design: a seed *is* a conversation. What does not hold
content is the terminal and the run logs — no title and no message is printed or logged at
any verbosity (§10), which is what makes a log safe to paste into an issue.

`logout` removes a source account's session, its open ask and anything a fetch staged,
and keeps its logs. It does not sign the account out anywhere else, and it deletes nothing
in the account or in the store. The destination's profile is inside the workspace and goes
with it.

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

### Working with the mock

You do not need a Claude account to run the tool end to end. `mock/` is a served stand-in
for claude.ai — its own project, no model behind it, stateful and reached by a real Chrome
— and `--mock` is the whole of how the tool reaches it:

```sh
uv run --package mocks claude-mock serve
# Mock claude.ai listening on http://127.0.0.1:8443
```

Plain HTTP on loopback. Nothing to paste into a config file, no certificate, no resolver
rule. The flag changes **one thing** — the origin every URL is built on and every wall is
built from — and `tests/test_mock_flag.py` asserts that field by field, which is what
[ADR 0010](docs/adr/0010-the-mock-is-reached-by-a-flag.md) claims now that
[ADR 0001](docs/adr/0001-no-door-in-the-wall.md) is superseded.

#### One command at a time

What you want while changing the tool or the mock. The mock has no inbox, so it prints
where an email would have arrived:

```sh
dataporter --mock login --account eddie                    # 1. opens a window and waits
#      type the address into the mock's own sign-in form
uv run --package mocks claude-mock sign-in-links           # 2. the "email": the last link
dataporter --mock login --account eddie --link "<link>"    # 3. spends it; step 1 returns
dataporter --mock extract --account eddie                  # 4. the ask
uv run --package mocks claude-mock exports                 # 5. the "email" again
dataporter --mock extract --account eddie --link "<link>"  # 6. the fetch; files a snapshot
dataporter --mock snapshots
```

Steps 1–3 are two commands because Claude signs in with an emailed link and nothing else
(brief `07` §72), and the mock mimics that — a person still types the address. Steps 4–6
are two because an export is asked for now and arrives later. **`--mock` is an address and
never control flow**: the moment it changed what a command *does*, the thing under test
would stop being the thing that ships.

#### Why it is safe to have shipped a flag

- **The walls are disjoint.** With `--mock` the tool refuses `claude.ai`; without it, it
  refuses the mock. A forgotten flag is a `SafetyError` naming the URL, not a real run.
- **`--mock` is the only door.** Not `DATAPORTER_MOCK`, not `config.toml`. It is visible at
  the call site every time, which an exported variable would not be.
- **What it writes is kept apart**, in `~/.dataporter/mock/{accounts,store}` and
  `./migration-mock`, so a mock's invented chats never appear in `snapshots` as a backup of
  the account they name.

#### The whole protocol, in one go

`rehearsal/` plays either protocol against the mocks with a model-free agent standing where
Hermes stands. The migration (§25's pass criteria, reconciled against the mock's own count
of what it was asked to do):

```sh
uv run --package mocks claude-mock serve              # in one terminal
PYTHONPATH=tests uv run python -m rehearsal.run --root /tmp/rehearsal
```

And brief `06`'s extraction protocol against both mocks — the account seeded, `login`, an
ask, the fetch, a second of each, `snapshots`, the ledger reconciled:

```sh
uv run --package mocks claude-mock serve               # in one terminal
uv run --package mocks chatgpt-mock serve              # in another
PYTHONPATH=tests uv run python -m rehearsal.run --protocol extraction --root /tmp/r3
```

With `--record docs/rehearsal-NN.md` either leaves a record like
[`docs/rehearsal-02.md`](docs/rehearsal-02.md) or
[`docs/rehearsal-03.md`](docs/rehearsal-03.md). Every step that drove a tab leaves a trace
under `<root>/traces/`, named after the step, and those traces say `127.0.0.1` — a
rehearsal's trace identifies itself, so it can never be mistaken for evidence about the
real site (brief `04` §48).

`--mock --non-interactive` runs **headless**, which `--non-interactive` alone cannot
against claude.ai: a mock has no bot check (ADR 0008). That is the combination CI would
use.

#### What it shows, and what it does not

The export is the shape a real one has (`64`): a settings panel at a fragment of `/new`, an
Export row matched by position among six buttons, a `202` and a toast, and a
`manifest.json` naming one single-use zip per category. The mock chatgpt.com is beside it
(brief `05`) on `8444`, with `8445` standing in for its auth origin.

It is **not** evidence about claude.ai — see [`specs/02-claude-mock.md`](specs/02-claude-mock.md)
§27 and [`mock/README.md`](mock/README.md). The panel renders instantly where a real one
takes ~2.9 s (`62`); parts are served off the mock rather than redirected to a storage
host; the toast is in English, so a real account served in another language matches
nothing; and §21's remaining list — a rate limit, a modal in the way, a generation error, a
CAPTCHA, a code prompt at sign-in — is unchanged.
[`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) carries each with its mark.

[`specs/README.md`](specs/README.md) is the map: what each slice is, what is `Done`, and
which brief section it satisfies. Start there rather than here.
