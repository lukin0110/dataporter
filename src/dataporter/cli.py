"""The command surface.

Every command in `specs/impl/01-foundation.md` is registered here so that `--help`
is stable from the first release and later slices fill in behaviour rather than
rename things. Nothing migrates anything yet: an unimplemented command exits `69`.

Output is plain `print` — no colour, no `rich`, no completion options — because
§9, §10 and §16 of the brief are golden strings and terminal decoration would break
byte comparison. Errors go to stderr, always, since stdout is spoken for: `18` owns
the progress block and `08`'s helpers print exactly one JSON object there.
"""

import importlib.metadata
import json
from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from typer.core import TyperGroup

from dataporter import PROGRAM_NAME, log, progress, state, summary
from dataporter import followup as following
from dataporter import importer as importing
from dataporter import judge as judging
from dataporter import pilot as piloting
from dataporter import report as reporting
from dataporter import seed as seeding
from dataporter import verify as verifying
from dataporter.browser import cdp, launcher, probe
from dataporter.browser import helpers as browser_helpers
from dataporter.browser import session as browser_session
from dataporter.config import (
    ConfigError,
    Settings,
    load_settings,
    with_attachments_dir,
    with_pacing,
    with_skip_attachments,
)
from dataporter.errors import AuthError, BrowserError, ExportError, HermesError
from dataporter.exit_codes import ExitCode
from dataporter.export import Conversation, load_export
from dataporter.export import Export as ParsedExport
from dataporter.hermes import doctor as hermes_doctor
from dataporter.hermes import profile as hermes_profile
from dataporter.plan import MigrationPlan, build_plan

__all__ = ["PROGRAM_NAME", "app"]
"""`PROGRAM_NAME` lives in `dataporter/__init__.py` — `09` builds the command line
Hermes runs through its terminal tool and cannot import `cli` to get it — and is
re-exported here because this is where every message that uses it is written."""

_logger = log.get_logger(__name__)


# --------------------------------------------------------------------------- #
# Plumbing
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AppContext:
    """What the global options resolved to, handed to every command."""

    settings: Settings
    verbose: bool
    quiet: bool


def fail(message: str, code: ExitCode = ExitCode.USAGE) -> NoReturn:
    """Report an operator-fixable problem and exit. No traceback."""
    print(f"error: {message}", file=typer.get_text_stream("stderr"))
    raise typer.Exit(code)


def invoked_name(ctx: typer.Context) -> str:
    """The command path as typed, e.g. `import` or `session status`.

    Not `ctx.command_path`, which prepends the program name and interpolates
    parent usage metavars. Derived rather than hardcoded per command, so renaming
    a command cannot desynchronise it from its message.
    """
    parts: list[str] = []
    # Typer vendors click; the parent chain is typed as its internal Context, which
    # has no public name to annotate against.
    current: Any = ctx
    while current is not None and current.parent is not None:
        if current.info_name:
            parts.append(current.info_name)
        current = current.parent
    return " ".join(reversed(parts))


def not_implemented(ctx: typer.Context, detail: str = "") -> NoReturn:
    """Exit `69`. A command, or — `detail` — one flag of an implemented one.

    Nothing in the surface answers it any more: `12` was the first caller of the
    second kind, refusing `--pilot` because a flag that asks for a different
    selection cannot be accepted and quietly ignored the way an inert one can,
    and `20` is what implemented the selection it was holding the place for. It
    stays because the surface is fixed in `01` and the next command to be
    registered ahead of its slice needs it.
    """
    named = f"{invoked_name(ctx)} {detail}".rstrip()
    print(
        f"not implemented in this build: {named}",
        file=typer.get_text_stream("stderr"),
    )
    raise typer.Exit(ExitCode.NOT_IMPLEMENTED)


def require_export(export: str) -> Path:
    """Check the export path exists, echoing it back exactly as the operator typed
    it — `str(Path("./nowhere"))` is `"nowhere"`, which would break the message."""
    path = Path(export)
    if not path.exists():
        fail(f"export not found: {export}")
    return path


def app_context(ctx: typer.Context) -> AppContext:
    """The resolved global options. Later slices read settings from here."""
    obj = ctx.find_object(AppContext)
    if obj is None:  # pragma: no cover - the root callback always sets it
        raise RuntimeError("application context was not initialised")
    return obj


def distribution_version() -> str:
    try:
        return importlib.metadata.version("dataporter")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover
        return "0.0.0+unknown"


class _RootGroup(TyperGroup):
    """Turns an unhandled exception into exit `70` instead of a traceback."""

    # `ctx` is typer's vendored click Context, which has no public name to annotate
    # against; narrowing it to typer.Context would violate the supertype signature.
    def invoke(self, ctx: Any) -> Any:
        try:
            return super().invoke(ctx)
        except (typer.Exit, typer.Abort, typer.TyperException):
            # Already carries its own exit code: usage errors, --version, our own
            # typer.Exit(...) calls. TyperException is the base of typer's vendored
            # click exception hierarchy.
            raise
        except ConfigError as exc:
            fail(str(exc))
        except state.StateError as exc:
            # A locked workspace, a workspace belonging to another export, an
            # unreadable state file: all operator-fixable, all exit `2`. The
            # invariant violations in `state` are `ValueError`s and fall through
            # to `70`, which is where a bug in us belongs.
            fail(str(exc))
        except AuthError as exc:
            # Exit `3`, the "destination session not authenticated" row. `07`
            # gave `session status` that code directly; `12` is what needs the
            # clause, because a run that finds itself signed out has to say so
            # from wherever it noticed.
            fail(exc.detail or type(exc).__name__, ExitCode.NOT_AUTHENTICATED)
        except launcher.PortInUse as exc:
            # A browser failure that is nonetheless the operator's to fix by
            # closing something, so exit `2` and not `6`. Before the broader
            # BrowserError clause, which it is a subclass of.
            fail(exc.detail or type(exc).__name__)
        except BrowserError as exc:
            # Exit `6`, the "environment not ready" row: no browser installed,
            # a debug port that never opened, a CDP call that went unanswered.
            # `doctor` (`09`) is what an operator runs next.
            fail(exc.detail or type(exc).__name__, ExitCode.ENVIRONMENT)
        except HermesError as exc:
            # The same row, for the other half of the environment: Hermes missing,
            # too old, misconfigured, or killed at a deadline. Only `setup` and
            # `doctor` let one reach here — `12` reads a conversation's Hermes
            # failure from the result contract and records it per conversation
            # rather than ending the run on it.
            fail(exc.detail or type(exc).__name__, ExitCode.ENVIRONMENT)
        except ExportError as exc:
            # A malformed export is operator-fixable, not an internal error, and
            # exit `2` is the table's "usage or configuration error" row — the
            # same code `require_export` already uses for a path that is not
            # there. Only this category: `auth` and `browser` map to codes of
            # their own, and the slice that adds that behaviour adds its clause.
            fail(exc.detail or type(exc).__name__)
        except Exception as exc:
            _logger.exception("unhandled error", extra={"command": invoked_name(ctx)})
            # The type only. The detail belongs in the log, not on an operator's
            # terminal, because nothing guarantees it is content-free.
            print(
                f"internal error: {type(exc).__name__}",
                file=typer.get_text_stream("stderr"),
            )
            raise typer.Exit(ExitCode.INTERNAL) from exc


def _typer(**kwargs: Any) -> typer.Typer:
    """A Typer app with this project's output discipline applied."""
    return typer.Typer(
        add_completion=False,  # --install-completion is not in the spec's surface
        pretty_exceptions_enable=False,  # no rich tracebacks; see _RootGroup
        rich_markup_mode=None,  # plain click help formatting
        **kwargs,
    )


app = _typer(
    cls=_RootGroup, help="Migrate a Claude export into another Claude account."
)
session_app = _typer(help="Inspect or end the destination browser session.")
browser_app = _typer(help="Deterministic browser primitives Hermes calls.")

app.add_typer(session_app, name="session")
app.add_typer(browser_app, name="browser")


# --------------------------------------------------------------------------- #
# Global options
# --------------------------------------------------------------------------- #


def _version_callback(value: bool) -> None:
    if not value:
        return
    # Hardcoded, not derived from the invoked program name: `--version` output is
    # a golden string and `python -m dataporter` must not change it.
    print(f"{PROGRAM_NAME} {distribution_version()}")
    raise typer.Exit()


Workspace = Annotated[
    Path | None,
    typer.Option(
        "--workspace",
        metavar="PATH",
        help="Workspace directory. Defaults to ./migration.",
    ),
]
Verbose = Annotated[
    bool,
    typer.Option("--verbose", "-v", help="Log diagnostics to stderr."),
]
Quiet = Annotated[
    bool,
    typer.Option("--quiet", "-q", help="Suppress progress output on stdout."),
]
Version = Annotated[
    bool,
    typer.Option(
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Print the version and exit.",
    ),
]


@app.callback()
def main(
    ctx: typer.Context,
    workspace: Workspace = None,
    verbose: Verbose = False,
    quiet: Quiet = False,
    version: Version = False,
) -> None:
    """Migrate a Claude export into another Claude account, via Hermes."""
    log.configure_logging(verbose=verbose)
    try:
        settings = load_settings(workspace=workspace)
    except ConfigError as exc:
        fail(str(exc))
    ctx.obj = AppContext(settings=settings, verbose=verbose, quiet=quiet)
    _logger.debug(
        "start",
        extra={
            "command": ctx.invoked_subcommand or "",
            "workspace": str(settings.workspace),
        },
    )


# --------------------------------------------------------------------------- #
# Shared argument and option types
# --------------------------------------------------------------------------- #

Export = Annotated[
    str,
    typer.Argument(metavar="EXPORT", help="Path to the Claude data export."),
]
"""The *path* to an export, as typed. `export.Export` — the parsed thing — is
imported as `ParsedExport` above so the two cannot be confused here."""
Only = Annotated[
    list[str] | None,
    typer.Option(
        "--only",
        metavar="UUID",
        help="Limit to this conversation. Repeatable.",
    ),
]
JsonOutput = Annotated[
    bool,
    typer.Option("--json", help="Emit machine-readable JSON instead of text."),
]
Limit = Annotated[
    int | None,
    typer.Option(
        "--limit",
        metavar="N",
        # Not a literal default: `15` tells an explicit --limit 10 from an unset
        # flag falling back to run.max_conversations, and refuses the first one
        # above the ceiling without --all.
        help="Migrate at most N conversations. Defaults to the configured maximum.",
    ),
]
All = Annotated[
    bool,
    typer.Option(
        "--all",
        help="Lift the configured maximum on how many conversations one run may do.",
    ),
]
Delay = Annotated[
    float | None,
    typer.Option(
        "--delay",
        metavar="SECONDS",
        min=0,
        help="Seconds between conversations. Defaults to the configured pacing.",
    ),
]
MaxRetries = Annotated[
    int | None,
    typer.Option(
        "--max-retries",
        metavar="N",
        min=0,
        help="Extra attempts per conversation after the first. Defaults to config.",
    ),
]
Timeout = Annotated[
    float | None,
    typer.Option(
        "--timeout",
        metavar="SECONDS",
        min=0,
        help="Seconds one conversation's Hermes run may take. Defaults to config.",
    ),
]
"""§13's three flag-configurable parameters (`15`). `None` rather than a literal
default for the reason `--limit` is `None`: the effective value belongs to
`Settings`, and a default typed here would outrank an operator's `config.toml`.

`min=0` is about the *flag's* own domain — "how many more goes" and "how many
seconds" have no negative values — and it is here rather than only on the setting
so that the error names what the operator typed: `--max-retries` counts retries
and `retries.max_attempts` counts attempts, and a message about the second is a
message about a number they did not type. The settings fields carry their own
constraints as well, which is what refuses the same value arriving through
`HCM_…` or `config.toml`, and what catches `--timeout 0` — zero is in range for
a flag and not for a subprocess deadline. (Raised by Copilot in review on #24.)"""

PILOT_CHOOSES = (
    "--pilot chooses the conversations itself: drop --only, --limit and --all"
)
"""`20`'s usage error. The pilot selection is the experiment's design — ten
categories, in order — so a flag that would narrow, widen or reorder it is
refused rather than silently losing to it, whichever way round that went."""

TOO_MANY = "use --all to migrate more than {limit} conversations in one run"
"""`15`'s usage error. The ceiling is `run.max_conversations`, and it is named in
the message because it is configurable and the operator may not know it."""
AttachmentsDir = Annotated[
    Path | None,
    typer.Option(
        "--attachments-dir",
        metavar="DIR",
        help="Attachment bytes. Defaults to <workspace>/attachments.",
    ),
]
"""`01` gave this to `import` only. `05` gives it to `inspect` too: whether a file
is attachment class 2 or class 3 depends on it, and `inspect` is the command whose
job is to explain that."""


# --------------------------------------------------------------------------- #
# Selection, and the plan it produces
# --------------------------------------------------------------------------- #


def selected_conversations(
    export: ParsedExport, only: Sequence[str]
) -> list[Conversation]:
    """The conversations `--only` names, or all of them, in export order.

    Export order rather than the order the flags were typed: two runs of the same
    command must write the same files and print the same lines. Resolution — full
    uuid or `06`'s 8-character short id, and an unknown value as an error rather
    than as an empty selection — is `state.resolve_only`, so `seeds --only` and
    `import --only` accept exactly the same things.

    This is the selection for the commands that have no state to consult (`04`'s
    `seeds`). `import` uses `state.select`, which also reads what earlier runs
    recorded.
    """
    if not only:
        return list(export.conversations)
    wanted = set(state.resolve_only([item.uuid for item in export.conversations], only))
    return [item for item in export.conversations if item.uuid in wanted]


def selection_for(
    settings: Settings,
    *,
    only: Sequence[str],
    limit: int | None,
    all_conversations: bool = False,
    retry_failed: bool = False,
    retry_partial: bool = False,
    force: bool = False,
    skip_attachments: bool = False,
    pilot: Sequence[state.PilotChoice] = (),
) -> state.Selection:
    """The flags, as the record `06` selects from and `run.json` keeps.

    `--limit` is resolved here rather than in `state`: an unset flag means
    `run.max_conversations`, and it is the effective number — the one that shaped
    the run — that belongs in the record. The flag itself stays `None` in the
    signature so that `15` can tell an explicit `--limit 10` from a default.

    `15`'s ceiling is the point of that distinction. `run.max_conversations` is
    not only a default but a limit on what one invocation may do to an account,
    so a `--limit` above it is a usage error naming the flag that lifts it rather
    than a number quietly honoured. `--all` alone is no limit at all; `--all`
    with a `--limit` is that limit, because an operator who typed both has asked
    for a number and knows the ceiling exists.

    `pilot` is `20`'s record of *why* each conversation is in `only`, carried
    through unchanged: the selection is made before this is called, and nothing
    here re-derives it.
    """
    ceiling = settings.run.max_conversations
    if limit is None:
        effective = None if all_conversations else ceiling
    else:
        if limit > ceiling and not all_conversations:
            fail(TOO_MANY.format(limit=ceiling))
        effective = limit
    return state.Selection(
        only=list(only),
        limit=effective,
        retry_failed=retry_failed,
        retry_partial=retry_partial,
        force=force,
        skip_attachments=skip_attachments,
        pilot=list(pilot),
    )


def plan_for(
    ctx: typer.Context,
    export: ParsedExport,
    *,
    uuids: Sequence[str] | None = None,
    attachments_dir: Path | None = None,
    skip_attachments: bool = False,
) -> MigrationPlan:
    """Classify a parsed export, or the part of it a selection kept.

    The selection is applied *before* the plan is built, so what the dry run
    counts is what this run would do rather than what the export happens to
    contain. The fingerprint stays the export's: it identifies the file, not the
    subset of it somebody asked about.
    """
    settings = with_skip_attachments(
        with_attachments_dir(app_context(ctx).settings, attachments_dir),
        skip_attachments,
    )
    conversations = (
        list(export.conversations)
        if uuids is None
        else [item for item in export.conversations if item.uuid in set(uuids)]
    )
    return build_plan(
        export.model_copy(update={"conversations": conversations}), settings
    )


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def print_report(outcome: importing.RunSummary) -> None:
    """§16's block, last, whatever became of the run.

    Printed under `--quiet` for the reason `18`'s final block is: `-q` suppresses
    progress, and this is what the run amounts to. Printed after a run that
    stopped, too — a paused or circuit-broken run is the one an operator most
    needs the failure list of, and the numbers are true of the workspace either
    way.

    The blank line is this function's and not `19`'s: something is always on the
    screen above it — §10's final block at every verbosity — and `report` prints
    the same text with nothing above it at all.
    """
    if outcome.report is not None:
        print(f"\n{reporting.render(outcome.report)}", end="")


LOGIN_PROMPT = "Log in to Claude in the browser window that just opened."
SIGNED_IN = browser_session.SIGNED_IN
SIGNED_OUT = browser_session.SIGNED_OUT
"""`07`'s two answers, re-exported: `12` refuses to start on the second one, so
the string lives beside the probe that produces it."""


@app.command()
def login(ctx: typer.Context) -> None:
    """Open Claude in a dedicated browser profile and wait for sign-in."""
    settings = app_context(ctx).settings
    log.enable_run_log(settings.workspace)
    browser = launcher.launch(settings, probe.NEW_CHAT_URL)
    try:
        if not browser_session.signed_in(browser):
            # Printed rather than logged: it is an instruction to the person at
            # the keyboard, and it is the only thing this command asks of them.
            print(LOGIN_PROMPT)
            arrived = browser_session.wait_for_login(
                browser, timeout_s=settings.timeouts.login_s
            )
            if arrived is None:
                fail(
                    f"timed out after {settings.timeouts.login_s:g}s waiting for login",
                    ExitCode.NOT_AUTHENTICATED,
                )
        print(f"Logged in. Session stored in {settings.browser_profile_dir}/.")
    finally:
        # Always, on every path: Chrome writes its cookie jar and session store
        # out on exit, so a profile that is never closed can come back signed
        # out — and a browser left running would hold the next run's port.
        browser.close()


@app.command("import")
def import_cmd(
    ctx: typer.Context,
    export: Export,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Parse and report; change no account."),
    ] = False,
    limit: Limit = None,
    all_conversations: All = False,
    only: Only = None,
    delay: Delay = None,
    max_retries: MaxRetries = None,
    timeout: Timeout = None,
    retry_failed: Annotated[
        bool,
        typer.Option("--retry-failed", help="Include previously failed conversations."),
    ] = False,
    retry_partial: Annotated[
        bool,
        typer.Option(
            "--retry-partial", help="Include previously partial conversations."
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Migrate again even if already completed."),
    ] = False,
    skip_attachments: Annotated[
        bool,
        typer.Option("--skip-attachments", help="Do not upload attachments."),
    ] = False,
    attachments_dir: AttachmentsDir = None,
    force_unlock: Annotated[
        bool,
        typer.Option(
            "--force-unlock",
            help="Remove a workspace lock left behind by a process that is gone.",
        ),
    ] = False,
    pilot: Annotated[
        bool,
        typer.Option("--pilot", help="Run the controlled pilot selection."),
    ] = False,
) -> None:
    """Migrate conversations from an export into the destination account."""
    path = require_export(export)
    context = app_context(ctx)
    parsed: ParsedExport | None = None
    """The export, once, when `--pilot` has already had to read it."""
    choices: list[state.PilotChoice] = []
    if pilot:
        if only or limit is not None or all_conversations:
            # A selection flag beside a flag that *is* the selection: one of the
            # two would have to be ignored, and `12`'s rule about `--pilot` — a
            # flag that chooses cannot be inert — cuts both ways.
            fail(PILOT_CHOOSES)
        parsed = load_export(path)
        choices = piloting.choose(
            parsed,
            plan_for(
                ctx,
                parsed,
                attachments_dir=attachments_dir,
                skip_attachments=skip_attachments,
            ),
        )
        only = piloting.uuids(choices)
        limit = piloting.PILOT_LIMIT
        # Printed before anything is migrated, and even under `--quiet`: §18's
        # answers are only worth having if the conversations behind them were
        # chosen for a reason, and this block is that reason. It is on stdout
        # rather than in the log because `run.json` is where it is kept and an
        # operator is who it is for.
        print(piloting.block(choices), end="")
        if not only:
            # Nothing migratable in the whole export: `06`'s rule for an empty
            # selection, reached here rather than below so that a dry run says
            # it too.
            raise typer.Exit(ExitCode.NOTHING_TO_DO)
    if not dry_run:
        settings = with_pacing(
            with_skip_attachments(
                with_attachments_dir(context.settings, attachments_dir),
                skip_attachments,
            ),
            delay=delay,
            max_retries=max_retries,
            timeout=timeout,
        )
        log.enable_run_log(settings.workspace)
        outcome = importing.Importer(
            settings,
            progress=progress.Reporter(quiet=context.quiet),
            force_unlock=force_unlock,
        ).run(
            path,
            selection_for(
                settings,
                only=only or [],
                limit=limit,
                all_conversations=all_conversations,
                retry_failed=retry_failed,
                retry_partial=retry_partial,
                force=force,
                skip_attachments=skip_attachments,
                pilot=choices,
            ),
        )
        print_report(outcome)
        raise typer.Exit(outcome.exit_code)

    # Nothing below this line writes, and nothing below it is allowed to: no run
    # log, so not even `<workspace>/logs/` comes into existence. §9 says no Claude
    # account is modified by a dry run; a workspace appearing next to the export
    # is the local half of the same promise. Reading `06`'s state is still fair —
    # what a run *would* do depends on what earlier runs already did.
    settings = context.settings
    parsed = parsed if parsed is not None else load_export(path)
    store = state.StateStore(settings.workspace)
    store.check_export(parsed.fingerprint)
    chosen = state.select(
        [item.uuid for item in parsed.conversations],
        store.load(),
        selection_for(
            settings,
            only=only or [],
            limit=limit,
            all_conversations=all_conversations,
            retry_failed=retry_failed,
            retry_partial=retry_partial,
            force=force,
            skip_attachments=skip_attachments,
            pilot=choices,
        ),
    )
    if not chosen:
        # `06`'s rule, and the one `seeds` already follows: an empty selection is
        # exit `4`, not a block of zeros that reads like a finished run.
        raise typer.Exit(ExitCode.NOTHING_TO_DO)
    plan = plan_for(
        ctx,
        parsed,
        uuids=chosen,
        attachments_dir=attachments_dir,
        skip_attachments=skip_attachments,
    )
    # Printed even under `--quiet`: `-q` suppresses progress, and this block is
    # the command's whole result rather than a report of its progress.
    print(summary.dry_run_report(plan.totals), end="")


@app.command("inspect")
def inspect_cmd(
    ctx: typer.Context,
    export: Export,
    attachments_dir: AttachmentsDir = None,
    json_output: JsonOutput = False,
) -> None:
    """Report what an export contains and what can be migrated."""
    path = require_export(export)
    plan = plan_for(ctx, load_export(path), attachments_dir=attachments_dir)
    if json_output:
        # The plan itself, and nothing else on stdout: this is what `12` and `19`
        # read, so a header line would be a header line in somebody's `jq`.
        print(plan.model_dump_json(indent=2))
        return
    # An empty export prints a block of zeros rather than exiting `4`: `inspect`
    # answers a question about a file, and "it contains nothing" is the answer,
    # not a refusal to run.
    print(summary.inspect_report(plan), end="")


@app.command()
def seeds(
    ctx: typer.Context,
    export: Export,
    only: Only = None,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out", metavar="DIR", help="Write seeds here instead of the workspace."
        ),
    ] = None,
) -> None:
    """Generate migration seeds without touching a browser."""
    path = require_export(export)
    context = app_context(ctx)
    root = out if out is not None else context.settings.seeds_dir
    log.enable_run_log(context.settings.workspace)

    conversations = selected_conversations(load_export(path), only or [])
    generator = seeding.SeedGenerator(context.settings)
    written = 0
    for outcome in generator.seeds(conversations):
        if outcome.seed is None:
            # stderr, not stdout: stdout is one line per *written* seed, and an
            # operator who asked for one conversation by uuid is owed the reason
            # nothing appeared. `05` is where the full accounting lives.
            print(
                # The short id is the head of a uuid the export chose, and a
                # skipped conversation is the one case where that uuid may be
                # malformed. One line per conversation, whatever it contains.
                f"skipped {log.safe_token(outcome.short_id)}: {outcome.reason}",
                file=typer.get_text_stream("stderr"),
            )
            continue
        seeding.write_seed(outcome.seed, root)
        written += 1
        if not context.quiet:
            print(
                f"{outcome.short_id}  parts={len(outcome.seed.chunks)}  "
                f"chars={outcome.seed.total_chars}"
            )
    if not written:
        raise typer.Exit(ExitCode.NOTHING_TO_DO)


@app.command()
def status(ctx: typer.Context, json_output: JsonOutput = False) -> None:
    """Show migration progress recorded in the workspace."""
    store = state.StateStore(app_context(ctx).settings.workspace)
    # Read before anything is printed, and on both paths: this is where a
    # workspace written by a build with a different state schema stops the
    # command instead of being reported with half its numbers missing.
    run = store.run()
    migration = store.load()
    if json_output:
        # `state.json` as it is on disk, plus the counters that live next door in
        # `run.json`. A workspace nothing has run in yet is an empty object and
        # four zeros, not an error: `status` answers a question, and "nothing has
        # happened here" is an answer.
        payload = {
            "state": migration.model_dump(mode="json"),
            "counters": {**state.status_counts(migration), **run.counters()},
        }
        print(json.dumps(payload, indent=2))
        return
    # Printed even under `--quiet`, for the reason the dry-run block is: `-q`
    # suppresses progress, and this is the command's whole result. No bar: `18`
    # draws one while a run moves, and a picture that is redrawn once says
    # nothing the numbers under it do not.
    print(summary.status_report(migration), end="")


@app.command()
def resume(ctx: typer.Context) -> None:
    """Continue a migration that paused for human intervention."""
    context = app_context(ctx)
    settings = context.settings
    log.enable_run_log(settings.workspace)
    try:
        outcome = importing.Importer(
            settings, progress=progress.Reporter(quiet=context.quiet)
        ).resume()
    except importing.NothingToResume:
        # Not an error, so no `error:` and no stderr: `resume` was asked whether
        # there was anything to continue and the answer was no. Exit `4` is the
        # same "nothing to do" the other commands use for an empty selection.
        print(importing.NOTHING_TO_RESUME)
        raise typer.Exit(ExitCode.NOTHING_TO_DO) from None
    print_report(outcome)
    raise typer.Exit(outcome.exit_code)


def verified(
    settings: Settings,
    store: state.StateStore,
    wanted: Sequence[tuple[str, verifying.Expected]],
) -> int:
    """Re-read every chosen chat, print a line each, and return the failures.

    The browser is opened here and not by an `Importer`: `17`'s `verify` runs
    without Hermes at all — no profile, no subprocess, no model — because the
    whole point of it is to check the account rather than to ask the thing that
    wrote to the account what it did.
    """
    # `launch` adopts the browser already on the port when it is ours, so a
    # `verify` run beside a window the operator left open reuses it. `12` opens
    # one the same way, and the rule for closing it is the same rule.
    browser = launcher.launch(settings, probe.NEW_CHAT_URL)
    failures = 0
    try:
        if not browser_session.signed_in(browser):
            # Exit `3`: a signed-out session makes every chat unreadable, and
            # reporting a hundred failed verifications would bury the one fact
            # that matters.
            raise AuthError(detail=SIGNED_OUT)
        verifier = verifying.Verifier(settings, browser.client)
        for uuid, expected in wanted:
            found = verifier.verify(expected)
            verifying.record(store, uuid, found)
            failures += 0 if found.ok else 1
            # Printed even under `--quiet`, for the reason `status`'s block is:
            # `-q` suppresses progress, and these lines are the whole result.
            print(found.line())
    finally:
        # A browser this command started is one it closes; one that was already
        # running belongs to whoever started it — `12`'s rule, and `07`'s flag.
        if not browser.adopted:
            browser.close()
    return failures


@app.command()
def verify(ctx: typer.Context, only: Only = None) -> None:
    """Check that migrated conversations exist in the destination account."""
    settings = app_context(ctx).settings
    log.enable_run_log(settings.workspace)
    store = state.StateStore(settings.workspace)
    # Read before anything is printed, like `status`: a workspace written by a
    # build with a different state schema stops the command here.
    store.run()
    wanted = list(verifying.verifiable(settings, store.load()))
    if only:
        chosen = set(state.resolve_only([uuid for uuid, _ in wanted], only))
        wanted = [item for item in wanted if item[0] in chosen]
    if not wanted:
        # Nothing migrated, or nothing selected. Exit `4` rather than the `0`
        # that "everything verified" would give it, for `06`'s reason: an empty
        # selection is not a success.
        raise typer.Exit(ExitCode.NOTHING_TO_DO)
    # Under the lock: this writes `state.json`, and a `verify` racing an `import`
    # would overwrite the status of a conversation being migrated as it reads it.
    lock = state.WorkspaceLock(settings.workspace)
    lock.acquire()
    try:
        failures = verified(settings, store, wanted)
    finally:
        lock.release()
    raise typer.Exit(ExitCode.FAILED if failures else ExitCode.OK)


def probed(
    settings: Settings, wanted: Sequence[tuple[str, state.ConversationState]]
) -> int:
    """Ask every chosen chat `20`'s question, print a line each, count the misses.

    The browser is opened here for the reason `verified` opens one: the probe is
    a question about the account, so the command that asks it is the command that
    proves the account is signed in. Hermes is what drives the page — `08`'s
    helpers insert the question and wait for the answer, and an agent is what
    finds the composer — so this is `verify`'s shape with `12`'s subprocess in
    the middle.

    Every answer is written as it arrives rather than at the end: a probe run is
    ten Hermes tasks and a minute each, and a run interrupted at the seventh
    should leave six replies rather than none.
    """
    browser = launcher.launch(settings, probe.NEW_CHAT_URL)
    asking = following.Prober(settings)
    file = following.read(settings)
    missing = 0
    try:
        if not browser_session.signed_in(browser):
            raise AuthError(detail=SIGNED_OUT)
        for position, (uuid, entry) in enumerate(wanted):
            answer = asking.ask(uuid, entry)
            file = file.replace(answer)
            following.write(settings, file)
            missing += 0 if answer.answered else 1
            # Printed even under `--quiet`, like `verify`'s lines: `-q`
            # suppresses progress, and these lines are the whole result.
            print(answer.line())
            if position + 1 < len(wanted):
                # §13's gap between conversations, for §13's reason: this is one
                # more message into a real account, sent by the same browser.
                importing.pause(settings.pacing.delay_between_conversations_s)
    finally:
        # A browser this command started is one it closes; one that was already
        # running belongs to whoever started it (`07`, `17`).
        if not browser.adopted:
            browser.close()
    return missing


@app.command()
def followup(ctx: typer.Context, only: Only = None) -> None:
    """Ask each migrated chat one follow-up question (the pilot's probe)."""
    settings = app_context(ctx).settings
    log.enable_run_log(settings.workspace)
    store = state.StateStore(settings.workspace)
    # Read before anything is printed, like `status` and `verify`: a workspace
    # written by a build with a different state schema stops the command here.
    store.run()
    wanted = list(following.probeable(store.load()))
    if only:
        chosen = set(state.resolve_only([uuid for uuid, _ in wanted], only))
        wanted = [item for item in wanted if item[0] in chosen]
    if not wanted:
        # Nothing completed, or nothing selected. Exit `4`, `06`'s rule for an
        # empty selection — a probe of no conversations is not a finished
        # experiment.
        raise typer.Exit(ExitCode.NOTHING_TO_DO)
    # The same local half of `doctor` a run makes before it starts (`12`): every
    # probe is a Hermes task, so a machine with no Hermes would otherwise report
    # ten identical failures instead of the one fact behind them.
    failure = hermes_doctor.local_failure(settings)
    if failure is not None:
        fail(f"{failure.label}: {failure.detail}", ExitCode.ENVIRONMENT)
    # Under the lock: this writes `<workspace>/pilot/`, and a probe racing an
    # `import` would ask a question in a chat that run is still writing into.
    lock = state.WorkspaceLock(settings.workspace)
    lock.acquire()
    try:
        missing = probed(settings, wanted)
    finally:
        lock.release()
    raise typer.Exit(ExitCode.FAILED if missing else ExitCode.OK)


@app.command()
def judge(ctx: typer.Context, only: Only = None) -> None:
    """Grade the follow-up replies with a model (the `judge` extra)."""
    settings = app_context(ctx).settings
    log.enable_run_log(settings.workspace)
    # The lock is taken before `probes.json` is read, and not only around the
    # writes: this command reads the file, decides there is nothing to do, and
    # writes back into it, and a `followup` filling it in the middle of that
    # would be a judge reporting "nothing to grade" about replies that were
    # arriving as it looked. A busy workspace is exit `2` and says who holds it,
    # which is the honest answer to "grade these". (Raised by Copilot in review
    # on #29.)
    lock = state.WorkspaceLock(settings.workspace)
    lock.acquire()
    try:
        file = following.read(settings)
        wanted = list(file.probes)
        if only:
            chosen = set(
                state.resolve_only([item.conversation_uuid for item in wanted], only)
            )
            wanted = [item for item in wanted if item.conversation_uuid in chosen]
        if not wanted:
            # No probe file, or nothing selected in it. Exit `4` rather than `0`:
            # `followup` is what produces the replies, and grading none of them
            # is not a graded experiment.
            raise typer.Exit(ExitCode.NOTHING_TO_DO)
        try:
            grade = judging.grader(settings)
        except judging.JudgeError as exc:
            # Exit `6`, the environment row: the extra is not installed, or the
            # key the judge would authenticate with is not in the environment.
            fail(str(exc), ExitCode.ENVIRONMENT)
        for item in wanted:
            verdict = judging.verdict_for(settings, item, grade=grade)
            file = file.replace(item.model_copy(update={"verdict": verdict}))
            following.write(settings, file)
            # The score, never the reason (§10). Even under `--quiet`.
            print(judging.line(item, verdict))
    finally:
        lock.release()


@app.command()
def report(ctx: typer.Context, json_output: JsonOutput = False) -> None:
    """Print the end-of-migration report."""
    workspace = app_context(ctx).settings.workspace
    # Reads `state.json`, `run.json`, `plan.json` and `logs/actions.jsonl`, and
    # writes nothing: no lock, no browser, no Hermes. A report is a question
    # about a workspace, and one that rewrote what it was asked to read could
    # not be run beside a migration that is still going — `import` is what
    # writes `report.json`, at the end of a run and under the lock.
    built = reporting.build(workspace)
    if json_output:
        print(built.model_dump_json(indent=2))
        return
    # Printed even under `--quiet`, like `status`: `-q` suppresses progress, and
    # this block is the command's whole result.
    print(reporting.render(built), end="")


@app.command()
def setup(ctx: typer.Context) -> None:
    """Create the Hermes profile and install the migration skill."""
    settings = app_context(ctx).settings
    report = hermes_profile.run_setup(settings)
    for line in report.lines():
        print(line)
    # Said on every run, not only the first: the transcripts accumulate, and an
    # operator who read this once during setup has forgotten it by `21`.
    print(hermes_profile.purge_hint(settings))
    if not report.model:
        # `09`'s exact words. A profile with no model cannot run a task, so there
        # is nothing for `doctor` to check yet and this is exit `6` like the rest
        # of "the environment is not ready".
        fail(
            hermes_profile.NO_MODEL.format(profile=settings.hermes.profile),
            ExitCode.ENVIRONMENT,
        )
    print(f"Next: {PROGRAM_NAME} doctor")


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Check that Hermes and Chrome are present and configured."""
    settings = app_context(ctx).settings
    log.enable_run_log(settings.workspace)
    # First, and unconditionally: §13's numbers are what this invocation would
    # run with, and an operator whose chain is broken still wants to see them.
    print(hermes_doctor.pacing_check(settings).render())
    failed = False
    # `closing` rather than a plain `for`: the generator launches a browser and
    # closes it in a `finally`, and leaving that to garbage collection would leave
    # a Chrome holding the debug port for as long as the interpreter felt like it.
    with closing(hermes_doctor.checks(settings)) as stream:
        for check in stream:
            # One line at a time, printed as it is produced: the two Hermes checks
            # take a minute each, and ten lines at the end reads like a hang.
            print(check.render())
            if not check.ok:
                failed = True
                break
    if failed:
        raise typer.Exit(ExitCode.ENVIRONMENT)


@session_app.command("status")
def session_status(ctx: typer.Context) -> None:
    """Report whether the destination account is signed in."""
    settings = app_context(ctx).settings
    client = cdp.CdpClient(
        port=settings.browser.cdp_port, timeout=settings.timeouts.cdp_call_s
    )
    # Raises `PortInUse` when the port answers and the browser on it is not
    # ours, which is the right answer to "what is my session doing" as well.
    running = launcher.adopt(client, settings.browser_profile_dir)
    if running is None and not settings.browser_profile_dir.exists():
        # No profile and no browser: there is nothing that could be signed in,
        # and starting Chrome to be told so would cost ten seconds and a window.
        print(SIGNED_OUT)
        raise typer.Exit(ExitCode.NOT_AUTHENTICATED)

    browser = running or launcher.launch(settings, probe.NEW_CHAT_URL)
    try:
        answer = browser_session.signed_in(browser)
    finally:
        # A browser this command started is a browser this command cleans up;
        # one that was already running belongs to whoever started it.
        if running is None:
            browser.close()
    print(SIGNED_IN if answer else SIGNED_OUT)
    if not answer:
        raise typer.Exit(ExitCode.NOT_AUTHENTICATED)


@session_app.command("logout")
def session_logout(ctx: typer.Context) -> None:
    """Sign the destination account out and clear the browser profile."""
    settings = app_context(ctx).settings
    removed = browser_session.remove_profile(settings)
    # Local only, and said so: the account itself is untouched, and a session on
    # another machine is not ended by this.
    print(
        f"Removed {settings.browser_profile_dir}/."
        if removed
        else f"Nothing to remove: {settings.browser_profile_dir}/ does not exist."
    )


# --------------------------------------------------------------------------- #
# The browser helpers Hermes calls (`08`)
# --------------------------------------------------------------------------- #

TargetOption = Annotated[
    str | None,
    typer.Option(
        "--target",
        metavar="ID",
        help="Drive this CDP target instead of the only claude.ai tab.",
    ),
]
ExpectOption = Annotated[
    list[str] | None,
    typer.Option(
        "--expect",
        metavar="TEXT",
        help="Report whether the last message contains TEXT. Repeatable.",
    ),
]


def emit_helper(
    ctx: typer.Context,
    name: str,
    work: Callable[[cdp.CdpClient, Settings], browser_helpers.Outcome],
) -> NoReturn:
    """Run one helper, print its object and exit with its code.

    One `print` and nothing else on stdout, ever: Hermes parses the line, and
    `19` reads the workspace. Diagnostics go to stderr under `--verbose` like
    everywhere else, and are suppressed by default here for the same reason
    `--quiet` cannot suppress this line — the object *is* the result.
    """
    emission = browser_helpers.run(app_context(ctx).settings, name, work)
    print(emission.text)
    raise typer.Exit(emission.exit_code)


@browser_app.command("probe")
def browser_probe(
    ctx: typer.Context,
    target: TargetOption = None,
    expect: ExpectOption = None,
    messages: Annotated[
        bool,
        typer.Option(
            "--messages",
            help="Report every message on the page, not only the last one.",
        ),
    ] = False,
    expect_title: Annotated[
        str | None,
        typer.Option(
            "--expect-title",
            metavar="TEXT",
            # Whether the title *is* TEXT, never what the title is: §10 keeps a
            # chat's name off stdout, and `17` needs an answer rather than a name.
            help="Report whether the chat's title is TEXT.",
        ),
    ] = None,
) -> None:
    """Report the current page state as JSON."""
    emit_helper(
        ctx,
        "probe",
        lambda client, settings: browser_helpers.probe_page(
            client,
            settings,
            target=target,
            expect=tuple(expect or ()),
            messages=messages,
            expect_title=expect_title,
        ),
    )


@browser_app.command("paste")
def browser_paste(
    ctx: typer.Context,
    seed: Annotated[
        Path,
        typer.Option("--seed", metavar="PATH", help="The seed part to insert."),
    ],
    method: Annotated[
        browser_helpers.PasteMethod,
        typer.Option("--method", help="How to insert the text."),
    ] = browser_helpers.PasteMethod.INSERT_TEXT,
    append: Annotated[
        bool,
        typer.Option("--append", help="Insert after what the composer holds."),
    ] = False,
    target: TargetOption = None,
) -> None:
    """Insert a seed into the composer byte for byte."""
    emit_helper(
        ctx,
        "paste",
        lambda client, settings: browser_helpers.paste_seed(
            client, settings, seed=seed, method=method, append=append, target=target
        ),
    )


@browser_app.command("attach")
def browser_attach(
    ctx: typer.Context,
    file: Annotated[
        Path,
        typer.Option("--file", metavar="PATH", help="The file to upload."),
    ],
    target: TargetOption = None,
) -> None:
    """Upload a file through the composer."""
    emit_helper(
        ctx,
        "attach",
        lambda client, settings: browser_helpers.attach_file(
            client, settings, file=file, target=target
        ),
    )


@browser_app.command("attachments")
def browser_attachments(
    ctx: typer.Context,
    file: Annotated[
        list[Path] | None,
        typer.Option(
            "--file",
            metavar="PATH",
            help="A file that must have a chip. Repeatable.",
        ),
    ] = None,
    target: TargetOption = None,
) -> None:
    """Check that every named file is attached to the message being composed."""
    emit_helper(
        ctx,
        "attachments",
        lambda client, settings: browser_helpers.attached_files(
            client, settings, files=tuple(file or ()), target=target
        ),
    )


@browser_app.command("await-response")
def browser_await_response(
    ctx: typer.Context,
    timeout: Annotated[
        float | None,
        typer.Option(
            "--timeout",
            metavar="S",
            # Not a literal default, for the reason `--limit` is not one: the
            # configured value is the default, and it is configurable.
            help="Seconds to wait. Defaults to the configured response timeout.",
        ),
    ] = None,
    expect: ExpectOption = None,
    target: TargetOption = None,
) -> None:
    """Wait until generation completes."""
    emit_helper(
        ctx,
        "await-response",
        lambda client, settings: browser_helpers.await_response(
            client,
            settings,
            timeout=timeout,
            expect=tuple(expect or ()),
            target=target,
        ),
    )


@browser_app.command("close-extra-tabs")
def browser_close_extra_tabs(ctx: typer.Context) -> None:
    """Close blank and duplicate new-chat tabs. Never a conversation."""
    emit_helper(
        ctx,
        "close-extra-tabs",
        lambda client, settings: browser_helpers.close_extra_tabs(client, settings),
    )
