"""Extraction: the ask, the fetch and the filing (`30`, `31`, brief `03` §31).

The export arrives in two moves with a person between them, because the vendor
puts an inbox there. This module is both moves and the record the first one
leaves:

```text
extract --source claude --account old-personal            the ask   (`31`)
        │  the vendor emails the person a link
extract --source claude --account old-personal --link …   the fetch (`30`)
extract --source claude --account old-personal --from …   an archive they had
```

The ask is here and the page it presses is in `browser/export_page.py`, which is
the division `probe` and the helpers already have: what the page looks like and
what may be clicked on it is one file's knowledge, and what an operator is told
and what is written down is this one's.

The fetch downloads to a temp file under the account home, hashes it as it
streams, checks that what arrived is an export of this source, and only then
hands it to the store to be filed. Downloading straight into the stamp directory
would turn every expired link into an unfinished snapshot, which is the opposite
of §31's "the ask stays open so the person can try again": nothing reaches the
store until the bytes are known to be an export. The cost is twice the disk for
the duration of one filing, and the temp file goes in a `finally`.

Three rules that are not obvious from the code alone:

- **The link is never kept and never logged.** It expires, and while it lives it
  is a credential to the whole archive (§32). `log.FORBIDDEN_FIELDS` carries
  `link` so that no record can name it, and no message here interpolates
  `str()` of an `HTTPError` or a `URLError` — both stringify the URL they failed
  on. Only `.code` and `.reason` reach an operator.
- **The ask lives in the account home, not in the store.** It is operational,
  abandonable state, and cookies, logs and open asks are exactly what a cloud
  store must never receive. `ask.json` is created with `O_EXCL` — which is what
  makes "one ask is open per account at a time" a fact rather than a check — and
  deleted once `COMPLETE` has landed.
- **The proxy is the environment's.** The opener is `urllib`'s default, unlike
  `cdp._NO_PROXY`: a proxy is wrong for a browser on `127.0.0.1` and right for
  a download from the internet.
"""

import hashlib
import os
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from orval import pretty_bytes, pretty_duration
from pydantic import BaseModel, ConfigDict, ValidationError

from dataporter import PROGRAM_NAME, links, log, plan, signin, sources, store
from dataporter import trace as tracing
from dataporter.browser import download, export_page, launcher, sites
from dataporter.browser import session as browser_session
from dataporter.browser import watch as watching
from dataporter.config import ASK_FILENAME, TMP_DIRNAME, Settings
from dataporter.console import DISCARD, Sink
from dataporter.errors import (
    AuthError,
    ExportError,
    FetchError,
    NetworkError,
    StoreError,
    UsageError,
)
from dataporter.exit_codes import ExitCode
from dataporter.export import ExportView

if TYPE_CHECKING:  # pragma: no cover - the browser is imported where it is used
    from dataporter.browser.launcher import BrowserSession
    from dataporter.sources.base import Reading, Source

_logger = log.get_logger(__name__)

DOWNLOAD_CHUNK = 1 << 16
"""How much of a response is read at a time. Small enough that the byte cap is
enforced on the stream rather than after it."""

DOWNLOAD_DISPLAY = "the download"
"""What a message about a fetched archive calls it. The temp file's name is a
uuid the operator never typed."""

BYTES_REASON = "files the export does not carry"
BYTES_REASON_ONE = "file the export does not carry"
"""The one gap kind a snapshot has today (§31, §64). A Claude export names the
files a conversation carried and ships none of their bytes; a ChatGPT export
is reported to ship them, and the gap is whichever it did not.

Two spellings because the reason is read as part of a sentence — §31's block
prints `Gaps: 38 files the export does not carry` — and `1 files` is not one.
(Raised by Copilot in review on #43.)
"""

# -- what an operator is told ------------------------------------------------ #

ACCOUNT_REQUIRED = "extract needs an account: --account LABEL"
LINK_AND_FILE = "--link and --from name two different archives; give one"
ABANDON_ALONE = "--abandon gives up the open ask; it takes no --link and no --from"

LINK_SCHEME = links.LINK_SCHEME
"""The only scheme the tool will download from.

A constant rather than a literal in the check: it is the whole of the rule,
spelled once in `links` because `login --link` (`53`) checks the same thing of
the sign-in link, and bound here by name so a test can pretend otherwise.
"""

LINK_NOT_HTTPS = links.LINK_NOT_HTTPS
LINK_REFUSED = (
    "link refused: HTTP {code} — the link may have expired; ask again with: "
    "{program} extract --source {source} --account {account}"
)
UNREACHABLE = "cannot reach the download host ({reason})"
TOO_LARGE = "the download is larger than store.max_download_bytes ({limit} bytes)"
NOT_A_ZIP = "the download is not a zip archive"
LINK_IS_A_PAGE = (
    "the link led to a page, not an archive (HTTP {code}); sign in with: "
    "{program} login --source {source} --account {account}, then try again"
)
DOWNLOAD_STALLED = "the download stalled for {seconds:g}s; try again"
DOWNLOAD_CANCELLED = "the browser cancelled the download; try again"
"""What a fetch through the session says when the link did not become an
archive (§63). A page where an archive should be is what a signed-out link
looks like, so the remedy named is the sign-in."""
NOT_AN_ARCHIVE = "--from takes the vendor's archive (.zip); a directory is not one"
NOT_A_ZIP_FILE = "--from takes the vendor's archive (.zip): {path}"
NO_SUCH_FILE = "no such file: {path}"

ASK_OPEN = (
    "an ask is already open for {source}/{account}; abandon it with: "
    "{program} extract --source {source} --account {account} --abandon"
)
ASK_ALREADY_OPEN = (
    "an ask is already open for {source}/{account}, made {asked_at}; fetch it with --link, or drop it with --abandon"
)
"""The same refusal, told twice, because the two know different things.

`ASK_ALREADY_OPEN` is `31`'s check before any browser starts: it has read the
record, so it can say when the ask was made, which is what an operator needs to
decide between fetching it and dropping it. `ASK_OPEN` is `write_ask`'s, raised
by `O_EXCL` against a file that appeared while this invocation was pressing a
button — a race nobody will see, and one that has no record in hand to quote.
"""
NO_ASK_OPEN = "no ask is open for {source}/{account}"
INVALID_ASK = "invalid {filename}: {path}"
ABANDONED = "Abandoned the open ask for {source}/{account}."

EXPORT_PANEL_MISSING = "the export panel did not appear on {path} within {seconds:g}s"
PANEL_MISSING_HEADLESS = "; headless Chrome is served a bot check on this page — try without --non-interactive"
PANEL_MISSING_HEADED = (
    "; if the session has expired, sign in with: {program} login --source {source} --account {account}"
)
NOT_CONFIRMED = "no confirmation that the export was requested"
ASK_DIALOG = "a javascript dialog is in the way on {path}; clear it and ask again"
"""Why an ask exited `1`. A dialog is never answered (`31`, §36): what it says is
unknown, and a tool that clicks OK on an unread question in an account it is
allowed one action in has taken a second one.

The panel line says a panel and a duration rather than a button, because since
`62` that is what was established: the ask polls for the control until
`timeouts.ask_s` runs out, so reaching this means it never rendered. Its second
half is whichever the run can actually be true about. Headless, it is a bot
check, measured: claude.ai serves `--headless=new` a Cloudflare interstitial
(`challenges.cloudflare.com`, a `ray-id` footer, forty-seven nodes) that never
resolves, while the same profile headed renders the panel in about three
seconds. Headed, the page is the vendor's own, so the thing that can have gone
wrong is the session — and `signed_out()` would not have caught it, since it
reads the page kind and Claude's export page is a fragment of `/new` whichever
way the session went."""

# -- §31's blocks ------------------------------------------------------------ #

HEADER = "{name} extraction — {account}"
REQUESTED = "Export requested {moment}."
FETCH_COMMAND = "  {program} extract --source {source} --account {account} --link <url>"
ASKED_AT_FORMAT = "%Y-%m-%d %H:%M UTC"
"""§31's ask block, byte for byte, and the one format an operator reads a moment
in: minutes, because the line is for the eye and the seconds belong to
`ask.json`, where the stamp the snapshot is filed under comes from. The
sentences between the moment and the command are the vendor's own
(`Source.ask_lines`, §60)."""

DOWNLOADED = "Downloaded {size} MB in {took}."
FILED = "Filed {name}."
NO_ASK_ON_RECORD = "Filed without an ask on record."
GAP_LINE = "Gaps: {count} {reason}"
SNAPSHOT_LINE = "Snapshot: {path}"
"""The brief's own block, byte for byte. `Downloaded` is base-10 megabytes to
one decimal — the unit a vendor's download page uses — then how long the fetch
took, whole seconds in `pretty_duration`'s spelling (`1m 6s`), counted from the
moment `fetch` began to the moment the block is printed (`60`): the browser, the
sign-in, the downloads and the filing, which is the number on the shell prompt.
The `Gaps:` line is omitted when there are none, because a zero there is a
question an operator has to answer rather than an answer. The count line is the
source's (`Source.counts_line`): what an archive holds is the vendor's to say."""

DOWNLOADED_LINE = "downloaded  {name}  {size}"
"""One line on stdout the moment a file lands, before it is read or checked
(`60`). Two spaces between columns and no full stop, as `18`'s event lines and
`verify`'s: it is progress and not the block, and `--quiet` drops it as it drops
theirs. The size is `pretty_bytes`, so a part of 716 bytes reads `716.0 B` and
not `0.0 MB`; the block keeps the brief's unit. The name is the vendor's, from
its manifest, through `safe_token`; a fetch without a manifest names
`export.zip`, what its one archive is filed as, because the name the vendor
suggested for it is never kept (§66)."""

MEGABYTE = 1_000_000


# --------------------------------------------------------------------------- #
# The request, and what one amounts to
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ExtractRequest:
    """What was asked of `extract`, before the library picks a mode.

    The flags arrive together and are refused together, as `import`'s are: two
    that name different archives, or `--abandon` beside either, cannot both be
    honoured, and quietly ignoring one is what `12` ruled out for `--pilot`.
    """

    link: str | None = None
    from_path: Path | None = None
    abandon: bool = False


@dataclass(frozen=True)
class ExtractOutcome:
    """What `extract` amounted to: the snapshot it filed, and a code."""

    snapshot: store.Snapshot | None = None
    path: Path | None = None
    exit_code: ExitCode = ExitCode.OK


# --------------------------------------------------------------------------- #
# The open ask
# --------------------------------------------------------------------------- #


def ask_path(settings: Settings) -> Path:
    """`<account home>/ask.json`. Never in the store."""
    return _account_home(settings) / ASK_FILENAME


def read_ask(settings: Settings) -> store.Ask | None:
    """Return the open ask, or `None` when there is not one.

    A file that will not parse is an error rather than a `None`: a fetch that
    read it as "no ask" would stamp the snapshot with the moment it was filed
    instead of the moment the account was as the export describes it, and §33
    says the stamp is the only ordering the store has.
    """
    path = ask_path(settings)
    if not path.exists():
        return None
    try:
        return store.Ask.model_validate_json(path.read_bytes())
    except (OSError, ValidationError, ValueError) as exc:
        raise StoreError(INVALID_ASK.format(filename=ASK_FILENAME, path=path)) from exc


def write_ask(settings: Settings, asked_at: datetime) -> store.Ask:
    """Record that the tool asked this vendor for this account's export (§31).

    `O_EXCL`, so a second ask while one is open is refused by the filesystem
    rather than by a check with a race in it. `31` is what calls this after the
    vendor's button has actually been pressed; it lives here because the whole
    life of the record — written, read by the fetch, deleted by either — belongs
    in one module.
    """
    ask = store.Ask(
        asked_at=asked_at,
        source=settings.source,
        account=_account(settings),
        tool_version=store.tool_version(),
    )
    path = ask_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise StoreError(
            ASK_OPEN.format(
                source=settings.source,
                account=_account(settings),
                program=PROGRAM_NAME,
            )
        ) from exc
    with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
        stream.write(ask.model_dump_json(indent=2) + "\n")
    return ask


def ask_block(ask: store.Ask) -> str:
    """§31's ask block, newline-terminated.

    The command it prints back is the one the operator will type when the email
    arrives, spelled with the flags they used rather than with the defaults: a
    person who named `--source claude` reads it back, and a person who did not
    still gets a line that works, because `source` is what this invocation
    resolved.
    """
    source = sources.REGISTRY[ask.source]
    lines = [
        HEADER.format(name=source.display_name, account=ask.account),
        "",
        REQUESTED.format(moment=ask.asked_at.strftime(ASKED_AT_FORMAT)),
        *source.ask_lines,
        "",
        FETCH_COMMAND.format(program=PROGRAM_NAME, source=ask.source, account=ask.account),
    ]
    return "".join(f"{line}\n" for line in lines)


def ask(settings: Settings, *, sink: Sink = DISCARD, flags: Sequence[str] = ()) -> ExtractOutcome:
    """Ask the vendor for this account's export, and write down that we did (§31).

    The whole of `31`, in the order the order matters:

    1. An ask that is already open is refused **before a browser starts**. A
       second export request is an account-level action taken on a premise the
       operator has not seen, and the fetch would have no way to tell which of
       the two links belongs to which moment.
    2. Then the browser, and the sign-in if the page asks for one. Credentials
       are **not** required to get this far (`61`): the session this runs on is
       the account's Chrome profile, and a profile a person signed in to needs
       no credential at all. They are required where a sign-in is attempted —
       `sign_in_to_source`, unattended — and the refusal there is the same
       `MISSING_CREDENTIALS`, exit `2`. Demanding them at the door would make
       an unattended backup impossible for a source whose sign-in no tool can
       automate (brief 07), which is every Claude account.
    3. Then one press, and the page's own word that it took (`31`'s
       `export_page`).
    4. Only then `ask.json`, with the moment of the press. A record written
       before the confirmation would send the fetch looking for an email nobody
       sent.

    `ExitCode.FAILED` and a note on stderr for a page that would not say it was
    requested: nothing failed *in* us, the account may or may not have taken the
    request, and the honest answer is to say what the page did and leave no
    record claiming otherwise.
    """
    account = _account(settings)
    # Both browserless refusals, in this order, and both before the run log.
    #
    # The open ask keeps the precedence step 1 of this docstring gives it: a
    # person holding one wants to be told to fetch it or abandon it, which is a
    # more useful answer than `not logged in` even when both are true. And both
    # come before `enable_run_log` for `logout`'s reason (`69`) — a refusal that
    # opened no browser and touched no account should leave no log saying it
    # did, which matters most for a mistyped label.
    open_ask = read_ask(settings)
    if open_ask is not None:
        raise StoreError(
            ASK_ALREADY_OPEN.format(
                source=settings.source,
                account=account,
                asked_at=open_ask.asked_at.strftime(ASKED_AT_FORMAT),
            )
        )
    browser_session.require_session(settings)
    log.enable_run_log(settings.logs_dir)
    source = sources.of(settings)
    browser = launcher.launch(settings, sites.export_page_url(source))
    try:
        with watching.watched(
            settings, command="extract", flags=flags, site=sites.extraction_site(source), browser=browser
        ) as traced:
            sign_in_or_record(settings, browser, source, sink=sink, traced=traced)
            result = export_page.request_export(settings, browser, source=source)
            traced.exit_code = ExitCode.OK if result.requested and result.pressed_at is not None else ExitCode.FAILED
    finally:
        # Chrome writes its cookie jar out on exit, and a browser left running
        # would hold the next session's port (`31`: one port, sequential
        # sessions). `login` closes it on every path for the same two reasons.
        browser.close()

    if not result.requested or result.pressed_at is None:
        # The second half is not a second case: a page that says the export was
        # requested was pressed, or the press is where the moment came from. It
        # is written as one condition so that "there is a moment" is a fact the
        # type carries rather than one a comment promises.
        sink.note(_why_not(settings, result.blocked, source))
        return ExtractOutcome(exit_code=ExitCode.FAILED)
    written = write_ask(settings, result.pressed_at)
    _logger.info("ask recorded", extra={"source": settings.source, "account": account})
    sink.block(ask_block(written))
    return ExtractOutcome()


def sign_in_or_record(
    settings: Settings,
    browser: "BrowserSession",
    source: "Source",
    *,
    sink: Sink,
    traced: "tracing.Opened",
    url: str | None = None,
) -> None:
    """`sign_in_to_source`, with the trace told how the run ended if it ended here (`70`).

    `watched` writes the exit code the body assigned it, and a body that raises
    assigns nothing — so a trace of the one failure `70` exists to report would
    be the only trace that does not say how its run ended. Two commands open a
    source session inside a `watched`, so the pair is spelled once, here.
    """
    try:
        sign_in_to_source(settings, browser, source, sink=sink, url=url)
    except AuthError:
        traced.exit_code = ExitCode.NOT_AUTHENTICATED
        raise


def sign_in_to_source(
    settings: Settings,
    browser: "BrowserSession",
    source: "Source",
    *,
    sink: Sink,
    url: str | None = None,
) -> None:
    """Have the source account signed in, in whichever mode this is (§35).

    The ask probes the export page rather than `/new`, which is what keeps the
    wall at two doors: `/new` is outside the extraction surface, and a tool
    that opens it to find out whether it is signed in has opened a new chat in
    the account it promised to take one action in. The fetch (`45`) probes the
    source's own root, since it has no business on the export page.

    This is also where an unattended run finds out it needs credentials (`61`):
    `ensure_signed_in` asks for them, and a run that never gets here never
    needed them.
    """
    url = sites.export_page_url(source) if url is None else url
    state = browser_session.current_state(browser, url, origins=source.origins, sign_in=source.sign_in_selectors)
    if not export_page.signed_out(state, source):
        return
    if source.sign_in_by_link:
        # Brief 07: a sign-in by link has its own two commands and its own
        # window, and neither this window nor `24`'s mode can finish one. The
        # remedy is the same in either mode, so it is said here, once.
        raise AuthError(detail=browser_session.signed_out_line(settings))
    if settings.non_interactive:
        # `24`'s agent half, or `44`'s walk: whichever the source says. An
        # unattended ask on a signed-in profile needs nothing — no walk, and no
        # credentials either (`61`) — which is why this is reached only after
        # the probe above.
        signin.ensure_signed_in(settings, browser)
        return
    sink.line(source.login_prompt)
    arrived = browser_session.wait_for_login(
        browser,
        timeout_s=settings.timeouts.login_s,
        url=url,
        origins=source.origins,
    )
    if arrived is None:
        raise AuthError(detail=browser_session.LOGIN_TIMED_OUT.format(seconds=settings.timeouts.login_s))


def _why_not(settings: Settings, blocked: str | None, source: "Source") -> str:
    """Return the line an operator reads when the ask did not go through."""
    path = source.export_page_path
    if blocked == export_page.BUTTON_NOT_FOUND:
        line = EXPORT_PANEL_MISSING.format(path=path, seconds=settings.timeouts.ask_s)
        if settings.headless:
            return line + PANEL_MISSING_HEADLESS
        return line + PANEL_MISSING_HEADED.format(
            program=PROGRAM_NAME, source=settings.source, account=_account(settings)
        )
    if blocked == export_page.JS_DIALOG:
        return ASK_DIALOG.format(path=path)
    return NOT_CONFIRMED


def abandon(settings: Settings, *, sink: Sink = DISCARD) -> ExtractOutcome:
    """Give up the open ask, so that a new one can be made (§31)."""
    path = ask_path(settings)
    if not path.exists():
        raise StoreError(NO_ASK_OPEN.format(source=settings.source, account=_account(settings)))
    path.unlink()
    _logger.info(
        "ask abandoned",
        extra={"source": settings.source, "account": _account(settings)},
    )
    sink.line(ABANDONED.format(source=settings.source, account=_account(settings)))
    return ExtractOutcome()


# --------------------------------------------------------------------------- #
# The fetch, and the archive a person already has
# --------------------------------------------------------------------------- #


def fetch(
    settings: Settings,
    link: str,
    *,
    open_url: Callable[..., Any] = urllib.request.urlopen,  # ruff: ignore[suspicious-url-open-usage] - the scheme is checked before any request
    sink: Sink = DISCARD,
    flags: Sequence[str] = (),
    quiet: bool = False,
    clock: Callable[[], float] = time.monotonic,
) -> ExtractOutcome:
    """Download the link the vendor emailed and file it as a snapshot (§31, §63).

    The scheme is checked before any request is made: a link that is not
    `https` is not a link this tool follows, and finding that out from the
    server would mean having spoken to it.

    Two ways to download, and the source says which (§63): without a browser,
    through `urllib`, where the vendor allows it; through the source session's
    own tab, the browser making the download and the tool catching it, where
    the vendor requires the download to be made signed in. What follows the
    download — the check that it is a zip, the parse, the filing — is one path.

    A link that may be single-use is never spent on a run that then stops at a
    sign-in form, and it is the **order** that keeps that true rather than a
    credential check at the door (`61`): the browser opens on the source's own
    root, the probe and any sign-in happen there, and the link is navigated to
    only once the session is good. So credentials are required where a sign-in
    is attempted and not before the browser — a profile a person signed in to
    needs none, which is the whole of an unattended backup for Claude.

    Every file prints `DOWNLOADED_LINE` as it lands, unless `quiet`, and the
    block says how long the whole of this took (`60`). `clock` is injectable
    for the same reason `open_url` is: so a test can pin the block's bytes.
    """
    started = clock()
    home = _account_home(settings)
    source = sources.of(settings)
    if source.link_serves_manifest or source.fetch_needs_session:
        # Only where the download goes through the session (`69`). A source whose
        # link `urllib` may follow needs no session, and refusing that fetch for
        # want of one would be a refusal about nothing. Both sources require one
        # today; the condition is written for the day one does not.
        browser_session.require_session(settings)
    log.enable_run_log(settings.logs_dir)
    if not links.is_followable(link, source.origins):
        raise FetchError(links.not_followable(source.origins))

    ask = read_ask(settings)
    asked_at = None if ask is None else ask.asked_at
    moment = datetime.now(UTC) if ask is None else ask.asked_at
    temp_dir = home / TMP_DIRNAME
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp: Path | None = None
    downloaded: list[Path] = []
    try:
        if source.link_serves_manifest:
            # The link is an index, not the archive: what it names is downloaded
            # beside it and filed with it, because all of it is the account's.
            parts = _download_manifest_and_parts(
                settings, source, link, temp_dir, sink=sink, flags=flags, collected=downloaded, quiet=quiet
            )[1]
            temp = archive_among(parts, source)
            size, digest = temp.stat().st_size, digest_of(temp)
        elif source.fetch_needs_session:
            temp, size, digest = _download_through_session(
                settings, source, link, temp_dir, sink=sink, flags=flags, quiet=quiet
            )
        else:
            temp = temp_dir / f"{uuid.uuid4()}.zip"
            size, digest = _download(settings, link, temp, open_url=open_url, sink=sink, quiet=quiet)
        if not zipfile.is_zipfile(temp):
            raise FetchError(NOT_A_ZIP)
        filing = _filing(
            settings,
            source,
            temp,
            display=DOWNLOAD_DISPLAY,
            origin="ask" if ask is not None else "link",
            asked_at=asked_at,
            stamp=store.stamp_of(moment),
            sha256=digest,
            size=size,
        )
        directory, snapshot = store.Store(settings.store_dir).file_archive(
            temp, filing, extra=[item for item in downloaded if item != temp]
        )
    finally:
        # Whatever happened — a refused link, a body that was not an export, a
        # store that would not take it — the bytes under the account home are
        # not something anybody asked us to keep.
        if temp is not None:
            temp.unlink(missing_ok=True)
        for spare in downloaded:
            spare.unlink(missing_ok=True)
    if ask is not None:
        # After `COMPLETE`, never before: an ask deleted on the way to a filing
        # that then failed is an ask nobody can fetch against any more.
        ask_path(settings).unlink(missing_ok=True)
    _log_filed(settings, snapshot)
    sink.block(
        block(
            settings,
            snapshot,
            first=DOWNLOADED.format(size=f"{size / MEGABYTE:.1f}", took=pretty_duration(round(clock() - started))),
            no_ask=ask is None,
        )
    )
    return ExtractOutcome(snapshot=snapshot, path=directory)


def file(settings: Settings, path: Path, *, sink: Sink = DISCARD) -> ExtractOutcome:
    """File an archive a person already has, with no ask behind it (§31).

    The vendor's archive and nothing else. An extracted directory is accepted by
    `import`, because somebody may have unpacked one; a snapshot is the vendor's
    own file, and a tree has no bytes to hash.
    """
    # The label first: `logs_dir` falls back to the workspace without one, and a
    # command about an account has no business writing into `./migration`.
    _account(settings)
    source = sources.of(settings)
    log.enable_run_log(settings.logs_dir)
    if not path.exists():
        raise FetchError(NO_SUCH_FILE.format(path=path))
    if path.is_dir():
        raise FetchError(NOT_AN_ARCHIVE)
    if not zipfile.is_zipfile(path):
        raise FetchError(NOT_A_ZIP_FILE.format(path=path))

    filing = _filing(
        settings,
        source,
        path,
        display=str(path),
        origin="file",
        asked_at=None,
        stamp=store.stamp_of(datetime.now(UTC)),
        sha256=digest_of(path),
        size=path.stat().st_size,
    )
    directory, snapshot = store.Store(settings.store_dir).file_archive(path, filing)
    sink.block(block(settings, snapshot, first=FILED.format(name=path.name), no_ask=False))
    return ExtractOutcome(snapshot=snapshot, path=directory)


class ManifestFile(BaseModel):
    """One file a manifest names, as the vendor describes it."""

    model_config = ConfigDict(extra="ignore")

    export_url: str
    filename: str
    category: str = ""
    part: int = 0


class LinkManifest(BaseModel):
    """What a link serves when it serves a list rather than an archive.

    Claude's shape, and the only one so far: a JSON index naming the real files,
    each at a single-use URL of its own, split by category and by part. Read
    leniently — `extra="ignore"` — because what the tool needs from it is the
    files, and a vendor adding a field to its own index is not a reason to
    refuse a person their data.
    """

    model_config = ConfigDict(extra="ignore")

    data_files: list[ManifestFile] = []


MANIFEST_FILENAME = "manifest.json"
"""What the vendor's index is called in the snapshot. Its own name carries the
export's uuid and a timestamp, which is provenance the snapshot already has."""

NO_FILES_IN_MANIFEST = "the link served a manifest naming no files"
NOT_A_MANIFEST = "the link served neither an archive nor a manifest"
NO_ARCHIVE_IN_MANIFEST = "none of the {count} files the manifest names is a {display} export"


def manifest_of(path: Path) -> LinkManifest | None:
    """Read `path` as a manifest, or `None` when it is not one."""
    try:
        return LinkManifest.model_validate_json(path.read_bytes())
    except (OSError, ValidationError, ValueError):
        return None


def _download_manifest_and_parts(
    settings: Settings,
    source: "Source",
    link: str,
    into: Path,
    *,
    sink: Sink,
    flags: Sequence[str],
    collected: list[Path],
    quiet: bool = False,
) -> tuple[Path, list[Path]]:
    """Download the manifest and every file it names, in one session.

    One browser for all of it: each part is single-use and answers `403` to
    anything without the session, so they are taken the way the manifest was and
    the tab is pointed at each in turn. Named as the manifest names them, because
    a snapshot holding `a1b2c3.zip` describes nothing.
    """
    browser = launcher.launch(settings, source.login_url)
    try:
        with watching.watched(
            settings, command="extract", flags=flags, site=sites.extraction_site(source), browser=browser
        ) as traced:
            sign_in_or_record(settings, browser, source, sink=sink, traced=traced, url=source.login_url)
            with tracing.redacting():
                try:
                    manifest_path, parts = index_and_files(
                        settings, browser, source, link, into, collected=collected, sink=sink, quiet=quiet
                    )
                except download.DownloadStopped as exc:
                    raise _not_an_archive(settings, source, exc) from exc
            traced.exit_code = ExitCode.OK
    finally:
        browser.close()
    return manifest_path, parts


def index_and_files(
    settings: Settings,
    browser: "launcher.BrowserSession",
    source: "Source",
    link: str,
    into: Path,
    *,
    collected: list[Path],
    sink: Sink = DISCARD,
    quiet: bool = False,
) -> tuple[Path, list[Path]]:
    """Download the index, then every file it names, into `into`.

    Split out so the caller's `try` stays the width of the one failure it
    turns into a line an operator reads.

    Every file is appended to `collected` the moment it lands, before anything
    is read or checked, because the caller deletes what is in there whatever
    happened: an index that names nothing, or names no archive, would otherwise
    leave its download under the account home. (Raised by Copilot in review
    on #52.)
    """
    got = download.fetch(settings, browser, link, into=into, origins=source.origins)
    manifest_path = got.path.rename(into / MANIFEST_FILENAME)
    collected.append(manifest_path)
    landed(manifest_path, name=manifest_path.name, size=got.bytes, sink=sink, quiet=quiet)
    manifest = manifest_of(manifest_path)
    if manifest is None:
        raise FetchError(NOT_A_MANIFEST)
    if not manifest.data_files:
        raise FetchError(NO_FILES_IN_MANIFEST)
    parts = []
    for item in manifest.data_files:
        _logger.info("export part", extra={"category": item.category, "part": item.part})
        each = download.fetch(settings, browser, item.export_url, into=into, origins=source.origins)
        parts.append(each.path.rename(into / Path(item.filename).name))
        collected.append(parts[-1])
        landed(parts[-1], name=parts[-1].name, size=each.bytes, sink=sink, quiet=quiet)
    return manifest_path, parts


def archive_among(parts: "Sequence[Path]", source: "Source") -> Path:
    """Return the part an importer reads: the one whose members this source owns.

    Claude splits its export by category, and only the conversations part carries
    `conversations.json`. That part is the snapshot's `archive`; the rest are its
    `parts`, kept because they are the account's data too.
    """
    for part in parts:
        if not zipfile.is_zipfile(part):
            continue
        with zipfile.ZipFile(part) as archive:
            names = archive.namelist()
        if source.recognise(names):
            return part
    raise FetchError(NO_ARCHIVE_IN_MANIFEST.format(count=len(parts), display=source.display_name))


def _download_through_session(
    settings: Settings,
    source: "Source",
    link: str,
    into: Path,
    *,
    sink: Sink,
    flags: Sequence[str],
    quiet: bool = False,
) -> tuple[Path, int, str]:
    """Open the source session, make sure it is signed in, and catch the download (§63).

    The session is opened and signed in exactly as the ask opens it — the
    window and the wait interactively, the credentials and the walk unattended
    — and probed at the site's root rather than at the export page, since the
    fetch has no business there. Then, and only under `trace.redacting`, the
    tab is pointed at the link (§66). The file comes back where the browser
    put it, named by its guid; the caller files it and deletes it.
    """
    browser = launcher.launch(settings, source.login_url)
    try:
        with watching.watched(
            settings, command="extract", flags=flags, site=sites.extraction_site(source), browser=browser
        ) as traced:
            sign_in_or_record(settings, browser, source, sink=sink, traced=traced, url=source.login_url)
            with tracing.redacting():
                try:
                    got = download.fetch(settings, browser, link, into=into, origins=source.origins)
                except download.DownloadStopped as exc:
                    raise _not_an_archive(settings, source, exc) from exc
            traced.exit_code = ExitCode.OK
    finally:
        browser.close()
    # The record names the guid the browser gave the file: a source that serves
    # one archive has no manifest to name it, and the vendor's own suggestion is
    # never kept (§66). The line names what the file is about to become.
    landed(got.path, name=store.ARCHIVE_NAME, size=got.bytes, sink=sink, quiet=quiet)
    return got.path, got.bytes, digest_of(got.path)


def _not_an_archive(settings: Settings, source: "Source", stopped: download.DownloadStopped) -> FetchError:
    """Return the line an operator reads when the link did not become an archive."""
    account = _account(settings)
    if stopped.reason == download.REFUSED:
        return FetchError(
            LINK_REFUSED.format(code=stopped.status, program=PROGRAM_NAME, source=source.name, account=account)
        )
    if stopped.reason == download.PAGE:
        return FetchError(
            LINK_IS_A_PAGE.format(code=stopped.status, program=PROGRAM_NAME, source=source.name, account=account)
        )
    if stopped.reason == download.TOO_LARGE:
        return FetchError(TOO_LARGE.format(limit=settings.store.max_download_bytes))
    if stopped.reason == download.STALLED:
        return FetchError(DOWNLOAD_STALLED.format(seconds=settings.timeouts.download_idle_s))
    return FetchError(DOWNLOAD_CANCELLED)


def _download(
    settings: Settings,
    link: str,
    target: Path,
    *,
    open_url: Callable[..., Any],
    sink: Sink = DISCARD,
    quiet: bool = False,
) -> tuple[int, str]:
    """Stream the link to `target`, hashing and counting as it goes.

    `download_idle_s` is the socket timeout, which `urllib` applies per read
    rather than to the whole transfer: a large archive on a slow link is not
    late, and a connection that has stopped sending is.
    """
    limit = settings.store.max_download_bytes
    digest = hashlib.sha256()
    size = 0
    try:
        response = open_url(link, timeout=settings.timeouts.download_idle_s)
    except urllib.error.HTTPError as exc:
        # Before `URLError`, which it subclasses. `exc.code` and nothing else:
        # `str(exc)` carries the URL, which is the one thing never written down.
        raise FetchError(
            LINK_REFUSED.format(
                code=exc.code,
                program=PROGRAM_NAME,
                source=settings.source,
                account=_account(settings),
            )
        ) from exc
    except urllib.error.URLError as exc:
        # No network at all, DNS, TLS: the environment, not the operator's
        # typing, so exit `6` and not `2`.
        raise NetworkError(detail=UNREACHABLE.format(reason=exc.reason)) from exc

    handle = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with response, os.fdopen(handle, "wb") as stream:
        while chunk := response.read(DOWNLOAD_CHUNK):
            size += len(chunk)
            if size > limit:
                # On the stream, not on a `Content-Length`: a wrong link is
                # under no obligation to declare its size honestly, or at all.
                raise FetchError(TOO_LARGE.format(limit=limit))
            digest.update(chunk)
            stream.write(chunk)
    _logger.info(
        "download complete",
        extra={
            "source": settings.source,
            "account": _account(settings),
            "bytes": size,
        },
    )
    landed(target, name=store.ARCHIVE_NAME, size=size, sink=sink, quiet=quiet)
    return size, digest.hexdigest()


def _filing(
    settings: Settings,
    source: "Source",
    path: Path,
    *,
    display: str,
    origin: store.Origin,
    asked_at: datetime | None,
    stamp: str,
    sha256: str,
    size: int,
) -> store.Filing:
    """Check that `path` is an export of this source, and say what it holds.

    One parse yields the counts, the fingerprint and the gap, so the manifest's
    numbers are the numbers a dry run of the same archive prints rather than a
    second count that agrees with them.
    """
    reading = _read(path, display, source)
    return store.Filing(
        source=settings.source,
        account=_account(settings),
        stamp=stamp,
        origin=origin,
        asked_at=asked_at,
        sha256=sha256,
        bytes=size,
        export_fingerprint=reading.fingerprint,
        counts=store.Counts(
            conversations=reading.conversations,
            projects=reading.projects,
            memories=reading.memories,
            files=reading.files,
        ),
        gaps=_gaps(reading),
    )


def _read(path: Path, display: str, source: "Source") -> "Reading":
    """Parse `path` as this source's export, or refuse it with the reason.

    Every refusal is a `FetchError` — exit `2`, "ask again" — rather than the
    `ExportError` the parser raises: what failed is the link or the file the
    operator handed over, not an export they are about to migrate.

    An archive that is another source's is refused by name before it is read
    (§64): two sources spell `conversations.json` and mean two shapes, and a
    person who typed the wrong `--source` is owed the name of the right one.
    """
    try:
        with ExportView.open(path, display=display) as view:
            looks = sources.recognised(view.names())
            # By name and not by identity (`65`): `recognised` reads the real
            # registry, and under `--mock` the source in hand is the same vendor
            # at another origin — a different object, and `Source` is `eq=False`.
            # An identity check here called every mock archive the wrong source's.
            if looks is not None and looks.name != source.name:
                raise FetchError(
                    sources.LOOKS_LIKE.format(looks=looks.display_name, asked=source.display_name, display=display)
                )
            return source.read(view)
    except ExportError as exc:
        raise FetchError(exc.detail) from exc


def _gaps(reading: "Reading") -> tuple[store.Gap, ...]:
    """Return what the account holds that this snapshot does not (§31).

    One kind today: the export refers to files and carries none of their bytes.
    No references, no gap — a snapshot with nothing missing says nothing, rather
    than saying zero.
    """
    missing = reading.missing_files
    if not missing:
        return ()
    reason = BYTES_REASON_ONE if missing == 1 else BYTES_REASON
    return (store.Gap(kind=plan.BYTES_NOT_IN_EXPORT, count=missing, reason=reason),)


def digest_of(path: Path) -> str:
    """Return the SHA-256 of a file already on disk, read a chunk at a time."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(store.COPY_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# The block
# --------------------------------------------------------------------------- #


def block(settings: Settings, snapshot: store.Snapshot, *, first: str, no_ask: bool) -> str:
    """§31's block, newline-terminated.

    The path is printed as the store was configured — `~` unexpanded when the
    default was used — because an operator who has never named a store reads
    back the words the documentation gives them, not one machine's home.
    """
    source = sources.REGISTRY[snapshot.source]
    lines = [
        HEADER.format(name=source.display_name, account=snapshot.account),
        "",
        first,
    ]
    if no_ask:
        lines.append(NO_ASK_ON_RECORD)
    lines.append(source.counts_line.format(**snapshot.counts.model_dump()))
    lines.extend(GAP_LINE.format(count=gap.count, reason=gap.reason) for gap in snapshot.gaps)
    lines.extend(["", SNAPSHOT_LINE.format(path=display_of(settings, snapshot))])
    return "".join(f"{line}\n" for line in lines)


def display_of(settings: Settings, snapshot: store.Snapshot) -> str:
    """Where the snapshot is, spelled as the store was configured."""
    root = Path(settings.store_display)
    return str(root / snapshot.source / snapshot.account / snapshot.stamp)


def landed(path: Path, *, name: str, size: int, sink: Sink, quiet: bool) -> None:
    """Say that a file landed, the moment the browser finished writing it.

    Said twice: a `downloaded` record naming the staging path, and
    `DOWNLOADED_LINE` on stdout unless `--quiet` (`60`). The staging path and
    not the store's: this is said while the download is the only copy there is,
    minutes before the filing that `_log_filed` names, and where an operator
    watching `-v` would go to look at it. The line is what an operator without
    `-v` follows the fetch by, since a manifest fetch is several downloads and,
    without it, a minute of silence.

    Two names, and they are not the same name. The record carries `path.name`,
    what the file is called on disk — the vendor's, from the manifest, or the
    browser's guid for a source that serves one archive. The line carries
    `name`, what the file is called to an operator — again the vendor's for a
    manifest part, and `store.ARCHIVE_NAME` for that single archive, since the
    name its vendor suggested is never kept (§66).

    Both go through `safe_token` regardless, as the filed line's does, because
    one of the two can be the vendor's: a name carrying a newline would
    otherwise forge a line of its own in what an operator reads, since
    `HumanFormatter` prints an extra as it is given. The directory is ours and
    is left whole, so the path stays one an operator can paste.
    (Raised by Copilot in review on #53, and its two-names half on #57.)
    """
    _logger.info("downloaded", extra={"path": str(path.parent / log.safe_token(path.name))})
    if not quiet:
        sink.line(DOWNLOADED_LINE.format(name=log.safe_token(name), size=pretty_bytes(size, "ds", precision=1)))


def _log_filed(settings: Settings, snapshot: store.Snapshot) -> None:
    """Name each filed file's store path, for an operator reading `-v`.

    One line per file — the archive first, then each part in the order the store
    kept them. The path is spelled as the store was configured (`~` unexpanded),
    the same as §31's block. `--verbose` is what puts it on stderr; the run log
    under the account home records it either way, as it does every event.

    The vendor's own part names appear here, the one place they do: §66 keeps them
    out of the trace and the action log, but `snapshot.json` records them already,
    so a line naming `light_metadata-000.zip` discloses nothing to disk that the
    manifest beside it does not. `safe_token` bounds the name and strips control
    characters so a vendor's name cannot forge a line an operator reads.
    """
    directory = Path(display_of(settings, snapshot))
    for name in (snapshot.archive.name, *(part.name for part in snapshot.parts)):
        _logger.info("filed", extra={"path": str(directory / log.safe_token(name))})


# --------------------------------------------------------------------------- #
# The command
# --------------------------------------------------------------------------- #


def extract_command(
    settings: Settings,
    request: ExtractRequest,
    *,
    sink: Sink = DISCARD,
    flags: Sequence[str] = (),
    quiet: bool = False,
) -> ExtractOutcome:
    """Ask, fetch, file or abandon — whichever the flags name (§31).

    The library picks the mode and refuses the combinations that cannot both be
    honoured, as `import_command` does for `--pilot`, so that a Python caller is
    refused by the same rule as a typed command. With no mode flag at all this
    is the ask (`31`), which is the command's first move and the one every other
    mode is about. `quiet` reaches the fetch alone: it is the one mode with
    progress to suppress.
    """
    if request.link is not None and request.from_path is not None:
        raise UsageError(LINK_AND_FILE)
    if request.abandon and (request.link is not None or request.from_path is not None):
        raise UsageError(ABANDON_ALONE)
    if request.abandon:
        return abandon(settings, sink=sink)
    if request.link is not None:
        return fetch(settings, request.link, sink=sink, flags=flags, quiet=quiet)
    if request.from_path is not None:
        return file(settings, request.from_path, sink=sink)
    return ask(settings, sink=sink, flags=flags)


def _account(settings: Settings) -> str:
    """Return the label, which every mode needs. `with_account` is what sets it."""
    if settings.account is None:
        raise UsageError(ACCOUNT_REQUIRED)
    return settings.account


def _account_home(settings: Settings) -> Path:
    """`<accounts>/<source>/<account>`: the session, the ask and the logs.

    Joined from `_account` rather than read off `Settings.account_home`, which
    is `None` when no label was given: one gate for the whole module, and a
    return type that is a path rather than a path-or-nothing.
    """
    return settings.accounts_dir / settings.source / _account(settings)
