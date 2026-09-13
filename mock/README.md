# claude-mock

A served stand-in for the whole of claude.ai, for **rehearsing** a migration
against: the shipped tool, unchanged, driven through its whole protocol by a
real Chrome, on a machine with no Claude account and no model.

It behaves on its own. It is not scripted per run, there is no model behind it,
and nothing in it knows what a rehearsal is doing. What it knows is how to be a
site: sign somebody in, take a message, answer it, keep the chat at a URL that
survives a reload, accept a file, take a new name for a chat — and, since `32`,
take an ask for the account's export and hand out a link instead of an email, so
that extraction can be rehearsed against it too.

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

Set in the tool's environment before fetching an export link from it:

  SSL_CERT_FILE=/home/you/.cache/claude-mock/claude-mock.pem

```

On a machine whose environment names a proxy — `https_proxy` and friends, which
Chrome reads on Linux — the mock prints a note, because a proxy resolves the host
name itself and the resolver rule would never fire. `"--no-proxy-server"` in the
same list is the answer for Chrome, and `no_proxy=127.0.0.1` beside
`SSL_CERT_FILE` is the answer for the tool's own fetch of an export link, which
reads the same proxy.

The tool then reaches the mock the way any operator's configuration reaches
anything: Chrome maps the host name, and trusts **this key and no other**. There
is no flag, no environment variable and no host setting in the tool that names
the mock ([ADR 0001](../docs/adr/0001-no-door-in-the-wall.md)).

The credentials are invented and configured here. The defaults are
`rehearsal@example.invalid` and `rehearsal-not-a-real-password`; `--email` and
`--password` change them. Exactly that pair signs in, and any other is refused,
so a wrong credential fails a rehearsal rather than passing it.

## Ask it for an export

The mock serves the page where claude.ai lets a user ask for their data — at the
tool's placeholder path, with the tool's placeholder selectors, all of them
`*unknown*` in the UI map — and, since it has no inbox to email, prints the link
in its own terminal and serves it to any other:

```sh
uv run --package claude-mock claude-mock exports      # one link per line, oldest first
```

The link is an address on the mock's own host and port, under `/__mock/`, and it
is fetched by the tool with Python rather than with Chrome: the two Chrome
arguments above do not reach it, which is why the block also names the
certificate to trust. That certificate names `127.0.0.1` alone, so on any other
`--host` the tool cannot fetch a link, and `serve` says so when it starts. The archive it downloads is the mock's own chats, rendered
as a Claude export at the moment of the fetch — so a rehearsal can migrate into
the mock and then extract what it migrated. A link nobody asked for is `404`,
which the tool reports as `link refused: HTTP 404` and leaves the ask open on.

Both moves of an extraction, end to end, on a machine with no account:

```sh
export DATAPORTER_AUTH__EMAIL=rehearsal@example.invalid
export DATAPORTER_AUTH__PASSWORD=rehearsal-not-a-real-password
dataporter --non-interactive login --account mock          # the source session
dataporter --non-interactive extract --account mock         # the ask; the mock prints the link
LINK=$(uv run --package claude-mock claude-mock exports | tail -n 1)
SSL_CERT_FILE=~/.cache/claude-mock/claude-mock.pem no_proxy=127.0.0.1 \
  dataporter extract --account mock --link "$LINK"          # the fetch; a snapshot is filed
dataporter snapshots
```

An unattended `login` needs a `hermes` on the path for the sign-in, which is
`24`'s agent half; `rehearsal/` writes a model-free one. Interactively, the
window is open and you sign in yourself.

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
Exports requested:             1

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
- **An export page.** A button, a confirmation, and a status region that appears
  only once the ask has been counted and a link minted. The link lives until the
  process stops, may be fetched any number of times, and a second ask adds a
  second link — the simplest behaviour the tool accepts, since every row of that
  page is *unknown*.
- **In memory.** State lives for as long as the process does, so a rehearsal in
  several sessions sees the same chats throughout. Restarting resets it.

## What it cannot do yet

Named so that a later slice can claim them (§21, §28): a rate limit, a login
expiry mid-run, a modal or a JavaScript dialog in the way, a generation error, a
CAPTCHA or security challenge, and a code prompt at sign-in. On the export page:
a link that expires, a rate limit on asking, and an email — the mock has no
clock a link could die on and no inbox to send to.

## Tests

```sh
uv run --package claude-mock pytest mock
```

They cover the behaviour (`site.py`) without a socket, the archive (`archive.py`)
with `zipfile` and `json` and nothing of the tool's, and the wire (`server.py`, a
FastAPI application served by uvicorn) over a real TLS connection to a real
port. What they cannot cover is a real Chrome: that is what a rehearsal is.
