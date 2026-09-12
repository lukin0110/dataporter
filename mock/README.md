# claude-mock

A served stand-in for the whole of claude.ai, for **rehearsing** a migration
against: the shipped tool, unchanged, driven through its whole protocol by a
real Chrome, on a machine with no Claude account and no model.

It behaves on its own. It is not scripted per run, there is no model behind it,
and nothing in it knows what a rehearsal is doing. What it knows is how to be a
site: sign somebody in, take a message, answer it, keep the chat at a URL that
survives a reload, accept a file, and take a new name for a chat.

> This is a **separate project** that lives in this repository for now. It
> imports nothing from `dataporter` and `dataporter` imports nothing from it;
> moving it out is a directory move ([ADR
> 0003](../docs/adr/0003-the-mock-is-a-separate-project.md)).

## Run it

```sh
uv run --package claude-mock claude-mock serve
```

It prints the one thing you need in order to reach it — nobody composes a
resolver rule by hand:

```text
Mock claude.ai listening on https://127.0.0.1:8443

Add to <workspace>/config.toml before running the tool:

[browser]
extra_args = [
  "--host-resolver-rules=MAP claude.ai 127.0.0.1:8443",
  "--ignore-certificate-errors-spki-list=AbCdEf0123456789AbCdEf0123456789AbCdEf0123456789=",
]

```

On a machine whose environment names a proxy — `https_proxy` and friends, which
Chrome reads on Linux — the mock prints one more line, because a proxy resolves
the host name itself and the resolver rule would never fire. `"--no-proxy-server"`
in the same list is the answer.

The tool then reaches the mock the way any operator's configuration reaches
anything: Chrome maps the host name, and trusts **this key and no other**. There
is no flag, no environment variable and no host setting in the tool that names
the mock ([ADR 0001](../docs/adr/0001-no-door-in-the-wall.md)).

The credentials are invented and configured here. The defaults are
`rehearsal@example.invalid` and `rehearsal-not-a-real-password`; `--email` and
`--password` change them. Exactly that pair signs in, and any other is refused,
so a wrong credential fails a rehearsal rather than passing it.

## Ask it what it did

```sh
uv run --package claude-mock claude-mock ledger
```

```text
Mock claude.ai — ledger

Sign-ins:                      2
Chats created:                 8
Messages received:            11
Files accepted:                2
Renames:                       8

```

This is the witness. Nothing in the tool can tell a rehearsal from a real run,
so the mock is the only party that can say what really happened on the other
side of the wire — and a rehearsal record whose numbers do not reconcile with
these is not a rehearsal (§25). The same numbers are printed when the process
is stopped, and served as JSON at `/__mock/ledger.json`.

## What it does, and why

Every state the mock can show is a row of
[`docs/claude-ui-map.md`](../docs/claude-ui-map.md) — the same table the tool's
own probe is written against — and `claude-mock rows` prints each row beside
what the mock decided it meant:

```sh
uv run --package claude-mock claude-mock rows
```

Where that table says *unknown*, which today is every row, the mock takes the
simplest behaviour the tool already accepts and says that it did. A behaviour
the mock needs and the table has no row for is added to the table first, marked
*unknown*. **A mock run never turns an *unknown* into an *observed***: only a
person watching the real claude.ai does that, and a rehearsal is not evidence
about claude.ai (§27).

The behaviours worth knowing before you read the code:

- **Obedient.** A migration seed ends by asking Claude to reply with exactly one
  line. The mock finds that line and replies with exactly it — after a non-zero
  delay, growing in at least two steps, so that "the reply stopped growing" is
  something a rehearsal really waits for. A message that asks for no particular
  line gets one canned sentence.
- **Two-step sign-in.** A banner that hides the form until it is dismissed once,
  buttons for other providers and a passkey that lead nowhere, then the email
  step and the password step.
- **Chats.** A submit creates a chat with its own id and URL; reloading that URL
  shows every turn; the chat's own menu renames it and the new name survives a
  reload; a file input takes a file and shows it by name.
- **In memory.** State lives for as long as the process does, so a rehearsal in
  several sessions sees the same chats throughout. Restarting resets it.

## What it cannot do yet

Named so that a later slice can claim them (§21, §28): a rate limit, a login
expiry mid-run, a modal or a JavaScript dialog in the way, a generation error, a
CAPTCHA or security challenge, and a code prompt at sign-in.

## Tests

```sh
uv run --package claude-mock pytest mock
```

They cover the behaviour (`site.py`) without a socket, and the wire (`server.py`,
a FastAPI application served by uvicorn) over a real TLS connection to a real
port. What they cannot cover is a real Chrome: that is what a rehearsal is.
