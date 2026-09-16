# 63 — Everything but the logs

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 08](../08-signing-out.md) §81, §82, §83, §84, §85, §86; amends
[Brief 07](../07-claude-sign-in.md) §74 and brief 02 §23
**Depends on:** [07](07-browser-session.md), [31](31-source-session-and-ask.md),
[45](45-fetch-through-the-session.md)
**Enables:** `nothing yet`
**Status:** Built

## Goal

Replace `session logout` with `dataporter logout --source claude --account work`, and make
it remove the account home's session, its open ask and what a fetch staged — keeping only
its logs. The command names one source account and has no destination form.

## In scope

- **`dataporter logout`**, a top-level command beside `login`. `browser.session.logout` is
  still the body and `LogoutOutcome(removed)` is still what it returns (`23`), so the
  library and the CLI stay the same command twice over.
- **`--account LABEL`, required**, declared as `extract`'s is — the bare `Account`
  annotation, so a missing one is click's own `Missing option '--account'.` and exit `2`
  before anything is resolved. `--source SRC` defaults to `claude` through `Settings.source`
  rather than through a literal, so `DATAPORTER_SOURCE` still outranks nothing. The pair is
  resolved by `config.with_account`, not `with_session_account`: there is no destination to
  fall back to.
- **`session logout` is gone.** Removed from `cli.py`, from `01`'s command surface, from
  `23`'s operations table, from the README's table and from the runbook.
- **`session status` gains the same required `--account`** (§86) and resolves through
  `with_account` too, leaving `with_session_account` to `login` alone.
- **What is removed**, by name and in this order: `browser-profile/`, `ask.json`, `tmp/`.
  `logs/` is not touched. The names come from `config` so that one module holds the shape of
  an account home.
- **`ASK_FILENAME` and `TMP_DIRNAME` move to `config.py`**, beside `BROWSER_PROFILE_DIRNAME`,
  and `extract` imports them from there. `extract` already imports `browser.session`, so the
  reverse import would cycle; this is the smallest change that lets `session` name what it
  deletes.
- **The browser precondition** (§85), run before anything is removed. `launcher.adopt` on
  the account's own profile: a marker that names the responding browser — same port, same
  browser id — means the window is ours, and it is closed with `BrowserSession.close()` and
  nothing printed. Anything else answering on `browser.cdp_port` is `PortInUseError`, exit
  `2`, with the invocation's own `logout` as the remedy. `adopt` already raises that for a
  browser it cannot claim, so the refusal is `adopt`'s, not a second check. **The port is
  read again after the close**: `_wait_for_port_to_go_quiet` gives an adopted browser
  `CLOSE_TIMEOUT_S` and then logs a warning and returns, so a browser that ignored
  `Browser.close` would otherwise be deleted out from under. Still answering is
  `PortInUseError`, exit `2`, nothing removed.
- **The two blocks** (§82), golden:

  ```text
  Signed out of Claude — work
  Removed /Users/you/.dataporter/accounts/claude/work/, except its logs.
  ```

  ```text
  Nothing to remove: /Users/you/.dataporter/accounts/claude/work/ has no session.
  ```

  The heading is `_heading`'s, as `login`'s second block is: the vendor's display name and
  ` — <label>`. `removed` is true when any of the three existed; both endings exit `0`.
- **A first `OSError` stops it** with `StateError` and exit `2`, as `remove_profile` does
  today, naming the path it could not remove. What was already removed stays removed.
- **`logout` with no account is refused in the library too.** `Settings.account_home` is
  `Path | None`, and `23` makes the library a surface of its own rather than something the
  CLI can constrain from outside: `browser_session.logout` on settings with no account is
  `UsageError`, exit `2`, naming the flag. The CLI cannot reach it — click refuses first —
  so this is the library's own door.
- **`WINDOW_CLOSED`'s remedy stops naming a command that cannot be run** (§86). `53` prints
  `status_command(settings)` when a window closes under a link; with no account that renders
  `dataporter session status`, which click now refuses. It becomes `login_command` where
  there is no account, and stays `status_command` where there is.
- **The rehearsals.** `29`'s protocol loses its `session status` and `session logout` steps
  (§86); `46`'s keeps both, renaming the second to `logout` — it passed a source and an
  account all along.
- **Tests**, in `tests/test_browser_session.py` (the deletion, the precondition, the blocks),
  `tests/test_source_session.py` (the account's own home, and the AST assertion over which
  `cli.py` functions resolve an account), `tests/test_cli.py` (the command inventory),
  `tests/test_operations.py` (library and CLI agreeing), `tests/test_rehearsal_extraction.py`.

## Out of scope

- **Revoking a session at the vendor**, §87. Sign-out is local by construction (§84).
- **Signing the destination out**, §87: §86 leaves the workspace's profile to `rm -rf`.
- **Clearing `tmp/` without signing out**, §87.
- **Signing out of every account at once**, §87.
- **The store.** A snapshot that was filed stays filed; nothing here reaches into it.

## Design notes

- **Named, not swept (Q19, Q23).** "Everything but the logs" can be written as a sweep —
  iterate the account home, delete what is not `logs/` — and that version is true by
  construction: a file a later slice adds dies without anybody editing this command. It was
  rejected anyway. A sweep deletes things nobody decided should go, including a file an
  operator put there by hand, and it moves the decision out of the specs and into an
  accident of what happened to be on disk. Naming the three keeps the decision a decision;
  the cost is that §83 has to be read and amended the day an account home grows a fifth
  thing, and §83 says so.
- **`--account` required, and the hole it leaves (Q8, Q11, Q26).** `session logout` without
  an account meant the destination. Requiring one removes that, and §86 removes
  `session status`'s matching form so the two commands say the same thing about what they
  are for. `login` keeps its destination form because the migration cannot start without
  one, so the destination can be signed in and then neither reported on nor cleared. That
  was weighed and taken: the destination's profile is inside the workspace, the runbook
  already removes the workspace whole, and `import` names `login` when it finds itself
  signed out. The alternative — a bare `logout` meaning the destination — puts a command
  that deletes "everything but the logs" within reach of the workspace, where `logs_dir` is
  the workspace itself and the neighbours are `state.json`, `seeds/` and the report.
- **Closed when it is provably ours (Q9).** `remove_profile` refused whenever anything
  answered on the port, without consulting the marker, so an open window on *another*
  account could refuse a sign-out that had nothing to do with it. The marker settles the
  positive case and only that: Chrome does not report its `--user-data-dir` over CDP, so a
  browser we cannot claim might still be holding this directory, and deleting under it is
  the half-written profile the old refusal existed to prevent. Ours is closed; anything else
  is still refused.
- **The precondition runs first, and again.** Before `browser-profile/`, before
  `ask.json`, before `tmp/`: a port check between two deletions would let a refusal arrive
  after the ask was gone — a sign-out that half happened and reported failure. And after
  the close, because closing is an ask and not a guarantee. `BrowserSession.close` on an
  adopted browser deliberately sends no signal — the process belongs to an earlier run and
  is holding the operator's session — so it waits, warns and returns. Taking that warning
  for a closed browser would put this command back to deleting a profile under a running
  Chrome, which is the one thing the old blanket refusal got right.
- **Idempotent, and the typo it swallows (Q3, Q24).** Sign-out states an end. When the end
  holds, exit `0` and a line that says nothing was there. That makes `--account wrok`
  indistinguishable from a job already done, which is the bargain `session status` already
  makes: nothing registers an account label, so there is no such thing as one that does not
  exist. Refusing an unknown label would mean inventing a registry to refuse against.
- **The ask goes with the session (Q2).** It is not a credential — §66 keeps no link, and
  `store.Ask` holds only when it was asked, by whom and with what version. It goes because
  it is a promise the tool cannot keep once the session is gone, and because the account
  home's contents after a sign-out should be a record and not an intention. The forfeit is
  not printed (§83): one ending, one shape, and a conditional line that appeared only
  sometimes would be a second golden block for a case that resolves itself.
- **`tmp/` is the reason this slice exists.** `45`'s download stages there and
  `browser/download.py` says outright that an interrupted run's `.crdownload` is left where
  it fell. Everything else here is a rename.
- **No trace, and no prompt.** Nothing drives a tab: closing a browser is not a move, and
  `session status` probes a page and opens no trace either (`33`). The command asks nothing
  before deleting, because the recovery is a fresh link and the friction would land on the
  one command whose job is to leave nothing behind.

## Acceptance criteria

- `dataporter logout --source claude --account work` on an account home holding all four
  items removes three and leaves `logs/` with its contents intact, prints §82's first block
  and exits `0` (`test_logout_removes_everything_but_the_logs`).
- The run log this invocation wrote is among the files still there afterwards
  (`test_logout_keeps_the_log_it_wrote_on_the_way_past`).
- An account home with no session prints §82's second block and exits `0`, and so does a
  label that names no directory at all
  (`test_logout_with_nothing_to_remove`, `test_logout_of_an_unknown_label_is_not_an_error`).
- Each of the three removable items missing on its own is still a sign-out, not a refusal
  (`test_logout_removes_what_is_there_and_not_what_is_not`).
- A browser the profile's marker names is closed and the sign-out proceeds
  (`test_logout_closes_the_window_it_owns`); a browser on the port that the marker does not
  name is exit `2` with nothing removed
  (`test_logout_refuses_a_browser_it_cannot_claim_and_removes_nothing`).
- A browser that does not go away when asked is exit `2` with nothing removed
  (`test_logout_refuses_a_browser_that_would_not_close`).
- `--account` missing is exit `2` (`test_logout_requires_an_account`), and so is
  `session status` without one (`test_session_status_requires_an_account`); the library
  called with no account refuses the same way
  (`test_the_library_refuses_a_logout_with_no_account`).
- After `login` and `extract`, the account home's children are exactly `browser-profile`,
  `ask.json`, `tmp` and `logs` — the claim §82's second line makes about the whole
  directory (`test_an_account_home_holds_exactly_what_sign_out_knows_about`).
- A window that closes under `login --link` for the destination names `login`, not
  `session status` (`test_a_closed_window_names_a_command_that_can_be_run`).
- `dataporter session logout` is no longer a command (`test_commands`, the inventory).
- The library and the CLI produce the same exit code and the same stdout for both endings
  (`test_logout_is_the_same_through_the_library`).
- `uv run python -m rehearsal.run --root <dir> --protocol extraction` completes with the
  renamed step. *not yet run*

## Risks

- **An account home grows a fifth thing and nobody amends §83.** Then sign-out leaves it,
  silently, and the command's one sentence is false. This is the cost of naming rather than
  sweeping, taken knowingly; what surfaces it is a reader of §83, not a test.
- **A browser we cannot claim is holding this profile.** It is refused, so nothing is
  deleted under it — but a person whose Chrome is on port 9222 for unrelated reasons cannot
  sign out until they close it. The message names the port and the command.
- **A complete archive in `tmp/` that was never filed** is removed with everything else, and
  the link that produced it was single-use. `fetch` only leaves one there by crashing
  between the download and the filing; a person who wants it must take it before signing
  out. §83 says the directory is removed, which is the only warning that can be given
  without a conditional line.
