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
  person watching the real claude.ai does that — or reading a trace of a run
  against it (the tool's brief `04`, §49). The mock is a consequence of the
  map, never evidence about it.
- A row's `WHAT_THE_MOCK_DOES` line may name the trace and line it was
  corrected from — `docs/spike/traces/<file>.jsonl:<line>` — as a citation and
  nothing more: the mock reads a trace the way a person does and imports
  nothing from the tool that wrote it.

Where a row is `*unknown*` — which today is all but one of them — the mock
takes the simplest behaviour the tool's code already accepts, and
`WHAT_THE_MOCK_DOES` below says what that was. The `link sent` row is the one
observed, and the mock's page is its controls re-typed.
"""

from collections.abc import Mapping

ROWS: Mapping[str, str] = {
    # page → the rows it is built out of
    "login": "signed out",
    "sign-in form": "sign-in form",
    # the other way the site says signed out (`70`, `71`)
    "sign-in screen in place": "sign-in screen in place",
    # the sign-in by link (`49`), out of brief 07's rows
    "link requested": "link requested",
    "link sent": "link sent",
    "sign-in link": "sign-in link",
    "signed in by the link": "signed in by the link",
    "link opened elsewhere": "link opened elsewhere",
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
    # the settings panel (`32`, corrected by `51`, `52` and this slice)
    "settings panel": "export page",
    "export row": "export button",
    "export screen": "export confirmation",
    "export period": "export period",
    "export toast": "export requested",
    # a sign-in that lapses while a run is under way
    "involuntary sign-out": "involuntary sign-out",
    # the account's own skills (`66`, `67`)
    "organisations": "skills list",
    "skills list": "skills list",
    "skill authorship": "skill authorship",
    "skill download": "skill download",
    "skill name": "skill name",
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
    "sign-in screen in place": (
        "with /__mock/signed-out-shape set, a signed-out request is answered "
        "`200` at the address it asked for instead of being redirected: two "
        'aria-hidden [data-client-attestation="hcaptcha-invisible"] containers, '
        "one on the channel send_magic_link, and a form holding "
        '[data-testid="email"] and [data-testid="continue"] together. Both '
        "signals or neither — a mock that served one of them would let a rule "
        "that cannot tell the two states apart pass a rehearsal"
    ),
    "sign-in form": (
        "a banner that hides the form until it is dismissed once, provider and "
        "passkey buttons that lead nowhere, then the email step alone — an "
        'input[type="email"] submitted by Enter; there is no password step, '
        "because claude.ai has none (brief 07 §72)"
    ),
    "link requested": (
        "the address step's POST mints a sign-in link instead of mailing one, "
        "counted as `links_minted`, printed where an email would arrive and "
        "listed at /__mock/sign-in-links; the real request carries an "
        "attestation the mock does not imitate (§79)"
    ),
    "link sent": (
        "after the address, /login shows the controls the real page showed on "
        '2026-09-15: input[data-testid="code"][autocomplete="one-time-code"]'
        '[inputmode="numeric"], a submit button[data-testid="continue"], and two '
        'type="button" controls that resend the link and change the address'
    ),
    "sign-in link": (
        "https://claude.ai/magic-link#<token>:<base64url address>, the real "
        "shape: the token in the fragment, which /magic-link's own script reads, "
        "clears from the address bar and posts to /login/redeem with the "
        "browser's pending-sign-in cookie"
    ),
    "signed in by the link": (
        "a link redeemed in the browser that gave the address, once, mints the "
        "session and sends the browser to /new — the tool's probe then reads a "
        "composer; a second redemption is refused"
    ),
    "link opened elsewhere": (
        "a link opened without its pending sign-in — another browser, a wrong "
        "address, one already spent — sends the browser to /login showing the "
        "code field, which is the one shape the tool recognises; what the real "
        "page shows is unknown, and no code is minted because the code door is "
        "deferred (§80)"
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
    "export page": (
        "a settings dialog over /new, opened by the address alone: markup on the "
        "chat page shown when the fragment is #settings/data-privacy-controls, "
        "with the composer and the file input behind it. `31`'s "
        "/settings/data-privacy-controls was a placeholder and is gone — signed "
        "in it is now not found, which is what the real path serves"
    ),
    "export button": (
        'six [data-settings-row] button[data-cds="Button"] under the panel, of '
        "which the Export row is the first visible one and a row above it holds a "
        "switch rather than a button. The first of the six is invisible, so that "
        '"the first visible match" is a claim this page can falsify; six is the '
        "count a sketch of the real panel took"
    ),
    "export confirmation": (
        "the Export row moves the address to "
        "#settings/data-privacy-controls/export-data and the panel renders a "
        "second screen in place of the first, carrying a visible "
        '[data-testid="export-confirm-button"]. In place of, not over: a sketch '
        "of the real second screen counts one confirmation and no export rows"
    ),
    "export period": (
        'the second screen carries a [role="radiogroup"] of All / Last 30 days / '
        "Last 90 days / Custom with All checked, and the ask touches none of it — "
        "exactly as the tool does not"
    ),
    "export requested": (
        'confirming POSTs /api/exports, which answers 202, and a [data-cds="Toast"] '
        '[role="dialog"] h2 reading exactly "Export started" is raised only once '
        "the ask is counted and a link minted. The link is an index at a /__mock/ "
        "address on the mock's own host, printed where an email would be sent"
    ),
    "involuntary sign-out": (
        "a request whose session the site no longer knows is answered "
        "/logout?involuntary&returnTo=…, and /logout answers "
        "/login?from&reauth&returnTo — two hops, as observed. Only a POST to the "
        "witness (/__mock/expire-session) can cause it: nothing the tool drives "
        "can, because an expiry is something that happens to a run"
    ),
    "skills list": (
        "GET /api/organizations answers one organisation with a uuid the site "
        "mints; GET /api/organizations/<org>/skills/list-skills answers "
        '{"skills": [...]} in the vendor\'s shape, six entries seeded as a mix — '
        "four the account wrote, one of Anthropic's, one nobody's — each read "
        "counted as `skills_listed`. Both want the session"
    ),
    "skill authorship": (
        "`creator_type` is `user`, `anthropic` or `organization`; the `user` "
        "ones include one switched off and one inside a plugin, so a rehearsal "
        "can prove both are filed, and the third value is one the tool does not "
        "know, so it can prove that one is not"
    ),
    "skill download": (
        "GET /api/organizations/<org>/skills/download-dot-skill-file?skill_id=… "
        "answers a zip holding SKILL.md as application/zip with a "
        "Content-Disposition attachment named <name>.skill, counted as "
        "`skills_served`; one seeded skill answers 500 instead, so that the "
        "tool's gap is a served failure and not a fake's. /__mock/skills.json "
        "lists what was served, for the reconciliation"
    ),
    "skill name": (
        "every seeded name is lowercase letters and hyphens, the rule the real "
        "dialog states; the mock enforces nothing, because a rehearsal never "
        "creates one"
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
