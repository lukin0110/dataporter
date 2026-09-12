# The mock is a separate project

The mock claude.ai (brief `02`, §21) stands in for claude.ai, not for any part of the
tool, and is meant to become its own repository. We decided that it is its own project now
— its own project file, dependencies, tests and README — listed as a workspace member of
this repository for convenience, with no import in either direction. The model-free
`hermes` that a rehearsal puts on the path is the tool's own test double and stays on the
tool's side of that line (§23).

## Considered

- A directory inside the tool's tree with a no-imports rule in prose. The rule rots the
  first time a helper is wanted on both sides.
- A separate repository from day one. Ceremony before there is code to put in it.

## Consequences

- Extraction is a directory move.
- A helper wanted on both sides is duplicated or promoted to a third package, never
  imported across.
