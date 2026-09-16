"""A served stand-in for the whole of chatgpt.com.

Brief `05` (§52–§58): the tool has no ChatGPT half yet, and this mock is built
*ahead* of it — out of what OpenAI documents and what others have reported, so
that the driver's first slice meets a sign-in on two host names, a composer that
turns a long paste into an attachment, and a download that wants a session,
before it meets the real ones.

The same three rules as the mock claude.ai hold here:

- **It behaves on its own.** Nothing is scripted per run and there is no model
  behind it. A submit creates a chat, a chat answers, a reload shows what was
  said, and the export page hands out a link instead of sending an email.
- **It is governed by `docs/chatgpt-ui-map.md`.** Every state it can show is a
  row of that table, and `uimap.py` is where each one is cited. It invents
  nothing: where the map says *unknown*, the simplest behaviour the shape
  admits is taken, and `WHAT_THE_MOCK_DOES` says that it was. A mock run never
  turns a *reported* or an *unknown* row *observed*.
- **It knows nothing about the tool.** This project imports nothing from
  `dataporter`, and `dataporter` imports nothing from it (ADR 0003). It is not
  evidence about chatgpt.com (§27 applies word for word), and `--source chatgpt`
  is refused by the tool today as it was before.

What this site shares with the mock claude.ai is `mockcore`'s (§53, ADR 0007).
What is here is chatgpt.com's alone: its two hosts, its pages, its paths, its
selectors, its archive, and its citations.
"""

from mockcore import Identity

PROGRAM_NAME = "chatgpt-mock"

SITE_HOST = "chatgpt.com"
AUTH_HOST = "auth.openai.com"
"""The two hosts the mock answers as (§54, *Sign-in*; OpenAI 7426629): the site,
and the host the sign-in passes through. One resolver rule sends both to the
mock, and its certificate names both."""

DEFAULT_PORT = 8444
"""Beside the mock claude.ai's `8443`, so that both run at once in one Chrome."""

IDENTITY = Identity(program=PROGRAM_NAME, site=SITE_HOST, hosts=(SITE_HOST, AUTH_HOST), port=DEFAULT_PORT)

AUTH_PORT = DEFAULT_PORT + 1
"""The second socket (`65`). The two hosts used to be one socket told apart by
the `Host` header, which the operator's resolver rule supplied; with no rule and
no TLS there is no name to route on, so the second origin is a second port.

Cheaper than it was, too: it was the certificate covering two SANs that made two
names awkward, and there is no certificate now."""

SITE_ORIGIN = f"http://127.0.0.1:{DEFAULT_PORT}"
AUTH_ORIGIN = f"http://127.0.0.1:{AUTH_PORT}"
"""How a page on one origin names the other. Absolute, because a redirect between
two origins cannot be spelled any other way; the same app answers both sockets,
so a path is served identically whichever one asked for it."""
