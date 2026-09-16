# The mock is reached by a flag

Supersedes [0001](0001-no-door-in-the-wall.md).

0001 decided that the tool gets **no** setting naming a mock: the helpers refuse every URL
that is not `https://claude.ai/...`, so the mock had to answer *as* `claude.ai`, over TLS,
and Chrome was pointed at it by the operator's own configuration — a resolver rule mapping
the host, and an SPKI pin trusting that one key. The prize was exact: the code under
rehearsal was the code that ships, byte for byte, because nothing it did told it the site
was a mock.

The bill for that prize is what changed. It is a certificate minted per site, a pin
computed off the live socket, a `[browser] extra_args` table an operator pastes into a
`config.toml`, a `cryptography` dependency, and a mock that must answer to a name it does
not own. And the thing it buys is fidelity that this project mostly does not need: what a
mock run is *for* is driving the mechanics — can the tool open a browser, ask for a login,
find the export button — without touching a real account every time, and being runnable in
CI. It was never the security rehearsal the apparatus implied.

So **`--mock` is a flag on the tool, and it changes exactly one thing: the origin.**
`http://127.0.0.1:8443` instead of `https://claude.ai`; plain HTTP, because Chrome treats
loopback as a trustworthy origin and there is nothing left for a certificate to do. The
mock answers on its own address under its own name, and nothing is pasted anywhere.

## What replaces the guarantee

0001's claim — *a rehearsal proves the code that ships, or it proves nothing* — is no
longer true, and is not replaced by a weaker version of itself. The claim is now narrower
and it is **a test rather than a sentence**: `tests/test_mock_flag.py` asserts, field by
field, that a mock `Source` differs from the shipped one in `origin` and `auth_origins`
alone; that every wall is the real wall with the origin swapped; and that the settings a
`--mock` run resolves differ only in the flag and the three paths it redirects. A rehearsal
proves the code that ships **with one value changed**, and the value is named and pinned.

Three things hold that honest:

- **The walls are disjoint.** With `--mock` only the mock's origin is admitted; without it,
  only the real host. A run given the wrong one stops at the wall with the URL in hand.
  0001's worry was "a typo points a real run at a real host"; the flag's worry is the
  mirror of it — a forgotten flag — and disjointness is what makes that loud.
- **The flag has one door.** Not `DATAPORTER_MOCK`, not `config.toml`. The whole hazard is
  "did I mean this run to be real", and the answer has to be on the command line every
  time rather than in a shell somebody exported an hour ago. 0001 rejected "an environment
  override honoured only under a test flag" as the same door, hidden; this keeps that
  refusal while opening the visible one.
- **What a mock run writes is kept apart.** `~/.dataporter/mock/{accounts,store}` and
  `./migration-mock`, so a snapshot of invented chats never sits in `dataporter snapshots`
  looking like a backup of the account it names.

## What was given up

- **Byte-identity**, above. A rehearsal now runs a binary configured one way against a
  mock and another way against the real site.
- **A real Hermes can no longer be pointed at a mock.** `skills/claude-migrate/SKILL.md`
  names `https://claude.ai` eight times, including the agent's own rule about where it may
  navigate, and it is installed once and never varies. Templating it would turn that rule
  into "wherever you were told", which is a worse trade than losing a capability nobody
  uses: brief 02 §23 already runs rehearsals with the scripted agent, and §28 already
  parked a real Hermes against a mock as not-a-rehearsal. It is now impossible rather than
  merely unsupported.
- **`Surface` is no longer a parameter and nothing else.** Its docstring said "never read
  from config or the environment… so the wall has no door that ships"; it is derived from
  the flag now, and that sentence is what this ADR supersedes in code.
- **The `certificate` observation is gone from traces**, with TLS. The extraction
  rehearsal's criterion that both of ChatGPT's hosts were certified is replaced by one
  that reads the crossing off a path only the auth origin serves.

## Considered

**Keeping TLS and injecting Chrome's arguments from the flag.** `--mock` would append the
resolver rule and `--ignore-certificate-errors` in `launcher.py`, leaving every URL, wall,
trace and the whole destination half untouched — about twenty lines, against the hundred
this took. It was rejected because it keeps the certificate machinery that is most of the
cost being removed, and because trusting *every* certificate is a broader hole than
pointing at one address.

**Serving plain HTTP as `claude.ai`.** It would have kept the host and cost only the
scheme. Chrome force-upgrades HSTS-preloaded domains, and `claude.ai` is one, so the mock
would never be reached.

**One origin for the mock chatgpt.com.** Both of its host names used to be one socket told
apart by the `Host` header the resolver rule supplied. With no rule there is no name to
route on, so the auth origin is a second port — cheap now that no certificate has to cover
two SANs, and it keeps the wall's auth branch and the sign-in's crossing exercised.
