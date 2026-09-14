"""Claude as a source (`42`): what `31` spelled across five modules, in one place.

Every row this object depends on is `*unknown*` in `docs/claude-ui-map.md`: the
export page's path, its button, whether a confirmation follows, and what the
page shows when the request was accepted. The first real ask is what corrects
them, and the constants below are what it corrects — one line each.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from dataporter.sources.base import Reading, Source

if TYPE_CHECKING:
    from dataporter.export.source import ExportView

HOST = "claude.ai"

EXPORT_PAGE_PATH = "/settings/data-privacy-controls"
"""Where claude.ai lets a user ask for their data. A placeholder: nobody has
looked. Everything else — the URL, the surface that admits it, the message that
names it — is built from this string, so the observation that corrects it is
one edit."""

EXPORT_BUTTON_SELECTOR = '[data-testid="export-data"], button[aria-label="Export data"]'
"""The control that asks the vendor for the account's data."""

CONFIRM_BUTTON_SELECTOR = '[role="dialog"] [data-testid="confirm-export"], [role="dialog"] button[type="submit"]'
"""The confirmation inside whatever dialog the button opens, if it opens one."""

REQUESTED_SELECTOR = '[data-testid="export-requested"], [role="status"]'
"""What the page shows once the request has been accepted.

Read as an element that is there, never as the sentence it holds: the ask obeys
`probe`'s rule that nothing off the page crosses the wire, and "the request was
accepted" is a fact about the page rather than a message from it.
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
