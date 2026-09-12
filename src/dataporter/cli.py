"""The command surface.

Every command in `specs/impl/01-foundation.md` is registered here so that `--help`
is stable from the first release and later slices fill in behaviour rather than
rename things. Nothing migrates anything yet: an unimplemented command exits `69`.

Output is plain `print` — no colour, no `rich`, no completion options — because
§9, §10 and §16 of the brief are golden strings and terminal decoration would break
byte comparison. Errors go to stderr, always, since stdout is spoken for: `18` owns
the progress block and `08`'s helpers print exactly one JSON object there.

`23` made this file an interface and nothing more. Every command is one shape:
parse the flags, take the settings the root callback resolved, call the one
library function that owns the command — `browser.session.login`,
`importer.import_command`, `verify.verify_all` — hand it a `console.Terminal` for
its lines, and exit with the code it returns. No loop, no branch on the
workspace, no browser and no lock is opened here, so a Python caller can do
everything this file does by calling the same functions with a
`console.Collected` instead.
"""

import importlib.metadata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from typer.core import TyperGroup

from dataporter import PROGRAM_NAME, console, log
from dataporter import followup as following
from dataporter import importer as importing
from dataporter import judge as judging
from dataporter import report as reporting
from dataporter import seed as seeding
from dataporter import selection as selecting
from dataporter import verify as verifying
from dataporter.browser import cdp
from dataporter.browser import helpers as browser_helpers
from dataporter.browser import session as browser_session
from dataporter.config import ConfigError, Settings, load_settings
from dataporter.errors import (
    AuthError,
    BrowserError,
    ExportError,
    HermesError,
    UsageError,
)
from dataporter.exit_codes import ExitCode
from dataporter.hermes import doctor as hermes_doctor
from dataporter.hermes import profile as hermes_profile

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


def finish(outcome: console.HasExitCode) -> NoReturn:
    """Exit with the code an operation came back with. Its lines are already out."""
    raise typer.Exit(outcome.exit_code)


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


def app_context(ctx: typer.Context) -> AppContext:
    """The resolved global options. Later slices read settings from here."""
    obj = ctx.find_object(AppContext)
    if obj is None:  # pragma: no cover - the root callback always sets it
        raise RuntimeError("application context was not initialised")
    return obj


def settings_of(ctx: typer.Context) -> Settings:
    return app_context(ctx).settings


def distribution_version() -> str:
    try:
        return importlib.metadata.version("dataporter")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover
        return "0.0.0+unknown"


class _RootGroup(TyperGroup):
    """Turns an unhandled exception into exit `70` instead of a traceback.

    This class is the whole of the CLI's knowledge of exit codes for errors: an
    operation raises, and the clause below that names its class prints
    `error: <detail>` and exits with the row of `01`'s table that class belongs
    to. A code an operation *returns* is `finish`'s, and needs no clause.
    """

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
        except UsageError as exc:
            # `23`: two flags that cannot both be honoured, an export that is not
            # there. The same row as a bad `config.toml`, and the same shape.
            fail(str(exc))
        except state_error() as exc:
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
        except port_in_use() as exc:
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
            # too old, misconfigured, or killed at a deadline. Only `setup`,
            # `doctor` and `followup` let one reach here — `12` reads a
            # conversation's Hermes failure from the result contract and records
            # it per conversation rather than ending the run on it.
            fail(exc.detail or type(exc).__name__, ExitCode.ENVIRONMENT)
        except judging.JudgeError as exc:
            # The same row again: the `judge` extra is not installed, or the key
            # the judge would authenticate with is not in the environment.
            fail(str(exc), ExitCode.ENVIRONMENT)
        except ExportError as exc:
            # A malformed export is operator-fixable, not an internal error, and
            # exit `2` is the table's "usage or configuration error" row — the
            # same code an export path that is not there already uses. Only this
            # category: `auth` and `browser` map to codes of their own.
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


def state_error() -> type[Exception]:
    """`state.StateError`, imported here so that this file's own import list stays
    the statement `23` makes: nothing in it opens a workspace."""
    from dataporter.state import StateError

    return StateError


def port_in_use() -> type[BrowserError]:
    """`launcher.PortInUse`, for the reason `state_error` is a function."""
    from dataporter.browser.launcher import PortInUse

    return PortInUse


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
NonInteractive = Annotated[
    bool,
    typer.Option(
        "--non-interactive",
        help="Never wait for a person: headless Chrome, sign in from credentials.",
    ),
]
Email = Annotated[
    str | None,
    typer.Option(
        "--email",
        metavar="EMAIL",
        help="The destination account's email, for --non-interactive.",
    ),
]
PasswordFile = Annotated[
    Path | None,
    typer.Option(
        "--password-file",
        metavar="PATH",
        # A file and never a value: a value would be in `ps` and the shell's
        # history, which is exactly where an unattended run's host keeps them.
        help="A file whose first line is the account password (--non-interactive).",
    ),
]
"""`24`'s three global options. The environment spells them `HCM_NON_INTERACTIVE`,
`HCM_AUTH__EMAIL` and `HCM_AUTH__PASSWORD`; `config.toml` may carry none of them."""


@app.callback()
def main(
    ctx: typer.Context,
    workspace: Workspace = None,
    verbose: Verbose = False,
    quiet: Quiet = False,
    version: Version = False,
    non_interactive: NonInteractive = False,
    email: Email = None,
    password_file: PasswordFile = None,
) -> None:
    """Migrate a Claude export into another Claude account, via Hermes."""
    log.configure_logging(verbose=verbose)
    try:
        settings = load_settings(
            workspace=workspace,
            non_interactive=non_interactive,
            email=email,
            password_file=password_file,
        )
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
"""The *path* to an export, as typed; `selection.export_path` is what checks it."""
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
# Commands
# --------------------------------------------------------------------------- #


@app.command()
def login(ctx: typer.Context) -> None:
    """Open Claude in a dedicated browser profile and wait for sign-in."""
    finish(browser_session.login(settings_of(ctx), sink=console.Terminal()))


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
    context = app_context(ctx)
    finish(
        importing.import_command(
            context.settings,
            importing.ImportRequest(
                export=export,
                dry_run=dry_run,
                limit=limit,
                all_conversations=all_conversations,
                only=only or (),
                delay=delay,
                max_retries=max_retries,
                timeout=timeout,
                retry_failed=retry_failed,
                retry_partial=retry_partial,
                force=force,
                skip_attachments=skip_attachments,
                attachments_dir=attachments_dir,
                force_unlock=force_unlock,
                pilot=pilot,
            ),
            quiet=context.quiet,
            sink=console.Terminal(),
        )
    )


@app.command("inspect")
def inspect_cmd(
    ctx: typer.Context,
    export: Export,
    attachments_dir: AttachmentsDir = None,
    json_output: JsonOutput = False,
) -> None:
    """Report what an export contains and what can be migrated."""
    finish(
        selecting.inspect_export(
            settings_of(ctx),
            export,
            attachments_dir=attachments_dir,
            json_output=json_output,
            sink=console.Terminal(),
        )
    )


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
    context = app_context(ctx)
    finish(
        seeding.write_seeds(
            context.settings,
            export,
            only=only or (),
            out=out,
            quiet=context.quiet,
            sink=console.Terminal(),
        )
    )


@app.command()
def status(ctx: typer.Context, json_output: JsonOutput = False) -> None:
    """Show migration progress recorded in the workspace."""
    finish(
        reporting.status(
            settings_of(ctx), json_output=json_output, sink=console.Terminal()
        )
    )


@app.command()
def resume(ctx: typer.Context) -> None:
    """Continue a migration that paused for human intervention."""
    context = app_context(ctx)
    finish(
        importing.resume_command(
            context.settings, quiet=context.quiet, sink=console.Terminal()
        )
    )


@app.command()
def verify(ctx: typer.Context, only: Only = None) -> None:
    """Check that migrated conversations exist in the destination account."""
    finish(
        verifying.verify_all(settings_of(ctx), only=only or (), sink=console.Terminal())
    )


@app.command()
def followup(ctx: typer.Context, only: Only = None) -> None:
    """Ask each migrated chat one follow-up question (the pilot's probe)."""
    finish(
        following.ask_all(settings_of(ctx), only=only or (), sink=console.Terminal())
    )


@app.command()
def judge(ctx: typer.Context, only: Only = None) -> None:
    """Grade the follow-up replies with a model (the `judge` extra)."""
    finish(
        judging.judge_all(settings_of(ctx), only=only or (), sink=console.Terminal())
    )


@app.command()
def report(ctx: typer.Context, json_output: JsonOutput = False) -> None:
    """Print the end-of-migration report."""
    finish(
        reporting.show(
            settings_of(ctx), json_output=json_output, sink=console.Terminal()
        )
    )


@app.command()
def setup(ctx: typer.Context) -> None:
    """Create the Hermes profile and install the migration skill."""
    finish(hermes_profile.setup(settings_of(ctx), sink=console.Terminal()))


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Check that Hermes and Chrome are present and configured."""
    finish(hermes_doctor.run_doctor(settings_of(ctx), sink=console.Terminal()))


@session_app.command("status")
def session_status(ctx: typer.Context) -> None:
    """Report whether the destination account is signed in."""
    finish(browser_session.status(settings_of(ctx), sink=console.Terminal()))


@session_app.command("logout")
def session_logout(ctx: typer.Context) -> None:
    """Sign the destination account out and clear the browser profile."""
    finish(browser_session.logout(settings_of(ctx), sink=console.Terminal()))


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
