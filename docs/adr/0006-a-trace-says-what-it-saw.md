# A trace says what it saw, not where it ran

[ADR 0001](0001-no-door-in-the-wall.md) gives the tool no host setting, so the tool
cannot tell a rehearsal against the mock from a run against claude.ai. Brief `04` wants
every trace to make plain which of the two it is — and which agent drove it — because a
trace of the real site is what the mock is corrected against, and a trace of the mock
mistaken for one would correct it against itself. We decided that a trace records
**marks, never a verdict**: the browser's extra arguments as configured (the resolver
rule that maps the host to the mock is visible there), the agent's `--version` line
verbatim, and the certificate the browser was shown for the host, as the first
observation that carries one. The scripted agent's version line says `(scripted agent)`
so that it is a mark too. A reader — a person, Claude Code, the rehearsal runner —
derives the label: a certificate signed by itself — its issuer its own subject, which is
the mock's — and the scripted agent is a rehearsal; the mock's certificate and a real
Hermes is a run against the mock; a public authority's certificate is the real world.
The filename stays neutral, because the file exists before the page is seen.

## Considered

- An `arena: rehearsal | mock | real` field written by the tool. It needs the tool to
  know what the mock's certificate looks like, which is the mock's knowledge inside the
  tool — ADR 0001's door, opened from the inside.
- A flag on the rehearsal runner that tells the tool it is rehearsing. The same door,
  with a sign on it.

## Consequences

- `rehearsal/hermes.py` prints `hermes 1.0.0 (scripted agent)`; the tool's version check
  is numeric and reads it as before.
- The rehearsal runner, which does know, files its traces under `<root>/traces/` and the
  rehearsal record labels them; a trace in a workspace or an account home is labelled by
  its reader.
- A mock served with a public certificate would be indistinguishable from the real site
  by this mark alone. The resolver rule in the browser arguments is the second mark, and
  the two are recorded so that a reader has both.
