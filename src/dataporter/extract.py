"""Extraction: the fetch, the filing and the open ask (`30`, brief `03` §31).

The export arrives in two moves with a person between them, because the vendor
puts an inbox there. This module is the second move and the record the first one
leaves:

```text
extract --source claude --account old-personal            the ask   (`31`)
        │  the vendor emails the person a link
extract --source claude --account old-personal --link …   the fetch (here)
extract --source claude --account old-personal --from …   an archive they had
```

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
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from dataporter import PROGRAM_NAME, log, plan, store
from dataporter.config import Settings
from dataporter.console import DISCARD, Sink
from dataporter.errors import (
    ExportError,
    FetchError,
    NetworkError,
    StoreError,
    UsageError,
)
from dataporter.exit_codes import ExitCode
from dataporter.export import Export, ExportSource, read_export
from dataporter.export.model import file_entries

_logger = log.get_logger(__name__)

ASK_FILENAME = "ask.json"
TMP_DIRNAME = "tmp"
"""Under the account home: the open ask, and where a download lands before it is
verified. Neither is ever in the store."""

DOWNLOAD_CHUNK = 1 << 16
"""How much of a response is read at a time. Small enough that the byte cap is
enforced on the stream rather than after it."""

DOWNLOAD_DISPLAY = "the download"
"""What a message about a fetched archive calls it. The temp file's name is a
uuid the operator never typed."""

BYTES_REASON = "files the export does not carry"
BYTES_REASON_ONE = "file the export does not carry"
"""The one gap kind a Claude snapshot has today (§31). The export names the
files a conversation carried and ships none of their bytes.

Two spellings because the reason is read as part of a sentence — §31's block
prints `Gaps: 38 files the export does not carry` — and `1 files` is not one.
(Raised by Copilot in review on #43.)
"""

# -- what an operator is told ------------------------------------------------ #

ACCOUNT_REQUIRED = "extract needs an account: --account LABEL"
LINK_AND_FILE = "--link and --from name two different archives; give one"
ABANDON_ALONE = "--abandon gives up the open ask; it takes no --link and no --from"
NOT_BUILT = f"not implemented in this build: {PROGRAM_NAME} extract (the ask)"

LINK_SCHEME = "https"
"""The only scheme the tool will download from.

A constant rather than a literal in the check: it is the whole of the rule, and
`31`'s extraction surface will want to name it beside the pages it allows.
"""

LINK_NOT_HTTPS = "the link must be an https URL"
LINK_REFUSED = (
    "link refused: HTTP {code} — the link may have expired; ask again with: "
    "{program} extract --source {source} --account {account}"
)
UNREACHABLE = "cannot reach the download host ({reason})"
TOO_LARGE = "the download is larger than store.max_download_bytes ({limit} bytes)"
NOT_A_ZIP = "the download is not a zip archive"
NOT_AN_ARCHIVE = "--from takes the vendor's archive (.zip); a directory is not one"
NOT_A_ZIP_FILE = "--from takes the vendor's archive (.zip): {path}"
NO_SUCH_FILE = "no such file: {path}"

ASK_OPEN = (
    "an ask is already open for {source}/{account}; abandon it with: "
    "{program} extract --source {source} --account {account} --abandon"
)
NO_ASK_OPEN = "no ask is open for {source}/{account}"
INVALID_ASK = "invalid {filename}: {path}"
ABANDONED = "Abandoned the open ask for {source}/{account}."

# -- §31's block ------------------------------------------------------------- #

HEADER = "{name} extraction — {account}"
DOWNLOADED = "Downloaded {size} MB."
FILED = "Filed {name}."
NO_ASK_ON_RECORD = "Filed without an ask on record."
COUNTS = (
    "Conversations: {conversations}     Projects: {projects}     Memories: {memories}"
)
GAP_LINE = "Gaps: {count} {reason}"
SNAPSHOT_LINE = "Snapshot: {path}"
"""The brief's own block, byte for byte. `Downloaded` is base-10 megabytes to
one decimal — the unit a vendor's download page uses — and the `Gaps:` line is
omitted when there are none, because a zero there is a question an operator has
to answer rather than an answer."""

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
    """The open ask, or `None` when there is not one.

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


def abandon(settings: Settings, *, sink: Sink = DISCARD) -> ExtractOutcome:
    """Give up the open ask, so that a new one can be made (§31)."""
    path = ask_path(settings)
    if not path.exists():
        raise StoreError(
            NO_ASK_OPEN.format(source=settings.source, account=_account(settings))
        )
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
    open_url: Callable[..., Any] = urllib.request.urlopen,
    sink: Sink = DISCARD,
) -> ExtractOutcome:
    """Download the link the vendor emailed and file it as a snapshot (§31).

    The scheme is checked before any request is made: a link that is not
    `https` is not a link this tool follows, and finding that out from the
    server would mean having spoken to it.
    """
    home = _account_home(settings)
    log.enable_run_log(settings.logs_dir)
    if urllib.parse.urlsplit(link).scheme != LINK_SCHEME:
        raise FetchError(LINK_NOT_HTTPS)

    ask = read_ask(settings)
    asked_at = None if ask is None else ask.asked_at
    moment = datetime.now(UTC) if ask is None else ask.asked_at
    temp = home / TMP_DIRNAME / f"{uuid.uuid4()}.zip"
    temp.parent.mkdir(parents=True, exist_ok=True)
    try:
        size, digest = _download(settings, link, temp, open_url=open_url)
        if not zipfile.is_zipfile(temp):
            raise FetchError(NOT_A_ZIP)
        filing = _filing(
            settings,
            temp,
            display=DOWNLOAD_DISPLAY,
            origin="ask" if ask is not None else "link",
            asked_at=asked_at,
            stamp=store.stamp_of(moment),
            sha256=digest,
            size=size,
        )
        directory, snapshot = store.Store(settings.store_dir).file_archive(temp, filing)
    finally:
        # Whatever happened — a refused link, a body that was not an export, a
        # store that would not take it — the bytes under the account home are
        # not something anybody asked us to keep.
        temp.unlink(missing_ok=True)
    if ask is not None:
        # After `COMPLETE`, never before: an ask deleted on the way to a filing
        # that then failed is an ask nobody can fetch against any more.
        ask_path(settings).unlink(missing_ok=True)
    sink.block(
        block(
            settings,
            snapshot,
            first=DOWNLOADED.format(size=f"{size / MEGABYTE:.1f}"),
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
    log.enable_run_log(settings.logs_dir)
    if not path.exists():
        raise FetchError(NO_SUCH_FILE.format(path=path))
    if path.is_dir():
        raise FetchError(NOT_AN_ARCHIVE)
    if not zipfile.is_zipfile(path):
        raise FetchError(NOT_A_ZIP_FILE.format(path=path))

    filing = _filing(
        settings,
        path,
        display=str(path),
        origin="file",
        asked_at=None,
        stamp=store.stamp_of(datetime.now(UTC)),
        sha256=_digest(path),
        size=path.stat().st_size,
    )
    directory, snapshot = store.Store(settings.store_dir).file_archive(path, filing)
    sink.block(
        block(settings, snapshot, first=FILED.format(name=path.name), no_ask=False)
    )
    return ExtractOutcome(snapshot=snapshot, path=directory)


def _download(
    settings: Settings,
    link: str,
    target: Path,
    *,
    open_url: Callable[..., Any],
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
    return size, digest.hexdigest()


def _filing(
    settings: Settings,
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
    export = _read(path, display)
    return store.Filing(
        source=settings.source,
        account=_account(settings),
        stamp=stamp,
        origin=origin,
        asked_at=asked_at,
        sha256=sha256,
        bytes=size,
        export_fingerprint=export.fingerprint,
        counts=store.Counts(
            conversations=len(export.conversations),
            projects=export.projects,
            memories=export.memories,
        ),
        gaps=_gaps(export),
    )


def _read(path: Path, display: str) -> Export:
    """Parse `path` as this source's export, or refuse it with the reason.

    Every refusal is a `FetchError` — exit `2`, "ask again" — rather than the
    `ExportError` the parser raises: what failed is the link or the file the
    operator handed over, not an export they are about to migrate.
    """
    try:
        with ExportSource.open(path, display=display) as source:
            return read_export(source)
    except ExportError as exc:
        raise FetchError(exc.detail) from exc


def _gaps(export: Export) -> tuple[store.Gap, ...]:
    """What the account holds that this snapshot does not (§31).

    One kind today: the export refers to files and carries none of their bytes.
    No references, no gap — a snapshot with nothing missing says nothing, rather
    than saying zero.
    """
    missing = file_entries(export)
    if not missing:
        return ()
    reason = BYTES_REASON_ONE if missing == 1 else BYTES_REASON
    return (store.Gap(kind=plan.BYTES_NOT_IN_EXPORT, count=missing, reason=reason),)


def _digest(path: Path) -> str:
    """The SHA-256 of a file already on disk, read a chunk at a time."""
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(store.COPY_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# The block
# --------------------------------------------------------------------------- #


def block(
    settings: Settings, snapshot: store.Snapshot, *, first: str, no_ask: bool
) -> str:
    """§31's block, newline-terminated.

    The path is printed as the store was configured — `~` unexpanded when the
    default was used — because an operator who has never named a store reads
    back the words the documentation gives them, not one machine's home.
    """
    lines = [
        HEADER.format(
            name=store.SOURCE_NAMES[snapshot.source], account=snapshot.account
        ),
        "",
        first,
    ]
    if no_ask:
        lines.append(NO_ASK_ON_RECORD)
    lines.append(
        COUNTS.format(
            conversations=snapshot.counts.conversations,
            projects=snapshot.counts.projects,
            memories=snapshot.counts.memories,
        )
    )
    lines.extend(
        GAP_LINE.format(count=gap.count, reason=gap.reason) for gap in snapshot.gaps
    )
    lines.extend(["", SNAPSHOT_LINE.format(path=_display(settings, snapshot))])
    return "".join(f"{line}\n" for line in lines)


def _display(settings: Settings, snapshot: store.Snapshot) -> str:
    """Where the snapshot is, spelled as the store was configured."""
    root = Path(settings.store_display)
    return str(root / snapshot.source / snapshot.account / snapshot.stamp)


# --------------------------------------------------------------------------- #
# The command
# --------------------------------------------------------------------------- #


def extract_command(
    settings: Settings, request: ExtractRequest, *, sink: Sink = DISCARD
) -> ExtractOutcome:
    """Ask, fetch, file or abandon — whichever the flags name (§31).

    The library picks the mode and refuses the combinations that cannot both be
    honoured, as `import_command` does for `--pilot`, so that a Python caller is
    refused by the same rule as a typed command. With no mode flag at all this
    is the ask, which `31` builds.
    """
    if request.link is not None and request.from_path is not None:
        raise UsageError(LINK_AND_FILE)
    if request.abandon and (request.link is not None or request.from_path is not None):
        raise UsageError(ABANDON_ALONE)
    if request.abandon:
        return abandon(settings, sink=sink)
    if request.link is not None:
        return fetch(settings, request.link, sink=sink)
    if request.from_path is not None:
        return file(settings, request.from_path, sink=sink)
    sink.note(NOT_BUILT)
    return ExtractOutcome(exit_code=ExitCode.NOT_IMPLEMENTED)


def _account(settings: Settings) -> str:
    """The label, which every mode needs. `with_account` is what sets it."""
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
