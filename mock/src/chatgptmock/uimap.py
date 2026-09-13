"""Which row of the UI map each state the mock can show comes from.

The mock invents no behaviour. Every page it serves is one or more rows of the
table in `docs/chatgpt-ui-map.md`, and this module is where the mock cites them,
so that "the mock does X" can always be answered with "because row Y says so".

Unlike the Claude map, whose rows were the tool's own guesses, this map's rows
come from what OpenAI documents about its site and what others have reported of
it, and each row's mark says which (§54, *Governed by its UI map*):

- A behaviour the mock needs and the map has no row for is added to the map
  first, marked *reported* if a source says so and *unknown* if none does.
  Adding it here without adding it there is the mistake
  `tests/test_chatgpt_uimap.py` exists to catch.
- A mock run never turns a *reported* or an *unknown* row *observed*. Only a
  person watching chatgpt.com does that — or reading a trace of a run against
  it (brief `04`, §49). The mock is a consequence of the map, never evidence
  about it.
- Where a row is *reported*, the mock serves the reported signal in the map's
  own spelling; where a row or a part of one is *unknown*, the mock takes the
  simplest behaviour the shape admits, and `WHAT_THE_MOCK_DOES` says what that
  was.
"""

from collections.abc import Mapping

ROWS: Mapping[str, str] = {
    # page → the rows it is built out of
    "landing": "signed out",
    "two hosts": "auth host",
    "email step": "email step",
    "password step": "password step",
    "other providers": "other providers",
    "no banner": "cookie banner",
    "new chat": "new chat",
    "conversation": "conversation",
    "composer": "composer present",
    "empty composer": "composer empty",
    "send button": "can submit",
    "stop button": "generating",
    "reply settled": "generation finished",
    "human turn": "human turn",
    "assistant turn": "assistant turn",
    "one reply": "interim assistant messages",
    "pasted text attachment": "paste over the threshold",
    "file input": "upload target",
    "attachment chip": "upload accepted",
    "sidebar entry": "chat title",
    "rename": "rename affordance",
    "profile menu": "settings",
    "export page": "export page",
    "export button": "export button",
    "export confirmation": "export confirmation",
    "export requested": "export requested",
    "second ask": "already requested",
    "download": "download needs session",
    "link lives": "link expired",
}
"""Each thing the mock can show, and the row of the map it comes from.

The keys are the mock's own words for its pages and controls; the values are the
row labels of the map's first column, undecorated: the table writes them in
backticks, and a citation that carried that decoration would rot the first time
a row was touched.
"""

WHAT_THE_MOCK_DOES: Mapping[str, str] = {
    "signed out": (
        "the site root is a landing page with a Log in button "
        '(button[data-testid="login-button"]) and a Sign up button that leads nowhere '
        "useful; every other path on the site redirects to /"
    ),
    "auth host": (
        "Log in goes to https://auth.openai.com/log-in; the email and password steps "
        "are served there, and a right pair comes back to "
        "https://chatgpt.com/auth/callback with a one-time code that the site turns "
        "into its session cookie — the simplest chain, since none was observed"
    ),
    "email step": (
        'a visible input[type="email"] and a Continue button on the auth host; Enter '
        "submits; exactly one configured address gets past it"
    ),
    "password step": (
        'a visible input[type="password"] and a Continue button; Enter submits; a wrong '
        "pair is refused back to the email step with an alert"
    ),
    "other providers": (
        "Continue with Google, Continue with Microsoft and Continue with Apple buttons "
        "that lead to a page nobody can sign in from, so a run that takes one fails"
    ),
    "cookie banner": "nothing — no source reports one, and the mock invents nothing",
    "new chat": (
        "/ signed in: an empty composer, a disabled send control, a hidden file input, "
        'and a New chat link, a[data-testid="create-new-chat-button"][href="/"]'
    ),
    "conversation": (
        "/c/<uuid>, a version-4 UUID: the whole thread, server-rendered, so a reload "
        'shows every turn; the sidebar links to it as a[href^="/c/"]'
    ),
    "composer present": (
        'a visible div#prompt-textarea[contenteditable="true"], ProseMirror-shaped: one '
        "<p> a line, white-space: pre-wrap — the shape before the redesign of "
        "September 2026, the map's highest-risk reported row"
    ),
    "composer empty": "the composer holds one empty paragraph after a submit",
    "can submit": (
        'button#composer-submit-button[data-testid="send-button"] with aria-label "Send '
        'prompt", disabled while nothing is typed, pasted or attached'
    ),
    "generating": (
        'the same button, its data-testid now "stop-button" and its aria-label "Stop '
        'streaming", until the reply is whole; pressing it stops the reply where it is'
    ),
    "generation finished": (
        "the reply is revealed in steps; at the last the control is send again and the "
        'turn carries a button[data-testid="copy-turn-action-button"] with aria-label '
        '"Copy response" — the page says the turn is finished, silence does not'
    ),
    "human turn": (
        'each submitted message is a div[data-message-author-role="user"] with its text '
        "in a .whitespace-pre-wrap, and a pasted text as a chip inside it"
    ),
    "assistant turn": 'each reply is a div[data-message-author-role="assistant"] with its text in a .markdown',
    "interim assistant messages": "nothing — one reply is one message, and it is the answer",
    "paste over the threshold": (
        "an insertion that takes the composer past 10,000 characters — a paste, or "
        "text the browser protocol inserts, since the trigger is unknown — becomes a "
        'chip outside the composer, "Pasted text", with a Show in text field button '
        "that puts the text back; what was typed stays in the composer, and the reply "
        "reads the pasted text too"
    ),
    "upload target": (
        'a hidden input[type="file"] behind button[data-testid="composer-plus-btn"] with '
        'aria-label "Add files and more", on every chat page'
    ),
    "upload accepted": (
        "a chip element outside the composer carrying the file's name, and not before the "
        "mock has read the bytes; the file belongs to the next message sent"
    ),
    "chat title": (
        'the chat\'s sidebar entry, #history a[aria-label="<title>"], its link text the '
        "title too; the document title; entries newest first"
    ),
    "rename affordance": (
        'the entry\'s options button, [data-testid="history-item-N-options"] with N its '
        "position, served visible rather than on hover, opens a menu holding Share, "
        'Rename, Archive and Delete as [role="menuitem"]s; Rename shows '
        'input[aria-label="Chat title"]; Enter confirms and Escape cancels; an empty '
        "name is not sent; the new title survives a reload"
    ),
    "settings": (
        'a profile button, [data-testid="profile-button"], opens a menu with Settings in '
        "it; /settings lists Data controls among its entries"
    ),
    "export page": (
        "/settings/data-controls — a page of its own, the path the slice picked — with "
        "the Improve the model for everyone switch on it and no composer; signed out it "
        "redirects to / like every page"
    ),
    "export button": "a visible Export button under an Export data heading",
    "export confirmation": (
        'pressing Export opens a [role="dialog"] holding a Confirm export button; nothing '
        "is asked of the site until that is pressed; the dialog's words are the mock's "
        "own, since none are documented"
    ),
    "export requested": (
        'confirming POSTs /api/exports, and a [role="status"] appears only once the ask '
        "is counted and a link minted — the link is printed where an email would be sent "
        "and listed at /__mock/exports on the mock's own host and port"
    ),
    "already requested": (
        "nothing — the export is ready at once, and a second ask adds a second link so "
        "that two extractions file two snapshots; the mock has no clock a request could "
        "still be processing on"
    ),
    "download needs session": (
        "the link is https://chatgpt.com/__mock/exports/<token>.zip, on the site's host "
        "because that is where the browser's session cookie is; the archive is served to "
        "the signed-in session and refused with 403 to anyone else, the listing stays "
        "open, and a token nobody minted is 404"
    ),
    "link expired": "nothing — a link lives until the process stops; the mock has no clock a link could die on",
}
"""What the mock does for each row, in one line.

This is the half of the citation that can be wrong in an interesting way: the
map says what the sources report chatgpt.com shows, and this says what the mock
decided that means. The mock's README quotes it, and a reader comparing the two
columns is reading the whole of the mock's claim to realism.
"""


def cited() -> list[str]:
    """Every map row the mock stands on, in one sorted list, without repeats."""
    return sorted(set(ROWS.values()))
