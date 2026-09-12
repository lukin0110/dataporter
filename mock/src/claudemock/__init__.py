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
  was said. What a rehearsal gets is a site, not a recording.
- **It is governed by `docs/claude-ui-map.md`.** Every state it can show is a row
  of that table, and `uimap.py` is where each one is cited. It invents nothing:
  where the map says *unknown*, the simplest behaviour the tool already accepts
  is taken, and `ROWS` says that it was.
- **It knows nothing about the tool.** This project imports nothing from
  `dataporter`, and `dataporter` imports nothing from it. Moving it to its own
  repository is a directory move (ADR 0003).
"""

__version__ = "0.1.0"

PROGRAM_NAME = "claude-mock"

HOST = "claude.ai"
"""The host the mock answers as. Nothing here maps it — the operator's Chrome
does, with the resolver rule the CLI prints."""
