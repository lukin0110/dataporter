"""One object for the five commands a host project actually reaches for (`68`).

`23` made every command's body a library function in the module that owns its
domain, and that table is still the whole API: `browser.session.login`,
`extract.fetch`, `hermes.doctor.run_doctor`. What it does not do is carry the
two things every one of those calls needs first — a `Settings`, and the source
and account a command is *about* — so a caller who wanted `extract-skills`
had to know `with_account`, `with_store_dir` and which module holds the
operation before writing a line.

`Dataporter` is that plumbing and nothing else:

    from pathlib import Path

    from dataporter import Dataporter

    dp = Dataporter(store=Path("~/backups").expanduser())
    dp.ask("work")                       # ask claude.ai for the export
    dp.fetch("work", link="https://…")   # file what the email links to
    dp.extract_skills("work")            # and the skills an export omits

Each method layers the settings the way the command line does and calls the one
operation `23` already wrote, returning that operation's own frozen outcome
unchanged. There is no second set of result types, no second set of exit codes
and no logic here that the CLI does not also run — `tests/test_api.py` is a
shape test that says so, and the equality tests beside it compare the bytes.

Four things are deliberately unlike the command line:

- **Nothing is read from `config.toml`.** The constructor builds `Settings` from
  what it was handed; the environment still fills in fields nobody named,
  because init values outrank it. `Dataporter.from_config()` is the door to the
  CLI's full ladder, and it is a different door on purpose (`68`).
- **`extract`'s four modes are four methods.** A command line has one entry per
  command and needs flags to choose; Python does not, so `ask`, `fetch`, `file`
  and `abandon` are separate and the combinations `extract_command` refuses are
  not expressible here at all.
- **`login` is two methods.** §73's two commands run in two terminals, which in
  Python is two calls: `login` opens the window and blocks, and `spend_link`
  spends the link in it from another process.
- **Nothing prints and nothing configures logging.** The default sink is
  `console.DISCARD`; pass `console.Collected()` to read the lines back or
  `console.Terminal()` to let them through. The operations still write their own
  run log under the workspace or the account home, which is `23`'s behaviour and
  not this module's to suppress.

Credentials are not parameters here. `24`'s email and password reach an
unattended ChatGPT extraction through `settings=` alone, which keeps this
module's surface free of a secret and leaves the one place that reads a password
file where `load_settings` already had it.
"""

from pathlib import Path

from dataporter import console
from dataporter import extract as extracting
from dataporter import extract_skills as skills_extracting
from dataporter.browser import session as browser_session
from dataporter.config import (
    Settings,
    load_settings,
    settings_without_config_file,
    validate_source,
    with_account,
    with_session_account,
    with_store_dir,
)
from dataporter.errors import UsageError
from dataporter.hermes import doctor as hermes_doctor

SETTINGS_ALONE = "settings= is the whole configuration; pass it alone, or pass the values instead"
"""Exit `2`'s message, raised from the constructor rather than from a command.

A `Settings` *and* a workspace is a caller who believes one of them is doing
something, and only one of them is. Refused rather than merged, for the reason
`12` refused `--pilot` beside a selection flag.
"""


class Dataporter:
    """The five commands, over one configuration.

    Hold one per configuration and call it as often as you like: the settings it
    was built with are never mutated, and every call derives its own copy for the
    account it names. Nothing here opens a browser, a workspace or a store until
    a method is called.
    """

    def __init__(
        self,
        *,
        workspace: Path | None = None,
        store: Path | None = None,
        source: str | None = None,
        mock: bool = False,
        non_interactive: bool = False,
        settings: Settings | None = None,
    ) -> None:
        """Build the configuration every call starts from.

        `workspace` is where a migration's state lives and, for a command about
        the destination, its browser profile; `store` is where snapshots are
        filed. Both default the way the flags do. `source` is the vendor every
        call means unless it says otherwise, and it is checked here rather than
        at the first extraction, so a typo raises on the line that holds it.

        `mock` moves the origin to the local mock *and* the default workspace to
        `./migration-mock`, exactly as `--mock` does: a rehearsal that wrote
        where a real run reads is what ADR 0010 exists to prevent.

        `settings` is the escape hatch for a caller who built its own, including
        one with `24`'s credentials in it. It is the whole configuration, so it
        is refused beside any of the values above.

        Raises `errors.UsageError` for that contradiction, and
        `config.ConfigError` for a source that does not exist or a value no
        `Settings` would accept.
        """
        if settings is not None and _values_given(workspace, store, source, mock=mock, non_interactive=non_interactive):
            raise UsageError(SETTINGS_ALONE)
        built = (
            settings
            if settings is not None
            else settings_without_config_file(workspace=workspace, non_interactive=non_interactive, mock=mock)
        )
        self._settings = _with_source(with_store_dir(built, store), source)

    @classmethod
    def from_config(
        cls,
        *,
        workspace: Path | None = None,
        store: Path | None = None,
        source: str | None = None,
        mock: bool = False,
        non_interactive: bool = False,
    ) -> "Dataporter":
        """Build one the way the command line does: `config.toml`, then the environment.

        The same parameters as the constructor and one difference: the workspace
        is bootstrapped first and the `config.toml` inside it is read, so an
        operator's file configures a library caller exactly as it configures a
        command. Use it when the host project is running on a machine somebody
        set up for the CLI; use the constructor when it is not.
        """
        loaded = load_settings(workspace=workspace, non_interactive=non_interactive, mock=mock)
        return cls(settings=_with_source(with_store_dir(loaded, store), source))

    @property
    def settings(self) -> Settings:
        """The configuration every call starts from, resolved.

        Read it to find out where the workspace and the store actually landed;
        `Settings` is immutable in practice here, and a call that needs a
        different one derives it rather than changing this.
        """
        return self._settings

    # ----------------------------------------------------------------------- #
    # The session (`07`, `31`, brief 07 §73, brief 08 §82)
    # ----------------------------------------------------------------------- #

    def login(
        self,
        account: str | None = None,
        *,
        source: str | None = None,
        sink: console.Sink = console.DISCARD,
    ) -> browser_session.LoginOutcome:
        """Open the sign-in page in the account's own profile, and block until it is signed in.

        **This waits for a person.** Claude signs in by emailed link behind an
        attestation (ADR 0008), so the window stays open and this call does not
        return until `spend_link` has spent the link in it — from another
        process, because this one is blocked. `timeouts.login_s` bounds the wait
        and `errors.AuthError` is what running out raises.

        No account means the destination, as it does on the command line; a
        label means that source account. A `source` without an `account` is
        refused, because it names the vendor of an account nobody gave.
        """
        return browser_session.login(with_session_account(self._settings, source, account), sink=sink)

    def spend_link(
        self,
        link: str,
        *,
        account: str | None = None,
        source: str | None = None,
        sink: console.Sink = console.DISCARD,
    ) -> browser_session.LoginOutcome:
        """Spend a sign-in link in the window a blocked `login` is holding (`53`).

        The other half of §73's pair, and the other process: this adopts the
        browser `login` opened and drives it to the link, and both calls then
        report the account signed in. The link is used once and written nowhere.
        """
        return browser_session.login(with_session_account(self._settings, source, account), link=link, sink=sink)

    def logout(
        self,
        account: str,
        *,
        source: str | None = None,
        sink: console.Sink = console.DISCARD,
    ) -> browser_session.LogoutOutcome:
        """Discard a source account's session, its open ask and what a fetch staged (§83).

        Local only (§84): the account is untouched, the vendor is not told, and
        the logs are kept. `removed` says whether there was anything to remove.
        """
        return browser_session.logout(self._for(account, source), sink=sink)

    # ----------------------------------------------------------------------- #
    # Extraction (`30`, `31`, `45`)
    # ----------------------------------------------------------------------- #

    def ask(
        self,
        account: str,
        *,
        source: str | None = None,
        sink: console.Sink = console.DISCARD,
    ) -> extracting.ExtractOutcome:
        """Ask the vendor for the account's export, and remember the ask (`31`).

        The first move of an extraction, and the slow one: the vendor emails a
        link when it is ready, which may be hours. One ask is open per account,
        so a second call while one stands is refused. Needs a signed-in session
        and a display.
        """
        return extracting.ask(self._for(account, source), sink=sink)

    def fetch(
        self,
        account: str,
        link: str,
        *,
        source: str | None = None,
        sink: console.Sink = console.DISCARD,
        quiet: bool = False,
    ) -> extracting.ExtractOutcome:
        """Download the archive the vendor's link serves and file it as a snapshot (`45`).

        `link` is what the email carried, handed over once and never written
        down. `quiet` suppresses the per-file `downloaded` lines and keeps the
        closing block, which matters only when a sink is passed.
        """
        return extracting.fetch(self._for(account, source), link, sink=sink, quiet=quiet)

    def file(
        self,
        account: str,
        path: Path,
        *,
        source: str | None = None,
        sink: console.Sink = console.DISCARD,
    ) -> extracting.ExtractOutcome:
        """File an archive already on disk, with no ask behind it (§33).

        The snapshot is stamped at the moment it is filed, because there is no
        ask to take a moment from. Nothing is downloaded and no browser opens.
        """
        return extracting.file(self._for(account, source), path, sink=sink)

    def abandon(
        self,
        account: str,
        *,
        source: str | None = None,
        sink: console.Sink = console.DISCARD,
    ) -> extracting.ExtractOutcome:
        """Give up the account's open ask, so another can be made (`31`).

        Forgets the tool's record of it. The vendor is not told, and a link that
        arrives afterwards still works: `fetch` will take it.
        """
        return extracting.abandon(self._for(account, source), sink=sink)

    def extract_skills(
        self,
        account: str,
        *,
        source: str | None = None,
        stamp: str | None = None,
        sink: console.Sink = console.DISCARD,
        quiet: bool = False,
    ) -> skills_extracting.SkillsOutcome:
        """Collect the skills the account wrote and file them beside its archive (`66`).

        A Claude export does not carry them, which is why this is its own
        command rather than a flag on the ask. `stamp` joins them to the
        snapshot that already exists, so one moment of an account is one
        directory; omitted, they get a snapshot of their own. Seconds rather
        than hours, and repeatable. Needs a signed-in session and a display.
        """
        return skills_extracting.extract_skills_command(
            self._for(account, source),
            skills_extracting.SkillsRequest(stamp=stamp),
            sink=sink,
            quiet=quiet,
        )

    # ----------------------------------------------------------------------- #
    # The environment (`09`)
    # ----------------------------------------------------------------------- #

    def doctor(self, *, sink: console.Sink = console.DISCARD) -> hermes_doctor.DoctorOutcome:
        """Check Hermes, Chrome, the profile and the pacing, stopping at the first failure.

        About the environment rather than an account, so it takes no label. Run
        it once from the host project to find out which half of the chain is
        missing: `checks` is every check that ran and `exit_code` is `6` when
        the last one failed.
        """
        return hermes_doctor.run_doctor(self._settings, sink=sink)

    # ----------------------------------------------------------------------- #

    def _for(self, account: str, source: str | None) -> Settings:
        """Return the settings for one call about one account.

        `with_account` is the command line's own layering, and the validation
        with it: an impossible source or a label that could not be a directory
        name is refused here, before anything joins it to a path.
        """
        return with_account(self._settings, source, account)


def _values_given(
    workspace: Path | None,
    store: Path | None,
    source: str | None,
    *,
    mock: bool,
    non_interactive: bool,
) -> bool:
    """Whether the constructor was handed anything beside a `Settings`.

    A `False` for either flag is indistinguishable from its default and is
    therefore not "given" — which costs nothing, because passing one is a no-op.
    """
    return workspace is not None or store is not None or source is not None or mock or non_interactive


def _with_source(settings: Settings, source: str | None) -> Settings:
    """Apply a constructor's `source`, checked, or leave the settings alone.

    Not `with_account`, which needs a label this has not got: the facade holds a
    vendor across calls and each call names its own account. The check is the
    same one, so both doors refuse the same tokens with the same words.
    """
    if source is None:
        return settings
    return settings.model_copy(update={"source": validate_source(source)})
