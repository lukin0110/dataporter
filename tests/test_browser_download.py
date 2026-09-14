"""Telling a page from a hop on the way to one (`download._Wait`).

A good link is a redirect chain: the vendor's own hop renders a document — and
fires `Page.loadEventFired` — before the archive's signed URL on another host
begins the download. Concluding "a page" on that first load abandons a download
that has not started yet, so what these pin is the rule that replaced it: a
document is a page only once both sessions have gone quiet and no download began.
"""

import time
from pathlib import Path

from dataporter.browser import download

SETTLE = 0.05
"""A settle window short enough to test, standing in for `download.SETTLE_S`."""


def _wait(tmp_path: Path) -> download._Wait:
    return download._Wait(into=tmp_path, idle_s=30.0, max_bytes=1 << 30)


def test_a_document_that_went_quiet_is_a_page(tmp_path: Path) -> None:
    """A login page loads and then says nothing more: that is a signed-out link."""
    wait = _wait(tmp_path)
    wait.loaded_at = time.monotonic() - 1.0
    wait.last_event = time.monotonic() - 1.0

    assert wait.settled_on_a_page(SETTLE)


def test_a_document_the_chain_is_still_moving_past_is_not_a_page(tmp_path: Path) -> None:
    """The hop rendered, but the redirect to the archive is still going.

    This is the run that used to fail: `a.claude.ai` renders, and the download
    from the signed URL has not begun. One poll's grace called that a page and
    gave up on a download Chrome went on to finish.
    """
    wait = _wait(tmp_path)
    wait.loaded_at = time.monotonic() - 1.0
    wait.saw_event()

    assert not wait.settled_on_a_page(SETTLE)


def test_a_download_that_began_is_never_a_page(tmp_path: Path) -> None:
    """Once the download has a guid there is nothing left to decide."""
    wait = _wait(tmp_path)
    wait.loaded_at = time.monotonic() - 1.0
    wait.last_event = time.monotonic() - 1.0
    wait.guid = "a-guid"

    assert not wait.settled_on_a_page(SETTLE)


def test_nothing_loaded_is_not_a_page(tmp_path: Path) -> None:
    """A navigation that became a download commits no document at all."""
    assert not _wait(tmp_path).settled_on_a_page(SETTLE)


def test_quiet_is_measured_from_the_last_event_not_the_load(tmp_path: Path) -> None:
    """A hop that loaded long ago is still not a page while events keep arriving."""
    wait = _wait(tmp_path)
    wait.loaded_at = time.monotonic() - 60.0
    wait.saw_event()

    assert not wait.settled_on_a_page(SETTLE)
    time.sleep(SETTLE)
    assert wait.settled_on_a_page(SETTLE)


# --------------------------------------------------------------------------- #
# The bytes are the signal the browser cannot fail to send
# --------------------------------------------------------------------------- #


def test_a_finished_file_is_the_download_even_with_no_event(tmp_path: Path) -> None:
    """`downloadProgress` is not always delivered; the bytes always are.

    Observed against claude.ai: a run downloaded every byte of a part and then
    waited out its idle budget for a completion that never came.
    """
    wait = _wait(tmp_path)
    landed = tmp_path / "a-guid"
    landed.write_bytes(b"the archive")

    assert wait.landed() is None, "not on the first sight of it: a file is made before it is written"
    got = wait.landed()

    assert got is not None
    assert got.path == landed
    assert got.bytes == len(b"the archive")


def test_a_download_still_being_written_is_not_finished(tmp_path: Path) -> None:
    """A `.crdownload` beside it means the browser is still writing."""
    wait = _wait(tmp_path)
    (tmp_path / "a-guid.crdownload").write_bytes(b"partial")

    assert wait.landed() is None
    assert wait.landed() is None


def test_a_file_that_was_already_there_is_not_the_download(tmp_path: Path) -> None:
    """The manifest and the parts filed before it stay in the staging dir."""
    already = tmp_path / "manifest.json"
    already.write_bytes(b"{}")
    wait = download._Wait(into=tmp_path, idle_s=30.0, max_bytes=1 << 30, before=frozenset([already]))

    assert wait.landed() is None
    assert wait.landed() is None


def test_an_empty_file_is_not_yet_the_download(tmp_path: Path) -> None:
    """Chrome creates the target before it writes a byte to it."""
    wait = _wait(tmp_path)
    (tmp_path / "a-guid").write_bytes(b"")

    assert wait.landed() is None
    assert wait.landed() is None


def test_a_growing_file_is_not_finished_until_it_stops(tmp_path: Path) -> None:
    """Two polls at the same size before the bytes are believed."""
    wait = _wait(tmp_path)
    target = tmp_path / "a-guid"
    target.write_bytes(b"one")

    assert wait.landed() is None
    target.write_bytes(b"one and more")
    assert wait.landed() is None, "the size moved, so it is still being written"
    assert wait.landed() is not None


def test_a_stale_crdownload_does_not_hold_the_fetch_open(tmp_path: Path) -> None:
    """One left by an interrupted run is not this navigation's write in flight.

    Nothing sweeps the staging dir, so a `.crdownload` from a run that was
    interrupted is still sitting there. Counting it as progress pushed the idle
    deadline out on every poll, so the fetch could reach neither the page nor the
    stall and hung for good. (Raised by Copilot in review on #53.)
    """
    stale = tmp_path / "old-guid.crdownload"
    stale.write_bytes(b"left behind")
    wait = download._Wait(into=tmp_path, idle_s=30.0, max_bytes=1 << 30, before=frozenset([stale]))
    wait.deadline = 0.0

    # On its own it says nothing, and above all it does not buy the fetch time:
    # a deadline pushed out on every poll is the hang this guards against.
    assert wait.landed() is None
    assert wait.deadline == 0.0

    landed = tmp_path / "new-guid"
    landed.write_bytes(b"the archive")
    assert wait.landed() is None, "the first sight of a new file is progress, not an answer"
    got = wait.landed()

    assert got is not None, "the stale .crdownload must not mask the file that did land"
    assert got.path == landed


def test_a_crdownload_is_never_itself_the_download(tmp_path: Path) -> None:
    """A write still in flight is not the archive, however new it is."""
    wait = _wait(tmp_path)
    (tmp_path / "a-guid.crdownload").write_bytes(b"half of it")

    assert wait.landed() is None
    assert wait.landed() is None


def test_a_file_that_vanishes_while_it_is_measured_is_not_an_error(tmp_path: Path) -> None:
    """Chrome renames out from under the listing; that is progress, not a failure.

    The fetch used to die with `FileNotFoundError` if a name listed a moment
    earlier was gone before it was measured. (Raised by Copilot in review on #53.)
    """
    wait = _wait(tmp_path)
    ghost = tmp_path / "a-guid"
    ghost.write_bytes(b"here for now")

    real_iterdir = Path.iterdir

    def vanishing(self: Path) -> object:
        items = list(real_iterdir(self))
        ghost.unlink(missing_ok=True)  # gone between the listing and the stat
        return iter(items)

    Path.iterdir = vanishing  # type: ignore[method-assign]
    try:
        assert wait.landed() is None
    finally:
        Path.iterdir = real_iterdir  # type: ignore[method-assign]
