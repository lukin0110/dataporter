# 71 — The mock grows a sign-in screen

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 02](../02-claude-mock.md) §21,
[brief 03](../03-extraction-and-backup.md) §35, §36
**Depends on:** [26](26-mock-claude.md), [46](46-extraction-rehearsal.md),
[70](70-the-sign-in-screen.md)
**Enables:** nothing yet
**Status:** Done

## Goal

Prove `70` with a real Chrome and the shipped tool, which is the only thing that can turn
its criteria from written to measured.

`70` reads two selectors off a page. Against a fake that answers the expression without
running it, that proves the Python; it does not prove that a browser given the real markup
answers `true`, that `:has()` resolves, that an `aria-hidden` element sized to zero is
still found, or that an ask meeting this state stops before it presses anything. The mock
is where those become facts.

Two states, not one. The session lapsing while the profile stays is `70`; the profile
being gone is `69`; they end with the same line and the same exit code and are told apart
by whether a browser opened at all. The rehearsal now walks both, in that order.

## In scope

- **`mock/src/claudemock/pages.py`** — `sign_in_screen()`, the page the site answers a
  signed-out request with when it answers in place. The two signals `70` reads, re-typed
  from `docs/spike/claude-sign-in-screen-2026-09-18.html`: two `aria-hidden`
  `[data-client-attestation="hcaptcha-invisible"]` containers, one on the channel
  `send_magic_link`, and a form holding `[data-testid="email"]` and
  `[data-testid="continue"]` **together**.
- **`mock/src/claudemock/site.py`** — `Site.signed_out_in_place`, default `False`.
- **`mock/src/claudemock/server.py`** — `SIGNED_OUT_SHAPE_PATH = "/__mock/signed-out-shape"`,
  a witness route taking `{"in_place": bool}`, and the `SignedOutError` handler branching on
  it: `200` with the screen at the requested address, or the two redirects it has always
  answered with.
- **`mock/src/claudemock/uimap.py`** — the `sign-in screen in place` row cited, and what the
  mock does for it.
- **`rehearsal/run.py`** — `tell_witness`, `witness_json`'s other half: the two routes a
  rehearsal asks rather than reads.
- **`rehearsal/extraction.py`** — `lapse_the_session`, and four steps on the Claude half
  after `session status`:

  | Step | Exit | What it proves |
  | --- | --- | --- |
  | `extract (the sign-in screen, in place)` | `3` | `70`, against a real Chrome |
  | `session status (signed out)` | `3` | the same session, asked rather than acted on |
  | `logout` | `0` | the profile goes |
  | `extract (no session at all)` | `3` | `69`: no browser opened |

  Three criteria with them: the exit code and the remedy, that nothing was pressed, and
  that the second refusal left no trace at all.
- **`docs/rehearsal-05.md`** — the record.

## Out of scope

- **ChatGPT.** Its map has no such row and its source declares no selectors, so the steps
  are behind `mock.link_signin` and the chatgpt half is unchanged.
- **Making the in-place shape the default.** Both shapes are observed and nobody has
  established when the real site picks which; `50` and `53` drive the redirect. A switch is
  the honest model of that, and the default stays where it was.

## Design notes

**A switch, not a replacement.** `docs/claude-ui-map.md` now has two signed-out rows, both
*observed*: the redirect through `/logout?involuntary` (2026-09-15, from a committed trace)
and the screen in place (2026-09-18, from the artefact). A mock that could only show one
would make the map's other row untestable, and choosing which to show by guessing at the
real site's rule would be the mock inventing claude.ai — which is the one thing §21 forbids
it.

**Both signals or neither.** The mock serves the attestation container and the form
together, and never one alone. A mock that spread the two test ids across different
elements, or dropped the attestation, would let a rule that cannot tell a sign-in screen
from an ordinary page pass a rehearsal — and the whole reason `70`'s rule is a conjunction
is that a single signal is not enough.

**The session lapses rather than never existing.** `lapse_the_session` sets the shape and
*then* expires the sessions, so the browser still carries its cookie and the profile is
still on disk. That is an **involuntary sign-out**, which is the state `70` is for; a
profile that was never signed in never reaches a browser at all after `69`.

**What the traces say, and why it is the better assertion.** The in-place step leaves a
trace of **two lines** — a header and an end — because the run opened a browser, probed
once and stopped. The no-session step leaves **none**. Counting lines and traces is a
sharper claim than reading stderr: it says the tool did not press, did not sketch, and in
the second case did not launch.

## Acceptance criteria

1. `POST /__mock/signed-out-shape {"in_place": true}` then `GET /new` with no session:
   `200` at `/new`, with `data-client-attestation-channel="send_magic_link"` present and
   both `data-testid="email"` and `data-testid="continue"` inside one `<form>`.
   `mock/tests/test_claude_server.py`. ✅
2. Without that call, `GET /new` with no session is still
   `303 /logout?involuntary=1&returnTo=/new`. ✅
3. `uv run python -m rehearsal.run --protocol extraction --root /tmp/r5 --record
   docs/rehearsal-05.md --number 5` against fresh mocks exits `0` and prints every
   criterion `pass`. ✅ *measured on 2026-09-18, Chrome/153.0.8010.48, mode
   `non-interactive`.*
4. In that record: `extract (the sign-in screen, in place)` is exit `3` with a two-line
   trace and no click; `extract (no session at all)` is exit `3` with no trace; both name
   `dataporter --mock login --source claude --account rehearsal`. ✅
5. `make check` and `make check-all` are green, except the one pre-existing macOS-only
   Hermes environment test. ✅

## Risks

- **The mock's markup is the artefact re-typed, not the artefact served.** If claude.ai
  changes either test id, the mock goes on passing while the tool goes quiet against the
  real site. That is true of every row the mock stands on and is why the map, not the
  mock, is the evidence.
- **A third shape.** The site may answer a signed-out export page some other way again —
  a bot check is the obvious candidate, and its row is still *unknown*. The switch takes a
  boolean today and would want a name the day there are three.
