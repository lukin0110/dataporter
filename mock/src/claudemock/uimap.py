"""Which row of the UI map each state the mock can show comes from.

The mock invents no behaviour. Every page it serves is one or more rows of the
table in `docs/claude-ui-map.md` — the table that also governs the tool's probe —
and this module is where the mock cites them, so that "the mock does X" can
always be answered with "because row Y says so".

Two consequences worth stating, because they are what the citation is *for*:

- A behaviour the mock needs and the map has no row for is added to the map
  first, marked `*unknown*`. Adding it here without adding it there is the
  mistake `tests/test_uimap.py` exists to catch.
- A mock run never turns an `*unknown*` into an `*observed on <date>*`. Only a
  person watching the real claude.ai does that. The mock is a consequence of the
  map, never evidence about it.

Where a row is `*unknown*` — which today is all of them — the mock takes the
simplest behaviour the tool's code already accepts, and `WHAT_THE_MOCK_DOES`
below says what that was.
"""

from collections.abc import Mapping

ROWS: Mapping[str, str] = {
    # page → the rows it is built out of
    "login": "signed out",
    "sign-in form": "sign-in form",
    "new chat": "new chat",
    "conversation": "conversation",
    "composer": "composer present",
    "empty composer": "composer empty",
    "send button": "can submit",
    "stop button": "generating",
    "reply settled": "generation finished",
    "human turn": "human turn",
    "assistant turn": "assistant turn",
    "transcript": "every message",
    "file input": "upload target",
    "attachment chip": "upload accepted",
    "every chip": "every upload accepted",
    "title": "chat title",
    "rename": "rename affordance",
}
"""Each thing the mock can show, and the row of the map it comes from.

The keys are the mock's own words for its pages and controls; the values are the
row labels of the map's first column, undecorated: the table writes them in
backticks and sometimes with the slice that added them beside, and a citation
that had to carry that decoration would rot the first time a row was renumbered.
"""

WHAT_THE_MOCK_DOES: Mapping[str, str] = {
    "signed out": (
        "any page but /login redirects to /login, which has no composer — so the "
        "tool's probe reads `kind: login` and `logged_in: false`"
    ),
    "sign-in form": (
        "a banner that hides the form until it is dismissed once, provider and "
        "passkey buttons that lead nowhere, then the email step and the password "
        "step, each an <input> the map names and each submitted by Enter"
    ),
    "new chat": "/new: an empty composer, a disabled Send, a hidden file input",
    "conversation": ("/chat/<uuid>: the whole transcript, server-rendered, so a reload shows every turn"),
    "composer present": 'a visible div[contenteditable="true"], one block per line',
    "composer empty": "the composer holds one empty paragraph after a submit",
    "can submit": 'a button whose aria-label contains "Send", disabled while the composer is empty',
    "generating": 'the Send button is replaced by one whose aria-label contains "Stop" until the reply is whole',
    "generation finished": (
        "the reply is revealed in steps, the last of which puts the Stop button "
        "back to Send — so a reader waiting for it to stop growing really waits"
    ),
    "human turn": 'each submitted message is a [data-testid="user-message"]',
    "assistant turn": 'each reply is a [data-testid="assistant-message"]',
    "every message": "both, in document order, in one transcript element",
    "upload target": 'a hidden input[type="file"] beside the composer, on every page',
    "upload accepted": "a chip element carrying the file's name, outside the composer",
    "every upload accepted": "one chip per accepted file, all of them at once",
    "chat title": 'a visible [data-testid="chat-menu-trigger"] carrying the title',
    "rename affordance": (
        "the chat menu opens from that trigger and holds a rename control and a "
        "text input; a renamed title survives a reload"
    ),
}
"""What the mock does for each row, in one line.

This is the half of the citation that can be wrong in an interesting way: the
map says what claude.ai shows, and this says what the mock decided that means.
The mock's README quotes it, and a reader comparing the two columns is reading
the whole of the mock's claim to realism.
"""


def cited() -> list[str]:
    """Every map row the mock stands on, in one sorted list, without repeats."""
    return sorted(set(ROWS.values()))
