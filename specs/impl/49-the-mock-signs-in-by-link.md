# 49 — The mock signs in by link

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 07](../07-claude-sign-in.md) §79; the rehearsal half of §73 and §76
**Depends on:** [26](26-mock-claude.md), [32](32-mock-export-page.md), [38](38-mock-core.md),
[46](46-extraction-rehearsal.md), [50](50-the-login-that-waits.md), [53](53-login-link.md)
**Enables:** [52](52-the-paperwork.md)
**Status:** Built

## Goal

The mock claude.ai grows the sign-in the real site has and loses the one it never had:
an address submitted mints a sign-in link instead of mailing one, redeeming that link in
the browser that asked signs it in, and there is no password step anywhere. Both
rehearsals then sign in to it the way brief 07's two commands sign in — `login` holding
the window, `login --link` spending the link in it — with the runner standing where a
person would stand at that window. The tool stays byte-identical (§22); what changes is
the site it is pointed at and the protocol that points it.

## In scope

- **The sign-in as state** (`mock/src/claudemock/site.py`): `SignInLink(token, email,
  pending, minted_at, spent)`, its `fragment` (`<token>:<base64url address>`, no
  padding); `Site.request_sign_in(email, pending=…)` — the account's one address
  remembered as pending for the browser that gave it and a 32-hex token minted, counted as
  `links_minted`, `None` for any other address; `Site.resend(pending)`,
  `Site.forget_pending(pending)`; `Site.sign_in_step(pending)` — `email` or `link_sent`;
  `Site.redeem(token, email, pending=…)` — a session, once, for the browser whose pending
  sign-in the link finishes, and `None` otherwise, that browser marked a *stray*;
  `Site.sign_in_links()` in the order minted; `Site.link_of(link)` —
  `https://claude.ai/magic-link#<fragment>`, on the site's own host, where Chrome's
  resolver rule sends it. `Site` loses `password` and `credentials_match`.
- **The pages** (`pages.py`): `login_page(step=…)` at two steps — the email step as `26`
  wrote it, less the password; the link-sent step re-typed from
  `docs/spike/claude-sign-in-link-sent.html`: `input[data-testid="code"]
  [autocomplete="one-time-code"][inputmode="numeric"]`, `button[type="submit"]
  [data-testid="continue"]`, two `type="button"` controls (`#resend`, `#change`) the
  page's script posts for — and `magic_link_page()`, whose script reads `location.hash`,
  clears it with `history.replaceState` as the real page does, and posts the token and
  the decoded address to `/login/redeem` with the browser's cookies, then navigates to
  whatever the answer names.
- **The wire** (`server.py`): `POST /login/email` mints, announces and redirects to
  `/login`; `POST /login/resend`, `POST /login/change`; `POST /login/code` refuses whatever
  was typed (`?error=code`); `GET /magic-link` with no session; `POST /login/redeem` →
  `{"ok": true, "next": "/new"}` with the session cookie, or `{"ok": false, "next":
  "/login"}` with the pending cookie set so that `/login` shows the code page; the witness
  `GET /__mock/sign-in-links` (text, oldest first) and `/__mock/sign-in-links.json`
  (`token`, `link`, `minted_at`, `spent`). `create_app`/`serve` take `announce_sign_in`.
  `/login/password` is gone.
- **The core** (`mockcore`): a seventh ledger row, `links_minted` / `Sign-in links
  minted:`, last, printed as `0` by the mock chatgpt.com; `LOGIN_MAX_AGE_S` (an hour) on
  the pending cookie, so the sign-in outlives the window it began in (§73's second path);
  `SIGN_IN_LINK_NOTE` and `announce_sign_in`; `parser(listings=…)` for a site's own
  listing command.
- **The command** (`claudemock/cli.py`): `claude-mock sign-in-links`; `serve` announces
  sign-in links where it announces export links; `--password` accepted and ignored, and
  the docstring says so.
- **The citations** (`uimap.py`): `sign-in form` rewritten, and five rows added out of
  the map's brief-07 rows — `link requested`, `link sent`, `sign-in link`, `signed in by
  the link`, `link opened elsewhere` — each with what the mock did about it.
- **The runner** (`rehearsal/run.py`): `Runner.start` / `Runner.join` for a step that
  runs while another does, its `Outcome` holding its place in `steps` from the moment it
  begins; `Outcome.flags`, the header flags a step's trace must carry, so that two steps
  writing into one `logs/` in the same moment each keep their own trace (`header_flags`);
  `command(attended=True)` and `run(attended=True)`, which leave `--non-interactive` off
  for a step that has no unattended half; `sign_in_by_link(runner, *source)` — `login` in
  the background, the person played, the newest link read, `login --link`, the join.
- **The person** (`rehearsal/person.py`, new): `enter_address(workspace, email)` reads
  the debug port off the tool's own `config.toml`, waits for the tool's Chrome to show
  the mock's sign-in page, dismisses the banner, focuses `input[type="email"]`, puts the
  address in through `Input.insertText`, presses Enter, and waits for the code field —
  the same control the tool reads as `link sent`; `newest_sign_in_link(host, port)`
  reads the listing that stands in for the inbox. `PersonError` on any deadline, which
  `sign_in_by_link` turns into a killed background step with the reason in its note.
- **Both protocols**: the migration rehearsal replaces `runner.run("login", "login")` with
  `sign_in_by_link(runner)`; the extraction rehearsal does the same for a mock whose
  `link_signin` is true (Claude), keeps `24`'s one unattended `login` for the other
  (ChatGPT), and its seeding `sign_in_claude` becomes the address, the newest link and the
  redeem post with the runner's own cookie jar. `Mock.agent_signin` is false for both.
- **The criteria** (`rehearsal/extraction.py`): `login signs the source account in` reads
  both steps; `driving` includes `login --link`; the sign-ins reconciliation is `1 + the
  tool's`, where the tool's is a link spent (Claude) or the password steps typed
  (ChatGPT); two new rows for Claude, `login saw the link sent and said so` (§73's line in
  the step's stdout) and `sign-in links minted == the seeding's + the tool's` (`2`); the
  ledger block has seven rows. The standing findings say how the sign-in is rehearsed.
- **Tests**: `mock/tests` — the address step, the listing, the link-sent controls, one
  redemption and no second, a link opened elsewhere, resend and change, a code refused,
  the pending cookie's lifetime, the announcement, the seventh row, the fifth command;
  `tests/test_rehearsal.py` — a started step holds its place and is collected, can be
  ended by force, the attended command, two traces told apart by their headers;
  `tests/test_rehearsal_extraction.py` — the Claude half's two steps, two links and
  thirteen criteria.
- **`mock/README.md`**: a *Sign in to the mock claude.ai* section, the export recipe
  without an unattended sign-in, the seven-row ledger, the `claude-mock` bullet.

## Out of scope

- **The words** — `docs/LIMITATIONS.md`, `unattended_signin="none"`, the deletion of
  Claude's agent path from the tool's own reach — which are `52`'s.
- **A code door.** The mock mints no code and takes none (§80). A rehearsal of `--code`
  waits on an observation of the real code page and on the slice that builds it.
- **What a link opened elsewhere really shows.** The row is *unknown*; the mock sends
  such a browser to the code page because that is the one shape the tool recognises, and
  `uimap.WHAT_THE_MOCK_DOES` says so rather than claiming the real page does.
- **A walk for the mock claude.ai.** `mock/README.md`'s walk is the mock chatgpt.com's;
  the mock claude.ai's is the tool's own run, as it has been since `29`.

## Design notes

- **The link is the real shape, fragment and all.** The mock could have put the token in
  the query and saved itself a script. It did not, because a rehearsal's trace is the
  baseline the mock is later corrected against: a query key would appear in a rehearsal
  trace and never in a real one, and a fragment is what `46`'s guard strips from both
  (Q10-A). The landing page's script is eleven lines and does what the real page's
  `__ml_handoff` hop does — reads the hash, clears it, posts it — which is also why
  `/magic-link` needs no session: it is how one is made.
- **Whose link is it.** A real link finishes the pending sign-in of whichever browser
  holds the matching address cookie; the mock has one account, so it binds the link to
  the pending *token* of the browser that asked, which is stricter and is what §73's
  *spent here rather than opened* means. A resent link carries the same pending token, so
  a person who did not get the first email is not locked out by asking again.
- **A stray is remembered, not invented.** A browser that redeems a link it has no
  pending sign-in for is marked a stray, and `/login` shows it the code page rather than
  the email step. That is the mock reaching for the one shape the tool recognises for
  `link opened elsewhere` — `signin_link.CODE_PROMPT` — and the citation says the real
  page's shape is unknown. The alternative, showing the email step, would have the tool
  report *not accepted* for a case it has a better line for.
- **The pending cookie has a lifetime because the tool's second path needs one.** §73
  says `login --link` with no window open launches the profile and tries anyway, and
  that works exactly when the pending sign-in survived Chrome closing. Whether the real
  site's cookie does is unobserved (ADR 0008); the mock's does, for an hour, so that path
  can be walked by hand. A rehearsal never takes it: the window is always open.
- **The person is slower than the tool, on purpose.** The first live run spent the link
  within a second of the address going in, between two of `login`'s two-second polls,
  and the tool went from the email step straight to signed in: correct, and §73's
  link-sent line never printed. The runner now leaves the link-sent page showing for
  `LINK_SENT_GRACE_S` (three seconds) before spending the link, as a person reaching an
  inbox would, and the criterion `login saw the link sent and said so` is what would
  catch the line going missing again.
- **The runner plays the person because nobody else can.** `login` has no unattended
  half (§76), so the scripted agent's sign-in task (`24`, `27`) has nothing to reach —
  the form is behind a window the tool holds open and waits at. The runner attaches to
  that window over the same debug port the tool launched it on, read off the tool's own
  `config.toml` rather than assumed, and does what `24`'s credential seam does: the value
  through `Input.insertText`, never through an expression. It is the keyboard, not an
  agent, and `rehearsal/agent.py`'s sign-in task stays in the tree unreachable (Q21-A).
- **Two steps, one `logs/`, one moment.** `login` and `login --link` write their traces
  into the same directory and end within seconds of each other, in either order. The
  runner keeps a step's trace by the `flags` in its header — `[]` for the one that
  waited, `["--link"]` for the one that spent — rather than by whatever is lying there
  when the step ends, which was `36`'s rule and would have filed the wrong trace under
  the wrong step half the time. `Outcome.flags` is `None` for every other step, and
  `36`'s behaviour for them is unchanged.
- **The background step holds its place.** `Runner.start` appends the outcome the moment
  the step begins, so the record reads `login`, `login --link` — the order the protocol
  began them — rather than the order they ended; `keep` still numbers files by when a
  step was collected, so `01-login---link.out` precedes `02-login.out` on disk. The record
  is the reader's; the directory is the diagnostician's.
- **`--non-interactive` stays on the protocol and comes off two steps.** `24` made the
  flag mean "no person"; brief 07 says a Claude sign-in is a person's step. The rehearsal
  keeps its mode for every other command and runs the two sign-in commands without it,
  which is what an operator whose cron job has just been told to `login` would do. The
  window is still headless: `browser.headless = true` in the rehearsal's `config.toml`
  overrides the mode either way (`61`), and the mock has no bot management to object.

## Acceptance criteria

- `uv run --package mocks pytest mock` passes: 160 tests, among them the address step
  minting a link, the link-sent controls, one redemption and no second, a link opened
  elsewhere landing on the code page, the pending cookie's `Max-Age`, the seventh row.
- `uv run pytest tests/test_rehearsal.py tests/test_rehearsal_extraction.py -m "slow or
  not slow"` passes: 56 tests, among them the two-command Claude half with fourteen
  criteria and the runner's background step.
- `POST /login/password` on a running mock claude.ai signs nobody in — signed out, it is
  the login page like every other path — and `sign_ins` stays `0`; the email step's page
  carries no `type="password"` input.
- `make lint` passes.
- **Live, still open:** the extraction rehearsal's Claude half against a real Chrome —
  `login` in the background, the runner at its window, `login --link`, both exit `0`,
  both blocks printed, `sign_ins == 2`, `links_minted == 2`, one trace per step with the
  right flags — and the migration rehearsal's sign-in the same way. Run three times on
  2026-09-15 with a headless Chrome 152 against the real mock: the sign-in half passed
  every time the tool's own race (`53`, *two readers of one window*) did not fire, which
  it did once in three before it was fixed. The rest of the extraction protocol failed
  for two reasons that predate this slice and are not its to fix: the mock's export page
  is still at `31`'s placeholder path while the tool has asked at
  `/new#settings/data-privacy-controls` since `51` (both asks wait out `ask_s` and the
  fetches get an empty link), and slice `60`'s per-file `downloaded` lines print before
  the heading the ChatGPT fetch criterion expects first. Both want a slice of their own;
  no rehearsal record is written from a run that did not pass.

## Risks

- **The person is timed.** `enter_address` gives the tool's Chrome ninety seconds to
  show the email field. A machine that starts Chrome slower than that fails the sign-in
  and the rehearsal says so in the step's note; the number is a constant to raise, not a
  design.
- **The runner reads the tool's `config.toml` for the port.** A rehearsal that wrote its
  configuration differently would leave the person knocking on the wrong port. The runner
  writes that file itself, so today the two agree by construction.
- **The mock's stray state is the mock's.** If the real page, on a link opened elsewhere,
  shows something the tool cannot recognise, the tool reports *not accepted* and the mock
  will have rehearsed a line the real site never produces. The map row is *unknown* and
  says so; the first real spend of a link in the wrong browser is what corrects it.
- **One mock, one account, one pending token per browser.** Two people signing in to the
  mock at once from two browsers each get their own link and their own pending token, and
  the listing interleaves them; the runner takes the newest, which is its own only because
  nothing else is asking. A rehearsal is one browser, so this holds.
