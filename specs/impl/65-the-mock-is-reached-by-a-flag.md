# 65 — `--mock`: the tool talks to a local origin

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 02](../02-claude-mock.md) §21, §22 (both amended),
[Brief 03](../03-extraction-and-backup.md) §40
**Amends:** brief 02 §22 (*The tool under rehearsal*) and §23; `26`'s reachability block,
`32`'s `SSL_CERT_FILE` tail, `38`'s description of that tail, `39`'s two-host resolver
rule and `46`'s environment. Supersedes [ADR 0001](../../docs/adr/0001-no-door-in-the-wall.md)
with [ADR 0010](../../docs/adr/0010-the-mock-is-reached-by-a-flag.md).
**Depends on:** [26](26-mock-claude.md), [38](38-mock-core.md), [42](42-source-seam.md),
[64](64-the-mock-catches-up.md)
**Status:** Built

## Goal

Make a mock cheap to reach. `--mock` is a flag on the tool that changes exactly one thing —
the **origin** — and the mocks drop TLS for plain HTTP on loopback. No certificate, no
SPKI pin, no `config.toml` table to paste, no host pretending to be another.

What this is *for* is narrower than the apparatus that grew around it: driving the CLI's
mechanics — can it open a browser, ask for a login, find the export button — without
touching a real account every time, and being runnable in CI. `--mock --non-interactive` is
the one combination that can run headless at all, because a mock has no bot check
(ADR 0008).

## In scope

- **`Source.origin`** (`sources/base.py`), with `host`, `hosts`, `auth_hosts` and
  `login_url` derived from it and `login_path` beside it. `host` stays **bare** because
  `cdp.Target.host` is `urlparse(url).hostname` and a port there would match no tab.
  `MOCK_REGISTRY` (`sources/__init__.py`) is the same sources through
  `dataclasses.replace(origin=…)`; `sources.of` returns from it under the flag, and that
  is the whole of the swap for the source half.
- **`Surface.origin`** (`browser/helpers.py`), with `host`/`hosts` derived. The 11
  host-touching helpers already took a `Surface`, so the origin reaches all of them for
  free. `migration_wall(origin)` builds §17's wall, so **the two walls are disjoint** — a
  run given the wrong flag stops with a `SafetyError` naming the URL.
- **`probe.destination_origin(settings)`** — the one place the destination half learns a
  mock exists. `session.whose`, `session.site_of`, `helpers.for_settings`,
  `probe.new_chat_url`, `probe.migration_site`, `verify.chat_url` and
  `login_form.login_url` all take what it returns.
- **`surface` defaults removed** from the six helpers that hold a `Settings`. They resolve
  their own wall now (`helpers.for_settings`), because a call site that forgot to pass one
  would have kept driving the real claude.ai inside a `--mock` run and said nothing — the
  only silent failure this change can have.
- **`links.is_followable(link, origins)`** replaces the bare `is_https` check at the two
  places a person hands the tool a link. A mock's links are plain HTTP, and *relaxing the
  scheme* would be a door: this admits a plain-HTTP link only when it is on an origin the
  source itself names.
- **`Settings.mock`**, and the **one channel** that sets it. `_EnvWithoutMock` drops
  `DATAPORTER_MOCK` from the environment source and `NOT_IN_CONFIG_FILE` refuses `mock` in
  `config.toml` — dropped in one and refused in the other, because a variable is ambient
  and a file was written for this tool.
- **The state a mock run leaves is kept apart**: `~/.dataporter/mock/{accounts,store}` and
  `./migration-mock`, as **defaults only**, so an explicit `store.dir` or `--workspace`
  still wins and `rehearsal/` keeps its own roots.
- **`helper_command(workspace, mock=…)`** carries the flag into the prefix the agent runs
  its helpers with. Without it, a `--mock` migration's subprocesses would drive the real
  site — the one place the agent's half could be pointed where the tool's half is not.
- **The mocks drop TLS** (`mockcore/wire.py`): `mockcore/certificate.py`, its tests and
  the `cryptography` dependency are deleted, with `resolver_rule`, the proxy note and the
  SPKI pin. The reachability block is two lines. The mock chatgpt.com gains a **second
  socket** (`AUTH_PORT`, 8445) for its auth origin, and its pending sign-ins and one-time
  codes move onto the `Site`, because two apps now serve one account.
- **Traces record the real origin**, so a rehearsal's trace says `127.0.0.1` and can never
  be mistaken for — or committed as — evidence about the real site (`37`).
- **`rehearsal/`** sheds `spki_pin`, `_public_key_der`, the two Chrome arguments and the
  `.pem`, and passes `--mock` on every command line. The extraction's auth-host criterion
  reads the crossing off `/log-in`, a path only the auth origin serves, because there is no
  `certificate` observation left to count.

## Out of scope

- **Templating `SKILL.md`.** It keeps naming `claude.ai`, so a *real* Hermes can no longer
  be pointed at a mock — see ADR 0010. Only `tests/fake_agent.py`, `rehearsal/agent.py` and
  `doctor`'s attach assertion learn the origin.
- **A panel that renders late** (`62`) and **the redirect to a storage host** — `64`'s two
  gaps, unchanged.

## Design notes

- **Origin as the stored field, host derived.** The other way round needs a port beside it
  and two fields that can disagree; this way a mock source is one `replace(…)` and
  `Target.host` keeps working untouched.
- **Disjoint rather than permissive.** The obvious cheap version is a wall that admits both
  origins. It would mean a forgotten flag drives the real site *successfully*, which is the
  exact failure ADR 0001 was written about.
- **Tab matching moved from host to origin.** Two mocks on loopback share a hostname and
  differ only by port, so `target.host in surface.hosts` called a tab on either of them the
  other's. `cdp.Target.origin` is the fix and it is strictly narrower for real runs too.

## Acceptance criteria

- `make check` passes, and `uv run ty check --error-on-warning src spikes rehearsal mock/src`.
- `tests/test_mock_flag.py`: a mock `Source` differs in `origin`/`auth_origins` alone;
  every wall is the real one with the origin swapped; the settings differ only in the flag
  and its three paths; neither wall admits the other's URLs; `DATAPORTER_MOCK=1` and a
  `mock = true` in `config.toml` both leave the flag off.
- `claude-mock serve` prints two lines and no certificate exists anywhere.
- Both rehearsals end `rehearsal: passed`, headless, with no `config.toml` naming a mock.
- By hand: `dataporter --mock login --account <label>` opens a window on the mock, a person
  types the email, the mock prints the link, `login --link` returns; then `extract`, the
  printed link, `extract --link`, `snapshots` — nothing pasted into any file.

## Risks

- **A missed `surface=` call site** drives the real site silently. The removed defaults and
  `test_every_destination_door_follows_the_flag` are the two things standing against it.
- **The claim is only as good as its test.** ADR 0010 rests on `tests/test_mock_flag.py`;
  a field added to `Source` that the mock registry should have changed and does not would
  pass, because the test asserts equality of everything *else*.
