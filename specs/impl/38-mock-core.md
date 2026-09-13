# 38 — The core and the rename

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 05](../05-chatgpt-mock.md) §53 (and §52 as the goal)
**Depends on:** [26](26-mock-claude.md), [32](32-mock-export-page.md) (the mock claude.ai
as it stands), ADR [0007](../../docs/adr/0007-the-mocks-are-one-project.md)
**Enables:** [39](39-chatgpt-mock-site.md)
**Status:** Built

## Goal

The mock claude.ai becomes one site of a project of mocks: the half it shares with every
mock to come — the certificate, the session, the witness routes, the ledger, the
reachability block, the obedient reply, the link — moves into a core package neither site
owns, the distribution is renamed, and the mock claude.ai keeps its command, its port, its
pages and every byte it prints. Nothing about what a rehearsal sees changes; what changes
is where the code that a second site would otherwise copy lives.

## In scope

- **The distribution** (`mock/pyproject.toml`): name `mocks`, version `0.2.0`, packages
  `src/mockcore`, `src/claudemock` and `src/chatgptmock` (the third empty until `39`),
  scripts `claude-mock` and `chatgpt-mock`. The workspace member is unchanged
  (`members = ["mock"]`); `make test-mock`, `make test-all` and the README say
  `--package mocks`. `uv.lock` follows.
- **`mockcore`** (`mock/src/mockcore/`, new), the core the sites share:
  - `__init__.py` — `DISTRIBUTION`, `__version__` read from the installed metadata, and
    `Identity(program, site, hosts, port)`, frozen: who a mock is, as the core needs to
    know it. `title` is `Mock <site>`, `heading` is `Mock <site> — ledger`,
    `spelled_hosts` is the hosts in prose (`claude.ai`; `chatgpt.com and auth.openai.com`).
  - `certificate.py` — `26`'s module, given an identity: `ensure(identity, directory)`
    mints a self-signed P-256 certificate whose common name is the first host, whose
    organisation is the program, and whose alternative names are every host, its
    wildcard, and `127.0.0.1`; the files are `<program>.pem` and `<program>.key` under
    `~/.cache/<program>/` (`default_directory(identity)`), so two mocks pointed at one
    directory keep two keys. `Material` and `pin_of` unchanged.
  - `ledger.py` — `LABELS`, `WIDTH` and `Ledger(heading, …)`: the six counters and the
    block, the heading now the site's, since two mocks running at once keep two ledgers
    (§54, *The ledger*).
  - `reply.py` — `ASK`, `CANNED`, `DEFAULT_REPLY_DELAY_S`, `DEFAULT_REPLY_STEPS`, `Turn`,
    `Reply`, `asked_line`, and `answer(message, *, started, delay_s, steps)`: the obedient
    reply, verbatim from `26`'s `site.py`.
  - `sessions.py` — `Sessions` (`open`, `holds`, `close`: the tokens that are signed in)
    and `Pending` (`new_token`, `remember`, `pending`, `forget`: a half-finished sign-in,
    or a one-time code between two hosts).
  - `exports.py` — `Export` and `Exports(wall)` (`request`, `fetch`, `all`): `32`'s link
    minted instead of an email, site-wide, a second ask adding a second link.
  - `wire.py` — the cookies (`SESSION_COOKIE`, `LOGIN_COOKIE`, `SESSION_MAX_AGE_S`), the
    caps, `SignedOutError`, `set_cookie`, `redirect`, `not_found`, `session_of(signed_in)`
    (the dependency a route with a session behind it declares), the witness paths, and
    `witness(app, *, ledger, exports, link_of)` registering `/__mock/ledger`,
    `/__mock/ledger.json`, `/__mock/exports` and `/__mock/exports.json` behind no session;
    `ARCHIVE_PATH` is the core's spelling and the site's route, because whether the
    download wants a session is the site's fact. `MockServer`, `listen` and
    `serve(build, *, port, host, material)`, where `build(host, port)` is told the address
    the socket really bound.
  - `cli.py` — `resolver_rule(identity, host, port)` (`MAP <host> <addr>:<port>` per host,
    comma-separated), `reachability(identity, *, host, port, flag, tail)` (the block, `26`'s
    bytes, the lines after the Chrome table the site's), `PROXY_NOTE` and
    `proxy_note(identity, names)` (the head of `26`'s note, the hosts spelled), `LINK_NOTE`,
    `link_note`, `announce`, `parser(identity, *, description, email, password)` (the four
    commands `serve`, `ledger`, `exports`, `rows`, the port the identity's),
    `refused_reply`, `wait(running)`, `ledger`, `exports`, `fetch_text`, `rows`.
- **`claudemock`, on the core**: `__init__.py` gains `IDENTITY` (`claude-mock`,
  `claude.ai`, `("claude.ai",)`, `8443`); `site.py` keeps `Chat`, `Site` and `names` and
  takes `Turn`, `Reply`, `answer`, `Sessions`, `Exports` and `Ledger(IDENTITY.heading)`
  from the core, its public surface unchanged; `server.py` keeps its routes and
  `EXPORT_PAGE_PATH`, registers the witness through the core and its open archive route
  itself, and its `serve` spells the link base from the bound socket as before;
  `cli.py` keeps `reachability` (the core's block with the `SSL_CERT_FILE` tail),
  `proxy_note` (the core's note with `FETCH_PROXY_NOTE` after it), `HOST_NOTE`, the
  defaults, and hands the rest to the core. `certificate.py` and `ledger.py` are deleted.
  `pages.py`, `archive.py` and `uimap.py` change one import.
- **Golden strings, unchanged**: the reachability block, the proxy note, the host note,
  the link note and the ledger block print the same bytes as before this slice, and
  `mock/tests/test_claude_cli.py` and `test_core_ledger.py` pin them.
- **Tests** (`mock/tests`, one directory, named by owner): `test_core_ledger.py`,
  `test_core_reply.py`, `test_core_certificate.py` (the key kept, the pin's length, every
  host and the loopback address named, two mocks two keys, the default directory the
  program's), `test_core_wire.py` (a server that cannot start releases its port, the
  bound address, the witness paths on no site), `test_core_cli.py` (the rule with one
  host and with two, the block, the note with the hosts spelled, the refusals, the
  parser's four commands and the identity's defaults, a mock nobody is serving);
  `26`'s and `32`'s tests renamed `test_claude_*.py`, unchanged in what they assert.
  `conftest.py` holds one certificate and one running mock per site.

## Out of scope

- Any page, path or selector: the core knows no site. The mock chatgpt.com's are
  [39](39-chatgpt-mock-site.md)'s and [40](40-chatgpt-export-and-archive.md)'s.
- A merged reachability block for two mocks at once (§58): the README says how to merge
  them by hand ([41](41-chatgpt-mock-walk.md)).
- Anything in `src/dataporter`: unchanged (§52).

## Design notes

- **An identity, not a settings object.** The core has to name a site in four places —
  the certificate, the ledger's heading, the reachability block, the program in an error
  — and a frozen dataclass of four fields handed in by the site is the smallest thing
  that keeps "the core knows no site" checkable: `grep claude mock/src/mockcore` finds
  docstrings and nothing else. Rejected: module-level constants the site sets on import
  (a global, and a second site would fight over it); a class per site subclassing a core
  site (the two sites' chats are not the same shape — a ChatGPT message carries pasted
  texts and files, a Claude chat carries files — and a base class would have to be the
  union).
- **The sites keep their `Site` classes; the core keeps the parts.** `Sessions`,
  `Exports` and `answer` are composed into each site's `Site` rather than inherited, so
  that the mock claude.ai's public surface (`sign_in`, `request_export`, `fetch_export`,
  `exports`, `all_chats`, …) is byte-identical to `32`'s and its tests did not change.
  The one seam a site hands the core its parts through is `wire.witness(app,
  ledger=…, exports=…, link_of=…)`.
- **The archive route is the site's.** Brief 03 §35 says a Claude link needs no session
  and §54 says a ChatGPT link does; a core route would have had to take a flag, and a
  flag is a decision hidden in a call. Each site registers `wire.ARCHIVE_PATH` itself,
  in three lines. Rejected: a `download(app, *, requires_session)` in the core.
- **The block's tail is the site's.** `26`'s block ends in the `SSL_CERT_FILE` line
  because the tool fetches that site's link with Python; the mock chatgpt.com's archive
  cannot be fetched by the tool at all, so its block has no tail. `reachability` takes
  the lines after the Chrome table as a sequence and appends the closing blank line, so
  `26`'s bytes are reproduced exactly with a four-line tail and the other site's with
  none. Rejected: a `cert_file: Path | None` parameter (it would name what the tail is
  for, which the core does not know).
- **The version is the distribution's.** `mockcore.__version__` reads the installed
  metadata of `mocks`, so `claude-mock --version` and `chatgpt-mock --version` print one
  number and `pyproject.toml` is the only place it is written. Rejected: a literal per
  package (three to keep in step).
- **One test directory, prefixed by owner.** `mock/tests/` stays flat: pytest imports a
  test module by its basename when there is no package, so two `test_site.py`s in two
  subdirectories would collide, and one `conftest.py` with one `Client` serves both
  sites. Rejected: `tests/claude/` and `tests/chatgpt/` packages (`__init__.py` files
  the project has never had, for a split the prefix already makes).

## Acceptance criteria

- `uv run --package mocks pytest mock` is green; `make check` is green; `uv lock` is
  current.
- `claude-mock serve` prints byte for byte the block `32` left it printing, and
  `claude-mock ledger` the block `32` left it printing.
- `grep -ri claude mock/src/mockcore/*.py` matches docstrings and comments only.
- `chatgpt-mock --version` and `claude-mock --version` print the same number, `0.2.0`.
- *(Live: it needs a headless Chromium and the scripted `hermes`, and no account.)* A
  rehearsal (`29`) against `claude-mock serve` from this slice passes as rehearsal 02
  did, with the same six-row ledger reconciled. Not yet run: the code the mock claude.ai
  serves is unchanged in every byte a rehearsal reads, and its suite of the wire is what
  says so until the next rehearsal record does.

The first four were met on 2026-09-13. The status is `Built` rather than `Done` because
the fifth is a rehearsal record nobody has written since the refactor, and §56's rule
holds for every slice of this brief: `Built` when its suite passes, `Done` when a
tool-driven run has walked it.

## Risks

- **A refactor that changed a byte a rehearsal reads.** The golden tests pin the printed
  blocks, and the tests of the wire pin the routes and the cookies; what they do not pin
  is the page script, which is unchanged in text. The next rehearsal is what would
  surface a change none of them caught.
- **The core grows a site's helper.** The temptation, the day Gemini's mock is built, is
  to put a helper two sites want *and the tool wants too* into the core; ADR 0003's line
  is that such a helper is duplicated, never imported across, and ADR 0007 restates it.
  The check is the one above: nothing in `mockcore` names a site.
