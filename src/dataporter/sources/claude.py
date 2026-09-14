"""Claude as a source (`42`): what `31` spelled across five modules, in one place.

Three of the four rows this object depends on were read off a real account on
2026-09-14, after `31`'s guesses sent a run to a page that does not exist: the
export page's address, the row that opens it, and the button on the second screen
that actually asks. All three stay `*unknown*` in `docs/claude-ui-map.md` even so
— a row is marked when an artefact under `docs/spike/` can be cited for it, and
the only one available carries the account's own name and its conversation
titles, which §10 keeps out of that directory.

The fourth is unknown in the stronger sense: what the panel shows once the
request is accepted can only be seen by asking a real account for a real export,
and nobody has. Until it is, an ask presses both buttons — the export *is*
requested — and then waits out `timeouts.ask_s` without recognising it.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from dataporter.sources.base import Reading, Source

if TYPE_CHECKING:
    from dataporter.export.source import ExportView

HOST = "claude.ai"

EXPORT_PAGE_PATH = "/new#settings/data-privacy-controls"
"""Where claude.ai lets a user ask for their data (*observed 2026-09-14*).

Not a path of its own: the settings are a dialog over the app, at a fragment.
`31`'s `/settings/data-privacy-controls` was a guess and served nothing. The
whole string is where the browser is sent; `Source.export_path` is the `/new`
a URL check compares, because a fragment is no part of a path (§77)."""

EXPORT_BUTTON_SELECTOR = '[data-perf-screen="data-privacy-controls"] [data-settings-row] button[data-cds="Button"]'
"""The control that asks the vendor for the account's data (*observed 2026-09-14*).

Matched by position, because the panel offers nothing better. Its rows carry no
test id; the only thing distinguishing the Export row from the five *Manage*
rows under it is the words in it, which a selector cannot read, and the ids that
are there (`_r_7v_`) are React's and regenerated on every render. What is stable
is the shape: every row above Export holds a switch rather than a button, so the
Export button is the first button in the panel, and `click_js` presses the first
visible match.

If claude.ai reorders that panel this presses *Manage* on another row instead,
which opens a list rather than asking for anything — and the ask then stops at
`REQUESTED_SELECTOR` rather than reporting a request nobody made."""

CONFIRM_BUTTON_SELECTOR = '[data-testid="export-confirm-button"]'
"""The control that actually asks (*observed 2026-09-14*).

The `Export data` row does not ask for anything: it opens a second screen inside
the settings dialog — a description, a *Conversations from* period, a list of
what the export will include, and this button. So the ask's two clicks are a
navigation and then the request, which is the shape `31` built for a modal and
which fits this one unchanged.

Unlike the row above it, this one has a test id and needs no positional
guessing. It is not qualified by `[role="dialog"]`: the settings panel is one, so
the qualifier would hold, but a test id this specific is better read on its own.
"""

REQUESTED_SELECTOR = '[data-testid="export-requested"], [role="status"]'
"""What the page shows once the request has been accepted.

Read as an element that is there, never as the sentence it holds: the ask obeys
`probe`'s rule that nothing off the page crosses the wire, and "the request was
accepted" is a fact about the page rather than a message from it.

Still `*unknown*`, for `CONFIRM_BUTTON_SELECTOR`'s reason. Until it is observed
an ask presses the button and then waits out `timeouts.ask_s` without
recognising its own success, so the export is requested and the run says it was
not. That is the last thing between this source and a working `extract`.
"""

EMAILED = "Claude will email a download link to the account's address."
WHEN_IT_ARRIVES = "When it arrives:"
COUNTS = "Conversations: {conversations}     Projects: {projects}     Memories: {memories}"
"""§31's block, byte for byte: the two sentences of the ask and the count line
of the fetch. The rest of either block is `extract`'s and every source's."""

LOGIN_PROMPT = "Log in to Claude in the browser window that just opened."


def looks_like(names: Sequence[str]) -> bool:
    """Whether an archive with these members is a Claude export, by its names.

    `conversations.json` is the one member the export cannot do without (`02`),
    and `user.json` — singular — is ChatGPT's account member where Claude's is
    `users.json`; a zip that has the first and not the second is Claude's to
    read, and `read` says whether it really is.
    """
    return "conversations.json" in names and "user.json" not in names


def read(view: "ExportView") -> Reading:
    """One parse yields the counts, the fingerprint and the gap (`30`).

    The export reader is imported here rather than at the top: `store` reads
    this package to know which sources exist, and the reader reads `store`.
    """
    from dataporter.export.model import file_entries  # ruff: ignore[import-outside-top-level] - see the docstring
    from dataporter.export.source import read_export  # ruff: ignore[import-outside-top-level] - see the docstring

    export = read_export(view)
    return Reading(
        conversations=len(export.conversations),
        fingerprint=export.fingerprint,
        projects=export.projects,
        memories=export.memories,
        missing_files=file_entries(export),
    )


CLAUDE = Source(
    name="claude",
    display_name="Claude",
    host=HOST,
    auth_hosts=(),
    login_url=f"https://{HOST}/new",
    sign_in_paths=("login(/.*)?",),
    app_paths=("new", "chat/[0-9a-f-]{36}"),
    export_page_path=EXPORT_PAGE_PATH,
    selectors={
        "EXPORT_BUTTON_SELECTOR": EXPORT_BUTTON_SELECTOR,
        "CONFIRM_BUTTON_SELECTOR": CONFIRM_BUTTON_SELECTOR,
        "REQUESTED_SELECTOR": REQUESTED_SELECTOR,
    },
    fetch_needs_session=False,
    signed_out_at_root=False,
    unattended_signin="agent",
    ask_lines=(EMAILED, WHEN_IT_ARRIVES),
    counts_line=COUNTS,
    login_prompt=LOGIN_PROMPT,
    recognise=looks_like,
    read=read,
)
"""Claude, as brief `03` built it: one host, an emailed link the tool fetches
without a browser, and `24`'s agent for the unattended sign-in."""
