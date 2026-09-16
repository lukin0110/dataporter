"""A served stand-in for the whole of claude.ai.

The tool this repository ships has two halves. One is an agent with a model
behind it; the other is deterministic — a browser session, a sign-in form, the
helpers, the import loop, verification, the report. The deterministic half had
never met a real browser showing a real, stateful site, because until now the
only such site was claude.ai itself. This is that site, for rehearsals
(`specs/02-claude-mock.md`, §21).

Three rules hold everywhere in this package:

- **It behaves on its own.** Nothing here is scripted per run and there is no
  model behind it. A submit creates a chat, a chat answers, a reload shows what
  was said, and the export page hands out a link instead of sending an email.
  What a rehearsal gets is a site, not a recording.
- **It is governed by `docs/claude-ui-map.md`.** Every state it can show is a row
  of that table, and `uimap.py` is where each one is cited. It invents nothing:
  where the map says *unknown*, the simplest behaviour the tool already accepts
  is taken, and `ROWS` says that it was.
- **It knows nothing about the tool.** This project imports nothing from
  `dataporter`, and `dataporter` imports nothing from it. Moving it to its own
  repository is a directory move (ADR 0003).

What this site shares with the other mocks — the certificate, the session, the
witness, the ledger, the reachability block, the obedient reply, the link — is
`mockcore`'s (brief `05` §53, ADR 0007). What is here is claude.ai's alone: its
pages, its paths, its selectors, its archive, and its citations.
"""

from mockcore import Identity

PROGRAM_NAME = "claude-mock"

HOST = "claude.ai"
"""The host the mock answers as. Nothing here maps it — the operator's Chrome
does, with the resolver rule the CLI prints."""

DEFAULT_PORT = 8443

IDENTITY = Identity(program=PROGRAM_NAME, site=HOST, hosts=(HOST,), port=DEFAULT_PORT)

ORIGIN = f"http://127.0.0.1:{DEFAULT_PORT}"
"""Where the mock really is, and what its links are spelled with (`65`).

`HOST` above is what this site *stands in for*, which is still `claude.ai` — the
ledger says so and the UI map is about that site. This is where it answers. The
tool spells the same string in `sources/claude.py:MOCK_ORIGIN`, re-typed rather
than imported, because the two projects share no code (ADR 0003)."""

EXPORT_CATEGORIES = ("light_metadata", "conversations")
"""The categories a Claude export is split into, in the order its manifest names
them: `light_metadata` is `batch_index` 0 and `conversations` is 1.

Here rather than in `archive.py` because both halves need it and neither may
import the other — `site.py` mints one part token per category when an export is
asked for, and `archive.py` says which file goes in which. Read off a real
`manifest.json`, as the `-000` in a part's name was."""
