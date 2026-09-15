# 61 — Headless extraction

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 03](../03-extraction-and-backup.md) §31,
[Brief 06](../06-chatgpt-extraction.md) §63 (amended)
**Depends on:** [24](24-non-interactive.md), [31](31-source-session-and-ask.md),
[45](45-fetch-through-the-session.md)
**Enables:** nothing yet
**Status:** Built

## Goal

Let both halves of an extraction run with no window:

```bash
dataporter --non-interactive extract --source claude --account eddie.v001
dataporter --non-interactive extract --source claude --account eddie.v001 --link 'https://…'
```

No new flag and no browser work: `24` already made `--non-interactive` mean headless
(`Settings.headless`, `launcher.HEADLESS_FLAG`), the ask's press is a JS `el.click()` and
the fetch's download is `Browser.setDownloadBehavior` on the browser target, which `45`'s
live test already drives through a real headless Chrome. One rule stood in the way, and
this slice is that rule: **extract no longer requires credentials to open a browser.**

## In scope

- **`extract.ask`**: delete `if settings.non_interactive: signin.require_credentials(...)`.
  The numbered steps lose their step 2; the browser and the probe are now step 2.
- **`extract.fetch`**: delete `if source.fetch_needs_session and settings.non_interactive:
  signin.require_credentials(...)`.
- **Nothing else changes.** `_sign_in_to_source` already routes an unattended signed-out
  session to `signin.ensure_signed_in`, whose `SignIn.perform` calls `require_credentials`
  itself. So a signed-out unattended run still exits `2` with `MISSING_CREDENTIALS`, the
  same text, from the same function — later, and only when a sign-in is really attempted.
- **`signin.MISSING_CREDENTIALS`'s docstring** records the exception: "before any browser
  starts" still holds for `login`, `verify`, `followup` and `resume`, and not for extract.
- **Tests**: `tests/test_ask.py` — the mode with no credentials asks on a signed-in
  profile and writes `ask.json`; the mode with no credentials on a signed-out profile is
  the same refusal, now with the browser having opened. `tests/test_chatgpt_fetch.py` —
  the same inversion, asserting `site.links == []`, which is the promise that matters.

## Out of scope

- **A `--headless` flag of its own.** `--non-interactive` is the flag that means "no
  person", and a window is what a person is handed; two flags for one fact is what `24`
  decided against, and nothing here changes that. `browser.headless` still overrides
  either way, which is how a headless run gets a window for a bot-check experiment.
- **A better refusal for a signed-out Claude profile.** `MISSING_CREDENTIALS` advises
  setting credentials that, for Claude, cannot sign in at all (brief 07) — the useful
  remedy is `dataporter login`. Worth its own slice; changing the text here would have
  meant changing it for ChatGPT too, where the advice is correct. *Done in `52`: Claude's
  unattended sign-in is `none`, and the refusal is `not logged in — run: dataporter login
  --source claude --account <label>`, exit `3`.*
- **The other commands.** `login`, `verify`, `followup` and `resume` keep the up-front
  gate, and `tests/test_unattended.py` still pins it.

## Design notes

- **The session is the profile's, so the credential is not the key.** Extract signs in to
  a *source* account, whose session lives in that account's own Chrome profile, put there
  once by a headed `login`. On such a profile `_sign_in_to_source` probes, finds the
  session live and returns — the credentials were never read. Demanding them at the door
  made an unattended backup impossible for exactly the accounts that need one, and for
  Claude it made it impossible full stop: brief 07 and ADR 0008 say Claude's sign-in
  needs an hCaptcha attestation and a cleared Cloudflare cookie, so no credential this
  tool holds can ever complete one. It was a toll, not a key.
- **The link is kept safe by the order, not by the check.** §63's sentence was written to
  protect a single-use link from being spent by a run that then stopped at a sign-in
  form. That protection does not come from the credential check: `_download_manifest_and_parts`
  and `_download_through_session` both launch on `source.login_url`, probe and sign in
  *there*, and navigate to the link only once the session is good. The check was an
  earlier, cheaper proxy for a guarantee the code already makes, and the test now asserts
  the guarantee itself — the link was never navigated to — rather than the proxy.
- **What is given up, stated plainly.** A signed-out unattended extract now opens and
  closes a browser before exiting `2`. That is the cost, it is paid only on the failure
  path, and `24`'s reason for the original rule — "a run that would stop at the first
  sign-in form is a run that should not have opened a window" — is worth less here than
  the runs it was refusing.
- **Two of the three tests were inverted, not deleted.** Each asserted the old rule by
  name (`starts_no_browser`, `refused_before_any_browser`). The new ones assert the new
  promise and keep the old refusal for the case that still earns it, so the pair reads as
  the rule it replaced.

## Acceptance criteria

- `make check-all` green on the coverage gate. (The macOS-only
  `test_the_child_really_sees_only_that` failure is pre-existing.)
- `--non-interactive` with no credentials, on a signed-in profile: the ask exits `0` and
  writes `ask.json`; the fetch files a snapshot.
- `--non-interactive` with no credentials, on a signed-out profile: exit `2`,
  `MISSING_CREDENTIALS`, nothing filed, the ask kept, and the link never navigated to.
- `login`, `verify`, `followup` and `resume` still refuse the mode without credentials
  before any browser.
- ~~A real headless run of both steps against claude.ai on a signed-in profile.~~
  **Answered 2026-09-15, and the answer is no for the ask**: claude.ai serves
  `--headless=new` a Cloudflare interstitial that never resolves, so the panel is never
  reached. The credentials rule this slice built is sound and the plumbing works — the
  browser starts, the profile is used, nothing asks for a password — but the vendor ends
  it there. See [`62`](62-waiting-for-the-export-panel.md) for the measurement and
  `docs/LIMITATIONS.md` for the limitation. The fetch is untested: it downloads from a
  signed URL on another host and may not be challenged. *observed*

## Risks

- **A bot check headed Chrome would pass.** `24`:173 wrote this down already — "Headless
  Chrome may be what trips a bot check that headed Chrome would not." The fallback is
  `DATAPORTER_BROWSER__HEADLESS=false` beside `--non-interactive`, which keeps the window
  and this slice's credential rule.
- **A lapsed session now fails later than it used to**, after a browser has started. The
  message is unchanged, so the failure reads the same; what an operator loses is the
  two seconds Chrome took to open.
