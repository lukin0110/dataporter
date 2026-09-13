"""The deterministic moves Hermes asks for, and the wall around them.

Hermes decides *when* to act: where the composer is, whether the page looks
right, what to do about a surprise. This module is the other half of that
division of labour (`specs/README.md`): the moves whose exactness matters —
insert a 45 kB seed byte for byte, put a file in the upload input, wait until
generation has actually finished — made the same way every time, each one
verifying its own effect.

Four properties hold for every helper here:

- **One JSON object on stdout, and nothing else.** `cli` prints
  `Emission.text` and exits `0` when `ok` is true, `1` when it is false and `2`
  when the arguments were wrong. Hermes reads the object; it never has to read
  prose.
- **It verifies what it did.** A paste is confirmed by hashing what the composer
  holds, an attachment by finding its chip, a response by watching the character
  count stop moving. Nothing here reports success because a CDP call returned.
- **It refuses to act outside the migration surface** (§17). The URL must be
  `/new` or `/chat/<uuid>` on claude.ai, checked before the tab is attached to
  and again on the live URL after, because the target list is a snapshot.
- **It records what it did.** One line per invocation in
  `<workspace>/logs/actions.jsonl`, which `19` sums into `Browser actions`.

No content reaches stdout or a log record. Seeds and composer text pass through
this process — they have to, to be compared — but what is printed is a length, a
digest and a file name, and what is logged is a helper name, a duration and a
conversation id.
"""

import json
import re
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from orval import utcnow
from pydantic import BaseModel, ConfigDict

from dataporter import log
from dataporter.browser import probe as probing
from dataporter.browser.cdp import CdpClient, Page, Target
from dataporter.browser.session import BLANK_URLS
from dataporter.config import Settings
from dataporter.errors import BrowserError, MigrationError, SafetyError
from dataporter.exit_codes import ExitCode
from dataporter.seed import sha256_of

_logger = log.get_logger(__name__)

ACTIONS_FILENAME = "actions.jsonl"

RESPONSE_POLL_S = 1.0
"""How often `await-response` looks. `08` fixes it at one second."""

STABLE_POLLS = 3
"""How many consecutive polls must agree before a response is finished.

Generation streams, so a message that has stopped growing for three seconds has
stopped growing. Two would fire on a pause between tokens; four costs a second
per conversation for nothing.
"""

CHIP_POLL_S = 0.5
"""How often `attach` looks for the attachment chip."""


# --------------------------------------------------------------------------- #
# The wall
# --------------------------------------------------------------------------- #

MIGRATION_SURFACE = re.compile(r"^https://claude\.ai/(new|chat/[0-9a-f-]{36})(\?.*)?$")
"""The only URLs a helper will act on (§17).

Deliberately coarser than `probe.conversation_id_of`, which parses the uuid
properly: this is a wall, not a parser, and a wall is easier to trust when it is
one line long. `/settings`, `/admin`, `/billing`, `/organizations` and
`/project` are outside it, and so is every other host.
"""


@dataclass(frozen=True)
class Surface:
    """A host and the URLs on it a helper may touch.

    A parameter rather than a setting, and never read from config or the
    environment: `CLAUDE` is what every command passes and the only thing an
    operator can run. The test suite is the one caller that substitutes another,
    to point the same helpers at a fixture server on `127.0.0.1` — so the wall
    has no door that ships.
    """

    host: str
    allowed: re.Pattern[str]

    def permits(self, url: str) -> bool:
        return self.allowed.match(url) is not None


CLAUDE = Surface(host=probing.CLAUDE_HOST, allowed=MIGRATION_SURFACE)


def guard(url: str, surface: Surface = CLAUDE) -> None:
    """Raise unless `url` is inside the migration surface."""
    if not surface.permits(url):
        raise SafetyError(detail=url)


# --------------------------------------------------------------------------- #
# What a helper prints
# --------------------------------------------------------------------------- #

NO_CLAUDE_TAB = "no_claude_tab"
AMBIGUOUS_TAB = "ambiguous_tab"
UNKNOWN_TARGET = "unknown_target"
OUTSIDE_MIGRATION_SURFACE = "outside_migration_surface"
COMPOSER_MISSING = "composer_missing"
COMPOSER_NOT_EMPTY = "composer_not_empty"
TEXT_MISMATCH = "text_mismatch"
SEED_NOT_FOUND = "seed_not_found"
SEED_UNREADABLE = "seed_unreadable"
FILE_NOT_FOUND = "file_not_found"
INPUT_NOT_FOUND = "input_not_found"
UPLOAD_REJECTED = "upload_rejected"
CHIP_NOT_FOUND = "chip_not_found"
RESPONSE_TIMEOUT = "response_timeout"
"""The `error` strings. Stable on the wire: `11` branches on them and `19`
counts them, so they are named here rather than written out at each raise.

`unknown_target`, `seed_not_found`, `seed_unreadable` and `file_not_found` are
`08`'s own additions to the set the spec names — an argument that points at
nothing is a different thing from a page that is not ready, and telling Hermes
which it was is the difference between retrying and stopping.
"""


class HelperModel(BaseModel):
    """Base for the printed objects: immutable, closed, and `ok` first."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class TabRef(HelperModel):
    """One candidate tab, as `ambiguous_tab` lists it.

    An id and a URL, which is what `--target` needs and all a claude.ai URL
    carries. No title: a tab's title is a conversation title (§10).
    """

    id: str
    url: str


class Failure(HelperModel):
    """`{"ok": false, "error": ...}`, plus whatever that error is owed.

    One model rather than one per error, with everything optional and `None`
    excluded when it is dumped, because Hermes parses `error` first and the rest
    only if it recognises it.
    """

    ok: Literal[False] = False
    error: str
    detail: str | None = None
    url: str | None = None
    tabs: tuple[TabRef, ...] | None = None
    expected_sha256: str | None = None
    observed_sha256: str | None = None
    observed_chars: int | None = None
    elapsed_s: float | None = None
    generating: bool | None = None


class ProbeResult(probing.PageState):
    """`07`'s `PageState`, plus `ok` and the last message.

    A subclass rather than a restatement, so a field added to `PageState` by
    `10` appears here without an edit. The inherited fields come first and `ok`
    follows them, which is the one thing subclassing costs.

    `messages` and `title` are `17`'s, and are `None` — dropped from the printed
    object, which is `exclude_none` — unless `--messages` asked for them. A probe
    that walks the whole transcript is the verification's probe; the poll loop's
    probe stays the three lines it was.
    """

    ok: Literal[True] = True
    last_message: probing.LastMessage
    messages: tuple[probing.LastMessage, ...] | None = None
    title: probing.TitleMatch | None = None


class PasteResult(HelperModel):
    """What the composer holds now, and how it got there.

    `chars` and `sha256` describe the composer after the insert — which under
    `--append` is the text that was already there plus the seed, and otherwise
    is the seed alone. Both are measured after normalisation, so they are
    comparable with `expected_sha256` in a `text_mismatch` and not necessarily
    with the digest of the seed file's bytes.
    """

    ok: Literal[True] = True
    chars: int
    sha256: str
    method: str
    elapsed_ms: int


class AttachResult(HelperModel):
    ok: Literal[True] = True
    file_name: str
    bytes: int


class ChipsResult(HelperModel):
    """What `attachments` found: which files the composer is carrying (`16`).

    `count` beside the list because the skill's check is a count — "as many chips
    as files" — and a number it does not have to compute is a number it cannot
    compute wrongly.
    """

    ok: Literal[True] = True
    file_names: tuple[str, ...]
    count: int


class AwaitResult(HelperModel):
    ok: Literal[True] = True
    elapsed_s: float
    conversation_id: str | None
    last_message: probing.LastMessage


class CloseResult(HelperModel):
    ok: Literal[True] = True
    closed: int


Result = ProbeResult | PasteResult | AttachResult | ChipsResult | AwaitResult | CloseResult | Failure


@dataclass(frozen=True)
class Outcome:
    """One helper's answer: the object to print, and what to record about it."""

    result: Result
    conversation_id: str | None = None
    usage: bool = False
    """True when the arguments were wrong rather than the page — exit `2`."""

    @property
    def ok(self) -> bool:
        return self.result.ok

    @property
    def exit_code(self) -> ExitCode:
        if self.usage:
            return ExitCode.USAGE
        return ExitCode.OK if self.ok else ExitCode.FAILED


@dataclass(frozen=True)
class Emission:
    """The line to print and the code to exit with. `cli` does both."""

    text: str
    exit_code: ExitCode


# --------------------------------------------------------------------------- #
# The expressions that touch content
# --------------------------------------------------------------------------- #

COMPOSER_TEXT_TAG = "dataporter:composer_text"
FOCUS_TAG = "dataporter:focus"
EXEC_COMMAND_TAG = "dataporter:exec_command"
FILE_INPUT_TAG = "dataporter:file_input"
CHIP_TAG = "dataporter:chip"
CHIPS_TAG = "dataporter:chips"

COMPOSER_TEXT_JS = probing.expression(
    COMPOSER_TEXT_TAG,
    "  return composer === null ? null : composerText();",
)
"""The composer's text, read the way `probe` counts it — `blockText`, one line
per block, and not `innerText`. The one expression here that returns content,
which is why it lives in this module and not in `probe`."""

_FOCUS_BODY = """  if (composer === null) return false;
  composer.focus();
  const range = document.createRange();
  range.selectNodeContents(composer);
  range.collapse(false);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
"""
"""Focus, and put the caret at the end.

`focus()` alone is not enough: `Input.insertText` and `execCommand('insertText')`
both insert at the selection, and an editable with no selection in it swallows
the insert. Collapsing to the end is also what makes `--append` mean append.
"""

FOCUS_JS = probing.expression(FOCUS_TAG, _FOCUS_BODY + "  return document.activeElement === composer;")

FILE_INPUT_JS = probing.expression(FILE_INPUT_TAG, "  return all(FILE_INPUT_SELECTOR).length > 0;")
"""Whether there is somewhere to put a file. Not filtered by visibility: the
upload input on claude.ai is hidden behind a button, which is normal."""


def exec_command_js(text: str) -> str:
    """Return the `exec_command` fallback: the same insert, through the DOM API.

    The text is a `const` on a line of its own so that the test suite's fake
    browser can read back what it was asked to insert without parsing JS.
    """
    return probing.expression(
        EXEC_COMMAND_TAG,
        f"  const text = {json.dumps(text)};\n"
        + _FOCUS_BODY
        + "  return document.execCommand('insertText', false, text) === true;",
    )


def chips_js(file_names: Sequence[str]) -> str:
    """Which of these files have a chip, in one look at the page.

    `chip_js`'s test, run over a list instead of over one name, and the same
    three cheap conditions before `visible` for the same reason. One expression
    rather than one call per file because this is asked once per conversation,
    just before the first paste, and the answer has to describe one moment: a
    chip that appeared between two round trips would make the count agree with a
    page that never existed.

    What comes back is the caller's own strings, filtered — the same shape
    `probe`'s `contains` has, and for the same reason: nothing off the page
    crosses the wire.
    """
    return probing.expression(
        CHIPS_TAG,
        f"  const names = {json.dumps(list(file_names))};\n"
        "  const leaves = all('*').filter((el) =>\n"
        "    el.children.length === 0 &&\n"
        "    (composer === null || !composer.contains(el)) &&\n"
        "    visible(el));\n"
        "  return names.filter((name) =>\n"
        "    leaves.some((el) => (el.textContent || '').indexOf(name) !== -1));",
    )


def chip_js(file_name: str) -> str:
    """Whether an attachment chip naming this file has appeared.

    A leaf element, visible, outside the composer. Leaf because every ancestor
    of the chip contains its text too, and outside the composer because a file
    name typed into the prompt is not an upload.

    The conditions are in that order on purpose: this runs over every element on
    the page twice a second for up to a minute, and `visible` reads
    `getClientRects`, which forces layout. Three string and tree tests first
    leave it with almost nothing to measure.
    """
    return probing.expression(
        CHIP_TAG,
        f"  const name = {json.dumps(file_name)};\n"
        "  return all('*').some((el) =>\n"
        "    el.children.length === 0 &&\n"
        "    (el.textContent || '').indexOf(name) !== -1 &&\n"
        "    (composer === null || !composer.contains(el)) &&\n"
        "    visible(el));",
    )


# --------------------------------------------------------------------------- #
# Comparing a seed with what the composer holds
# --------------------------------------------------------------------------- #

NBSP = "\u00a0"
"""The non-breaking space ProseMirror writes where a seed had a plain one."""


def normalise(text: str) -> str:
    r"""Return what is compared, on both sides of the comparison.

    ProseMirror rewrites a leading space as a non-breaking one and drops the
    trailing whitespace of a line; a `contenteditable` reports line breaks as
    `\n` on one platform and `\r\n` on another. None of that is the seed
    changing, so none of it may read as one — and writing the rule down here is
    what makes a mismatch mean something.
    """
    unified = text.replace("\r\n", "\n").replace("\r", "\n").replace(NBSP, " ")
    return "\n".join(line.rstrip() for line in unified.split("\n")).strip()


def normalised_title(value: str | None) -> str | None:
    """Return the `--expect-title` string as the page will spell it, or `None`.

    `probe.normalise_title` and nothing else, wrapped only to keep `None`
    meaning "nobody asked": an empty `--expect-title` is a question about an
    empty title, which is a different thing from not asking.
    """
    return None if value is None else probing.normalise_title(value)


class PasteMethod(StrEnum):
    """How the seed gets into the composer.

    `insert_text` is CDP `Input.insertText` — what Playwright's
    `keyboard.insertText` uses, and it bypasses the paste handler that turns a
    large clipboard paste into a "pasted text" attachment. `exec_command` is the
    fallback for a composer that ignores the CDP input event. `10` measures both
    against the real page and owns the default from then on.
    """

    INSERT_TEXT = "insert_text"
    EXEC_COMMAND = "exec_command"


# --------------------------------------------------------------------------- #
# Choosing the tab, and holding it
# --------------------------------------------------------------------------- #


def surface_tabs(client: CdpClient, surface: Surface = CLAUDE) -> list[Target]:
    """Every page target on the surface's host, in the browser's own order."""
    return [item for item in client.pages() if item.host == surface.host]


def chosen_tab(client: CdpClient, *, target_id: str | None = None, surface: Surface = CLAUDE) -> Target | Failure:
    """Return the one tab to drive, or the refusal that says why there isn't one.

    `--target` names a tab outright, for the case the operator or `10` has two
    open on purpose. Everything else is: exactly one, or no.
    """
    if target_id is not None:
        found = next((item for item in client.pages() if item.id == target_id), None)
        if found is None:
            return Failure(error=UNKNOWN_TARGET, detail=log.safe_token(target_id))
        return found
    tabs = surface_tabs(client, surface)
    if not tabs:
        return Failure(error=NO_CLAUDE_TAB)
    if len(tabs) > 1:
        return Failure(
            error=AMBIGUOUS_TAB,
            tabs=tuple(TabRef(id=item.id, url=item.url) for item in tabs),
        )
    return tabs[0]


@contextmanager
def driving(client: CdpClient, target: Target, surface: Surface = CLAUDE) -> Iterator[Page]:
    """Attach to a tab that is inside the surface, and let go of it afterwards.

    The gate is applied twice. First to the URL in the target list, so a tab at
    `/settings/profile` is refused without a single CDP call being made against
    it. Then to the live URL, because the target list is a snapshot and a page
    that has since redirected to a login screen is not the page we were
    promised.
    """
    guard(target.url, surface)
    page = client.attach(target.id)
    try:
        guard(page.url, surface)
        yield page
    finally:
        page.close()


# --------------------------------------------------------------------------- #
# The helpers
# --------------------------------------------------------------------------- #


def probe_page(
    client: CdpClient,
    settings: Settings,
    *,
    target: str | None = None,
    expect: Sequence[str] = (),
    messages: bool = False,
    expect_title: str | None = None,
    surface: Surface = CLAUDE,
) -> Outcome:
    """`browser probe`: the page state, and what the last message says.

    `--messages` (`17`) widens it to every turn on the page and the title, which
    is what one verification needs and what a poll loop has no use for.
    `--expect-title` is the only question that may be asked about the title, for
    the reason `--expect` is the only question that may be asked about a message.
    """
    tab = chosen_tab(client, target_id=target, surface=surface)
    if isinstance(tab, Failure):
        return Outcome(tab)
    count = len(surface_tabs(client, surface))
    extra: dict[str, object] = {}
    with driving(client, tab, surface) as page:
        if messages or expect_title is not None:
            report = probing.page_report(
                page,
                tab_count=max(count, 1),
                expect=expect,
                expect_title=normalised_title(expect_title),
            )
            view: probing.PageView = report
            extra = {"messages": report.messages, "title": report.title}
        else:
            view = probing.page_view(page, tab_count=max(count, 1), expect=expect)
    return Outcome(
        ProbeResult(**view.state.model_dump(), last_message=view.last_message, **extra),
        conversation_id=view.state.conversation_id,
    )


def paste_seed(  # ruff: ignore[too-many-return-statements] - one return per way a paste can end
    client: CdpClient,
    settings: Settings,
    *,
    seed: Path,
    method: PasteMethod = PasteMethod.INSERT_TEXT,
    append: bool = False,
    target: str | None = None,
    surface: Surface = CLAUDE,
) -> Outcome:
    """`browser paste`: a seed into the composer, byte for byte, verified."""
    started = time.monotonic()
    text = _read_seed(seed)
    if isinstance(text, Failure):
        return Outcome(text, usage=True)

    tab = chosen_tab(client, target_id=target, surface=surface)
    if isinstance(tab, Failure):
        return Outcome(tab)
    conversation_id = probing.conversation_id_of(tab.url)
    with driving(client, tab, surface) as page:
        state = probing.probe(page)
        if not state.composer_present:
            return Outcome(Failure(error=COMPOSER_MISSING), conversation_id)
        if state.composer_chars > 0 and not append:
            return Outcome(
                Failure(error=COMPOSER_NOT_EMPTY, observed_chars=state.composer_chars),
                conversation_id,
            )

        prior = _composer_text(page) if append else ""
        if prior is None:
            return Outcome(Failure(error=COMPOSER_MISSING), conversation_id)
        if not page.evaluate(FOCUS_JS):
            # The composer was there a moment ago and will not take the caret
            # now. Inserting anyway would type the seed into whatever did.
            return Outcome(Failure(error=COMPOSER_MISSING), conversation_id)

        if method is PasteMethod.INSERT_TEXT:
            page.insert_text(text)
        else:
            page.evaluate(exec_command_js(text))

        observed_raw = _composer_text(page)
        if observed_raw is None:
            return Outcome(Failure(error=COMPOSER_MISSING), conversation_id)
        expected = normalise(prior + text)
        observed = normalise(observed_raw)
        expected_digest = sha256_of(expected)
        observed_digest = sha256_of(observed)
        elapsed_ms = round((time.monotonic() - started) * 1000)
        if observed_digest != expected_digest:
            return Outcome(
                Failure(
                    error=TEXT_MISMATCH,
                    expected_sha256=expected_digest,
                    observed_sha256=observed_digest,
                    observed_chars=len(observed),
                ),
                conversation_id,
            )
        _logger.info(
            "seed pasted",
            extra={
                "chars": len(expected),
                "method": str(method),
                "elapsed_ms": elapsed_ms,
            },
        )
        return Outcome(
            PasteResult(
                chars=len(expected),
                sha256=expected_digest,
                method=str(method),
                elapsed_ms=elapsed_ms,
            ),
            conversation_id,
        )


def attach_file(
    client: CdpClient,
    settings: Settings,
    *,
    file: Path,
    target: str | None = None,
    surface: Surface = CLAUDE,
    poll_s: float | None = None,
) -> Outcome:
    """`browser attach`: a file into the upload input, confirmed by its chip."""
    interval = CHIP_POLL_S if poll_s is None else poll_s
    path = Path(file)
    if not path.is_file():
        return Outcome(
            Failure(error=FILE_NOT_FOUND, detail=log.safe_token(str(file))),
            usage=True,
        )
    # The name is export-derived and reaches stdout, so it goes through the same
    # reduction every other borrowed string does.
    name = path.name
    size = path.stat().st_size

    tab = chosen_tab(client, target_id=target, surface=surface)
    if isinstance(tab, Failure):
        return Outcome(tab)
    conversation_id = probing.conversation_id_of(tab.url)
    with driving(client, tab, surface) as page:
        if not page.evaluate(FILE_INPUT_JS):
            return Outcome(Failure(error=INPUT_NOT_FOUND), conversation_id)
        try:
            page.set_file_input_files(probing.FILE_INPUT_SELECTOR, [path])
        except BrowserError as exc:
            # The input is there and the browser would not take the file:
            # too large, a type it refuses, a path it cannot read.
            return Outcome(Failure(error=UPLOAD_REJECTED, detail=exc.detail), conversation_id)

        deadline = time.monotonic() + settings.timeouts.attach_s
        expression = chip_js(name)
        while True:
            if page.evaluate(expression):
                return Outcome(
                    AttachResult(file_name=log.safe_token(name), bytes=size),
                    conversation_id,
                )
            if time.monotonic() >= deadline:
                return Outcome(
                    Failure(error=CHIP_NOT_FOUND, detail=log.safe_token(name)),
                    conversation_id,
                )
            time.sleep(interval)


def attached_files(
    client: CdpClient,
    settings: Settings,
    *,
    files: Sequence[Path],
    target: str | None = None,
    surface: Surface = CLAUDE,
) -> Outcome:
    """`browser attachments`: every one of these files has a chip, or which does not.

    `16`'s check before the first paste. `attach` already proved each upload one
    at a time; this proves they are *all* still there in one look, which is the
    thing that matters at the moment the message is about to be sent — a chip
    that was dropped while the next file was being uploaded is a file the chat
    will not carry, and nothing else would notice.

    `settings` is unused and is taken anyway: every helper in this module has the
    same shape, and `cli.emit_helper` passes both. There is nothing to wait for
    here — `attach` has already waited for each chip — so there is no timeout to
    read.
    """
    names = [Path(item).name for item in files]
    if not names:
        # Nothing to look for. Asking about no files is a question with a true
        # answer, not a usage error: it is what a conversation with no
        # attachments would ask, and refusing it would make the skill branch.
        return Outcome(ChipsResult(file_names=(), count=0))

    tab = chosen_tab(client, target_id=target, surface=surface)
    if isinstance(tab, Failure):
        return Outcome(tab)
    conversation_id = probing.conversation_id_of(tab.url)
    with driving(client, tab, surface) as page:
        found = page.evaluate(chips_js(names))
        present = [str(item) for item in found] if isinstance(found, list) else []
        missing = [name for name in names if name not in present]
        if missing:
            return Outcome(
                Failure(
                    error=CHIP_NOT_FOUND,
                    detail=log.safe_token(", ".join(missing)),
                ),
                conversation_id,
            )
        return Outcome(
            ChipsResult(
                file_names=tuple(log.safe_token(name) for name in present),
                count=len(present),
            ),
            conversation_id,
        )


def await_response(
    client: CdpClient,
    settings: Settings,
    *,
    timeout: float | None = None,
    expect: Sequence[str] = (),
    target: str | None = None,
    surface: Surface = CLAUDE,
    poll_s: float | None = None,
) -> Outcome:
    """`browser await-response`: wait until Claude has finished answering.

    Three conditions, all of which must hold at once, three polls running: the
    page says it is not generating, the last turn is the assistant's, and its
    length has stopped changing. The first alone is not enough — the Stop button
    goes away before the last token lands — and the third alone would fire on a
    transcript that has not started rendering.
    """
    limit = settings.timeouts.response_s if timeout is None else timeout
    interval = RESPONSE_POLL_S if poll_s is None else poll_s
    started = time.monotonic()

    tab = chosen_tab(client, target_id=target, surface=surface)
    if isinstance(tab, Failure):
        return Outcome(tab)
    with driving(client, tab, surface) as page:
        stable = 0
        seen = -1
        while True:
            # No tab count: this reads the same page every second and the
            # target list is an HTTP round trip for a number nothing here
            # prints. What is printed is the last message and the id.
            view = probing.page_view(page, expect=expect)
            # The URL is re-checked every poll because submitting a seed moves
            # the tab from `/new` to `/chat/<uuid>`, and anywhere else is a
            # redirect we must not keep watching.
            guard(view.state.url, surface)
            settled = not view.state.generating and view.last_message.role == "assistant"
            if settled and view.last_message.chars == seen:
                stable += 1
            elif settled:
                stable = 1
                seen = view.last_message.chars
            else:
                stable = 0
                seen = -1
            elapsed = time.monotonic() - started
            if stable >= STABLE_POLLS:
                return Outcome(
                    AwaitResult(
                        elapsed_s=round(elapsed, 1),
                        conversation_id=view.state.conversation_id,
                        last_message=view.last_message,
                    ),
                    view.state.conversation_id,
                )
            if elapsed >= limit:
                return Outcome(
                    Failure(
                        error=RESPONSE_TIMEOUT,
                        elapsed_s=round(elapsed, 1),
                        generating=view.state.generating,
                    ),
                    view.state.conversation_id,
                )
            time.sleep(interval)


def close_extra_tabs(client: CdpClient, settings: Settings, *, surface: Surface = CLAUDE) -> Outcome:
    """`browser close-extra-tabs`: tidy up, and never close a conversation.

    The only tabs this closes are blank ones and the second and later new-chat
    tabs, so it needs no target of its own — which is just as well, since the
    state it exists to clear up is the one that makes choosing a target
    ambiguous. A `/chat/<uuid>` tab is never a candidate, whatever else is open.
    """
    closed = 0
    kept_new_chat = False
    for target in client.pages():
        if target.url in BLANK_URLS:
            client.close_target(target.id)
            closed += 1
            continue
        if target.host != surface.host:
            continue
        if probing.kind_of(target.url) is not probing.PageKind.NEW_CHAT:
            continue
        if kept_new_chat:
            client.close_target(target.id)
            closed += 1
        else:
            kept_new_chat = True
    if closed:
        _logger.info("extra tabs closed", extra={"closed": closed})
    return Outcome(CloseResult(closed=closed))


def _read_seed(seed: Path) -> str | Failure:
    path = Path(seed)
    if not path.is_file():
        return Failure(error=SEED_NOT_FOUND, detail=log.safe_token(str(seed)))
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return Failure(error=SEED_UNREADABLE, detail=f"{log.safe_token(str(seed))}: {exc}")


def _composer_text(page: Page) -> str | None:
    """Return the composer's text, or `None` if there is no composer any more."""
    value = page.evaluate(COMPOSER_TEXT_JS)
    return value if isinstance(value, str) else None


# --------------------------------------------------------------------------- #
# Running one, and writing down that it ran
# --------------------------------------------------------------------------- #


def run(
    settings: Settings,
    helper: str,
    work: Callable[[CdpClient, Settings], Outcome],
) -> Emission:
    """Run one helper and reduce it to a line and an exit code.

    Every failure a helper can meet ends up as `{"ok": false, ...}` here rather
    than as a message on stderr: Hermes reads one object per call, so a browser
    that has gone away has to be reportable in the same shape as a composer that
    is not empty. Only a bug in us escapes, and `cli` turns that into exit `70`.
    """
    client = CdpClient(port=settings.browser.cdp_port, timeout=settings.timeouts.cdp_call_s)
    started = time.monotonic()
    try:
        outcome = work(client, settings)
    except SafetyError as exc:
        # The wall, and the one refusal that is raised rather than returned:
        # nothing after the gate may run, and a `return` can be forgotten.
        outcome = Outcome(Failure(error=OUTSIDE_MIGRATION_SURFACE, url=exc.detail or ""))
    except MigrationError as exc:
        outcome = Outcome(
            Failure(
                error=str(exc.category),
                detail=exc.detail or type(exc).__name__,
            )
        )
    elapsed_ms = round((time.monotonic() - started) * 1000)
    record_action(
        settings.workspace,
        helper,
        ok=outcome.ok,
        elapsed_ms=elapsed_ms,
        conversation_id=outcome.conversation_id,
    )
    return Emission(
        text=outcome.result.model_dump_json(exclude_none=True),
        exit_code=outcome.exit_code,
    )


def actions_path(workspace: Path) -> Path:
    return workspace / log.LOGS_DIRNAME / ACTIONS_FILENAME


def count_actions(workspace: Path) -> int:
    """How many records `logs/actions.jsonl` holds.

    The number `19` reports as `Browser actions`, and the one `12` bumps
    `run.json`'s counter by after every conversation. Blank lines are not
    records; a file that is not there is no actions at all, which is what a
    workspace nothing has run in should say rather than an error.
    """
    try:
        with Path(actions_path(workspace)).open(encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return 0


def record_action(
    workspace: Path,
    helper: str,
    *,
    ok: bool,
    elapsed_ms: int,
    conversation_id: str | None = None,
    url: str | None = None,
    selector: str | None = None,
) -> None:
    """Append one line to `<workspace>/logs/actions.jsonl`.

    Best effort: a workspace that cannot be written to is worth a warning, not a
    lost result. The helper has already acted on the page by the time this runs,
    and `19` counting one action fewer is a smaller loss than Hermes never
    learning what happened.

    `url` and `selector` are `31`'s: an ask is two clicks on a page no helper
    may touch, and what it clicked is worth writing down. Omitted from the record
    rather than written as `null`, so a helper's line keeps the five keys it has
    always had and `19` reads the same file either way. Neither is content —
    the URL is the export page's and the selector is ours — and the element's
    own text is never recorded at all.
    """
    record: dict[str, object] = {
        "ts": utcnow().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "helper": helper,
        "ok": ok,
        "elapsed_ms": elapsed_ms,
        "conversation_id": conversation_id,
    }
    record.update({key: value for key, value in (("url", url), ("selector", selector)) if value})
    path = actions_path(workspace)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with Path(path).open("a", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError as exc:
        _logger.warning("actions log not written", extra={"reason": str(exc)})
