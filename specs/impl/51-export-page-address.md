# 51 — The export page's real address

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 07](../07-claude-sign-in.md) §77
**Depends on:** [48](48-the-words.md)
**Status:** Built

## Goal

Point the Claude ask at the page that exists. `31`'s `export_page_path` was a
placeholder nobody had checked, and a real run found it: signed in, on the right
profile, `export button not found on /settings/data-privacy-controls`.

## What was wrong

Observed 2026-09-14 on a real account. The export is asked for from a **settings
dialog over the app**, at `https://claude.ai/new#settings/data-privacy-controls`
— a fragment, not a path of its own. `31` guessed a path, and it served nothing.

The panel's markup offers no test id, and the ids that are on it (`_r_7v_`) are
React's, regenerated every render. The only thing distinguishing the Export row
from the five *Manage* rows beneath it is the words in it, which a CSS selector
cannot read. What is stable is the shape: every row above Export holds a switch
rather than a button, so the Export button is the panel's first.

## In scope

- **`sources/claude.py`**: `EXPORT_PAGE_PATH` → `/new#settings/data-privacy-controls`;
  `EXPORT_BUTTON_SELECTOR` → `[data-perf-screen="data-privacy-controls"] [data-settings-row] button[data-cds="Button"]`;
  `CONFIRM_BUTTON_SELECTOR` → `[data-testid="export-confirm-button"]`.
  `REQUESTED_SELECTOR` stays as it was and says in its docstring that it is still
  `*unknown*`.
- **The `Export data` row asks for nothing.** It opens a second screen inside the
  same dialog — a description, a `Conversations from` period, a list of what the
  export will include, and the button that actually asks. `31` built the ask's two
  clicks for a modal confirmation; the shape fits this unchanged, and `view.dialog`
  is true throughout because the settings panel is itself a `[role="dialog"]`.
  Unlike the row, that button has a test id and needs no positional guessing.
- **`export_page.on_export_page`**: compares a URL's path **and fragment** against
  the address, rather than the path alone.
- **`docs/claude-ui-map.md`**: the `export page` and `export button` rows now
  describe what the code does, and both stay `*unknown*` — see the design note.
- **`tests/fixtures/pages/settings-export.html`**: rebuilt on the observed shape —
  a switch row above, the Export row, a *Manage* row below — so the live test
  exercises the selector's actual claim.
- **`tests/fake_pages.py`**: `EXPORT_PANEL_PATH = "/settings-export"`, because the
  fixture server already serves `/new`.

## Out of scope

- **The accepted signal.** `REQUESTED_SELECTOR` needs somebody to press Export on a
  real account, which asks the vendor for a real export.
- **The period control.** The second screen offers `All` / `30 days` / `90 days` /
  `Custom`, and the ask touches none of it: `All` is the default and a backup wants
  all of it. Recorded in the UI map because a changed default would make `extract`
  file partial snapshots while reporting success.
- **Whether the second screen changes the address.** If its fragment differs from
  the first's, `_click`'s `on_export_page` guard refuses the second click. Unknown,
  and the next real run is what says.

## Design notes

- **Path *and* fragment, not one or the other.** Three things read this address and
  they do not want the same thing. The wall (`sites.extraction_pattern`) matches a
  URL as a *string*, so keeping the fragment in it leaves the wall exactly as narrow
  as when the page had its own path — `/new#settings/data-privacy-controls` is
  admitted and `/new` is not. `on_export_page` compares a *parsed* URL, so it had to
  learn to put the fragment back: a first attempt compared only the path, and
  `test_an_interactive_ask_waits_for_the_person_and_comes_back_to_the_page` caught
  it — a person who signs in is left on `/new`, which a path-only check reads as
  already being on the export page. A trace records neither (§66), so a move shows
  `/new` and the tests say so.
- **A positional selector, named as one.** Rejected: matching on the row's React id,
  which changes every render; adding a text-matching mechanism to the selector layer
  for one vendor's panel. If claude.ai reorders that panel this presses *Manage*,
  which opens a list rather than asking for anything, and the ask then stops at
  `REQUESTED_SELECTOR` rather than reporting a request nobody made.
- **The rows stay `*unknown*` although somebody looked.** `test_an_observed_row_cites_its_evidence`
  requires an artefact under `docs/spike/` for any row marked *observed*, and the
  only artefact here is the panel's markup as it was read — which carries the
  account's name and its conversation titles, which §10 keeps out of that
  directory. A redacted extract would qualify and is the account holder's to
  approve, so the rows wait and this slice says why rather than marking them on a
  citation that is not there. The guard caught the first attempt, which is what it
  is for.
- **The fixture models the shape, not the site.** It leaves out that the real panel
  is itself a `[role="dialog"]` — true, and it would make `view.dialog` true before
  anything is clicked, which is the one thing the three-stage live test exists to
  tell apart.

## Acceptance criteria

- `make check-all` green on the coverage gate. (The macOS-only
  `test_the_child_really_sees_only_that` failure is pre-existing.)
- `on_export_page` is true for the address, false for `/new` and for `/login`.
- The extraction wall admits the address and refuses `/new`.
- A real `dataporter extract --source claude --account <label>` reaches the panel
  and presses Export — which is what turns `52` from blocked into observable.

## Risks

- **The ask now presses a real button and cannot yet see that it worked.** With
  `REQUESTED_SELECTOR` still unknown, a real run asks the vendor for a real export
  and then waits out `timeouts.ask_s` before reporting that it did not. The export
  is requested; the run says otherwise. `52` is what closes that, and until it does
  this is the one thing to warn an operator about.
- **The address was right and the panel still was not there.** This slice fixed where the
  ask looks; it did not ask *when*. The selector is read once, and on a real account the
  panel renders about 2.9 s after the navigation while the read happens at about 1.4 s —
  so a correct selector reported `export button not found`, and every ask that worked won
  a race. Fixed by [`62`](62-waiting-for-the-export-panel.md), which also recorded what a
  headless run gets instead: Cloudflare's interstitial, and never the panel at all.
