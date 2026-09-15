# 53 — `login --link`

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 07](../07-claude-sign-in.md) §73 (the second command), §74, §76 (the
refusal), §78
**Depends on:** [07](07-browser-session.md), [45](45-fetch-through-the-session.md),
[50](50-the-login-that-waits.md)
**Enables:** [49](49-the-mock-signs-in-by-link.md), [52](52-the-paperwork.md)
**Status:** Built

## Goal

Spend the sign-in link a person read: point the account's own profile at it, wait for the
session to come back signed in, and say so with §73's second block — or say which of the
two known ways it did not. The link is a credential while it lives (§74) and is handled as
the export link is: checked, navigated to once, redacted in the trace, kept nowhere.

## In scope

- **`login --link URL`** on the `login` command, a value and not a file, as `extract --link`
  is. `browser/signin_link.spend` is the body; `session.login` dispatches to it for a source
  that signs in by link.
- **The check.** `links.is_https` before any browser is touched; `LINK_NOT_HTTPS`, exit `2`.
  The scheme rule and its message move to `dataporter/links.py`, and `extract` binds them by
  name so a test can still pretend otherwise. The host is not pinned (Q5).
- **Whose window.** `launcher.adopt` first: `login` (`50`) holds its window open on this
  profile's port, and the marker proves it is ours. Adopted, the browser is never closed
  here (`status`'s rule). No browser on the port: `launcher.launch` the profile, spend the
  link, close it (Q28-A). Headed either way: the mode was refused by `50` before this is
  reached, so `Settings.headless` is `browser.headless` or `False`.
- **The drive.** A signed-in profile prints the block and spends nothing. Otherwise the
  first tab on the site's hosts — the tab the person entered their address in (Q26) — is
  pointed at the link with `Page.navigate` sent directly, as `45`'s fetch does, so that no
  refusal names the URL; `tracing.redacting()` around it, and one move `sign-in-link` in
  `actions.jsonl` and the trace with `url_fields` under redaction: the host, `<link>`, no
  query, no fragment.
- **The wait.** `session.await_signin` for `timeouts.signin_s` (120 s), the same loop `50`
  waits with, read the other way round: signed in is the block; the code field showing again
  — the tab back on `/login` with the pending sign-in not in this profile — is
  `CODE_PROMPT`; the time running out is `NOT_ACCEPTED`. Both exit `3` with the
  invocation's own `login` as the remedy (Q16):

  ```text
  the link led to a code prompt — the pending sign-in is not in this profile; sign in again with: dataporter login --source claude --account work
  the link was not accepted — it may have expired; sign in again with: dataporter login --source claude --account work
  ```

- **The wall.** `claude.SIGN_IN_LINK_PATH = "magic-link"` joins Claude's `sign_in_paths`, so
  both the sign-in's wall and the extraction's admit `/magic-link` and the probe may look at
  where the link lands. The fragment form is not admitted and does not need to be: the page
  moves the hash out of the address bar itself, and nothing drives that URL through a wall.
- **Tests**, in `tests/test_signin_by_link.py`: the link spent in the window `login` is
  holding (adopted, not closed, one navigation, no new tab); the trace's move carrying the
  host and `<link>` and nothing of the token anywhere under `logs/`; the code-prompt refusal;
  the not-accepted refusal; the scheme refusal before any browser; a signed-in profile
  spending nothing; no window open → the profile launched headed and closed.

## Out of scope

- **The mock's redemption and the rehearsal's second terminal**,
  [`49`](49-the-mock-signs-in-by-link.md).
- **Recognising the real code page.** What claude.ai shows when a link is opened where the
  pending sign-in is not has not been seen (`link opened elsewhere`, *unknown*); the refusal
  fires on the one shape the tool knows and the rest is `NOT_ACCEPTED`.
- **`--code`**, §80. **ChatGPT**, which `50` refuses a link for and otherwise ignores.

## Design notes

- **Adopt, don't launch (Q23, Q27).** The pending sign-in is in the window `login` holds
  open; spending the link anywhere else would spend it on nothing. `launcher.adopt` already
  answers "is the browser on this port ours" by the marker, and `status` already uses it
  and leaves what it adopted running. Nothing new was needed to make two terminals share
  one window, only the ownership rule kept.
- **The first tab, not a new one (Q26).** A new tab would leave the first at the code prompt
  and the person with two windows, and `login`'s wait probes the first tab. Navigating the
  tab the person used is also what the vendor's own page expects: its script reads the
  pending sign-in's cookie and the hash together.
- **The two refusals are told apart (Q6)** because they mean different remedies for a
  person: a code prompt means the profile lost the pending sign-in and `login` must be run
  again from the start; not accepted means the link itself is the problem. The words are
  fixed even though the second covers several causes, because the tool cannot tell them
  apart and a message that guessed would be worse than one that says what it saw.
- **Back at the code prompt, not still on it.** The tab was on the link-sent page, code
  field showing, when the link was navigated to, and `Page.navigate` returns before the
  old document is gone — so the first looks after it can still be answered by that page,
  and a wait that took the code field as its answer at once would refuse a link about to
  work (raised by Copilot in review on #58). `_await` therefore has its own loop rather
  than `session.await_signin`'s: the code field is `CODE_PROMPT` only once the tab has
  been seen somewhere else first — at a URL that is not the one the link was navigated
  away from, off `/login` altogether, or mid-navigation with nothing to read. Signed in
  ends it at any time; nothing else inside `signin_s` is `NOT_ACCEPTED`. The URL and not
  only the page's kind, because where a link lands is unobserved: one that landed under
  `/login` would never leave that kind, and the tab would sit at a real code prompt
  reporting that the link was not accepted (raised by the spec review of #58).
- **A window that closes under the wait is exit `1`, not `6`.** Exit `6` means the
  environment is not ready and names `doctor`; nothing here is unready. This is `ask`'s
  shape for a page that would not confirm (`31`): the link is spent, the account may or
  may not have taken it, so the note says what happened, `session status` is named, and
  no record claims either way.
- **The trace carries the host (§66).** As the fetch's move does: enough to say where the
  link went, nothing of the link. The header records `--link` as a flag name only (`33`).
- **Two readers of one window, and who blinks first.** `49`'s rehearsal found the race in
  one run of three: `login` saw the session signed in and closed its window in the same
  instant, and this command's next two-second look found no browser and died of a
  connection error after doing its job. So this command polls every `LINK_POLL_S` (0.5 s)
  after the navigation, `login` keeps its window `session.SPENDER_GRACE_S` (3 s) after it
  sees the link spent, and a window that still goes early is named rather than guessed at:
  `WINDOW_CLOSED`, exit `6`, pointing at `session status` with the account's flags. The
  session may well be signed in at that point; this command does not say so without having
  seen it.

## Acceptance criteria

- `dataporter login --link <url>` while `login` holds the window: exit `0`, the second block,
  one `Page.navigate` to the link, no `Browser.close`, no new tab
  (`test_the_link_is_spent_in_the_window_login_is_holding`).
- The trace has one move, `sign-in-link`, with `{"host": "claude.ai", "path": "<link>",
  "query": []}`, and the token appears nowhere under `logs/`
  (`test_the_trace_carries_the_link_s_host_and_never_the_link`).
- The tab back at the code field — after being seen on the link's page — is `CODE_PROMPT`,
  exit `3`; the old document still answering with the code field right after the
  navigation is not (`test_the_old_document_answering_after_the_navigation_is_not_a_code_prompt`);
  nothing inside `signin_s` is `NOT_ACCEPTED`, exit `3`; `http://` is exit `2` before any browser
  (`test_a_link_that_lands_back_on_the_code_prompt_is_refused`,
  `test_a_link_that_is_not_accepted_in_time_is_refused`,
  `test_a_link_that_is_not_https_is_refused_before_any_browser`).
- No window open: the profile is launched without `--headless=new`, the link spent, the
  browser closed (`test_with_no_window_open_the_link_launches_the_profile_and_closes_it`).
- The adopted window closing after the navigation is `WINDOW_CLOSED` on stderr, exit `1`,
  naming `session status`, with nothing on stdout
  (`test_a_window_that_closes_under_the_link_names_status_rather_than_guessing`).
- A code prompt on a sign-in path of the link's own is still `CODE_PROMPT`
  (`test_a_code_prompt_on_a_login_path_of_its_own_is_still_a_code_prompt`).
- Live against the mock claude.ai (`49`, Chrome 152, headless): a link minted by the mock,
  spent while `login` holds its window, ends both commands with the second block. *run on
  2026-09-15, three times; the third found the race above, fixed since.*
- Live against claude.ai: a real link. *not yet run*

## Risks

- **The emailed address is a mail host's redirect**, not `claude.ai/magic-link` itself. The
  navigation follows it (`Page.navigate` follows redirects), the trace records the mail
  host and `<link>`, and the wait sees the tab come back to claude.ai; only the `link sent`
  row's artefact says what the final URL is. *unknown* until a real link is seen.
- **The pending sign-in does not survive the window closing.** Then the no-window branch
  always ends at `CODE_PROMPT`, which is the honest answer, and §80 records the observation
  that would settle it.
- **A link spent in a window `extract` is holding** navigates the ask's tab away
  (`docs/LIMITATIONS.md`, *two terminals, one browser*).
