# 22 — Test performance

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** nothing in the brief — tooling
**Depends on:** nothing
**Enables:** every slice after it, by giving back the inner loop
**Status:** Done — `make check-all` is 23 s where it was 280. Items 1–4 and 6 landed, 5 was
measured and declined, 7 was measured and answered.

## Goal

Make the slow half of the test suite quick enough that there is no slow half. The
fast/slow split that landed with `15` is containment: it puts four minutes behind a marker
so that `make check` is three seconds and a pull request is not gated on them. This slice
removes the four minutes instead of hiding them, and the split stays as a safety rail
rather than a necessity.

It is the one slice that implements no brief section. Every other one exists because §2–§19
asks for something; this one exists because the suite got slow enough to change how people
work — during `15` the full suite was run three times, cost about twenty minutes, and was
once made worse by a second run started on top of a first.

## In scope

The measurements are from single runs on one machine (Linux, Python 3.12.3, 4 cores,
`pytest -q --no-cov -m "slow or not slow" --durations=0`). The **Before** column was
re-measured at the head this slice branched from, not copied from the first draft of this
document: the suite had grown from 978 tests to 1 354 in the six slices since, and the
ranking is what the fixes were chosen against.

**Before: 1 335 passed, 18 skipped, 272 s. After: 1 336 passed, 18 skipped, 64 s — 22 s
across four cores, which is what `make test-all` now runs.**

| Module | Tests | Before | After |
| --- | --- | --- | --- |
| `test_importer.py` | 50 | 33.6s | 5.5s |
| `test_browser_helpers.py` | 91 | 29.9s | 1.6s |
| `test_hermes_doctor.py` | 38 | 25.6s | 14.1s |
| `test_intervention.py` | 42 | 24.9s | 5.2s |
| `test_recovery.py` | 43 | 22.9s | 4.5s |
| `test_pacing.py` | 58 | 20.6s | 4.1s |
| `test_browser_cdp.py` | 32 | 16.6s | 1.1s |
| `test_verify.py` | 45 | 14.2s | 2.2s |
| `test_attachments.py` | 30 | 13.4s | 1.9s |
| `test_browser_session.py` | 28 | 11.5s | 0.8s |
| `test_hermes_runner.py` | 32 | 8.6s | 6.2s |
| `test_skill_dry_run.py` | 13 | 7.9s | 1.5s |
| every other module | ~852 | 38.8s | 11.8s |

There was no fat head: the sixty slowest tests were only ~50 s of the 272, and the
distribution was flat from 0.5 s down. That was ~300 tests each paying a fixed tax, so the
fixes are all about the tax and none of them is about a slow test. It is flat again at a
quarter of the size — the slowest test left is 4.6 s and the next is 1.5 s.

The work, in the order it was ranked by what it buys. Each was landable alone; all but
item 5 were taken.

1. **`serve_forever(poll_interval=0.01)` in `tests/fake_chrome.py`. ~140 s, one line.
   Done.** `FakeChrome` started its debug-port HTTP server with
   `threading.Thread(target=self._http.serve_forever)` and no `poll_interval`, so the
   stdlib default of 0.5 s applied. `stop_http()` calls `shutdown()`, which blocks until
   the select loop next wakes — a flat half second, every teardown. Measured directly:
   bringing the server up and serving a request is 2 ms; stopping it was 501 ms, and the
   WebSocket half shuts down in ~0 ms, so all of it was the poll interval.
   `test_browser_cdp.py` alone paid 27 × 0.50 s = 13.5 s of its 16.6 s in teardown. A full
   run builds 331 fake browsers, which is why this was estimated at 115 s and worth more:
   half the suite's runtime for a one-line change with no effect on what is tested.
   `HTTP_POLL_S` is named and documented where it is spent.
2. **Stop rebuilding the Hermes profile per test. ~45 s. Done.** `tests/world.py::build`
   called `profiling.run_setup(settings)`, which is 1 `profile list` + 1 `profile create`
   + **12** `config set` + 1 `config show` — fifteen real subprocess spawns before the test
   body ran, for each of the 129 tests that take the `world` fixture. A spawn measures
   ~31 ms and the fake `hermes` imports only stdlib, so there was nothing to make cheaper:
   the only move was to make fewer. `build` now says
   `hermes.with_profile(settings.hermes.profile, **profile_config(settings))`, which
   reaches the same end state with **zero** subprocesses, and then `skilling.install` for
   real — that half of `run_setup` is a `copytree`, not a spawn, and `12`'s preflight
   refuses to start without it. `run_setup` itself stays covered where it belongs, by
   `test_hermes_setup.py` and `test_hermes_doctor.py`; `hermes/profile.py` is still at
   100%.
   The shared-state worry did not materialise, but it is worth naming: `conftest`'s
   `clean_environment` clears `DATAPORTER_*` and nothing else, and what keeps one world out of
   another's profile is that `hermes.home` is under `tmp_path`, per test.
3. **Make `wait_for_login`'s poll reachable under test. ~2 s. Done, as a production fix.**
   `test_browser_session.py::test_login_asks_the_operator_and_gives_up` sets
   `DATAPORTER_TIMEOUTS__LOGIN_S=0.05` but could not shorten the poll: `LOGIN_POLL_S` is 2.0 in
   `browser/session.py`, and the loop slept a whole poll interval after the deadline check.
   The fix is the one that was worth making anyway — `time.sleep(min(poll_s, remaining))`,
   so the wait never runs past its own budget. An operator who asks for a one-minute login
   window is now told at sixty seconds rather than at sixty-two, and
   `test_a_wait_never_sleeps_past_its_own_deadline` pins it by what the wait asks `sleep`
   for rather than by a stopwatch.
4. **Trim the two deliberate waits. ~4 s. Done.** `test_hermes_runner.py` slept
   `CHILD_DELAY_S * 2` = 6.0 s to prove a grandchild does *not* write its marker; the
   margin is now a named `SURVIVAL_MARGIN = 1.2`, which is still longer than the
   one-second deadline that kills it. `test_browser_cdp.py`'s literal `page.drain(2.0)` is
   0.25 s: `drain` waits its whole budget out by construction — it returns on the socket
   timeout, not on an event — and the event it collects is already on the wire when `push`
   returns, which the sibling test reads back in 0.05 s.
5. **Share `FakeChrome` across a module. Measured, then declined.** This was always
   contingent on (1): almost all of a fake browser's cost was the half-second teardown, and
   with that gone the five browser modules went from 72 s to 5 s without touching how they
   build one. What is left is two `bind()`s and two threads per test, and against that a
   module-scoped fake is a shared mutable — `chrome.calls`, `chrome.targets` and
   `chrome.events` are all read and written by the tests that use it — for perhaps a
   second across the suite. The prerequisite work (moving inline `Browser(FakePage(...))`
   constructions behind fixtures, so `conftest.SLOW_FIXTURES` could mark them by name)
   stays undone with it, and `no_expensive_fakes` remains the first line of defence rather
   than the second.
6. **`pytest-xdist` with `-n auto`. 72 s → 22 s. Done, last.** The remaining minute is
   ~1 300 tests each paying a spawn or a socket, and it divides by the core count almost
   exactly. It is in the `test-all` Make target and deliberately *not* in `addopts`: a
   parallel run is a worse place to debug from — no live output, no `--pdb`, tracebacks out
   of order — and the inner loop `addopts` serves is three seconds either way. It costs a
   dev dependency and a `uv.lock` regeneration, which CI's `uv sync --locked` requires.
7. **What the live-browser tests cost. Measured: 17.6 s, and they stay.** The 18
   `@requires_a_browser` tests are skipped on any machine without Chrome, which is every
   developer's, so nobody had seen their duration. Two numbers now exist. In CI they are
   not skipped at all — the last `check-all` run on `main` before this slice reports
   `1264 passed` and no skips in 300.85 s, on a runner that ships Google Chrome. Locally,
   pointed at a Chromium with `DATAPORTER_TEST_BROWSER`, `pytest -m live` is **17.6 s for
   18 tests**, and 10.8 s of that is three deliberate waits (a 6 s generation settle, a 3 s
   timeout proof, the paste ladder's own round). So they belong exactly where they are:
   on `main` and on `workflow_dispatch`, not on a nightly `schedule:`. Seventeen seconds is
   not worth a second workflow, a second place for a failure to be noticed late, or the
   chance that the only tests which check a real selector against a real browser go a week
   unrun. The `live` marker stays, because the number that would change this decision is
   the one it lets somebody act on without re-marking anything.

## Out of scope

- The split itself, which landed with `15`: the `slow` and `live` markers, the
  `no_expensive_fakes` guard in `tests/conftest.py`, the `check` / `check-all` Make
  targets and the conditional CI step. All of it stays; `22` changes what is behind the
  marker, not the marker.
- Deleting tests. Nothing above removes a test or weakens an assertion — the suite gained
  one, for item 3's production fix.

## Design notes

- **The trade item 2 makes, in the words `tests/fake_hermes.py` asks for.** That module
  argues — correctly — that the fake being a *real process* is what exercises the
  environment allowlist, the working directory, the output files and the process-group
  kill. Item 2 keeps every one of those covered in `test_hermes_*`, and removes it only
  from the loop tests, whose subject is `Importer`'s decisions and not the subprocess
  boundary. A world still spawns a real `hermes` for every conversation it migrates; what
  it no longer does is spawn fifteen more to arrive at a profile whose *making* no test in
  those modules asserts anything about.
- **Why a marker split was done first rather than this work.** The split is one commit and
  no risk; every item above touches shared test machinery and can be got wrong quietly.
  Containing the cost bought the time to do the rest carefully.
- **Why item 3 changes production code** to make a test faster, which is normally the
  wrong direction. It is here because the behaviour was also wrong for an operator — a
  login wait that overshoots its own timeout by two seconds — so the test speed is a
  symptom rather than the reason. The alternative considered and rejected was a settings
  field for the poll interval: a knob nobody would ever set, to work around a bug, rather
  than the bug.
- **Why the fixture-name auto-mark is not the whole mechanism.** It was measured:
  deselecting on `fixturenames` alone left 739 tests taking 38 s, because several modules
  build `FakeChrome`, `Browser` and `FakeHermes` inline in the test body, where no fixture
  name gives them away. Hence `no_expensive_fakes`, which fails loudly on the pull request
  that introduces the problem instead of silently widening the fast suite. Item 5 would
  have made the fixture rule viable after all; it was declined, so the guard stays first.
- **`world` stays `slow`, at a tenth of the cost.** The marker is about what a test *does*
  — spawn, bind, launch — and not about a threshold it currently sits under. A rule that
  re-sorted itself by the stopwatch would move tests between the halves on every machine.
- **The one case nothing automatic catches** is a slow test that uses no fake and no
  `world` — like the two `WorkspaceLock` tests in `test_state.py`, which spawn a real
  interpreter and are marked by hand. This slice decided against a wall-clock budget: the
  suite is flat again, its slowest test is 4.6 s of deliberate sleeping, and a budget that
  fails when a machine is busy teaches people to re-run rather than to fix — which is what
  `tests/test_suite_shape.py` already says about itself.

## Acceptance criteria

All checked on the reference machine at the head of this slice.

- `make check` stays under 5 s. **3.8 s**, of which 3.0 s is 867 tests.
- `make check-all` drops below 60 s. **22.4 s**, against ~280 s before.
- `uv run pytest -m "slow or not slow" --cov` still reports coverage at or above
  `fail_under`, and the `TOTAL` statement count is unchanged: a fix that makes the suite
  faster by covering less has not made the suite faster. **99.48%, unchanged to two
  decimals; 5 391 statements against 5 390** — the one added statement is item 3's
  production fix, and `browser/session.py` and `hermes/profile.py` are both still at 100%.
- Every test that exercised the subprocess or CDP boundary before this slice still does.
  `tests/test_suite_shape.py` still passes. **1 336 passed, 18 skipped**, one more than
  before, and `pytest -m live` is 18 passed against a real browser.

## Risks

- **A shared fixture is a shared mutable.** Item 2 replaces per-test setup with a written
  file, which is how a suite acquires order-dependent failures. Mitigated by landing it
  alone, and by the run order changing underneath it: `-n auto` distributes by load, so
  the three runs made after item 6 landed were three different orders, all green.
- **`-n auto` hides cost rather than removing it.** A test that grows a ten-second sleep
  is now a tenth as visible in the total. `--durations=0` on a serial run is what to check
  before believing the suite is still flat, and this document's table is the shape to
  compare against.
- **One fork warning is now visible.** `test_a_kill_between_tmp_and_replace_leaves_the_previous_file`
  calls `os.fork()`, and an xdist worker has execnet's receiver thread, so Python 3.12
  warns that forking a multi-threaded process may deadlock. The child only writes a file
  and kills itself, and the locks it could block on (`logging`, the import lock, the
  allocator) are all reinitialised on fork; fifteen consecutive runs of that module under
  `-n 4` were green. It is recorded here rather than silenced, because if that test ever
  hangs, this is the paragraph that explains why — and the fix is to spawn an interpreter
  instead of forking one, as the `WorkspaceLock` tests already do.
- **The numbers above rot.** They are one machine, one day. Anybody acting on them should
  re-run `uv run pytest -q --no-cov -m "slow or not slow" --durations=0` first and correct
  this document, which is what makes it a living one.
