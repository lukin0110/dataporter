# 62 — Waiting for the export panel

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 03](../03-extraction-and-backup.md) §31,
[Brief 07](../07-claude-sign-in.md) §77
**Depends on:** [31](31-source-session-and-ask.md), [51](51-export-page-address.md),
[61](61-headless-extraction.md)
**Enables:** nothing yet
**Status:** Built

## Goal

Stop the ask calling a panel that has not rendered a panel that is not there. It read the
DOM for the export control **once**, the instant `document.readyState` went `complete`,
and claude.ai is a React app served from a fragment of `/new` (§77) that has painted
nothing at that moment. Measured on a real account: the control appears about **2.9 s**
after the navigation, and the read was happening at about **1.4 s**. Every successful ask
so far won a race by roughly a second.

## What a real run showed

`61` left one criterion unverified — a real headless run. It failed, and the measurement
is the whole of this slice. Both columns are the same signed-in profile, minutes apart,
polling the ask's own JS and clicking nothing:

```text
headless   1.2s  nodes=16   title 'Just a moment...'
           2.2s  nodes=47   title 'Un momento…'
          19.3s  nodes=47   title 'Un momento…'      never appeared in 20s
headed     1.5s  nodes=143  title 'Claude'
           2.9s  nodes=670  title 'New chat - Claude'   button appeared
```

Two separate findings, and they must not be confused:

1. **The race is real and it is not about headless.** Headed, the panel needs ~2.9 s and
   the single read happened at ~1.4 s. A slow network, a cold profile or a busy machine
   loses that race with a window open. This slice fixes that.
2. **Headless cannot reach the page at all.** The headless document loads
   `challenges.cloudflare.com` and carries a `ray-id` footer — Cloudflare's interstitial —
   and it never resolves. No wait fixes that, and this slice does not try.

`logged_in=False` in the failing run's log was a red herring: on this URL it means "no
visible composer" (`probe.py:546`), which is also true of a settings page, which is why
`export_page.signed_out` reads the page kind instead (`31` §52).

## In scope

- **`export_page._await_button`**: poll `ExportPageView.read` on the ask's existing
  `deadline` and `poll_s` until the control is there, returning the last view at the
  deadline. A JavaScript dialog returns **immediately** — §36 never answers one, and a
  dialog is an answer about the page, not a page that has not finished. Not `_wait_until`,
  which raises `BrowserError`: a control that never appeared is an `AskResult` an operator
  reads, not a browser fault.
- **One budget.** `timeouts.ask_s` covers both halves — finding the control and seeing the
  answer — because it is one ask and a slow page is slow in whichever half.
- **`extract`'s line** splits in two, on `Settings.headless`, because only one of them can
  be true about a given run: headless says the bot check and names dropping
  `--non-interactive`; headed says the session and names `login`. Neither guesses at the
  other's cause.
- **`tests/fake_export_page.py`**: `button_after_view`, how many looks before the control
  renders — the real failure as a fixture, beside the existing `leaves_after_view`.
- **Tests** (`tests/test_ask.py`): a panel that renders on the third look is waited for and
  pressed; one that never renders still stops at `button_not_found`, with each of the two
  lines asserted byte for byte.

## Out of scope

- **Making headless work.** It cannot be made to work without defeating bot management,
  which [ADR 0008](../../docs/adr/0008-the-sign-in-stays-in-the-browser.md) settles: "A
  tool that got good at clearing bot management would be a tool whose runs a vendor cannot
  tell from an attack." No user-agent override, no stealth flags. The limitation is
  written down in `docs/LIMITATIONS.md` instead.
- **Detecting the interstitial to fail faster.** A headless ask now spends `ask_s` — sixty
  seconds by default — before saying so. A check for a `challenges.cloudflare.com` script
  would cut that to a poll, and it would be structural rather than textual, so it reads
  nothing of the account. Worth doing; not done here, because it wants its own row in the
  UI map and the evidence to go with it.
- **`signed_out()`'s blind spot.** A signed-out `/new` that does not redirect still reads
  as "the panel did not appear", since `signed_out_at_root` is `False` for Claude. The
  headed line names `login` for exactly that reason, but the diagnosis is still inferred
  rather than observed.

## Design notes

- **The navigation is not the arrival, and the URL is not the DOM.**
  `_bring_to_export_page` already waits twice, and both waits are about the address: the
  tab's `location.href`, then the target list. On a site that routes in a fragment those
  can both be true while the app is empty. The read that follows them needed a wait of its
  own, on the thing it actually wants.
- **Why this was invisible until now.** The rehearsals run headless end to end and pass —
  against the **mock** claude.ai on localhost (`docs/rehearsal-01.md:27`), which serves the
  panel in the first response. A fixture that renders instantly cannot fail this way, so
  `button_after_view` exists to make a fixture that can.
- **Why the line is split rather than made general.** One line covering both causes would
  send a headed operator after a bot check and a headless one after their session. The run
  knows which it is, so it says which it is.

## Acceptance criteria

- `make check-all` green on the coverage gate. (The macOS-only
  `test_the_child_really_sees_only_that` failure is pre-existing.)
- A panel that appears on the third look is pressed; the ask writes its `ask.json`.
- A panel that never appears is `button_not_found` after `ask_s`, with the headed line
  headed and the headless line headless.
- A real headed `dataporter extract --source claude --account <label>` still asks. The
  measurement above says it now has ~57 s of margin where it had about a second and a half
  of luck. *unverified since the change*

## Risks

- **The budget is shared.** A page that takes fifty seconds to render leaves ten for the
  confirmation, and the ask then reports that it could not confirm — wrong in the safe
  direction (`31`'s rule: never write an `ask.json` for a request the vendor may not have
  received), but it would read as a different failure than it is.
- **`ask_s` is now reachable in a new way.** Before this slice a missing button was
  instant; now an operator waits a minute for it. That is the cost of not guessing, and
  the interstitial check above is what would buy it back.
