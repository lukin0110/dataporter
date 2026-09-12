"""The rehearsal: the full run's protocol, run against the mock.

Nothing in here ships. The tool under rehearsal is byte-identical to the tool
that will meet claude.ai and has no setting that names the mock (§22, ADR 0001),
so this package holds only the three things a rehearsal needs *beside* it:

- `export.py` — the synthetic export a rehearsal migrates (§24);
- `agent.py` — the scripted agent's hands: the moves the skill leaves to an
  agent, made against a real Chrome over CDP;
- `hermes.py` — that agent packaged as a `hermes` executable, which is what
  stands where Hermes stands (§23);
- `run.py` — the protocol, the pass criteria and the record (§23, §25, §26).

The scripted agent's *procedure* is not here. It is `tests/fake_agent.py`, which
performs `11`'s steps in `11`'s order with `13`'s recovery, and which the tool's
own suite already drives against a fake page. A rehearsal gives that same
procedure a real browser and a real site; a second copy of it would be a second
thing to keep in step with the skill.
"""

__all__ = ["PROGRAM_NAME"]

PROGRAM_NAME = "rehearsal"
