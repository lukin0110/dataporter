# 50 — The link-sent state, and a login that waits

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 07](../07-claude-sign-in.md) §73 (the first command), §74, §75, §76 (the
refusal), §78
**Depends on:** [07](07-browser-session.md), [24](24-non-interactive.md), [42](42-source-seam.md),
[48](48-the-words.md)
**Enables:** [53](53-login-link.md), [49](49-the-mock-signs-in-by-link.md), [52](52-the-paperwork.md)
**Status:** Built

## Goal

Give `login` the shape §73 describes for a Claude account: a window at the sign-in page, the
block that tells a person what to do in it, the moment the vendor says the link is on its
way recognised without reading a word, and a window that stays open until `login --link`
(`53`) has spent the link in it. Nothing here signs anybody in: the person and the vendor do
that, and the tool waits, says what it sees, and closes the window it opened.

## In scope

- **The signal.** `login_form.CODE_SELECTOR`, `input[data-testid="code"],
  input[autocomplete="one-time-code"]`, beside the email and password selectors; a third
  boolean, `code`, in `LOGIN_FIELDS_JS` and `Fields`; the `link sent` row of
  [`docs/claude-ui-map.md`](../../docs/claude-ui-map.md), *observed on 2026-09-15* against
  [`docs/spike/claude-sign-in-link-sent.html`](../../docs/spike/claude-sign-in-link-sent.html),
  a redacted copy of the page read in Spanish. `Fields.any` leaves `code` out, and
  `fill_and_submit` reports a page already showing it as `code_or_challenge`, which is what
  it is.
- **The source says so.** `Source.sign_in_by_link`, `True` for Claude and default `False`;
  `session.Whose` carries the vendor's display name and the flag, and the destination — a
  Claude account (§75) — gets Claude's.
- **`session.login`** branches on it. A source that signs in with a form keeps `07`'s bytes.
  A source that signs in by link runs `_login_by_link`: launch, the probe (`signed_in`, which
  may still open the browser's first tab), and then
  - signed in already → the second block;
  - otherwise the first block on the sink, and `await_signin` for `timeouts.login_s`: signed
    in → the second block; the code field → `LINK_SENT_LINE` with `login_s / 60` minutes and
    `await_signin` again on a fresh `login_s` with `link_sent_ends=False` — signed in → the
    second block, or `LINK_TIMED_OUT` with the invocation's own `login` command, exit `3`;
    the first phase's timeout is `LOGIN_TIMED_OUT` unchanged.
  - Chrome is closed on every path, as `07` closes it — after `SPENDER_GRACE_S` (3 s) when
    the link was spent, so that the terminal that spent it sees the signed-in page before
    the window goes (`53`'s design notes have the race `49` found).
- **`session.observe` and `await_signin`.** `wait_for_login`'s loop with one difference: it
  never creates a tab. `observe` attaches to the first tab on the site's hosts, waits for
  the document, probes, and reads the code field only when the probe's kind is `LOGIN`; a
  browser with no tab on the site is "not yet", as a failed probe is. `poll_s` is read at
  call time from `LOGIN_POLL_S`, so a test can shorten the cadence.
- **The three golden strings.** `SIGN_IN_BLOCK` and `SIGNED_IN_BLOCK` are §73's two blocks
  with `{vendor}` and a heading that carries ` — <label>` only for a source account, and the
  invocation's own command spelled with `--source` and `--account` (`login_command`).
  `LINK_SENT_LINE` is §73's line. The destination's `Logged in. Session stored in …` becomes
  `Signed in to Claude` over two lines; ChatGPT keeps `Logged in. Session stored in …`.
- **The mode is refused** for a source that signs in by link: `UNATTENDED_REFUSED`, exit `2`,
  before any browser starts, with or without `--link` (Q15-A). `require_credentials` is not
  reached.
- **`NO_LINK_SIGN_IN`**, exit `2`, for `--link` on a source that signs in with a form.
  ChatGPT's link story is out of scope; a flag silently dropped is not.
- **Tests.** `tests/test_signin_by_link.py`, against a fake tab (`SignInPage`) that answers
  the probe and `login_form`'s field reading stage by stage: the whole first command, a
  source account's block, the restarted clock and its timeout, a pending sign-in the window
  opens on, the wait opening no tab while the tab is off the site, the mode refused, the
  form source refusing a link. The golden pins in `test_browser_session.py`,
  `test_source_session.py`, `test_sources.py`, `test_login_form.py` and `test_unattended.py`
  move with the words.

## Out of scope

- **Spending the link**, which is [`53`](53-login-link.md).
- **The mock and the rehearsals**, which are [`49`](49-the-mock-signs-in-by-link.md).
- **`unattended_signin = "none"`** and the words around it, which are
  [`52`](52-the-paperwork.md). Until then `import --non-interactive` on a signed-out
  destination still reaches `24`'s agent half; `login` in the mode does not.
- **`session status` on a pending sign-in** (Q11): it says `not logged in` and names `login`,
  which is true. A "link on its way" answer waits on the reopen observation §80 names.
- **`--code`**, §80.

## Design notes

- **The window stays open (Q23-A).** `48` designed the first command to leave when the link
  was sent, on the strength of the pending sign-in being "already in that cookie jar". Nobody
  has read that cookie's lifetime, and Chrome drops a cookie without one on exit. Keeping the
  window open makes the design independent of the answer: the link is spent in the browser
  that started the sign-in, whatever its cookie jar does afterwards. What it costs is a
  blocking command and a second terminal, and §73 now says so. ADR 0008's sentence was
  widened rather than replaced.
- **Two phases, one number (Q24-B).** The mailbox's delay starts when the link is sent. A
  person who spent nine minutes on a challenge should not be left sixty seconds for their
  email, and a second setting would be a second number nobody can explain; `login_s` is
  simply restarted.
- **The signal is a field, not a request (Q2).** The watch sees `POST
  /api/auth/send_magic_link` too, and a trace records it — but a trace says what it saw (ADR
  0006), and a decision made on a network observation would be a decision made where the
  tool's own signals are not. The field is on the page, in the same place `24` already looked
  for a code prompt, and it is the same thing `login_form` reports as `code_or_challenge`.
  The pending-login cookie was never a candidate: its value is the address.
- **Probe-only waiting (Q26).** `53` navigates the tab the person used, and a link that hops
  through a mail host takes that tab off claude.ai for a moment. A wait that opened a tab
  there would leave the person two windows and `53` a tab it did not navigate. The browser
  `login` launched already has a tab, so nothing is lost by never creating one.
- **Both commands print the ending (Q27).** The person may be watching either terminal, and
  `53` may be the only command running. Each terminal is complete on its own.
- **The interactive extract on a signed-out Claude profile** used to print the old prompt
  and wait ten minutes for a sign-in that could only be finished by clicking a link in a mail
  client — which shows a code, not a session. `52` makes it exit `3` and name `login`.

## Acceptance criteria

- `dataporter login` on a signed-out destination prints §73's first block byte for byte,
  then the link-sent line when the code field appears, then the second block when the
  session is signed in, exit `0`, and Chrome is closed (`test_login_prints_the_block_and_waits_until_the_link_is_spent`).
- A source account's heading and command carry its label and flags
  (`test_a_source_account_s_block_carries_its_label_and_its_own_command`).
- A link never spent: the second phase times out with `LINK_TIMED_OUT` naming the command,
  exit `3` (`test_the_clock_restarts_when_the_link_is_sent`).
- The wait creates no tab while the only tab is off the site
  (`test_the_wait_opens_no_tab_while_the_link_hops_through_another_host`).
- `--non-interactive login`, with or without `--link`, is exit `2` with `UNATTENDED_REFUSED`
  and no browser (`test_login_in_the_mode_is_refused_before_a_browser_starts`,
  `test_the_mode_is_refused_with_a_link_too`).
- `CODE_SELECTOR` is spelled once and counted by the sketch by name
  (`test_the_code_field_is_read_and_never_typed_into`).
- The window outlives the sight of the link spent by the grace, and the grace is the last
  pause before the close (`test_the_window_stays_a_grace_after_the_link_is_spent`).
- Live against the mock claude.ai (`49`): `login` prints the block, the line and the second
  block, and its trace shows the link-sent state. *run on 2026-09-15*.
- Live: a real `login` against claude.ai prints the line when the page shows the code field,
  and the `link sent` row's artefact is the page it read. *observed on 2026-09-15 for the
  page; the run itself not yet*.

## Risks

- **The code field moves or loses its attributes.** The tool then never sees the link sent,
  prints no line, and the first phase times out with `LOGIN_TIMED_OUT` — wrong in the safe
  direction, and one edit in `login_form.CODE_SELECTOR`.
- **The email step's own markup is unobserved.** Nothing here depends on it: the person
  types there, not the tool.
- **A challenge that takes the tab off `/login`** (a Cloudflare interstitial on its own
  path) reads as "not yet" until it resolves; the first phase's ten minutes are the budget
  for that, as `07` intended.
