"""The one place that knows what claude.ai looks like.

Everything else in this package is about *a* browser. This module is about *the*
page: which of the four states it is in, whether a composer is there, whether
Claude is generating, whether something is in the way. `08`'s helpers, `11`'s
step protocol and `17`'s verification all decide by reading a `PageState`, so
when the UI changes, this file is the one that changes.

Two rules shape it:

- **Nothing here reads content.** `composer_chars` is a length; `dialogs` names a
  kind, never a message; `last_message` reports a role, a length and which of the
  caller's own `--expect` strings were found — the matching happens in the page,
  so the message text never crosses the wire. Nothing returns a title or a
  message body. §10 forbids content on stdout and in logs, and `08` prints these
  objects to stdout verbatim. `17` needed the chat's *title* and is held to the
  same rule: `TitleMatch` is a length and an answer to "is it this string", with
  the string supplied by the caller and the comparison made in the page.
- **One round trip.** The whole DOM question is a single `Runtime.evaluate`, so a
  probe cannot observe a half-changed page across several calls, and polling
  every two seconds for ten minutes costs 300 CDP calls rather than 1,800.
  `page_view` keeps that true for `08`'s poll loop: state and last message come
  back together.

`08` needs the composer itself and not only facts about it — its text, its focus,
a file input beside it. Those expressions live in `helpers`, because they handle
content and this module does not; what they share with the state expression is
`PRELUDE_JS` and the selector constants below, so there is still exactly one
place that names an element of claude.ai.

`10` is the slice that checks these signals against the real application and
owns the selectors from then on. Until it does, they are informed guesses and
are written here in one place so that correcting them is a small edit.
`docs/claude-ui-map.md` is where each of them is recorded as observed or still
guessed; when that file and this one disagree, that file is the one that looked.
"""

import json
import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Any, Literal, Self
from urllib.parse import urlparse

from orval import deep_get
from pydantic import BaseModel, ConfigDict

from dataporter import log
from dataporter.browser.cdp import Page

_logger = log.get_logger(__name__)

CLAUDE_HOST = "claude.ai"
NEW_CHAT_URL = f"https://{CLAUDE_HOST}/new"

_CHAT_PATH = re.compile(
    r"^/chat/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?$",
    re.IGNORECASE,
)
_NEW_CHAT_PATHS = frozenset({"/", "/new"})

DIALOG_OPENING = "Page.javascriptDialogOpening"
DIALOG_CLOSED = "Page.javascriptDialogClosed"


# --------------------------------------------------------------------------- #
# What an element of claude.ai is called
# --------------------------------------------------------------------------- #

COMPOSER_SELECTOR = 'div[contenteditable="true"]'
"""The prompt box. A ProseMirror-style `contenteditable`, not a `textarea`."""

HUMAN_MESSAGE_SELECTOR = '[data-testid="user-message"]'
ASSISTANT_MESSAGE_SELECTOR = '[data-testid="assistant-message"]'
MESSAGE_SELECTOR = f"{HUMAN_MESSAGE_SELECTOR}, {ASSISTANT_MESSAGE_SELECTOR}"
"""A turn in the transcript. Role is read by which of the two an element
matches, so the union must stay the union of exactly those two."""

TITLE_SELECTOR = (
    '[data-testid="chat-menu-trigger"], [data-testid="conversation-title"], '
    "header h1, header h2"
)
"""Where the chat's displayed title is shown (`17`).

A union, widest guess last, because the title is the one element of the page we
read without knowing what it is called: `docs/claude-ui-map.md` marks the row
`*unknown*`, and the fallback when none of these matches is `document.title`,
which a browser always has. Nothing reads what it *says* — see `TitleMatch`.
"""

FILE_INPUT_SELECTOR = 'input[type="file"]'
"""`08`'s `attach` puts files here. Hidden is normal and is fine: the element is
found by selector and filled by CDP, never clicked."""

_SELECTORS: tuple[tuple[str, str], ...] = (
    ("COMPOSER_SELECTOR", COMPOSER_SELECTOR),
    ("HUMAN_MESSAGE_SELECTOR", HUMAN_MESSAGE_SELECTOR),
    ("MESSAGE_SELECTOR", MESSAGE_SELECTOR),
    ("TITLE_SELECTOR", TITLE_SELECTOR),
    ("FILE_INPUT_SELECTOR", FILE_INPUT_SELECTOR),
)
"""The selectors, as JavaScript consts. Injected rather than interpolated into
each expression, so the Python constant above is the only spelling of each."""

PRELUDE_JS = (
    "".join(f"  const {name} = {json.dumps(value)};\n" for name, value in _SELECTORS)
    + """\
  const visible = (el) =>
    !!el &&
    (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0);
  const all = (selector) =>
    Array.prototype.slice.call(document.querySelectorAll(selector));
  const composer = all(COMPOSER_SELECTOR).filter(visible)[0] || null;
  const blockText = (el) => {
    if (!el) return '';
    const lines = [];
    let inline = '';
    const flush = () => { lines.push(inline); inline = ''; };
    for (const node of Array.prototype.slice.call(el.childNodes)) {
      if (node.nodeType === 3) { inline += node.nodeValue || ''; continue; }
      if (node.nodeType !== 1) continue;
      if (node.nodeName === 'BR') { flush(); continue; }
      if (getComputedStyle(node).display === 'inline') {
        inline += node.textContent || '';
        continue;
      }
      if (inline !== '') flush();
      lines.push((node.innerText || '').replace(/\\n+$/, ''));
    }
    if (inline !== '' || lines.length === 0) flush();
    return lines.join('\\n');
  };
  const composerText = () => blockText(composer);
"""
)
"""What every expression in this package starts with: the selectors, a few
helpers, and the composer. `08`'s expressions open with it too, which is what
makes "the element `paste` types into" and "the element `probe` counts" the same
element by construction.

`blockText` is the one piece of it with a finding behind it, measured against
Chromium 141 while `08` was built. The composer's text is **not** its
`innerText`: a rich-text editor keeps one block element per line, and
`innerText` is worth *two* line breaks at a `<p>` boundary and two more for an
empty `<p><br></p>`, so a seed with a blank line in it comes back with three.
What this reads instead is the editor's own plain-text projection — one line per
block, a `<br>` as a line break, inline elements folded into the line they are
in — which round-trips both shapes an editable takes: a paragraph per line, and
the leading bare text node plus `<div>`s that Chrome's native editing produces.
It is also why an empty ProseMirror composer, which holds `<p><br></p>` and
whose `innerText` is therefore `"\\n"`, reads here as the empty string it looks
like. `10` checks it against the real composer.
"""

PAGE_STATE_TAG = "hcm:page_state"
PAGE_VIEW_TAG = "hcm:page_view"
PAGE_REPORT_TAG = "hcm:page_report"


def expression(tag: str, body: str) -> str:
    """One page expression: the shared prelude, then `body`, as an IIFE.

    `tag` is written into a leading comment. It costs nothing in the page, it
    names the expression in a CDP trace, and it is how the test suite's fake
    browser tells one expression from another without running it.
    """
    return f"(() => {{\n  /* {tag} */\n{PRELUDE_JS}{body}\n}})()"


_STATE_OBJECT = """(() => {
    const buttons = all('button').filter(visible);
    const label = (b) => (b.getAttribute('aria-label') || '') + '';
    const labelled = (needle) =>
      buttons.filter((b) => label(b).indexOf(needle) !== -1);
    const disabled = (b) =>
      b.disabled === true || b.getAttribute('aria-disabled') === 'true';
    return {
      url: location.href,
      composer_present: composer !== null,
      composer_chars: composerText().length,
      generating: labelled('Stop').length > 0,
      send_enabled: labelled('Send').some((b) => !disabled(b)),
      dom_dialogs: all('[role="dialog"]').filter(visible).length,
    };
  })()"""
"""No content, only facts about it.

`composer_chars` counts what `08`'s `paste` would read back — see `blockText` in
the prelude — so that "the composer is empty" and "the seed went in whole" are
answers to the same question and cannot disagree.
"""

_LAST_MESSAGE_OBJECT = """(() => {
    const turns = all(MESSAGE_SELECTOR).filter(visible);
    const last = turns.length === 0 ? null : turns[turns.length - 1];
    const text = last === null ? '' : (last.innerText || '');
    return {
      role: last === null
        ? null
        : (last.matches(HUMAN_MESSAGE_SELECTOR) ? 'human' : 'assistant'),
      chars: text.length,
      contains: expect.filter((needle) => text.indexOf(needle) !== -1),
    };
  })()"""
"""The last turn, as a role, a length and an answer to the caller's question.

`contains` is computed here rather than by returning the text and searching it
in Python, because a returned message is content on the wire and in whatever
holds it next. What comes back is the caller's own strings, filtered.
"""

_MESSAGES_ARRAY = """(() => {
    const turns = all(MESSAGE_SELECTOR).filter(visible);
    return turns.map((el) => {
      const text = el.innerText || '';
      return {
        role: el.matches(HUMAN_MESSAGE_SELECTOR) ? 'human' : 'assistant',
        chars: text.length,
        contains: expect.filter((needle) => text.indexOf(needle) !== -1),
      };
    });
  })()"""
"""Every turn on the page, in order, each one shaped like `_LAST_MESSAGE_OBJECT`.

`17` asks the page three questions at once — are there as many human messages as
there were parts, does the first one carry the source id, has every part been
acknowledged — and all three are "which of my strings are in which turn". So the
answer is the caller's own strings, filtered, once per turn: the same reduction
the last message already got, applied to the whole transcript.
"""

_TITLE_OBJECT = """(() => {
    const el = all(TITLE_SELECTOR).filter(visible)[0] || null;
    const raw = el === null
      ? (document.title || '')
      : (el.innerText || el.textContent || '');
    const squashed = raw.replace(/\\s+/g, ' ').trim();
    return {
      chars: squashed.length,
      source: el === null ? 'document' : 'chat',
      matches: expectTitle === null ? null : squashed === expectTitle,
    };
  })()"""
"""The chat's title, as a length and a yes/no. Never as a title.

Whitespace is squashed on this side of the wire and on ours (`normalise_title`),
because the rename field takes what it is given and the header renders it with
whatever spacing the layout wants — a title that came back with two spaces in it
is the title, not a failed rename.

`source` says which of the two places it was read from, so that a run whose
`TITLE_SELECTOR` matches nothing on a changed claude.ai is visible as a page
answering `document` rather than as a title that will not match. It is a
provenance, not a value: `docs/claude-ui-map.md` is where the row gets corrected.
"""

PAGE_STATE_JS = expression(PAGE_STATE_TAG, f"  return {_STATE_OBJECT};")


def _expect_const(expect: Sequence[str]) -> str:
    """`expect` as a JavaScript const. Empty strings are dropped: `indexOf('')`
    is 0 on every string, so one would report itself as found in anything."""
    return f"  const expect = {json.dumps([item for item in expect if item])};\n"


def page_view_js(expect: Sequence[str] = ()) -> str:
    """State and last message in one evaluate, so a poll sees one moment."""
    return expression(
        PAGE_VIEW_TAG,
        _expect_const(expect)
        + f"  return Object.assign({{}}, {_STATE_OBJECT}, "
        + f"{{last_message: {_LAST_MESSAGE_OBJECT}}});",
    )


def page_report_js(expect: Sequence[str] = (), expect_title: str | None = None) -> str:
    """`page_view`, plus every message and the title (`17`).

    Still one evaluate, for the reason `page_view` is one: a verification that
    read the transcript and then the title would be describing two moments, and
    the one thing it exists to prove is that a single page holds all of it.
    """
    return expression(
        PAGE_REPORT_TAG,
        _expect_const(expect)
        + f"  const expectTitle = {json.dumps(expect_title)};\n"
        + f"  return Object.assign({{}}, {_STATE_OBJECT}, {{\n"
        + f"    last_message: {_LAST_MESSAGE_OBJECT},\n"
        + f"    messages: {_MESSAGES_ARRAY},\n"
        + f"    title: {_TITLE_OBJECT},\n"
        + "  });",
    )


def normalise_title(value: str) -> str:
    """A title, as both sides of the comparison spell it.

    The rule is one line and it lives here rather than in `17` because the other
    half of it is `_TITLE_OBJECT`, three lines up: whatever changes here changes
    there.
    """
    return " ".join(value.split())


# --------------------------------------------------------------------------- #
# What one look at the page saw
# --------------------------------------------------------------------------- #


class PageKind(StrEnum):
    """Where the browser is, as far as this tool is concerned."""

    LOGIN = "login"
    NEW_CHAT = "new_chat"
    CHAT = "chat"
    OTHER = "other"


class PageState(BaseModel):
    """What one probe saw. `08` prints this as its JSON object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    kind: PageKind
    logged_in: bool
    composer_present: bool
    composer_chars: int
    generating: bool
    send_enabled: bool
    dialogs: tuple[str, ...]
    conversation_id: str | None
    tab_count: int


class LastMessage(BaseModel):
    """One turn in the transcript, with no turn in it.

    `role` is `null` on a page with no messages — a new chat, or one whose
    transcript has not rendered yet. `contains` is the caller's `--expect`
    strings that were found, which is how `11` reads an acknowledgement line
    without anyone reading the message.

    Named for the one turn `08` needed and used for all of them since: `17`'s
    `messages` is a list of exactly this shape, because "which of my strings are
    in this turn" is the same question asked further up the page.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["human", "assistant"] | None
    chars: int
    contains: tuple[str, ...]

    @classmethod
    def from_raw(cls, raw: Any) -> Self:
        """Build one from whatever the page answered with.

        Tolerant in the same way `probe` is: a page that answers with nothing —
        an error page, a document that has not rendered — reads as "no message"
        rather than raising.
        """
        if not isinstance(raw, dict):
            raw = {}
        role = raw.get("role")
        found = raw.get("contains")
        return cls(
            role=role if role in ("human", "assistant") else None,
            chars=int(raw.get("chars") or 0),
            contains=tuple(str(item) for item in found)
            if isinstance(found, list)
            else (),
        )


class TitleMatch(BaseModel):
    """What the chat is called, without saying what the chat is called (`17`).

    `matches` is `None` when the caller asked no question — `probe --messages`
    with no `--expect-title` — and a `bool` when it did. A length and a
    provenance beside it, so an operator reading a failed rename can tell "the
    title is something else" from "there is no title element on this page at
    all", neither of which requires the title itself.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    chars: int
    source: Literal["chat", "document"]
    matches: bool | None = None

    @classmethod
    def from_raw(cls, raw: Any) -> Self:
        """Build one from whatever the page answered with, tolerantly.

        A page with no title element and no `document.title` is an empty title
        read from the document, which is what an unrendered chat looks like —
        and reading it as a match would be `17` verifying a rename against
        nothing.
        """
        if not isinstance(raw, dict):
            raw = {}
        matches = raw.get("matches")
        return cls(
            chars=int(raw.get("chars") or 0),
            source="chat" if raw.get("source") == "chat" else "document",
            matches=matches if isinstance(matches, bool) else None,
        )


class PageView(BaseModel):
    """One evaluate's worth: the state, and the last message beside it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: PageState
    last_message: LastMessage


class PageReport(PageView):
    """The same, plus every turn and the title: what `17` verifies from.

    A subclass of `PageView` rather than a second model, so that the one thing
    `08`'s poll loop and `17`'s verification disagree about is how much of the
    page they asked for.
    """

    messages: tuple[LastMessage, ...]
    title: TitleMatch

    def with_role(self, role: str) -> tuple[LastMessage, ...]:
        """The turns one side of the conversation took, in page order."""
        return tuple(item for item in self.messages if item.role == role)


# --------------------------------------------------------------------------- #
# Reading the URL
# --------------------------------------------------------------------------- #


def path_of(url: str) -> str:
    """The path of an http(s) URL, without the query.

    `""` for everything else — `about:blank`, `chrome://newtab/`, a `file:` URL —
    so that a browser sitting on a blank tab is `other` and never `new_chat`.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return ""
    return parsed.path or "/"


def kind_of(url: str) -> PageKind:
    """Which of the four states a URL names.

    Path only, and never the host: the fixtures the probe is tested against are
    served from `127.0.0.1`, and the rule that keeps the tool on claude.ai is
    `08`'s safety gate, which is a separate thing from reading where we are.
    """
    path = path_of(url)
    if path.startswith("/login"):
        return PageKind.LOGIN
    if path in _NEW_CHAT_PATHS:
        return PageKind.NEW_CHAT
    if _CHAT_PATH.match(path):
        return PageKind.CHAT
    return PageKind.OTHER


def conversation_id_of(url: str) -> str | None:
    """The uuid in `/chat/<uuid>`, or `None`."""
    match = _CHAT_PATH.match(path_of(url))
    return match.group(1) if match else None


# --------------------------------------------------------------------------- #
# Reading the page
# --------------------------------------------------------------------------- #


def pending_dialogs(page: Page) -> list[str]:
    """The JavaScript dialogs that have opened and not yet closed.

    Kinds only — `alert`, `confirm`, `prompt`, `beforeunload` — never the
    message, which is page text and therefore content. Openings and closings are
    matched by order because CDP gives no dialog identity; a dialog reported as
    open when it is not costs one `07` poll, and the opposite would let a run
    walk into a modal.
    """
    page.drain()
    opened = page.events(DIALOG_OPENING)
    closed = page.events(DIALOG_CLOSED)
    return [
        "javascript:" + log.safe_token(str(deep_get(item, "params.type", "dialog")))
        for item in opened[len(closed) :]
    ]


def rate_limited(state: PageState) -> bool | None:
    """Whether the page still refuses to send, as far as a probe can tell (`15`).

    Three answers, because the page really does give three. The skill's own
    signal for a rate limit (`11`, *Recovery*) is a send control that is disabled
    beside a composer that is *not* empty — a seed that was pasted and would not
    go — and that is `True` here. A send control that is enabled is `False`: the
    page will take a submit, whatever banner it is still showing. An empty
    composer with nothing to send is `None`, because that is what an idle new
    chat looks like and reading it as "the limit lifted" would end a wait the
    account asked for on no evidence at all.

    `15` waits out the whole `retry_after_s` on `None`, so the only thing this
    buys today is noticing a limit that lifted early — and only when the composer
    still holds the part that could not be sent. `docs/claude-ui-map.md` records
    the row as `*unknown*`: nobody has watched claude.ai do this, and when `20`
    does, this function is where the observation lands.
    """
    if state.send_enabled:
        return False
    if state.composer_chars > 0:
        return True
    return None


def _state_from(page: Page, raw: Any, tab_count: int) -> PageState:
    """Turn one evaluate's answer into a `PageState`."""
    if not isinstance(raw, dict):  # pragma: no cover - defensive
        raw = {}
    url = str(raw.get("url") or page.target.url)
    kind = kind_of(url)
    composer_present = bool(raw.get("composer_present"))
    dialogs = pending_dialogs(page) + ["dom"] * int(raw.get("dom_dialogs") or 0)
    state = PageState(
        url=url,
        kind=kind,
        # Not "who is logged in": §8 asks for the signed-in *state*, and reading
        # the account would mean reading the page's text.
        logged_in=kind is not PageKind.LOGIN and composer_present,
        composer_present=composer_present,
        composer_chars=int(raw.get("composer_chars") or 0),
        generating=bool(raw.get("generating")),
        send_enabled=bool(raw.get("send_enabled")),
        dialogs=tuple(dialogs),
        conversation_id=conversation_id_of(url),
        tab_count=tab_count,
    )
    # The URL is not logged: a claude.ai chat URL carries only a uuid, but this
    # probe also runs against fixtures and, one day, against a mistyped address.
    _logger.debug(
        "probe",
        extra={
            "kind": str(state.kind),
            "logged_in": state.logged_in,
            "generating": state.generating,
            "dialogs": len(state.dialogs),
        },
    )
    return state


def probe(page: Page, *, tab_count: int = 1) -> PageState:
    """Read the page. One CDP evaluate, plus whatever events are already queued.

    `tab_count` is the caller's: a page cannot see its siblings, and the count
    that matters — claude.ai tabs — is a question for the target list.
    """
    return _state_from(page, page.evaluate(PAGE_STATE_JS), tab_count)


def _messages_from(raw: Any) -> tuple[LastMessage, ...]:
    """The `messages` array as models, or nothing at all.

    Tolerant for the reason `LastMessage.from_raw` is: a page that answered with
    something other than a list has no readable transcript, and `17` reports
    that as a failed check rather than as an exception out of a probe.
    """
    if not isinstance(raw, list):
        return ()
    return tuple(LastMessage.from_raw(item) for item in raw)


def page_report(
    page: Page,
    *,
    tab_count: int = 1,
    expect: Sequence[str] = (),
    expect_title: str | None = None,
) -> PageReport:
    """State, last message, every message and the title. Still one evaluate."""
    raw = page.evaluate(page_report_js(expect, expect_title))
    if not isinstance(raw, dict):  # pragma: no cover - defensive
        raw = {}
    state = _state_from(page, raw, tab_count)
    return PageReport(
        state=state,
        last_message=LastMessage.from_raw(raw.get("last_message")),
        messages=_messages_from(raw.get("messages")),
        title=TitleMatch.from_raw(raw.get("title")),
    )


def page_view(
    page: Page, *, tab_count: int = 1, expect: Sequence[str] = ()
) -> PageView:
    """The same, plus the last message. Still one evaluate.

    `08`'s `probe` and `await-response` both need the pair, and asking twice
    would let generation finish between the two questions.
    """
    raw = page.evaluate(page_view_js(expect))
    state = _state_from(page, raw, tab_count)
    last = LastMessage.from_raw(
        raw.get("last_message") if isinstance(raw, dict) else None
    )
    return PageView(state=state, last_message=last)
