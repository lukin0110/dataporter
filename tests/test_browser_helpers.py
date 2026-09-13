"""The deterministic primitives, the wall around them, and what they print.

Four kinds of test, in this order:

- the wall and the normalisation as pure functions, because they are the two
  rules the rest of the slice is built on;
- every helper against `FakeChrome` and a modelled page, which is what makes the
  suite cover this module on a machine with no browser;
- the commands, for the exit codes and the one-object-on-stdout promise;
- `08`'s acceptance criteria against a real Chrome rendering the checked-in
  fixtures, skipped where no browser is installed.
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataporter import cli
from dataporter.browser import export_page, helpers, launcher, probe
from dataporter.browser.cdp import CdpClient
from dataporter.config import BrowserSettings, Settings, TimeoutSettings
from dataporter.errors import SafetyError, UIError
from dataporter.exit_codes import ExitCode
from dataporter.seed import sha256_of
from fake_chrome import Call, free_port
from fake_composer import Browser, FakePage, Turn
from fake_pages import (
    CHAT_ID,
    GENERATING_CHAT_ID,
    RESPONDING_CHAT_ID,
    PageServer,
)
from live_browser import live_browser, requires_a_browser, visit

pytestmark = pytest.mark.slow
"""Slow all the way through: every helper is driven against a fake Chrome on a real
debug port.
"""

CHAT_URL = f"https://claude.ai/chat/{CHAT_ID}"
NEW_URL = "https://claude.ai/new"


# --------------------------------------------------------------------------- #
# The wall
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url",
    [
        NEW_URL,
        "https://claude.ai/new?q=1",
        CHAT_URL,
        f"{CHAT_URL}?first=1",
    ],
)
def test_the_migration_surface_admits_the_two_pages_a_migration_uses(url: str) -> None:
    assert helpers.CLAUDE.permits(url)


@pytest.mark.parametrize(
    "url",
    [
        # The five paths `08` names, one by one.
        "https://claude.ai/settings/profile",
        "https://claude.ai/admin",
        "https://claude.ai/billing",
        "https://claude.ai/organizations/abc",
        "https://claude.ai/project/abc",
        # And the rest of the world.
        "https://claude.ai/",
        "https://claude.ai/login",
        "https://claude.ai/chat/not-a-uuid",
        "https://example.com/new",
        "http://claude.ai/new",
        "https://claude.ai.evil.test/new",
        "about:blank",
    ],
)
def test_the_migration_surface_admits_nothing_else(url: str) -> None:
    assert not helpers.CLAUDE.permits(url)
    with pytest.raises(SafetyError):
        helpers.guard(url)


@pytest.mark.parametrize(
    "url",
    [
        export_page.EXPORT_PAGE_URL,
        f"{export_page.EXPORT_PAGE_URL}?tab=data",
        "https://claude.ai/login",
        "https://claude.ai/login/callback",
    ],
)
def test_the_extraction_surface_admits_the_two_pages_an_ask_uses(url: str) -> None:
    assert export_page.EXTRACTION_SURFACE.permits(url)


@pytest.mark.parametrize("url", [NEW_URL, CHAT_URL, "https://claude.ai/settings"])
def test_the_extraction_surface_admits_no_chat(url: str) -> None:
    """§36: the source session never imports, and a page it cannot open is a chat it cannot create."""
    assert not export_page.EXTRACTION_SURFACE.permits(url)
    with pytest.raises(SafetyError):
        helpers.guard(url, export_page.EXTRACTION_SURFACE)


def test_the_migration_surface_admits_no_export_page() -> None:
    """And the other way round, which makes the two lists a wall rather than a preference.

    Every helper Hermes can run refuses the export page.
    """
    assert not helpers.CLAUDE.permits(export_page.EXPORT_PAGE_URL)
    with pytest.raises(SafetyError):
        helpers.guard(export_page.EXPORT_PAGE_URL)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain", "plain"),
        ("two\r\nlines", "two\nlines"),
        ("old\rmac", "old\nmac"),
        ("\u00a0leading", "leading"),
        ("mid\u00a0space", "mid space"),  # the NBSP ProseMirror writes
        ("trailing   \nspace  ", "trailing\nspace"),
        ("\n\n  padded  \n\n", "padded"),
        ("keep\n\nthe blank line", "keep\n\nthe blank line"),
    ],
)
def test_normalise(raw: str, expected: str) -> None:
    """Written down so that a mismatch means the seed changed, and not that ProseMirror rewrote a space."""
    assert helpers.normalise(raw) == expected


# --------------------------------------------------------------------------- #
# A browser that answers to order
# --------------------------------------------------------------------------- #


@pytest.fixture
def new_chat(tmp_path: Path) -> Iterator[Browser]:
    """One tab, on an empty new chat. What a migration starts from."""
    with Browser(FakePage(url=NEW_URL)) as browser:
        yield browser


# -- choosing the tab -------------------------------------------------------- #


def test_no_claude_tab(tmp_path: Path) -> None:
    with Browser(FakePage(url="https://example.com/")) as browser:
        outcome = helpers.probe_page(browser.client, browser.settings(tmp_path))
    assert outcome.result.model_dump() == {"ok": False, "error": "no_claude_tab"} | {
        key: None for key in helpers.Failure.model_fields if key not in {"ok", "error"}
    }
    assert outcome.exit_code == ExitCode.FAILED


def test_two_claude_tabs_are_ambiguous(tmp_path: Path) -> None:
    with Browser(FakePage(url=NEW_URL), FakePage(url=CHAT_URL)) as browser:
        outcome = helpers.probe_page(browser.client, browser.settings(tmp_path))
    failure = outcome.result
    assert isinstance(failure, helpers.Failure)
    assert failure.error == "ambiguous_tab"
    assert failure.tabs == (
        helpers.TabRef(id="page-1", url=NEW_URL),
        helpers.TabRef(id="page-2", url=CHAT_URL),
    )
    # An id and a URL, and nothing that could be a conversation title (§10).
    assert set(helpers.TabRef.model_fields) == {"id", "url"}


def test_target_resolves_an_ambiguous_browser(tmp_path: Path) -> None:
    with Browser(FakePage(url=NEW_URL), FakePage(url=CHAT_URL, last_role="assistant")) as browser:
        outcome = helpers.probe_page(browser.client, browser.settings(tmp_path), target="page-2")
    assert outcome.ok
    assert outcome.conversation_id == CHAT_ID


def test_an_unknown_target_is_named_as_such(new_chat: Browser, tmp_path: Path) -> None:
    outcome = helpers.probe_page(new_chat.client, new_chat.settings(tmp_path), target="page-9")
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.error == "unknown_target"
    assert outcome.result.detail == "page-9"


def test_a_control_character_in_target_cannot_forge_output(new_chat: Browser, tmp_path: Path) -> None:
    outcome = helpers.probe_page(new_chat.client, new_chat.settings(tmp_path), target="page\n9")
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.detail == "page?9"


# -- the gate ---------------------------------------------------------------- #

OUTSIDE = "https://claude.ai/settings/profile"


def helper_calls(tmp_path: Path, url: str) -> list[tuple[str, list[Call]]]:
    """Run every helper against a tab at `url`, and collect what each printed and what it asked the browser."""
    collected: list[tuple[str, list[Call]]] = []
    for name, work in (
        ("probe", helpers.probe_page),
        (
            "paste",
            lambda c, s: helpers.paste_seed(c, s, seed=_seed_file(tmp_path, "x")),
        ),
        ("attach", lambda c, s: helpers.attach_file(c, s, file=_any_file(tmp_path))),
        ("await-response", lambda c, s: helpers.await_response(c, s, poll_s=0.01)),
    ):
        with Browser(FakePage(url=url)) as browser:
            emission = helpers.run(browser.settings(tmp_path), name, work)
            collected.append((emission.text, browser.chrome.calls))
    return collected


def test_every_helper_refuses_a_page_outside_the_migration_surface(
    tmp_path: Path,
) -> None:
    """And makes no CDP call while refusing.

    The URL in the target list is enough to know, and attaching would already be acting.
    """
    for text, calls in helper_calls(tmp_path, OUTSIDE):
        assert json.loads(text) == {
            "ok": False,
            "error": "outside_migration_surface",
            "url": OUTSIDE,
        }
        assert calls == []


def test_a_tab_that_has_moved_since_the_target_list_is_refused(
    tmp_path: Path,
) -> None:
    """The list said `/new`; the page has since redirected to a login screen.

    The gate runs a second time on the live URL, which costs one `location.href`
    and is the only CDP call made.
    """
    with Browser(FakePage(url=NEW_URL)) as browser:
        browser.chrome.targets[0].url = NEW_URL
        browser.page().url = "https://claude.ai/login"
        emission = helpers.run(browser.settings(tmp_path), "probe", helpers.probe_page)
        methods = browser.chrome.methods()
    assert json.loads(emission.text)["error"] == "outside_migration_surface"
    assert json.loads(emission.text)["url"] == "https://claude.ai/login"
    assert methods == ["Page.enable", "Runtime.evaluate"]


# -- probe ------------------------------------------------------------------- #


def test_probe_prints_the_page_state_and_the_last_message(
    tmp_path: Path,
) -> None:
    with Browser(
        FakePage(
            url=CHAT_URL,
            composer="draft",
            last_role="assistant",
            last_text="ACK part 2 of 3 — done",
            send_enabled=True,
        )
    ) as browser:
        outcome = helpers.probe_page(
            browser.client,
            browser.settings(tmp_path),
            expect=["ACK part 2 of 3", "ACK part 3 of 3"],
        )
    printed = json.loads(outcome.result.model_dump_json(exclude_none=True))
    assert printed["ok"] is True
    assert printed["kind"] == "chat"
    assert printed["conversation_id"] == CHAT_ID
    assert printed["composer_chars"] == 5
    assert printed["tab_count"] == 1
    assert printed["last_message"] == {
        "role": "assistant",
        "chars": len("ACK part 2 of 3 — done"),
        "contains": ["ACK part 2 of 3"],
    }
    # The acknowledgement was found without the message ever being printed.
    assert "done" not in json.dumps(printed)


def test_probe_reports_a_page_with_no_messages(new_chat: Browser, tmp_path: Path) -> None:
    outcome = helpers.probe_page(new_chat.client, new_chat.settings(tmp_path), expect=["ACK"])
    assert isinstance(outcome.result, helpers.ProbeResult)
    assert outcome.result.last_message == probe.LastMessage(role=None, chars=0, contains=())


def test_an_ordinary_probe_says_nothing_about_messages_or_the_title(new_chat: Browser, tmp_path: Path) -> None:
    """`17` widened the object; `08`'s poll loop still gets the narrow one."""
    outcome = helpers.probe_page(new_chat.client, new_chat.settings(tmp_path))
    printed = json.loads(outcome.result.model_dump_json(exclude_none=True))
    assert "messages" not in printed
    assert "title" not in printed


def test_probe_messages_reports_every_turn_and_never_a_message(
    tmp_path: Path,
) -> None:
    """`17`'s probe: one object per turn, each one a role, a length and which of the caller's own strings were in it."""
    with Browser(
        FakePage(
            url=CHAT_URL,
            transcript=[
                Turn("human", "Original conversation ID: aa000001 — and the rest"),
                Turn("assistant", "MIGRATION-ACK aa000001 1/1 — done"),
            ],
        )
    ) as browser:
        outcome = helpers.probe_page(
            browser.client,
            browser.settings(tmp_path),
            expect=["MIGRATION-ACK aa000001 1/1"],
            messages=True,
        )
    printed = json.loads(outcome.result.model_dump_json(exclude_none=True))
    assert [item["role"] for item in printed["messages"]] == ["human", "assistant"]
    assert printed["messages"][1]["contains"] == ["MIGRATION-ACK aa000001 1/1"]
    assert printed["messages"][0]["contains"] == []
    assert "and the rest" not in json.dumps(printed)


def test_probe_answers_about_a_title_and_never_with_one(tmp_path: Path) -> None:
    """§10 again: the question is the caller's string, and the answer is a boolean and a length."""
    with Browser(FakePage(url=CHAT_URL, title="Notes on pooling")) as browser:
        settings = browser.settings(tmp_path)
        asked = helpers.probe_page(browser.client, settings, expect_title="  Notes   on pooling ")
        wrong = helpers.probe_page(browser.client, settings, expect_title="Something else")
    printed = json.loads(asked.result.model_dump_json(exclude_none=True))
    # Whitespace is squashed on both sides before the comparison.
    assert printed["title"] == {
        "chars": len("Notes on pooling"),
        "source": "chat",
        "matches": True,
    }
    assert "Notes on pooling" not in json.dumps(printed)
    assert json.loads(wrong.result.model_dump_json())["title"]["matches"] is False


def test_probe_result_is_the_page_state_plus_four_fields() -> None:
    """A field `10` adds to `PageState` must appear here without an edit.

    `messages` and `title` are `17`'s, and are the two that are `None` unless
    `--messages` asked for them — `exclude_none` is what keeps the ordinary
    probe's object the shape `08` printed.
    """
    assert set(helpers.ProbeResult.model_fields) == set(probe.PageState.model_fields) | {
        "ok",
        "last_message",
        "messages",
        "title",
    }


# -- paste ------------------------------------------------------------------- #


def _seed_file(tmp_path: Path, text: str, name: str = "part-01.txt") -> Path:
    path = tmp_path / "seeds" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


def _any_file(tmp_path: Path, name: str = "notes.txt") -> Path:
    path = tmp_path / "attachments" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"bytes")
    return path


def test_paste_inserts_the_seed_and_hashes_what_the_composer_holds(new_chat: Browser, tmp_path: Path) -> None:
    seed = "MIGRATION PART 1 OF 2\n\nHello\n"
    outcome = helpers.paste_seed(new_chat.client, new_chat.settings(tmp_path), seed=_seed_file(tmp_path, seed))
    result = outcome.result
    assert isinstance(result, helpers.PasteResult)
    assert result.ok
    assert result.method == "insert_text"
    assert result.chars == len(helpers.normalise(seed))
    assert result.sha256 == _sha(helpers.normalise(seed))
    assert new_chat.page().composer == seed
    # The seed itself is never printed, only its size and its digest.
    assert "Hello" not in result.model_dump_json()


def test_paste_can_go_through_exec_command(new_chat: Browser, tmp_path: Path) -> None:
    seed = "MIGRATION PART 2 OF 2\n"
    outcome = helpers.paste_seed(
        new_chat.client,
        new_chat.settings(tmp_path),
        seed=_seed_file(tmp_path, seed),
        method=helpers.PasteMethod.EXEC_COMMAND,
    )
    assert isinstance(outcome.result, helpers.PasteResult)
    assert outcome.result.method == "exec_command"
    assert new_chat.page().composer == seed


def test_paste_refuses_a_composer_that_is_not_empty(tmp_path: Path) -> None:
    with Browser(FakePage(url=NEW_URL, composer="half a prompt")) as browser:
        outcome = helpers.paste_seed(browser.client, browser.settings(tmp_path), seed=_seed_file(tmp_path, "x"))
        assert browser.page().composer == "half a prompt"
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.error == "composer_not_empty"
    assert outcome.result.observed_chars == len("half a prompt")
    assert outcome.exit_code == ExitCode.FAILED


def test_append_adds_to_what_is_there(tmp_path: Path) -> None:
    with Browser(FakePage(url=NEW_URL, composer="first half\n")) as browser:
        outcome = helpers.paste_seed(
            browser.client,
            browser.settings(tmp_path),
            seed=_seed_file(tmp_path, "second half\n"),
            append=True,
        )
        assert browser.page().composer == "first half\nsecond half\n"
    result = outcome.result
    assert isinstance(result, helpers.PasteResult)
    # The digest describes the composer, which under `--append` is both halves.
    assert result.sha256 == _sha("first half\nsecond half")


def test_paste_refuses_a_page_with_no_composer(tmp_path: Path) -> None:
    with Browser(FakePage(url=NEW_URL, composer=None)) as browser:
        outcome = helpers.paste_seed(browser.client, browser.settings(tmp_path), seed=_seed_file(tmp_path, "x"))
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.error == "composer_missing"


def test_a_composer_that_goes_away_before_the_insert_is_not_typed_into(
    tmp_path: Path,
) -> None:
    """`--append` reads the composer between the probe and the insert.

    A page that navigates in that window must not be typed into anyway.
    """
    with Browser(FakePage(url=NEW_URL, composer="first half", vanish_text_at=1)) as browser:
        outcome = helpers.paste_seed(
            browser.client,
            browser.settings(tmp_path),
            seed=_seed_file(tmp_path, "x"),
            append=True,
        )
        assert "Input.insertText" not in browser.chrome.methods()
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.error == "composer_missing"


def test_a_composer_that_goes_away_after_the_insert_is_reported(
    tmp_path: Path,
) -> None:
    with Browser(FakePage(url=NEW_URL, vanish_text_at=1)) as browser:
        outcome = helpers.paste_seed(browser.client, browser.settings(tmp_path), seed=_seed_file(tmp_path, "x"))
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.error == "composer_missing"


def test_a_composer_that_will_not_take_the_caret_is_not_typed_into(
    tmp_path: Path,
) -> None:
    with Browser(FakePage(url=NEW_URL, focusable=False)) as browser:
        outcome = helpers.paste_seed(browser.client, browser.settings(tmp_path), seed=_seed_file(tmp_path, "x"))
        assert "Input.insertText" not in browser.chrome.methods()
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.error == "composer_missing"


def test_an_editor_that_mangles_the_seed_is_caught_by_the_hash(
    tmp_path: Path,
) -> None:
    """The reason the helper hashes rather than trusting the CDP call."""
    with Browser(FakePage(url=NEW_URL, insert=lambda text: text.replace("l", "1"))) as browser:
        outcome = helpers.paste_seed(
            browser.client,
            browser.settings(tmp_path),
            seed=_seed_file(tmp_path, "hello world"),
        )
    failure = outcome.result
    assert isinstance(failure, helpers.Failure)
    assert failure.error == "text_mismatch"
    assert failure.expected_sha256 == _sha("hello world")
    assert failure.observed_sha256 == _sha("he11o wor1d")
    assert failure.observed_chars == len("he11o wor1d")


def test_an_editor_that_only_rewrites_whitespace_is_not_a_mismatch(
    tmp_path: Path,
) -> None:
    """ProseMirror turns a leading space into a non-breaking one and drops the trailing whitespace of a line.

    Neither is the seed changing.
    """
    with Browser(
        FakePage(
            url=NEW_URL,
            insert=lambda text: text.replace("\n ", "\n\u00a0").replace("end", "end   "),
        )
    ) as browser:
        outcome = helpers.paste_seed(
            browser.client,
            browser.settings(tmp_path),
            seed=_seed_file(tmp_path, "start\n indented\nend"),
        )
    assert isinstance(outcome.result, helpers.PasteResult)


def test_a_seed_that_is_not_there_is_a_usage_error(new_chat: Browser, tmp_path: Path) -> None:
    outcome = helpers.paste_seed(new_chat.client, new_chat.settings(tmp_path), seed=tmp_path / "nowhere.txt")
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.error == "seed_not_found"
    assert outcome.exit_code == ExitCode.USAGE
    # Nothing was asked of the browser: the argument was wrong.
    assert new_chat.chrome.calls == []


def test_a_seed_that_is_not_utf8_is_reported_rather_than_crashing(new_chat: Browser, tmp_path: Path) -> None:
    path = tmp_path / "part-01.txt"
    path.write_bytes(b"\xff\xfe not text")
    outcome = helpers.paste_seed(new_chat.client, new_chat.settings(tmp_path), seed=path)
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.error == "seed_unreadable"
    assert outcome.exit_code == ExitCode.USAGE


def test_paste_reports_the_tab_it_could_not_choose(tmp_path: Path) -> None:
    with Browser(FakePage(url=NEW_URL), FakePage(url=NEW_URL)) as browser:
        outcome = helpers.paste_seed(browser.client, browser.settings(tmp_path), seed=_seed_file(tmp_path, "x"))
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.error == "ambiguous_tab"


# -- attach ------------------------------------------------------------------ #


def test_attach_sets_the_file_and_waits_for_the_chip(tmp_path: Path) -> None:
    with Browser(FakePage(url=CHAT_URL, chip_polls=2)) as browser:
        outcome = helpers.attach_file(
            browser.client,
            browser.settings(tmp_path),
            file=_any_file(tmp_path),
            poll_s=0.01,
        )
        assert browser.page().uploaded == ["notes.txt"]
    result = outcome.result
    assert isinstance(result, helpers.AttachResult)
    assert result.file_name == "notes.txt"
    assert result.bytes == len(b"bytes")
    assert outcome.conversation_id == CHAT_ID


def test_attach_reports_a_chip_that_never_appears(tmp_path: Path) -> None:
    with Browser(FakePage(url=CHAT_URL, chip_polls=1000)) as browser:
        outcome = helpers.attach_file(
            browser.client,
            browser.settings(tmp_path),
            file=_any_file(tmp_path),
            poll_s=0.01,
        )
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.error == "chip_not_found"
    assert outcome.result.detail == "notes.txt"


def test_attach_reports_a_page_with_nowhere_to_put_a_file(tmp_path: Path) -> None:
    with Browser(FakePage(url=CHAT_URL, file_input=False)) as browser:
        outcome = helpers.attach_file(browser.client, browser.settings(tmp_path), file=_any_file(tmp_path))
        assert "DOM.setFileInputFiles" not in browser.chrome.methods()
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.error == "input_not_found"


def test_attach_reports_a_file_the_browser_refuses(tmp_path: Path) -> None:
    with Browser(FakePage(url=CHAT_URL, accept_files=False)) as browser:
        outcome = helpers.attach_file(browser.client, browser.settings(tmp_path), file=_any_file(tmp_path))
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.error == "upload_rejected"


def test_a_file_that_is_not_there_is_a_usage_error(new_chat: Browser, tmp_path: Path) -> None:
    outcome = helpers.attach_file(new_chat.client, new_chat.settings(tmp_path), file=tmp_path / "nowhere.png")
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.error == "file_not_found"
    assert outcome.exit_code == ExitCode.USAGE
    assert new_chat.chrome.calls == []


def test_attach_reports_the_tab_it_could_not_choose(tmp_path: Path) -> None:
    with Browser(FakePage(url=NEW_URL), FakePage(url=NEW_URL)) as browser:
        outcome = helpers.attach_file(browser.client, browser.settings(tmp_path), file=_any_file(tmp_path))
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.error == "ambiguous_tab"


# -- attachments ------------------------------------------------------------- #


def test_attachments_finds_every_chip_in_one_look(tmp_path: Path) -> None:
    """`16`'s check before the first paste: all of them, at one moment."""
    files = [_any_file(tmp_path, "notes.txt"), _any_file(tmp_path, "chart.png")]
    with Browser(FakePage(url=CHAT_URL, uploaded=["notes.txt", "chart.png"])) as browser:
        outcome = helpers.attached_files(browser.client, browser.settings(tmp_path), files=files)
        # One evaluate for the chips, not one per file: a chip that appeared
        # between two round trips would describe a page that never existed.
        expressions = [str(call.params.get("expression", "")) for call in browser.chrome.calls]
        assert sum(helpers.CHIPS_TAG in item for item in expressions) == 1
    result = outcome.result
    assert isinstance(result, helpers.ChipsResult)
    assert result.file_names == ("notes.txt", "chart.png")
    assert result.count == 2
    assert outcome.conversation_id == CHAT_ID


def test_attachments_names_the_file_with_no_chip(tmp_path: Path) -> None:
    files = [_any_file(tmp_path, "notes.txt"), _any_file(tmp_path, "chart.png")]
    with Browser(FakePage(url=CHAT_URL, uploaded=["notes.txt"])) as browser:
        outcome = helpers.attached_files(browser.client, browser.settings(tmp_path), files=files)
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.error == "chip_not_found"
    assert outcome.result.detail == "chart.png"


def test_attachments_reports_the_tab_it_could_not_choose(tmp_path: Path) -> None:
    with Browser(FakePage(url=NEW_URL), FakePage(url=NEW_URL)) as browser:
        outcome = helpers.attached_files(
            browser.client,
            browser.settings(tmp_path),
            files=[_any_file(tmp_path)],
        )
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.error == "ambiguous_tab"


def test_attachments_with_no_files_asks_the_page_nothing(tmp_path: Path) -> None:
    """A conversation with no attachments asks a question with a true answer."""
    with Browser(FakePage(url=CHAT_URL)) as browser:
        outcome = helpers.attached_files(browser.client, browser.settings(tmp_path), files=[])
        assert browser.chrome.calls == []
    result = outcome.result
    assert isinstance(result, helpers.ChipsResult)
    assert result.count == 0
    assert outcome.exit_code == ExitCode.OK


# -- await-response ---------------------------------------------------------- #


def streaming(page: FakePage, view: int) -> None:
    """Stage a reply that streams for three polls and then stops."""
    if view == 1:
        page.generating = True
    elif view <= 3:
        page.generating = True
        page.last_role = "assistant"
        page.last_text = "ACK" * view
    else:
        page.generating = False
        page.last_role = "assistant"
        page.last_text = "ACK part 1 of 1"


def test_await_response_waits_for_three_polls_that_agree(tmp_path: Path) -> None:
    with Browser(FakePage(url=CHAT_URL, on_view=streaming)) as browser:
        outcome = helpers.await_response(
            browser.client,
            browser.settings(tmp_path),
            timeout=30.0,
            expect=["ACK part 1 of 1"],
            poll_s=0.01,
        )
        assert browser.page().views == 6
    result = outcome.result
    assert isinstance(result, helpers.AwaitResult)
    assert result.conversation_id == CHAT_ID
    assert result.last_message.contains == ("ACK part 1 of 1",)
    assert result.elapsed_s >= 0


def test_a_response_that_is_still_growing_is_not_finished(tmp_path: Path) -> None:
    """The Stop button goes away before the last token lands.

    "not generating" alone would return a truncated answer.
    """

    def forever(page: FakePage, view: int) -> None:
        page.generating = False
        page.last_role = "assistant"
        page.last_text = "a" * view

    with Browser(FakePage(url=CHAT_URL, on_view=forever)) as browser:
        outcome = helpers.await_response(browser.client, browser.settings(tmp_path), timeout=0.05, poll_s=0.01)
    failure = outcome.result
    assert isinstance(failure, helpers.Failure)
    assert failure.error == "response_timeout"
    assert failure.generating is False
    assert failure.elapsed_s is not None


def test_await_response_times_out_on_a_page_that_never_stops(tmp_path: Path) -> None:
    with Browser(FakePage(url=CHAT_URL, generating=True)) as browser:
        outcome = helpers.await_response(browser.client, browser.settings(tmp_path), poll_s=0.01)
    failure = outcome.result
    assert isinstance(failure, helpers.Failure)
    assert failure.error == "response_timeout"
    assert failure.generating is True
    # The default came from the configured timeout, which the fixture set low.
    assert failure.elapsed_s is not None
    assert failure.elapsed_s < 5


def test_await_response_stops_watching_a_page_that_navigates_away(
    tmp_path: Path,
) -> None:
    def redirect(page: FakePage, view: int) -> None:
        if view > 1:
            page.url = "https://claude.ai/login"

    with Browser(FakePage(url=CHAT_URL, on_view=redirect)) as browser, pytest.raises(SafetyError):
        helpers.await_response(browser.client, browser.settings(tmp_path), timeout=5.0, poll_s=0.01)


def test_await_response_reports_the_tab_it_could_not_choose(tmp_path: Path) -> None:
    with Browser(FakePage(url="https://example.com/")) as browser:
        outcome = helpers.await_response(browser.client, browser.settings(tmp_path), poll_s=0.01)
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.error == "no_claude_tab"


# -- close-extra-tabs -------------------------------------------------------- #


def test_close_extra_tabs_keeps_one_new_chat_and_every_conversation(
    tmp_path: Path,
) -> None:
    with Browser(
        FakePage(url="about:blank"),
        FakePage(url=NEW_URL),
        FakePage(url=CHAT_URL),
        FakePage(url=NEW_URL),
        FakePage(url="https://claude.ai/"),
        FakePage(url="https://example.com/"),
    ) as browser:
        outcome = helpers.close_extra_tabs(browser.client, browser.settings(tmp_path))
        left = [item.url for item in browser.client.pages()]
    assert isinstance(outcome.result, helpers.CloseResult)
    assert outcome.result.closed == 3
    assert left == [NEW_URL, CHAT_URL, "https://example.com/"]


def test_close_extra_tabs_with_nothing_to_close(new_chat: Browser, tmp_path: Path) -> None:
    outcome = helpers.close_extra_tabs(new_chat.client, new_chat.settings(tmp_path))
    assert isinstance(outcome.result, helpers.CloseResult)
    assert outcome.result.closed == 0


# --------------------------------------------------------------------------- #
# Running one, and writing down that it ran
# --------------------------------------------------------------------------- #


def test_a_browser_that_is_not_there_is_still_one_json_object(tmp_path: Path) -> None:
    settings = Settings(
        workspace=tmp_path / "migration",
        browser=BrowserSettings(cdp_port=free_port()),
        timeouts=TimeoutSettings(cdp_call_s=0.5),
    )
    emission = helpers.run(settings, "probe", helpers.probe_page)
    printed = json.loads(emission.text)
    assert printed["ok"] is False
    assert printed["error"] == "browser"
    assert emission.exit_code == ExitCode.FAILED


def test_any_failure_in_the_taxonomy_becomes_its_category(tmp_path: Path) -> None:
    def explode(client: CdpClient, settings: Settings) -> helpers.Outcome:
        raise UIError(detail="the composer moved", transient=True)

    settings = Settings(workspace=tmp_path / "migration")
    emission = helpers.run(settings, "paste", explode)
    assert json.loads(emission.text) == {
        "ok": False,
        "error": "ui",
        "detail": "the composer moved",
    }


def test_every_run_appends_one_action_line(tmp_path: Path) -> None:
    with Browser(FakePage(url=CHAT_URL, last_role="assistant")) as browser:
        settings = browser.settings(tmp_path)
        helpers.run(settings, "probe", helpers.probe_page)
        helpers.run(settings, "close-extra-tabs", helpers.close_extra_tabs)
    lines = [
        json.loads(line) for line in helpers.actions_path(settings.workspace).read_text(encoding="utf-8").splitlines()
    ]
    assert [item["helper"] for item in lines] == ["probe", "close-extra-tabs"]
    assert [item["ok"] for item in lines] == [True, True]
    assert lines[0]["conversation_id"] == CHAT_ID
    assert lines[0]["ts"].endswith("Z")
    assert set(lines[0]) == {"ts", "helper", "ok", "elapsed_ms", "conversation_id"}
    assert isinstance(lines[0]["elapsed_ms"], int)


def test_a_refusal_is_recorded_too(tmp_path: Path) -> None:
    """`19` counts browser actions, and a refused one is still an action."""
    with Browser(FakePage(url=OUTSIDE)) as browser:
        settings = browser.settings(tmp_path)
        helpers.run(settings, "probe", helpers.probe_page)
    line = json.loads(helpers.actions_path(settings.workspace).read_text("utf-8"))
    assert line == {
        "ts": line["ts"],
        "helper": "probe",
        "ok": False,
        "elapsed_ms": line["elapsed_ms"],
        "conversation_id": None,
    }


def test_a_workspace_that_cannot_be_written_to_does_not_lose_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The helper has already acted on the page by then.

    Hermes needs to know what happened more than `19` needs the tally.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(helpers.Path, "mkdir", refuse)
    with Browser(FakePage(url=NEW_URL)) as browser:
        emission = helpers.run(browser.settings(tmp_path), "probe", helpers.probe_page)
    assert json.loads(emission.text)["ok"] is True
    assert emission.exit_code == ExitCode.OK


# --------------------------------------------------------------------------- #
# The commands
# --------------------------------------------------------------------------- #


def adoptable(browser: Browser, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Point the CLI at the fake browser, as `07`'s command tests do."""
    settings = browser.settings(tmp_path)
    monkeypatch.setenv("DATAPORTER_WORKSPACE", str(settings.workspace))
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", str(browser.chrome.port))
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__CDP_CALL_S", "2")
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__RESPONSE_S", "0.2")
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__ATTACH_S", "0.2")
    return settings


def test_browser_probe_prints_one_object_and_exits_zero(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Browser(FakePage(url=CHAT_URL, last_role="assistant", last_text="ACK part 1 of 1")) as browser:
        adoptable(browser, tmp_path, monkeypatch)
        result = runner.invoke(
            cli.app,
            ["browser", "probe", "--expect", "ACK part 1 of 1"],
            catch_exceptions=False,
        )
    assert result.exit_code == ExitCode.OK
    assert not result.stderr
    # Exactly one object, on one line, and nothing else.
    assert len(result.stdout.splitlines()) == 1
    printed = json.loads(result.stdout)
    assert printed["ok"] is True
    assert printed["last_message"]["contains"] == ["ACK part 1 of 1"]


def test_browser_paste_exits_one_when_it_refuses(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Browser(FakePage(url=NEW_URL, composer="a draft")) as browser:
        adoptable(browser, tmp_path, monkeypatch)
        result = runner.invoke(
            cli.app,
            ["browser", "paste", "--seed", str(_seed_file(tmp_path, "x"))],
            catch_exceptions=False,
        )
    assert result.exit_code == ExitCode.FAILED
    assert json.loads(result.stdout)["error"] == "composer_not_empty"


def test_browser_paste_takes_a_method_and_the_append_flag(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Browser(FakePage(url=NEW_URL, composer="first\n")) as browser:
        adoptable(browser, tmp_path, monkeypatch)
        result = runner.invoke(
            cli.app,
            [
                "browser",
                "paste",
                "--seed",
                str(_seed_file(tmp_path, "second\n")),
                "--method",
                "exec_command",
                "--append",
            ],
            catch_exceptions=False,
        )
        assert browser.page().composer == "first\nsecond\n"
    assert result.exit_code == ExitCode.OK
    assert json.loads(result.stdout)["method"] == "exec_command"


def test_browser_paste_without_a_seed_exits_two(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Typer's own missing-option error. Nothing lands on stdout."""
    with Browser(FakePage(url=NEW_URL)) as browser:
        adoptable(browser, tmp_path, monkeypatch)
        result = runner.invoke(cli.app, ["browser", "paste"], catch_exceptions=False)
    assert result.exit_code == ExitCode.USAGE
    assert not result.stdout


def test_browser_paste_with_a_seed_that_is_not_there_exits_two(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Browser(FakePage(url=NEW_URL)) as browser:
        adoptable(browser, tmp_path, monkeypatch)
        result = runner.invoke(
            cli.app,
            ["browser", "paste", "--seed", str(tmp_path / "nowhere.txt")],
            catch_exceptions=False,
        )
    assert result.exit_code == ExitCode.USAGE
    assert json.loads(result.stdout)["error"] == "seed_not_found"


def test_browser_attach_prints_the_file_and_its_size(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Browser(FakePage(url=CHAT_URL)) as browser:
        adoptable(browser, tmp_path, monkeypatch)
        result = runner.invoke(
            cli.app,
            ["browser", "attach", "--file", str(_any_file(tmp_path))],
            catch_exceptions=False,
        )
    assert result.exit_code == ExitCode.OK
    assert json.loads(result.stdout) == {
        "ok": True,
        "file_name": "notes.txt",
        "bytes": 5,
    }


def test_browser_attachments_prints_what_the_composer_carries(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Browser(FakePage(url=CHAT_URL, uploaded=["notes.txt"])) as browser:
        adoptable(browser, tmp_path, monkeypatch)
        result = runner.invoke(
            cli.app,
            ["browser", "attachments", "--file", str(_any_file(tmp_path))],
            catch_exceptions=False,
        )
    assert result.exit_code == ExitCode.OK
    assert json.loads(result.stdout) == {
        "ok": True,
        "file_names": ["notes.txt"],
        "count": 1,
    }


def test_browser_await_response_prints_the_timeout_it_hit(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Browser(FakePage(url=CHAT_URL, generating=True)) as browser:
        adoptable(browser, tmp_path, monkeypatch)
        monkeypatch.setattr(helpers, "RESPONSE_POLL_S", 0.01)
        result = runner.invoke(
            cli.app,
            ["browser", "await-response", "--timeout", "0.05"],
            catch_exceptions=False,
        )
    assert result.exit_code == ExitCode.FAILED
    printed = json.loads(result.stdout)
    assert printed["error"] == "response_timeout"
    assert printed["generating"] is True


def test_browser_await_response_returns_when_the_page_settles(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Browser(FakePage(url=CHAT_URL, on_view=streaming)) as browser:
        adoptable(browser, tmp_path, monkeypatch)
        monkeypatch.setattr(helpers, "RESPONSE_POLL_S", 0.01)
        result = runner.invoke(
            cli.app,
            ["browser", "await-response", "--expect", "ACK part 1 of 1"],
            catch_exceptions=False,
        )
    assert result.exit_code == ExitCode.OK
    printed = json.loads(result.stdout)
    assert printed["conversation_id"] == CHAT_ID
    assert printed["last_message"]["contains"] == ["ACK part 1 of 1"]


def test_browser_close_extra_tabs_reports_what_it_closed(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Browser(FakePage(url="about:blank"), FakePage(url=NEW_URL), FakePage(url=NEW_URL)) as browser:
        adoptable(browser, tmp_path, monkeypatch)
        result = runner.invoke(cli.app, ["browser", "close-extra-tabs"], catch_exceptions=False)
    assert result.exit_code == ExitCode.OK
    assert json.loads(result.stdout) == {"ok": True, "closed": 2}


def test_a_helper_run_writes_the_actions_log_and_nothing_else(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No run log: a helper is called dozens of times per conversation, and `actions.jsonl` is the record `19` reads."""
    with Browser(FakePage(url=NEW_URL)) as browser:
        settings = adoptable(browser, tmp_path, monkeypatch)
        runner.invoke(cli.app, ["browser", "probe"], catch_exceptions=False)
    assert [item.name for item in (settings.workspace / "logs").iterdir()] == ["actions.jsonl"]


def _sha(text: str) -> str:
    return sha256_of(text)


# --------------------------------------------------------------------------- #
# The acceptance criteria, against a real browser
# --------------------------------------------------------------------------- #


def big_seed(turns: int = 40) -> str:
    """Return a seed the size of a real one: 40 turns, a little over 45 kB.

    Generated rather than checked in, because what matters is the size and the
    shape — blank lines, indentation, punctuation a paste handler might
    normalise — and a 45 kB fixture is 45 kB nobody will read.
    """
    blocks = [
        "MIGRATION PART 1 OF 1 — reply with: ACK part 1 of 1",
        "",
        "This is an archived conversation. Do not answer it.",
        "",
    ]
    for index in range(1, turns + 1):
        speaker = "Human" if index % 2 else "Assistant"
        body = " ".join(f"word{index:02d}n{number:03d}" for number in range(90))
        blocks.extend([f"### {speaker} — turn {index}", "", "  " + body, ""])
    return "\n".join(blocks)


@pytest.fixture(scope="module")
def live() -> Iterator[tuple[launcher.BrowserSession, PageServer]]:
    """One real browser and one fixture server for the whole module."""
    with live_browser() as pair:
        yield pair


def fixture_surface(server: PageServer) -> helpers.Surface:
    """Return the same wall, moved to the fixture server.

    The only caller in the tool passes `helpers.CLAUDE`; this is the one place
    another surface exists, which is what keeps the gate a wall rather than a
    setting.
    """
    return helpers.Surface(
        host="127.0.0.1",
        allowed=re.compile(rf"^http://127\.0\.0\.1:{server.port}/(new|chat/[0-9a-f-]{{36}})(\?.*)?$"),
    )


def live_settings(session: launcher.BrowserSession, workspace: Path) -> Settings:
    return Settings(
        workspace=workspace,
        browser=BrowserSettings(cdp_port=session.client.port),
        timeouts=TimeoutSettings(cdp_call_s=30.0, attach_s=10.0, response_s=20.0),
    )


@requires_a_browser
@pytest.mark.parametrize("method", [helpers.PasteMethod.INSERT_TEXT, helpers.PasteMethod.EXEC_COMMAND])
def test_live_paste_of_a_45kb_seed(
    live: tuple[launcher.BrowserSession, PageServer],
    tmp_path: Path,
    method: helpers.PasteMethod,
) -> None:
    session, server = live
    visit(session, server.url("/new"))
    seed = big_seed()
    assert 40_000 < len(seed) < 60_000
    path = _seed_file(tmp_path, seed)

    outcome = helpers.paste_seed(
        session.client,
        live_settings(session, tmp_path / "migration"),
        seed=path,
        method=method,
        surface=fixture_surface(server),
    )
    result = outcome.result
    assert isinstance(result, helpers.Failure) is False, result.model_dump_json()
    assert isinstance(result, helpers.PasteResult)
    assert result.chars == len(helpers.normalise(seed))
    assert result.sha256 == _sha(helpers.normalise(seed))
    assert result.method == str(method)


@requires_a_browser
def test_live_paste_refuses_a_composer_that_is_not_empty(
    live: tuple[launcher.BrowserSession, PageServer], tmp_path: Path
) -> None:
    session, server = live
    visit(session, server.url(f"/chat/{CHAT_ID}"))
    outcome = helpers.paste_seed(
        session.client,
        live_settings(session, tmp_path / "migration"),
        seed=_seed_file(tmp_path, "a seed"),
        surface=fixture_surface(server),
    )
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.error == "composer_not_empty"


@requires_a_browser
def test_live_probe_reads_the_last_message(live: tuple[launcher.BrowserSession, PageServer], tmp_path: Path) -> None:
    session, server = live
    visit(session, server.url(f"/chat/{CHAT_ID}"))
    outcome = helpers.probe_page(
        session.client,
        live_settings(session, tmp_path / "migration"),
        expect=["ACK part 1 of 1", "ACK part 2 of 2"],
        surface=fixture_surface(server),
    )
    result = outcome.result
    assert isinstance(result, helpers.ProbeResult)
    assert result.last_message.role == "assistant"
    assert result.last_message.contains == ("ACK part 1 of 1",)
    assert result.conversation_id == CHAT_ID


@requires_a_browser
def test_live_attach_finds_the_chip_for_a_hidden_input(
    live: tuple[launcher.BrowserSession, PageServer], tmp_path: Path
) -> None:
    session, server = live
    visit(session, server.url("/new"))
    outcome = helpers.attach_file(
        session.client,
        live_settings(session, tmp_path / "migration"),
        file=_any_file(tmp_path, "diagram.png"),
        surface=fixture_surface(server),
    )
    result = outcome.result
    assert isinstance(result, helpers.AttachResult)
    assert result.file_name == "diagram.png"


@requires_a_browser
def test_live_await_response_returns_when_generation_stops(
    live: tuple[launcher.BrowserSession, PageServer], tmp_path: Path
) -> None:
    """The fixture drops its Stop button after four seconds, having written the last of the reply a beat earlier."""
    session, server = live
    visit(session, server.url(f"/chat/{RESPONDING_CHAT_ID}"))
    outcome = helpers.await_response(
        session.client,
        live_settings(session, tmp_path / "migration"),
        expect=["ACK part 1 of 1"],
        surface=fixture_surface(server),
    )
    result = outcome.result
    assert isinstance(result, helpers.AwaitResult)
    assert 4 <= result.elapsed_s <= 8
    assert result.last_message.contains == ("ACK part 1 of 1",)
    assert result.conversation_id == RESPONDING_CHAT_ID


@requires_a_browser
def test_live_await_response_times_out_on_a_page_that_never_stops(
    live: tuple[launcher.BrowserSession, PageServer], tmp_path: Path
) -> None:
    session, server = live
    visit(session, server.url(f"/chat/{GENERATING_CHAT_ID}"))
    outcome = helpers.await_response(
        session.client,
        live_settings(session, tmp_path / "migration"),
        timeout=3.0,
        surface=fixture_surface(server),
    )
    assert isinstance(outcome.result, helpers.Failure)
    assert outcome.result.error == "response_timeout"
    assert outcome.result.generating is True


@requires_a_browser
def test_live_a_page_outside_the_surface_is_refused(
    live: tuple[launcher.BrowserSession, PageServer], tmp_path: Path
) -> None:
    session, server = live
    visit(session, server.url("/settings/profile"))
    with pytest.raises(SafetyError):
        helpers.probe_page(
            session.client,
            live_settings(session, tmp_path / "migration"),
            surface=fixture_surface(server),
        )


@requires_a_browser
def test_live_the_export_page_walks_its_three_stages(
    live: tuple[launcher.BrowserSession, PageServer],
) -> None:
    """`31`'s two expressions against a real Chrome and a real document.

    Not evidence about claude.ai — every row of the UI map this fixture is built
    from is still `*unknown*` — but evidence about us: that `EXPORT_PAGE_JS`
    tells the three stages apart, that `click_js` clicks the first *visible*
    match rather than the first match, and that a confirmation dialog is only
    confirmable while it is open.
    """
    session, server = live
    visit(session, server.url(export_page.EXPORT_PAGE_PATH))
    tab = session.client.pages()[0]
    page = session.client.attach(tab.id)
    try:
        before = export_page.ExportPageView.read(page)
        assert (before.button, before.dialog, before.requested) == (True, False, False)

        assert page.evaluate(export_page.click_js(export_page.EXPORT_BUTTON_SELECTOR))
        opened = export_page.ExportPageView.read(page)
        # The button is still there behind the dialog, because that is what a
        # modal is. The ask presses it once, before the loop, and never again.
        assert (opened.dialog, opened.confirm) == (True, True)

        assert page.evaluate(export_page.click_js(export_page.CONFIRM_BUTTON_SELECTOR))
        after = export_page.ExportPageView.read(page)
        assert (after.requested, after.dialog) == (True, False)
    finally:
        page.close()


@requires_a_browser
def test_live_a_click_finds_nothing_to_click(
    live: tuple[launcher.BrowserSession, PageServer],
) -> None:
    """`false`, not an exception.

    "there was nothing there" is an answer the ask reports rather than a page expression
    that threw.
    """
    session, server = live
    visit(session, server.url(export_page.EXPORT_PAGE_PATH))
    page = session.client.attach(session.client.pages()[0].id)
    try:
        assert page.evaluate(export_page.click_js(export_page.CONFIRM_BUTTON_SELECTOR)) is False
    finally:
        page.close()
