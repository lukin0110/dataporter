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
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from typer.core import TyperGroup

from dataporter import log
from dataporter import seed as seeding
from dataporter.config import ConfigError, Settings, load_settings
from dataporter.errors import ExportError
from dataporter.exit_codes import ExitCode
from dataporter.export import Conversation, load_export
from dataporter.export import Export as ParsedExport

PROGRAM_NAME = "hermes-claude-migrate"

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


def not_implemented(ctx: typer.Context) -> NoReturn:
    """Exit `69`. Every command body in this slice ends here."""
    print(
        f"not implemented in this build: {invoked_name(ctx)}",
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


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


@app.command()
def login(ctx: typer.Context) -> None:
    """Open Claude in a dedicated browser profile and wait for sign-in."""
    not_implemented(ctx)


@app.command("import")
def import_cmd(
    ctx: typer.Context,
    export: Export,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Parse and report; change no account."),
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            metavar="N",
            # Not a literal default: `15` must be able to tell an explicit
            # --limit 10 from an unset flag falling back to run.max_conversations.
            help="Migrate at most N conversations. Defaults to the configured maximum.",
        ),
    ] = None,
    only: Only = None,
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
    attachments_dir: Annotated[
        Path | None,
        typer.Option(
            "--attachments-dir",
            metavar="DIR",
            help="Attachment bytes. Defaults to <workspace>/attachments.",
        ),
    ] = None,
    pilot: Annotated[
        bool,
        typer.Option("--pilot", help="Run the controlled pilot selection."),
    ] = False,
) -> None:
    """Migrate conversations from an export into the destination account."""
    require_export(export)
    not_implemented(ctx)


@app.command("inspect")
def inspect_cmd(
    ctx: typer.Context, export: Export, json_output: JsonOutput = False
) -> None:
    """Report what an export contains and what can be migrated."""
    require_export(export)
    not_implemented(ctx)


def selected_conversations(
    export: ParsedExport, only: Sequence[str]
) -> list[Conversation]:
    """The conversations `--only` names, or all of them, in export order.

    Export order rather than the order the flags were typed: two runs of the same
    command must write the same files and print the same lines, and `06` will
    make selection its own concern anyway. An unknown uuid is an operator
    mistake, not an empty selection — silently doing nothing is how a typo turns
    into "the tool skipped my conversation".
    """
    if not only:
        return list(export.conversations)
    wanted = set(only)
    known = {conversation.uuid for conversation in export.conversations}
    missing = [uuid for uuid in only if uuid not in known]
    if missing:
        fail(f"conversation not in export: {missing[0]}")
    return [item for item in export.conversations if item.uuid in wanted]


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
                f"skipped {outcome.short_id}: {outcome.reason}",
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
    not_implemented(ctx)


@app.command()
def resume(ctx: typer.Context) -> None:
    """Continue a migration that paused for human intervention."""
    not_implemented(ctx)


@app.command()
def verify(ctx: typer.Context, only: Only = None) -> None:
    """Check that migrated conversations exist in the destination account."""
    not_implemented(ctx)


@app.command()
def report(ctx: typer.Context, json_output: JsonOutput = False) -> None:
    """Print the end-of-migration report."""
    not_implemented(ctx)


@app.command()
def setup(ctx: typer.Context) -> None:
    """Create the Hermes profile and install the migration skill."""
    not_implemented(ctx)


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Check that Hermes and Chrome are present and configured."""
    not_implemented(ctx)


@session_app.command("status")
def session_status(ctx: typer.Context) -> None:
    """Report whether the destination account is signed in."""
    not_implemented(ctx)


@session_app.command("logout")
def session_logout(ctx: typer.Context) -> None:
    """Sign the destination account out and clear the browser profile."""
    not_implemented(ctx)


@browser_app.command("probe")
def browser_probe(ctx: typer.Context) -> None:
    """Report the current page state as JSON."""
    not_implemented(ctx)


@browser_app.command("paste")
def browser_paste(ctx: typer.Context) -> None:
    """Insert a seed into the composer byte for byte."""
    not_implemented(ctx)


@browser_app.command("attach")
def browser_attach(ctx: typer.Context) -> None:
    """Upload a file through the composer."""
    not_implemented(ctx)


@browser_app.command("await-response")
def browser_await_response(ctx: typer.Context) -> None:
    """Wait until generation completes."""
    not_implemented(ctx)


@browser_app.command("close-extra-tabs")
def browser_close_extra_tabs(ctx: typer.Context) -> None:
    """Close every tab but the one being driven."""
    not_implemented(ctx)
