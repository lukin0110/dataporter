# 22 — Test performance

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** nothing in the brief — tooling
**Depends on:** nothing
**Enables:** every slice after it, by giving back the inner loop
**Status:** Not started

## Goal

Make the slow half of the test suite quick enough that there is no slow half. The
fast/slow split that landed with `15` is containment: it puts ~240 seconds behind a
marker so that `make check` is two seconds and a pull request is not gated on four
minutes. This slice removes the 240 seconds instead of hiding them, and then the split
can stay as a safety rail rather than a necessity.

It is the one slice that implements no brief section. Every other one exists because §2–§19
asks for something; this one exists because the suite got slow enough to change how people
work — during `15` the full suite was run three times, cost about twenty minutes, and was
once made worse by a second run started on top of a first.

## In scope

The measurements below are from a single run on one machine (Linux, Python 3.12.3,
`pytest -q --no-cov`), and are what the fixes are ranked against. Re-measure before
starting: the point of the numbers is the ranking, not the absolute values.

**Total: 978 passed, 17 skipped, 232 s.** Per module:

| Module | Tests | Time |
| --- | --- | --- |
| `test_importer.py` | 50 | 35.6s |
| `test_hermes_doctor.py` | 38 | 31.4s |
| `test_intervention.py` | 38 | 27.8s |
| `test_recovery.py` | 38 | 25.9s |
| `test_browser_helpers.py` | 61 | 25.9s |
| `test_pacing.py` | 41 | 22.8s |
| `test_browser_cdp.py` | 32 | 16.7s |
| `test_browser_session.py` | 27 | 11.7s |
| `test_hermes_runner.py` | 32 | 8.7s |
| `test_browser_launcher.py` | 24 | 7.8s |
| `test_browser_probe.py` | 21 | 5.1s |
| `test_hermes_setup.py` | 14 | 5.0s |
| `test_skill_dry_run.py` | 7 | 4.1s |
| every other module | ~580 | under 3s combined |

There is no fat head: the sixty slowest tests are only ~50 s of the 232, and the
distribution is flat from 0.5 s down. This is ~300 tests each paying a fixed tax, so the
fixes are all about the tax and none of them is about a slow test.

The work, in descending order of what it buys. The next PR picks these up; it does not
have to take them all, and each is independently landable.

1. **`serve_forever(poll_interval=0.01)` in `tests/fake_chrome.py`. ~115 s, one line.**
   `FakeChrome` starts its debug-port HTTP server with
   `threading.Thread(target=self._http.serve_forever)` and no `poll_interval`, so the
   stdlib default of 0.5 s applies. `stop_http()` calls `shutdown()`, which blocks until
   the select loop next wakes — a flat half second, every teardown. Measured directly:
   bringing the server up and serving a request is 2 ms; stopping it is 501 ms, and the
   WebSocket half shuts down in ~0 ms, so all of it is the poll interval.
   `test_browser_cdp.py` alone pays 27 × 0.50 s = 13.5 s of its 16.7 s in teardown. This is
   half the suite's runtime for a one-line change with no effect on what is tested. **Do
   this first, before anything else on this list.**
2. **Stop rebuilding the Hermes profile per test. ~45 s.** `tests/world.py::build` calls
   `profiling.run_setup(settings)`, which is 1 `profile list` + 1 `profile create` + **12**
   `config set` + 1 `config show` — fifteen real subprocess spawns before the test body
   runs, for each of the 91 tests that take the `world` fixture. A spawn measures ~31 ms
   and the fake `hermes` imports only stdlib, so there is nothing to make cheaper: the
   only move is to make fewer. `FakeHermes.with_profile` already exists and takes
   `**config`, so `hermes.with_profile(settings.hermes.profile, **profile_config(settings))`
   reaches the same end state with **zero** subprocesses. `run_setup` itself stays covered
   where it belongs, by `test_hermes_setup.py` and `test_hermes_doctor.py`.
   Watch for shared state: `conftest.clean_environment` clears `HCM_*` and nothing else,
   so a profile directory shared between tests is a new way for one test to see another's
   writes.
3. **Make `wait_for_login`'s poll reachable under test. ~2 s.**
   `test_browser_session.py::test_login_asks_the_operator_and_gives_up` sets
   `HCM_TIMEOUTS__LOGIN_S=0.05` but cannot shorten the poll: `LOGIN_POLL_S` is 2.0 in
   `browser/session.py`, the deadline is checked *before* the sleep, so the first probe
   comes in under budget and the loop then sleeps a full two seconds before giving up. The
   direct-call tests in the same module pass `poll_s=0.01`; the CLI path has no seam. This
   one is a small production change — a settings field, or the deadline checked after the
   probe — and is worth doing for its own sake, not only for the 2 s.
4. **Trim the two deliberate waits.** `test_hermes_runner.py` sleeps `CHILD_DELAY_S * 2`
   = 6.0 s to prove a grandchild does *not* write its marker — a sound negative test with
   a 2× margin that could be 1.2×. `test_browser_cdp.py` has a literal `page.drain(2.0)`.
   About 4 s together; take it only after 1 and 2.
5. **Share `FakeChrome` across a module.** Once (1) has removed the teardown cost this is
   worth much less, which is why it is below the one-liner. `tests/live_browser.py`
   already module-scopes its live fixtures for this reason. A prerequisite is moving the
   inline `Browser(FakePage(...))` constructions behind fixtures — which would also make
   `conftest.SLOW_FIXTURES` able to do the marking that `no_expensive_fakes` currently has
   to catch after the fact.
6. **`pytest-xdist` with `-n auto`, last.** The workload is subprocess-bound and should
   scale close to linearly, but it *hides* the cost rather than removing it, and it costs
   a dev dependency plus a `uv.lock` regeneration (CI runs `uv sync --locked`). Do it
   after 1–5 so it multiplies an already-small number.
7. **Find out what the live-browser tests cost in CI.** The 17 `@requires_a_browser` tests
   are skipped on any machine without Chrome, which is every developer's, so nobody has
   ever seen their duration. `ubuntu-latest` ships Google Chrome, so until `15` they ran on
   every pull request unnoticed. Read the number off a `check-all` run on `main`, then
   decide whether they belong in every merge or on a nightly `schedule:` — the `live`
   marker exists so that move needs no re-marking.

## Out of scope

- The split itself, which landed with `15`: the `slow` and `live` markers, the
  `no_expensive_fakes` guard in `tests/conftest.py`, the `check` / `check-all` Make
  targets and the conditional CI step.
- Deleting tests. Nothing on the list above removes a test or weakens an assertion. In
  particular, `tests/fake_hermes.py` argues — correctly — that the fake being a *real
  process* is what exercises the environment allowlist, the working directory, the output
  files and the process-group kill; item 2 keeps every one of those covered in
  `test_hermes_*` and removes it only from the loop tests, whose subject is `Importer`'s
  decisions and not the subprocess boundary. If that trade is taken, it belongs in this
  slice's *Design notes* in those words.

## Design notes

- **Why a marker split was done first rather than this work.** The split is one commit and
  no risk; every item above touches shared test machinery and can be got wrong quietly.
  Containing the cost bought the time to do the rest carefully.
- **Why the fixture-name auto-mark is not the whole mechanism.** It was measured:
  deselecting on `fixturenames` alone left 739 tests taking 38 s, because several modules
  build `FakeChrome`, `Browser` and `FakeHermes` inline in the test body, where no fixture
  name gives them away. Hence `no_expensive_fakes`, which fails loudly on the pull request
  that introduces the problem instead of silently widening the fast suite. Item 5 above
  would make the fixture rule viable after all, at which point the guard becomes a second
  line of defence rather than the first.
- **The one case nothing automatic catches** is a slow test that uses no fake and no
  `world` — like the two `WorkspaceLock` tests in `test_state.py`, which spawn a real
  interpreter and are marked by hand. A wall-clock budget is the only general answer, and
  this slice should decide whether one is worth the flakiness it brings.

## Acceptance criteria

- `make check` stays under 5 s on the reference machine.
- `make check-all` drops below 60 s — that is (1) and (2) together, and the rest is
  headroom.
- `uv run pytest -m "slow or not slow" --cov` still reports coverage at or above
  `fail_under`, and the `TOTAL` statement count is unchanged: a fix that makes the suite
  faster by covering less has not made the suite faster.
- Every test that exercised the subprocess or CDP boundary before this slice still does.
  `tests/test_suite_shape.py` still passes.

## Risks

- **A shared fixture is a shared mutable.** Items 2 and 5 both replace per-test setup with
  something reused, which is how a suite acquires order-dependent failures. Mitigate by
  landing each one alone and, once `pytest-xdist` is in (item 6), running `-p no:randomly`
  off and the suite twice in different orders before trusting it.
- **Item 3 changes production code** to make a test faster, which is normally the wrong
  direction. It is on the list because the current behaviour is also wrong for an operator
  — a login wait that overshoots its own timeout by two seconds — so the test speed is a
  symptom rather than the reason.
- **The numbers above rot.** They are one machine, one day. Anybody acting on them should
  re-run `uv run pytest -q --no-cov --durations=0` first and correct this document, which
  is what makes it a living one.
