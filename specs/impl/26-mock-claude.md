# 26 — The mock claude.ai

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 02](../02-claude-mock.md) §21
**Depends on:** [08](08-browser-helpers.md), [10](10-attach-spike.md)'s
[UI map](../../docs/claude-ui-map.md)
**Enables:** [27](27-scripted-hermes.md), [29](29-rehearsal.md)
**Status:** Done

## Goal

A served stand-in for the whole of claude.ai that a real Chrome can be pointed
at: it signs somebody in, takes a message, answers it, keeps the chat at a URL
that survives a reload, accepts a file, and takes a new name for a chat. It
behaves on its own — nothing in it is scripted per run and there is no model
behind it — and it counts what it was asked to do, because that count is the
only witness a rehearsal record can reconcile against.

It is not a simulation of claude.ai. It is a consequence of
[`docs/claude-ui-map.md`](../../docs/claude-ui-map.md), and a rehearsal against
it is no evidence at all about the real site (§27).

## In scope

- **A separate project** (ADR [0003](../../docs/adr/0003-the-mock-is-a-separate-project.md)):
  `mock/`, package `claudemock`, command `claude-mock`, its own `pyproject.toml`,
  dependencies, tests and `README.md`, listed in the root `pyproject.toml`'s
  `[tool.uv.workspace]`. One dependency, `cryptography`, and it exists only to
  mint a certificate. It imports nothing from `dataporter` and `dataporter`
  imports nothing from it.
- **`site.py`** — the behaviour, with no HTTP in it. `Site` holds the accounts,
  the chats and the ledger; `Chat.view(now)` is the transcript as the page shows
  it; `Reply` is an answer being written. `asked_line` finds the one line a seed
  asks for — `Reply\s+with\s+exactly\s+one\s+line:` and the line under it, the
  **last** match winning — and the reply is exactly that line, after a non-zero
  delay, revealed in at least two steps. A message that asks for no line gets
  `CANNED`, one sentence about nothing.
- **`pages.py`** — the markup, selector for selector out of the UI map's middle
  column: a ProseMirror-shaped `div[contenteditable="true"]` (one `<p>` a line,
  `white-space: pre-wrap`), `[data-testid="user-message"]` and
  `…="assistant-message"` turns, a `Send`/`Stop` `aria-label` pair, a hidden
  `input[type="file"]`, a chip row outside the composer, and
  `[data-testid="chat-menu-trigger"]` carrying the title with a rename control
  and a title field behind it. The page's own script submits, polls, uploads and
  renames through the mock's HTTP API, and renders the human turn *synchronously*
  on Enter, because that is the state the tool probes for immediately afterwards.
- **The sign-in page**: a banner that hides the form until it is dismissed once
  (a cookie, so the dismissal survives the form's own POST), buttons for Google,
  Apple, SSO and a passkey that lead to `/login/unsupported`, then the email step
  and the password step. Exactly one configured pair signs in; any other is
  refused with `?error=refused` and the email step again.
- **`server.py`** — HTTPS on `127.0.0.1`, threaded, HTTP/1.1. Routes: `/login`
  and its two POSTs, `/new`, `/chat/<uuid>`, `/api/chats`,
  `/api/chats/<id>/messages`, `/api/chats/<id>/title`, `/api/uploads`, and the
  ledger at `/__mock/ledger` and `/__mock/ledger.json`. Signed out, everything
  but `/login` redirects to it. The session cookie carries a `Max-Age`, so a
  session survives Chrome being closed and started again.
- **`certificate.py`** — a self-signed P-256 certificate for `claude.ai`, kept
  between runs under `~/.cache/claude-mock`, and `pin_of`, the base64 sha-256 of
  its DER SubjectPublicKeyInfo, which is exactly what Chrome's
  `--ignore-certificate-errors-spki-list` hashes.
- **`ledger.py`** — five counters and §21's block, byte for byte, 32 columns
  wide.
- **`cli.py`** — `claude-mock serve` prints §21's reachability block and nothing
  else on start (plus one advisory line when this machine's environment names a
  proxy, which Chrome reads and which would resolve the host itself); `ledger`
  prints the count from a running mock; `rows` prints every UI map row the mock
  stands on beside what it decided that row meant. A reply delay of zero or
  fewer than two steps is refused with exit `2`.
- **`uimap.py`** — `ROWS` (the mock's own words → the map's row labels) and
  `WHAT_THE_MOCK_DOES` (a line per row). `mock/tests/test_uimap.py` reads
  `docs/claude-ui-map.md` and fails when the mock cites a row that is not there.
- **Tests**: the behaviour without a socket (obedience, the wrapped instruction,
  growth in steps, the ledger), and the wire over a real TLS connection to a real
  port (the redirect when signed out, both sign-in steps, both refusals, a chat
  that survives a reload, a second message, a rename, an upload, the ledger).

## Out of scope

- Failure states on cue — a rate limit, a login expiry mid-run, a modal, a
  generation error, a CAPTCHA, a code prompt. §21 names them and §28 keeps them;
  the mock's README repeats the list.
- Serving `08`'s fixture pages. That needs failure pages the mock cannot produce.
- State that survives a restart. In memory is what §21 asks for.
- Anything the UI map has no row for. Adding the row comes first, marked
  *unknown*.

## Design notes

- **The banner hides the form.** The map's `sign-in form` row is *unknown*, so
  the mock may take any behaviour the tool already accepts — and a banner that
  covered nothing would make "dismiss the banner" a step a rehearsal could skip
  without noticing. Hiding the form behind it is what makes §24's agent half do
  something a rehearsal can fail without.
- **The obedience regex tolerates wrapping.** The first rehearsal answered a
  canned sentence to every part of its only multi-part conversation, because the
  seed's footer wraps `Reply with` / `exactly one line:` across two lines. The
  words are separated by `\s+` now. This is the shape of mistake the mock is for:
  it reads the tool's real output rather than a summary of it.
- **The session cookie has a lifetime.** Without one, closing Chrome ended the
  session, and every command after `login` signed in again — which is not what
  storing a session in the workspace profile means, and would have made §25's
  sign-in reconciliation meaningless.
- **Trust is scoped to the key, never to every certificate.**
  `--ignore-certificate-errors` would take the operator's rehearsal browser off
  the internet's trust rules for every host it visits. The SPKI pin is the
  smallest thing that works.
- **The ledger lives at a path no helper will drive.** `/__mock/ledger` is not a
  claude.ai path, so §17's wall keeps the tool away from its own witness.

## Acceptance criteria

- `claude-mock serve` prints §21's block with a real pin in it; a Chrome given
  those two arguments loads `https://claude.ai/login` from the mock.
- The configured pair signs in and any other pair does not; `claude-mock ledger`
  then reports one sign-in.
- A submit creates a chat with a `/chat/<uuid>` URL, the reply appears in at
  least two steps and is exactly the line the seed asked for, and reloading the
  URL shows every turn.
- A renamed chat still has its new name after a reload; a file put into the file
  input is counted and shown by name.
- `claude-mock rows` names only rows that exist in `docs/claude-ui-map.md`.
- `uv run --package claude-mock pytest mock` is green.

## Risks

- **The mock is only as good as the UI map, and the map is entirely `*unknown*`.**
  A rehearsal that passes against it says nothing about claude.ai. The mitigation
  is the sentence, repeated in the README, the record and §27: a mock run never
  turns an `*unknown*` into an `*observed*`.
- **A mock that is wrong in the same direction as the tool cannot catch the
  tool.** Both are written against the same table by the same people. What limits
  that is the ledger: the numbers come from the mock's own request handling, not
  from anything the tool told it.
