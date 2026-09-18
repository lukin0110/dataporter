"""Extracting the skills an account wrote (`66`, brief `09`).

A Claude export does not carry the account's skills, so every Claude snapshot
was missing something the account holds and said nothing about it — the one
thing §32 forbids. This is the second way to extract an account, and it shares
a destination with the first and nothing else (§88): an ask waits hours on an
email and may be open once at a time, and skills come back in seconds.

```text
extract-skills --source claude --account work                  a snapshot of their own
extract-skills --source claude --account work --stamp <stamp>  beside that stamp's archive
```

The tool **clicks nothing** in the account (§92). It opens the source session
on the export page — the one page an ask stands on, already inside the wall and
already sketched by every ask — reads the account's organisation and its skills
there, keeps the ones the account wrote, points the tab at each one's address
and catches the download as `45` catches a link's, and files what landed. Then
the block, and the browser closed, as `extract`'s fetch does.

Two rules that are not obvious from the code alone:

- **Names go on stdout and into the manifest, and nowhere else.** A skill's
  name is the vendor's constrained field and the file it becomes, which is why
  the `downloaded` line and `snapshot.json` carry it (§94, §91). The run log
  carries the staging path — a guid — and the trace carries the download
  address as a path and a query's *names* (§46), so neither holds a name.
- **A skill that will not come back is a gap, and the list that will not be
  read is an error** (§93). The first is recorded and the run succeeds; the
  second files nothing, because a snapshot cannot be honest about what it is
  missing if it never learned what there was.
"""

import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from orval import pretty_duration

from dataporter import extract as extracting
from dataporter import log, sources, store
from dataporter.browser import download, export_page, helpers, launcher, sites
from dataporter.browser import skills as reading
from dataporter.browser import watch as watching
from dataporter.config import TMP_DIRNAME, Settings
from dataporter.console import DISCARD, Sink
from dataporter.errors import BrowserError, UsageError
from dataporter.exit_codes import ExitCode

if TYPE_CHECKING:
    from dataporter.browser.launcher import BrowserSession
    from dataporter.sources.base import Source

_logger = log.get_logger(__name__)

COMMAND = "extract-skills"
"""What the trace header calls this run."""

# -- what an operator is told ------------------------------------------------ #

ACCOUNT_REQUIRED = "extract-skills needs an account: --account LABEL"
BAD_STAMP = "--stamp takes a snapshot stamp such as 2026-09-18T09-14-02Z, not: {stamp}"
NO_SKILLS_SOURCE = "{name} has no skills to extract"
"""Three refusals before a browser opens. The stamp is refused for not parsing
rather than for containing a separator, because §33's ordering is the whole
reason the flag takes a stamp: a directory name the store cannot sort by time
is not a stamp, and `../..` is the same refusal for the same reason."""

READ_HEADLESS = extracting.PANEL_MISSING_HEADLESS
"""The second half of a failed read, when it can be true: the ask's own hint
(`62`'s finding), cited rather than re-typed. The reads are made on the page the
ask stands on, so *this page* is the same page."""

# -- §94's blocks ------------------------------------------------------------ #

HEADER = "{name} skills — {account}"
DOWNLOADED = "Downloaded {count} {noun} in {took}."
COUNT = "{count} {noun}."
NO_SKILLS = "No skills of your own to extract."
GAP_LINE = extracting.GAP_LINE
SNAPSHOT_LINE = extracting.SNAPSHOT_LINE
"""Brief `09` §94's block, byte for byte. A distinct header, so a skills run and
an export run are told apart at a glance; a count of skills rather than the
megabytes `extract.DOWNLOADED` prints, because a skill is a few kilobytes and
every run would otherwise read `0.0 MB`; and the `Gaps:` and `Snapshot:` lines
as `extract`'s block spells them. The count is the snapshot's, as `extract`'s
count line is the archive's: what the snapshot holds, which after an append may
be more than this run downloaded."""

SKILL = "skill"
SKILLS = "skills"
"""`1 skill.` and not `1 skills.`, as `store.GAPS_ONE` already has it."""

NOT_DOWNLOADED = "skill_not_downloaded"
NOT_DOWNLOADED_REASON = "skills could not be downloaded"
NOT_DOWNLOADED_REASON_ONE = "skill could not be downloaded"
"""The one gap kind a skills extraction has (§93): listed, and not landed. Two
spellings because the reason is read as part of `Gaps: 1 skill could not be
downloaded`, as `extract.BYTES_REASON` has two."""

SLUG = re.compile(r"[^a-z0-9-]+")
FALLBACK_NAME = "skill"
"""The vendor constrains a skill's `name` to lowercase letters, digits and
hyphens (read off its own dialog, 2026-09-18), so the slug is near-identity and
the suffix a collision takes is belt-and-braces (§91)."""


# --------------------------------------------------------------------------- #
# The request, and what one amounts to
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SkillsRequest:
    """What was asked of `extract-skills`: which snapshot, or none."""

    stamp: str | None = None


@dataclass(frozen=True)
class SkillsOutcome:
    """What `extract-skills` amounted to: the snapshot, where its skills are, and a code."""

    snapshot: store.Snapshot | None = None
    path: Path | None = None
    skills: int = 0
    """How many this run filed — not how many the snapshot holds."""
    exit_code: ExitCode = ExitCode.OK


def extract_skills_command(
    settings: Settings,
    request: SkillsRequest,
    *,
    sink: Sink = DISCARD,
    flags: Sequence[str] = (),
    quiet: bool = False,
    clock: Callable[[], float] = time.monotonic,
) -> SkillsOutcome:
    """Read the account's skills, file the ones it wrote, and say what did not come back.

    Everything that can be refused is refused before a browser opens: the
    label, the stamp and the source. `quiet` reaches the `downloaded` lines
    alone, as it does for the fetch; `clock` is injectable so a test can pin
    the block's bytes.
    """
    started = clock()
    account = _account(settings)
    stamp = _stamp(request.stamp)
    source = sources.of(settings)
    if not source.has_skills:
        raise UsageError(NO_SKILLS_SOURCE.format(name=source.display_name))
    log.enable_run_log(settings.logs_dir)
    into = settings.accounts_dir / settings.source / account / TMP_DIRNAME
    into.mkdir(parents=True, exist_ok=True)
    collected: list[Path] = []
    try:
        ours, staged, missing = _collect(
            settings, source, into, sink=sink, flags=flags, quiet=quiet, collected=collected
        )
        if not ours:
            sink.block(_no_skills_block(source, account))
            return SkillsOutcome()
        filing = store.SkillsFiling(
            source=settings.source,
            account=account,
            stamp=stamp,
            skills=tuple(staged),
            gaps=_gaps(missing),
        )
        directory, snapshot = store.Store(settings.store_dir).file_skills(filing)
    finally:
        # Whatever happened, the bytes under the account home are not something
        # anybody asked us to keep: the store has them, or the run failed.
        # Best-effort, so a cleanup that cannot be made does not mask the
        # browser or store error that reached here — nor turn a run that filed
        # its snapshot into a failure. (Raised by Copilot in review on #64.)
        _discard(collected)
    took = pretty_duration(round(clock() - started))
    sink.block(block(settings, source, snapshot, downloaded=len(staged), took=took, gaps=filing.gaps))
    return SkillsOutcome(snapshot=snapshot, path=directory / store.SKILLS_DIRNAME, skills=len(staged))


# --------------------------------------------------------------------------- #
# In the account
# --------------------------------------------------------------------------- #


def _collect(
    settings: Settings,
    source: "Source",
    into: Path,
    *,
    sink: Sink,
    flags: Sequence[str],
    quiet: bool,
    collected: list[Path],
) -> tuple[list[reading.Listed], list[store.StagedSkill], int]:
    """Open the session, read the list, catch each download, and close.

    One browser for all of it, opened on the export page and signed in exactly
    as the ask opens it (`sign_in_to_source`), then the two reads under the
    wall, then one navigation per skill with the wall's third door. Returns the
    skills the account wrote, the ones that landed, and how many did not.
    """
    browser = launcher.launch(settings, sites.export_page_url(source))
    try:
        with watching.watched(
            settings, command=COMMAND, flags=flags, site=sites.extraction_site(source), browser=browser
        ) as traced:
            extracting.sign_in_to_source(settings, browser, source, sink=sink)
            org, listed = _read(settings, browser, source)
            ours = [item for item in listed if item.ours]
            staged, missing = _fetch_each(
                settings, browser, source, org, ours, into, sink=sink, quiet=quiet, collected=collected
            )
            traced.exit_code = ExitCode.OK
    finally:
        browser.close()
    return ours, staged, missing


def _read(settings: Settings, browser: "BrowserSession", source: "Source") -> tuple[str, tuple[reading.Listed, ...]]:
    """Make the two reads, on the export page, under the wall.

    `bring_to_export_page` is the ask's own navigation into the surface: after
    an interactive sign-in the tab is wherever the site left the person, which
    `helpers.driving` refuses to attach to, and the export page is the one
    address inside the wall that is a page. The reads need no page at all, but
    they need to be made from one the wall admits.
    """
    surface = sites.extraction_surface(source)
    deadline = time.monotonic() + settings.timeouts.ask_s
    export_page.bring_to_export_page(browser, source, deadline=deadline, poll_s=export_page.ASK_POLL_S)
    tab = helpers.chosen_tab(browser.client, surface=surface)
    if isinstance(tab, helpers.Failure):
        raise BrowserError(detail=str(tab.error))
    with helpers.driving(browser.client, tab, surface) as page:
        org = _move(settings, page, reading.ORG_ACTION, lambda: reading.read_org(page, source))
        listed = _move(settings, page, reading.LIST_ACTION, lambda: reading.read_list(page, source, org))
    return org, listed


def _move[T](settings: Settings, page: "helpers.Page", action: str, read: Callable[[], T]) -> T:
    """One read, recorded as one move whether it answered or not."""
    url = page.url
    started = time.monotonic()
    try:
        answer = read()
    except BrowserError as exc:
        helpers.record_step(settings, action, ok=False, url=url, elapsed_ms=_elapsed(started))
        detail = exc.detail + (READ_HEADLESS if settings.headless else "")
        raise BrowserError(detail=detail) from exc
    helpers.record_step(settings, action, ok=True, url=url, elapsed_ms=_elapsed(started))
    return answer


def _fetch_each(
    settings: Settings,
    browser: "BrowserSession",
    source: "Source",
    org: str,
    ours: Sequence[reading.Listed],
    into: Path,
    *,
    sink: Sink,
    quiet: bool,
    collected: list[Path],
) -> tuple[list[store.StagedSkill], int]:
    """Point the tab at each skill's address and catch what lands; count what does not.

    `download.fetch` unchanged, once per skill: the address answers the file as
    an attachment, so the navigation becomes a download and every rule `45`
    learned — the guid, the bytes as the one signal that cannot go missing, the
    idle budget — holds as it does for a link. A download that stops for any of
    its reasons is one gap and the next skill is tried (§93).
    """
    names = filenames_for(ours)
    staged: list[store.StagedSkill] = []
    missing = 0
    for item in ours:
        filename = names[item.id]
        address = sites.skills_download_url(source, org, item.id)
        before = frozenset(into.iterdir())
        try:
            got = download.fetch(settings, browser, address, into=into, origins=source.origins)
        except download.DownloadStopped as exc:
            _logger.info("skill not downloaded", extra={"reason": exc.reason, "status": exc.status})
            _sweep(into, before)
            missing += 1
            continue
        collected.append(got.path)
        extracting.landed(got.path, name=filename, size=got.bytes, sink=sink, quiet=quiet)
        staged.append(
            store.StagedSkill(
                name=item.name,
                filename=filename,
                path=got.path,
                sha256=extracting.digest_of(got.path),
                bytes=got.bytes,
                enabled=item.enabled,
                plugin=item.plugin,
            )
        )
    return staged, missing


def _discard(paths: "Iterable[Path]") -> None:
    """Remove staged files without ever raising: cleanup is best-effort (`66`).

    The one write in this module that must not decide the command's outcome. A
    file left because it could not be removed is logged and swept by `logout`,
    the way `45`'s `.crdownload` is; raising here would replace the run's real
    error, or fail a run whose snapshot is already filed — the mistake the
    store made with `APPENDING` and fixed the same way. (Raised by Copilot in
    review on #64.)
    """
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            _logger.warning("staged file not removed", extra={"reason": exc.strerror or str(exc)})


def _sweep(into: Path, before: frozenset[Path]) -> None:
    """Remove what a download that did not finish left in the staging dir.

    `download.fetch` names what it caught and nothing else, and `45` says
    outright that an interrupted run's `.crdownload` is left where it fell —
    right for a fetch that then fails, since `logout` sweeps the staging dir. A
    skills extraction goes on to *succeed* after a gap (§93), so what a stalled
    download wrote would otherwise sit under the account home behind a run
    that reported success. Only what this attempt added: what was there before
    is an earlier skill of this run, on its way to the store. (Raised by
    Copilot in review on #64.)
    """
    _discard(set(into.iterdir()) - set(before))


# --------------------------------------------------------------------------- #
# Names, stamps, gaps
# --------------------------------------------------------------------------- #


def slug_of(name: str) -> str:
    """Return the vendor's name as a filename stem: lowercase, `[a-z0-9-]`, never empty."""
    cleaned = SLUG.sub("-", name.lower()).strip("-")
    return cleaned or FALLBACK_NAME


def filenames_for(listed: Sequence[reading.Listed]) -> dict[str, str]:
    """One filename per skill, by id: the slug, and `-1`, `-2` for a collision (§91).

    In listing order, so the same list names the same files twice — which is
    what lets a second run into the same stamp be refused by the store rather
    than filed under fresh suffixes beside the first.
    """
    taken: set[str] = set()
    names: dict[str, str] = {}
    for item in listed:
        base = slug_of(item.name)
        candidate, bump = base, 0
        while candidate in taken:
            bump += 1
            candidate = f"{base}-{bump}"
        taken.add(candidate)
        names[item.id] = f"{candidate}{store.SKILL_SUFFIX}"
    return names


def _stamp(given: str | None) -> str:
    """Return the stamp to file under: the one given, or now (§89)."""
    if given is None:
        return store.stamp_of(datetime.now(UTC))
    if store.parse_stamp(given) is None:
        raise UsageError(BAD_STAMP.format(stamp=given))
    return given


def _gaps(missing: int) -> tuple[store.Gap, ...]:
    """Return what was listed and did not land, as one gap (§93). None is no gap, not zero."""
    if not missing:
        return ()
    reason = NOT_DOWNLOADED_REASON_ONE if missing == 1 else NOT_DOWNLOADED_REASON
    return (store.Gap(kind=NOT_DOWNLOADED, count=missing, reason=reason),)


def _account(settings: Settings) -> str:
    """Return the label, which everything here needs. `with_account` is what sets it."""
    if settings.account is None:
        raise UsageError(ACCOUNT_REQUIRED)
    return settings.account


def _elapsed(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


# --------------------------------------------------------------------------- #
# The block
# --------------------------------------------------------------------------- #


def block(
    settings: Settings,
    source: "Source",
    snapshot: store.Snapshot,
    *,
    downloaded: int,
    took: str,
    gaps: Sequence[store.Gap],
) -> str:
    """§94's block, newline-terminated.

    The gaps are this run's, not the snapshot's: a snapshot appended to an
    archive already carries the archive's `files the export does not carry`,
    which is not something this extraction did or could do anything about.
    """
    held = snapshot.counts.skills or 0
    lines = [
        HEADER.format(name=source.display_name, account=snapshot.account),
        "",
        DOWNLOADED.format(count=downloaded, noun=_noun(downloaded), took=took),
        COUNT.format(count=held, noun=_noun(held)),
    ]
    lines.extend(GAP_LINE.format(count=gap.count, reason=gap.reason) for gap in gaps)
    where = Path(extracting.display_of(settings, snapshot)) / store.SKILLS_DIRNAME
    lines.extend(["", SNAPSHOT_LINE.format(path=where)])
    return "".join(f"{line}\n" for line in lines)


def _no_skills_block(source: "Source", account: str) -> str:
    """§94's other block: the account wrote none, and nothing was filed."""
    return "".join(f"{line}\n" for line in (HEADER.format(name=source.display_name, account=account), "", NO_SKILLS))


def _noun(count: int) -> str:
    return SKILL if count == 1 else SKILLS
