# The mocks are one project

Brief `05` adds a mock chatgpt.com beside the mock claude.ai, and a mock for Gemini will
follow. [ADR 0003](0003-the-mock-is-a-separate-project.md) made the mock claude.ai a
separate project so that it could leave this repository as a directory move, and said a
helper wanted on both sides of the line between the tool and the mock is duplicated or
promoted to a third package. We decided that the mocks are **one project**: `mock/`, one
project file, one distribution, a core package the sites share, and one package and one
command per site — rather than a project per site with a shared package between them, or
a copy per site. The mocks share more than they differ (a certificate, a session, the
witness routes, the ledger, the reachability block, the obedient reply, the link), a
rehearsal will one day run two of them in one Chrome, and they would leave this
repository together.

## Considered

- Three workspace members: a core package, and a project per site depending on it. No
  rename, and each site could leave on its own — at the cost of a third project file and
  a core the two would have to pull from somewhere. Right if the mocks were ever to live
  in separate repositories, and nothing says they will.
- A copy per site. Nothing shared and nothing refactored, and a third copy of the same
  certificate code the day Gemini's mock is built.

## Consequences

- The distribution is renamed, `claude-mock` → `mocks`, by the slice that adds the core;
  the directory and the two commands keep their names.
- ADR 0003's line is unchanged: the project imports nothing from `dataporter` and
  `dataporter` imports nothing from it. A helper wanted by two sites goes into the core; a
  helper wanted by a site and the tool is still duplicated, never imported across.
- Each site keeps its own UI map, its own citations, its own archive shape, its own port
  and its own certificate; the core knows no site.
