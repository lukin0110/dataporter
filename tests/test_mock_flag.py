"""`--mock` changes the origin, and the tests that say it changes nothing else (`65`).

ADR 0010 gives up ADR 0001's guarantee — that the tool has no setting naming a
mock, so a rehearsal proves the shipped binary byte for byte — and puts a
narrower claim in its place: *the only difference `--mock` makes is the origin*.
A claim like that is a wish unless something checks it, and this file is the
something. Every assertion below is the ADR's sentence in a form that fails.
"""

import re
from dataclasses import fields
from pathlib import Path

import pytest

from dataporter import links, sources, state
from dataporter import verify as verifying
from dataporter.browser import helpers, login_form, sites
from dataporter.browser import probe as probing
from dataporter.browser import session as browser_session
from dataporter.config import (
    MOCK_ACCOUNTS,
    MOCK_STORE,
    MOCK_WORKSPACE,
    ConfigError,
    Settings,
    load_settings,
    with_account,
)
from dataporter.hermes import prompt as prompting
from dataporter.sources import chatgpt as chatgpt_source
from dataporter.sources import claude as claude_source

CHAT_ID = "aa000001-0000-4000-8000-000000000000"


@pytest.fixture
def real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.chdir(tmp_path)
    return load_settings()


@pytest.fixture
def mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.chdir(tmp_path)
    return load_settings(mock=True)


# --------------------------------------------------------------------------- #
# The claim: one field, and the paths that keep a mock's leavings apart
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["claude", "chatgpt"])
def test_a_mock_source_differs_in_the_origin_and_in_nothing_else(name: str) -> None:
    """The whole of ADR 0010's claim, field by field.

    `Source` is `eq=False`, so this compares what it holds rather than asking it.
    A mock source that had quietly changed a selector, a path or
    `fetch_needs_session` would be a different tool under rehearsal, and the
    rehearsal would not be evidence about the one that ships.
    """
    moved = {"origin", "auth_origins"}
    real_source, mock_source = sources.REGISTRY[name], sources.MOCK_REGISTRY[name]
    for field in fields(sources.Source):
        if field.name in moved:
            continue
        assert getattr(real_source, field.name) == getattr(mock_source, field.name), field.name
    assert real_source.origin != mock_source.origin


def test_the_mock_origins_are_the_ports_the_mocks_serve_on() -> None:
    assert sources.MOCK_REGISTRY["claude"].origin == claude_source.MOCK_ORIGIN == "http://127.0.0.1:8443"
    assert sources.MOCK_REGISTRY["chatgpt"].origin == chatgpt_source.MOCK_ORIGIN == "http://127.0.0.1:8444"
    assert sources.MOCK_REGISTRY["chatgpt"].auth_origins == (chatgpt_source.MOCK_AUTH_ORIGIN,)


@pytest.mark.parametrize("name", ["claude", "chatgpt"])
def test_every_wall_is_the_real_one_with_the_origin_swapped(name: str) -> None:
    """The assertion that catches an `https://` left hardcoded in a pattern."""
    real_source, mock_source = sources.REGISTRY[name], sources.MOCK_REGISTRY[name]
    for pattern in (sites.extraction_pattern, sites.login_pattern):
        expected = pattern(real_source).pattern
        for was, now in zip(real_source.origins, mock_source.origins, strict=True):
            expected = expected.replace(re.escape(was), re.escape(now))
        assert pattern(mock_source).pattern == expected


def test_the_settings_a_mock_run_gets_differ_only_where_they_must(real: Settings, mock: Settings) -> None:
    expected = real.model_dump() | {"mock": True, "workspace": Path(MOCK_WORKSPACE).absolute()}
    assert mock.model_dump() == expected
    assert mock.store_dir == Path(MOCK_STORE).expanduser().absolute()
    assert mock.accounts_dir == Path(MOCK_ACCOUNTS).expanduser().absolute()


def test_nothing_a_mock_run_writes_lands_where_a_real_one_would(real: Settings, mock: Settings) -> None:
    """One root, apart from the real one: a mock snapshot is in no real listing."""
    for got, was in ((mock.store_dir, real.store_dir), (mock.accounts_dir, real.accounts_dir)):
        assert was not in got.parents
        assert got != was


# --------------------------------------------------------------------------- #
# Disjoint: neither wall admits the other's origin
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["claude", "chatgpt"])
def test_neither_wall_admits_the_others_origin(name: str) -> None:
    """A run given the wrong flag stops at the wall instead of driving the wrong site."""
    real_source, mock_source = sources.REGISTRY[name], sources.MOCK_REGISTRY[name]
    for wall in (sites.extraction_surface, sites.login_surface):
        real_wall, mock_wall = wall(real_source), wall(mock_source)
        real_url = f"{real_source.origin}{real_source.export_page_path}"
        mock_url = f"{mock_source.origin}{mock_source.export_page_path}"
        assert not mock_wall.permits(real_url)
        assert not real_wall.permits(mock_url)


def test_the_destinations_wall_is_disjoint_too() -> None:
    mock_wall = helpers.destination(claude_source.MOCK_ORIGIN)
    for path in ("/new", f"/chat/{CHAT_ID}"):
        assert helpers.CLAUDE.permits(f"{claude_source.ORIGIN}{path}")
        assert mock_wall.permits(f"{claude_source.MOCK_ORIGIN}{path}")
        assert not helpers.CLAUDE.permits(f"{claude_source.MOCK_ORIGIN}{path}")
        assert not mock_wall.permits(f"{claude_source.ORIGIN}{path}")


def test_a_mock_surface_still_counts_the_sites_selectors() -> None:
    """Without a `Site`, `sketch_of` counts nothing and a mock trace stops being evidence."""
    mock_wall = helpers.destination(claude_source.MOCK_ORIGIN)
    assert mock_wall.site is not None
    assert mock_wall.site.selectors == probing.SELECTORS
    assert mock_wall.site.host == "127.0.0.1"


# --------------------------------------------------------------------------- #
# The branch point, and the one channel the flag has
# --------------------------------------------------------------------------- #


def test_whose_session_moves_with_the_flag_and_says_the_same_words(real: Settings, mock: Settings) -> None:
    was, now = browser_session.whose(real), browser_session.whose(mock)
    assert (was.prompt, was.vendor, was.by_link) == (now.prompt, now.vendor, now.by_link)
    assert was.url == f"{claude_source.ORIGIN}/new"
    assert now.url == f"{claude_source.MOCK_ORIGIN}/new"
    assert now.origins == (claude_source.MOCK_ORIGIN,)


def test_the_flag_is_the_only_door(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Not the environment and not `config.toml` — ADR 0010's one channel (§8).

    A variable is ambient and a file is written for this tool, so one is dropped
    and the other refused; neither may point a run at a stand-in, or away from
    one, without saying so on the command line.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATAPORTER_MOCK", "1")
    assert load_settings().mock is False
    assert load_settings(mock=True).mock is True


def test_a_config_file_may_not_carry_the_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    workspace = tmp_path / "migration"
    workspace.mkdir()
    (workspace / "config.toml").write_text("mock = true\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=re.escape("not in config.toml")):
        load_settings()


# --------------------------------------------------------------------------- #
# The destination half: every door follows the flag
# --------------------------------------------------------------------------- #


def test_every_destination_door_follows_the_flag(real: Settings, mock: Settings) -> None:
    """The silent failure this change can have, asserted away.

    A door left on the module constant keeps driving the real claude.ai inside a
    `--mock` run and says nothing. These are all of them.
    """
    assert probing.destination_origin(real) == claude_source.ORIGIN
    assert probing.destination_origin(mock) == claude_source.MOCK_ORIGIN
    for settings, origin in ((real, claude_source.ORIGIN), (mock, claude_source.MOCK_ORIGIN)):
        assert probing.new_chat_url(probing.destination_origin(settings)) == f"{origin}/new"
        assert helpers.for_settings(settings).origin == origin
        assert browser_session.site_of(settings).host == ("claude.ai" if settings is real else "127.0.0.1")
        assert verifying.chat_url(CHAT_ID, probing.destination_origin(settings)) == f"{origin}/chat/{CHAT_ID}"
        assert login_form.login_url(sources.of(settings).origin) == f"{origin}/login"


def test_what_verify_is_told_to_look_at_follows_the_flag(mock: Settings) -> None:
    """The chat `verify` reloads is on the origin the run drove (`65`).

    A missed origin here is *not* a loud failure: the `Verifier`'s wall is the
    mock's, so an expectation naming the real site is refused as a safety error —
    which the retry table reads as "try again", so the run spends its whole
    backoff budget saying nothing. It cost a rehearsal ten minutes to find.

    `expected_for` is one of the two places an `Expected` is built; `importer`
    builds the other by hand, and the assertion that catches either is the last
    one: the wall a `Verifier` carries must admit the URL it is handed.
    """
    entry = state.ConversationState(
        status=state.Status.COMPLETED,
        chunks_total=1,
        title="t",
        destination=state.Destination(conversation_id=CHAT_ID),
    )
    expected = verifying.expected_for(mock, "u", entry)
    assert expected is not None
    assert expected.origin == claude_source.MOCK_ORIGIN
    assert expected.url == f"{claude_source.MOCK_ORIGIN}/chat/{CHAT_ID}"
    assert helpers.for_settings(mock).permits(expected.url)
    assert not helpers.CLAUDE.permits(expected.url)


def test_every_remedy_a_mock_run_prints_carries_the_flag(real: Settings, mock: Settings) -> None:
    """A remedy is a command a person retypes, and it must not lose `--mock` (`65`).

    The one direction that matters: a mock run telling somebody to run `login`
    without the flag sends them at the real site with the real profile.
    """
    for settings, expected in ((real, "dataporter login"), (mock, "dataporter --mock login")):
        assert browser_session.login_command(settings) == expected
        named = with_account(settings, source="claude", account="eddie")
        assert browser_session.login_command(named) == f"{expected} --source claude --account eddie"
        assert ("--mock" in browser_session.signed_out_line(named)) is named.mock


def test_the_helper_prefix_the_agent_runs_carries_the_flag() -> None:
    """The agent's subprocesses drive the same site the run does (`65`)."""
    assert "--mock" not in prompting.helper_command(Path("/ws"))
    assert "--mock" in prompting.helper_command(Path("/ws"), mock=True)


@pytest.mark.parametrize("name", ["claude", "chatgpt"])
def test_a_mock_link_is_followable_and_a_stray_http_link_is_not(name: str) -> None:
    """`--mock`'s links are plain HTTP, and widening the scheme would be a door."""
    mock_source = sources.MOCK_REGISTRY[name]
    assert links.is_followable(f"{mock_source.origin}/__mock/exports/abc", mock_source.origins)
    assert not links.is_followable("http://evil.example/x", mock_source.origins)
    assert links.is_followable("https://anything.example/x", mock_source.origins)
    assert not links.is_followable(f"{mock_source.origin}/x", sources.REGISTRY[name].origins)
