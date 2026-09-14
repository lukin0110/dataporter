"""ChatGPT as a source (`43`, `44`; brief `06` §60).

Every control this object names is the tool's own spelling of a row of
`docs/chatgpt-ui-map.md`, typed here on the tool's side of ADR 0003's line and
never imported from the mock. The rows are *reported* or *unknown*; the first
real run is what corrects them, one line each.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from dataporter.sources.base import Reading, Source

if TYPE_CHECKING:
    from dataporter.export.source import ExportView

HOST = "chatgpt.com"
AUTH_HOST = "auth.openai.com"
"""Signing in passes through the second host (help article 7426629, §61)."""

EXPORT_PAGE_PATH = "/settings/data-controls"
"""Where chatgpt.com lets a user ask for their data. The mock's path; the
site's is *unknown* (`export page` in the map), and this is the one string a
trace corrects (§62)."""

EXPORT_BUTTON_SELECTOR = "button#export"
"""**Export**, under the **Export data** heading (`export button`, reported)."""

CONFIRM_BUTTON_SELECTOR = '[role="dialog"] button#confirm-export'
"""**Confirm export**, in the dialog the button opens (`export confirmation`)."""

REQUESTED_SELECTOR = '[role="status"]#export-requested'
"""The status the page shows once the ask has been counted (`export requested`)."""

LOGIN_BUTTON_SELECTOR = 'button[data-testid="login-button"]'
"""**Log in** on the landing page (`signed out`, reported)."""

CONTINUE_SELECTOR = 'button[type="submit"]'
"""**Continue** on the auth host's email and password steps (`email step`,
`password step`, unknown). Counted by every sketch; the form is submitted with
Enter, as the map says it can be."""

EMAILED = "ChatGPT will email or text a download link to the account's address."
SEVEN_DAYS = "It can take up to 7 days. When it arrives:"
COUNTS = "Conversations: {conversations}     Files: {files}"
"""§60's block: the vendor's own two sentences (help article 7260999), and the
count line of §63's — conversations, and the files the archive carries."""

LOGIN_PROMPT = "Log in to ChatGPT in the browser window that just opened."


def looks_like(names: Sequence[str]) -> bool:
    """Whether an archive with these members is ChatGPT's, by its names."""
    from dataporter.export import chatgpt  # ruff: ignore[import-outside-top-level] - `store` reads this package; the reader reads `store`

    return chatgpt.looks_like(names)


def read(view: "ExportView") -> Reading:
    """Count the archive, or refuse it with the reason (§64)."""
    from dataporter.export import chatgpt  # ruff: ignore[import-outside-top-level] - see `looks_like`

    return chatgpt.read(view)


CHATGPT = Source(
    name="chatgpt",
    display_name="ChatGPT",
    host=HOST,
    auth_hosts=(AUTH_HOST,),
    login_url=f"https://{HOST}/",
    sign_in_paths=("", "auth/login", "auth/callback"),
    app_paths=(),
    export_page_path=EXPORT_PAGE_PATH,
    selectors={
        "EXPORT_BUTTON_SELECTOR": EXPORT_BUTTON_SELECTOR,
        "CONFIRM_BUTTON_SELECTOR": CONFIRM_BUTTON_SELECTOR,
        "REQUESTED_SELECTOR": REQUESTED_SELECTOR,
        "LOGIN_BUTTON_SELECTOR": LOGIN_BUTTON_SELECTOR,
        "CONTINUE_SELECTOR": CONTINUE_SELECTOR,
    },
    fetch_needs_session=True,
    signed_out_at_root=True,
    unattended_signin="walk",
    ask_lines=(EMAILED, SEVEN_DAYS),
    counts_line=COUNTS,
    login_prompt=LOGIN_PROMPT,
    recognise=looks_like,
    read=read,
)
"""ChatGPT, as brief `06` builds it: two hosts, a landing page a signed-out
request lands on, a link that wants the session (§63), and a sign-in the tool
walks itself (§61)."""
