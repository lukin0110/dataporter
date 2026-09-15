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

SIGN_IN_LINK_PATH = "magic-link"
"""Where a sign-in link lands on claude.ai (*observed 2026-09-15*, from the
page's own script): `/magic-link#<token>:<address>`, the token in the
fragment, which the page reads and posts itself and which `46`'s guard never
records. A door in the sign-in's wall (`53`), so that the probe may look at
where the link lands; the navigation to it is `Page.navigate`'s and passes
through no wall, as the fetch's does (`45`)."""

EXPORT_PAGE_PATH = "/new#settings/data-privacy-controls"
"""Where claude.ai lets a user ask for their data (*observed 2026-09-14*).

Not a path of its own: the settings are a dialog over the app, at a fragment.
`31`'s `/settings/data-privacy-controls` was a guess and served nothing. The
whole string is where the browser is sent, and `on_export_page` compares a URL's
path and fragment together against it — `/new` is the app, `/new#settings/…` is
the panel, and only the fragment tells them apart (§77)."""

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

REQUESTED_SELECTOR = '[data-cds="Toast"] [role="dialog"] h2'
REQUESTED_TEXT = "Export started"
"""What the page shows once the request has been accepted (*observed 2026-09-15*).

A toast, bottom right: a `[data-cds="Toast"]` container holding one
`[role="dialog"]` per notification, and in it an `h2` carrying the words. No test
id anywhere in it, and the heading's `id` is React's (`_r_6k_`), regenerated on
every render.

So this is the one signal read by its words as well as its shape, and the reason
is the failure the shape alone caused. The container is the site's notification
furniture: *every* toast claude.ai raises matches it — a copy confirmation, an
error, a rename. `31` paired the old test id with `[role="status"]` as a
fallback, and on 2026-09-14 that generosity matched a live region before anything
had been asked for: the run pressed the `Export data` row, never reached the
`Export` button on the second screen, and still wrote an `ask.json` for a request
the vendor never received. A selector that is too generous does not fail loudly —
it fabricates. Matching any toast would be the same mistake with better markup.

The words never cross the wire. `export_page_js` compares them inside the page
and returns a boolean, which is `probe`'s rule kept exactly: what the tool learns
is *that* the export was accepted, not the sentence saying so.

What this costs is English and this wording. A claude.ai in another language, or
one that reworded the toast, matches nothing — and then the ask presses both
buttons, waits out `timeouts.ask_s` and reports that it could not confirm. That
is the wrong answer in the safe direction, which is the direction this selector
is tuned in: an ask that under-claims wastes a minute, and an ask that
over-claims sends a person to wait for an email nobody asked for.
"""

EMAILED = "Claude will email a download link to the account's address."
WHEN_IT_ARRIVES = "When it arrives:"
COUNTS = "Conversations: {conversations}     Projects: {projects}     Memories: {memories}"
"""§31's block, byte for byte: the two sentences of the ask and the count line
of the fetch. The rest of either block is `extract`'s and every source's."""

FETCH_NEEDS_SESSION = True
"""Whether the archive is served only to the signed-in session (*observed 2026-09-14*).

Brief 03 §35 assumed not: Claude was the source whose link a browserless fetch
could take, and `31` shipped `False` on that assumption because nobody had a link
to try it with. A real one, minutes old and well inside its 24 hours, answered
`HTTP 403` to a plain request — the download address is on `claude.ai` and is
served to the session or to nobody.

So the fetch goes through the source session, which is the shape `45` built for
ChatGPT and which §63 already governs: the browser makes the request, the cookie
never leaves it, and the tool never learns what it is.
"""

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
    sign_in_paths=("login(/.*)?", f"{SIGN_IN_LINK_PATH}(/.*)?"),
    app_paths=("new", "chat/[0-9a-f-]{36}"),
    export_page_path=EXPORT_PAGE_PATH,
    selectors={
        "EXPORT_BUTTON_SELECTOR": EXPORT_BUTTON_SELECTOR,
        "CONFIRM_BUTTON_SELECTOR": CONFIRM_BUTTON_SELECTOR,
        "REQUESTED_SELECTOR": REQUESTED_SELECTOR,
        "REQUESTED_TEXT": REQUESTED_TEXT,
    },
    fetch_needs_session=FETCH_NEEDS_SESSION,
    link_serves_manifest=True,
    signed_out_at_root=False,
    unattended_signin="none",
    ask_lines=(EMAILED, WHEN_IT_ARRIVES),
    counts_line=COUNTS,
    login_prompt=LOGIN_PROMPT,
    recognise=looks_like,
    read=read,
    sign_in_by_link=True,
)
"""Claude, as brief `03` built it and brief `07` corrected it: one host, an
export served to the session, and a sign-in by an emailed link that no
credential can make (§72, `50`)."""
