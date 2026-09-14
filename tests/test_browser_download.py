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
