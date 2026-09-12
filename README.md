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
belongs. [`specs/README.md`](specs/README.md) is the per-slice state.

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

The tool never sees your Claude password (§8): you sign in yourself, in a browser window
it opens. It never reads the API key Hermes uses; that is Hermes's own `.env`.

## Requirements

- Python ≥ 3.12 and [`uv`](https://docs.astral.sh/uv/).
- Google Chrome, Chromium, Brave or Edge, installed locally.
- Hermes, installed with its official installer, on `PATH`, with a model configured and an
  API key in its `.env`. `doctor` checks the version, the profile, the model and the
  config, and tells you which of them is missing.
- A **throwaway destination account**. Not the source account, and not an account whose
  contents you would miss: this is an experiment that writes to it.
- Your Claude data export, as the `.zip` you were sent or a directory you unpacked it to.

## Install

```sh
git clone <this repository> && cd dataporter
make install                      # uv sync
uv run hermes-claude-migrate --version
```

Everything below is written as `hermes-claude-migrate …`; prefix it with `uv run` when you
have not installed the package into your own environment.

## Run it

```sh
# 1. The Hermes profile and the migration skill. Idempotent; run it again any time.
hermes-claude-migrate setup

# 2. Hermes, Chrome, the profile, the skill, the pacing — every check, in order.
hermes-claude-migrate doctor

# 3. Sign in to the *destination* account, by hand, in the window this opens.
hermes-claude-migrate login

# 4. What would be migrated, and what cannot be. Touches no account.
hermes-claude-migrate import <export> --dry-run

# 5. The pilot: five to ten conversations chosen by category (20). Start here.
hermes-claude-migrate import <export> --pilot
hermes-claude-migrate report

# 6. The full export, in sessions. Resume by running it again.
hermes-claude-migrate import <export> --all --limit 50
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
| `login` | Open the dedicated browser profile and wait for you to sign in. |
| `session status` / `session logout` | Whether that profile is signed in; remove it locally. |
| `inspect <export>` | What the export contains, and what is migratable. |
| `seeds <export>` | Write the migration seeds without touching a browser. |
| `import <export>` | Migrate. `--dry-run`, `--pilot`, `--all`, `--limit`, `--only`, `--retry-failed`, `--retry-partial`, `--force`, `--skip-attachments`. |
| `status` | What the workspace records, per conversation. |
| `resume` | Continue a run that paused for a person. |
| `verify` | Re-read migrated chats in the account and check they hold what was sent. |
| `report` | The end-of-migration report: counters, failures, limitations. |
| `followup` / `judge` | The pilot's semantic probe, and the optional model grade for it. |

Global options go before the subcommand: `--workspace PATH`, `--verbose`, `--quiet`,
`--version`. Configuration is `<workspace>/config.toml`, `HCM_…` environment variables and
flags, in that order of precedence, ending at the flags.

## Where your conversations end up

Three places, all local, and each one is purged by deleting a directory:

| Where | What is in it | How to purge |
| --- | --- | --- |
| `<export>` | Your export, opened read-only. The tool never writes to it. | Yours; keep it. |
| `migration/` (the workspace, `--workspace` to move it) | `state.json`, `run.json`, `plan.json`, `report.json`, `seeds/` (the rendered transcripts), `attachments/`, `pilot/probes.json` (replies Claude wrote), `browser-profile/` (a signed-in Chrome profile) and `logs/`. | `rm -rf migration/` |
| `~/.hermes/profiles/dataporter/` | Hermes's own session transcripts, which contain page snapshots and therefore conversation content. | `rm -rf ~/.hermes/profiles/dataporter/` — `setup` prints the path on every run. |

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

[`specs/README.md`](specs/README.md) is the map: what each slice is, what is `Done`, and
which brief section it satisfies. Start there rather than here.
