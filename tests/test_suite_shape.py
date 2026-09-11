"""The split itself, held to its own rules.

`make check` is only worth trusting if "fast" means something a person cannot
quietly break. Three claims make it mean something, and each one is checked here
rather than believed:

- **The guard is armed.** An unmarked test that builds a fake Chrome, a fake
  Hermes or the live-page server fails. The tests below prove it the only way
  that needs no machinery: they are unmarked, so the guard is live inside them,
  and they assert that the constructor refuses.
- **And it lets the slow half through.** A guard that refused everywhere would
  pass the first check and break the suite, so one `slow` test builds one and
  closes it.
- **Every `live` test is `slow`.** They are separate marks for a reason — `live`
  is the narrower set, and a later change may move it to a nightly run — but a
  `live` test that escaped `slow` would run on every pull request, launching a
  real Chrome, which is exactly what marking them was meant to stop. It is also
  an easy mistake to make: nesting the mark decorators *looks* like it composes
  them and does not.

What is deliberately not checked here is wall-clock time. A test that fails when
a machine is busy teaches people to re-run it rather than to fix anything. `22`
owns the budget; this module owns the shape.
"""

import pytest

from conftest import EXPENSIVE
from fake_chrome import FakeChrome
from fake_hermes import FakeHermes
from fake_pages import PageServer
from live_browser import requires_a_browser

EXPENSIVE_CLASSES = (FakeChrome, FakeHermes)
"""The two the guard patches a constructor on. `PageServer` is checked apart
because what it guards is `__enter__`: constructing one is cheap, and binding
its port is not."""


# --------------------------------------------------------------------------- #
# The guard is armed
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("expensive", EXPENSIVE_CLASSES)
def test_an_unmarked_test_cannot_build_an_expensive_fake(expensive: type) -> None:
    """This test is not `slow`, so the guard is live inside it. That is the
    proof: no `pytester`, no subprocess, no second copy of the rule."""
    with pytest.raises(AssertionError) as raised:
        expensive()

    assert raised.value.args[0] == EXPENSIVE.format(name=expensive.__name__)


def test_an_unmarked_test_cannot_start_the_page_server() -> None:
    """The third one, and the one that would launch a real browser behind it."""
    with pytest.raises(AssertionError) as raised:
        PageServer().__enter__()

    assert raised.value.args[0] == EXPENSIVE.format(name="PageServer")


@pytest.mark.slow
def test_a_slow_test_may_build_one() -> None:
    """The other half: a guard that refused everywhere would be a broken suite,
    not a fast one."""
    with FakeChrome() as chrome:
        assert chrome.port > 0


# --------------------------------------------------------------------------- #
# Every `live` test is `slow`
# --------------------------------------------------------------------------- #


def test_requires_a_browser_applies_all_three_marks() -> None:
    """`live`, `slow` and `skipif`, on the same function, as siblings.

    Read off a function the decorator has just been applied to rather than off
    `_MARKS`, because the bug this catches is in the *applying*: a nested
    `pytest.mark.slow(pytest.mark.live(...))` puts `live` inside `slow`'s
    arguments and only `slow` reaches the test.
    """

    @requires_a_browser
    def a_live_test() -> None: ...  # pragma: no cover - never called

    names = {mark.name for mark in a_live_test.pytestmark}
    assert names == {"live", "slow", "skipif"}
