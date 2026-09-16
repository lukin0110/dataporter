"""A second signed-in session, kept apart from the destination's (`31`, §35).

`login`, `session status` and `logout` are `07`'s three commands, and this slice
adds one thing to each: a label. What the tests below are really about is that the
label changes exactly one thing — where the browser profile is. Its *absence* used to
change nothing at all (§35); brief 08 §86 ends that for two of the three, and `login`
is the one left where absence still means the destination.

The last two are the other half of §36: the source session never imports, and
nothing on the migration surface can reach the export page. Both are read off
the code rather than exercised, because "there is no path" is a claim about
every path and not about the one a test would take.
"""

import ast
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataporter import cli
from dataporter.browser import export_page, helpers, launcher, probe
from dataporter.config import AccountsSettings, BrowserSettings, Settings, TimeoutSettings, with_account
from dataporter.exit_codes import ExitCode
from fake_chrome import FakeChrome, FakeTarget, free_port, page_state

pytestmark = pytest.mark.slow
"""Slow all the way through: a fake Chrome per test, binding two ports."""

ACCOUNT = "old-personal"


def make_settings(tmp_path: Path, port: int) -> Settings:
    return Settings(
        workspace=tmp_path / "migration",
        browser=BrowserSettings(executable=Path(sys.executable), cdp_port=port),
        timeouts=TimeoutSettings(cdp_call_s=2.0),
    )


@pytest.fixture
def chrome() -> Iterator[FakeChrome]:
    with FakeChrome(targets=[FakeTarget(id="page-1", url="https://claude.ai/new", evaluate=page_state())]) as fake:
        yield fake


def account_env(chrome: FakeChrome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Return a source account whose profile carries a marker for this fake browser.

    `07`'s `adoptable`, one directory further down: `launch` adopts rather than
    starting anything, so the command tests exercise the real path — `adopt`,
    `probe`, `close` — with no Chrome anywhere.
    """
    settings = make_settings(tmp_path, chrome.port)
    monkeypatch.setenv("DATAPORTER_WORKSPACE", str(settings.workspace))
    monkeypatch.setenv("DATAPORTER_ACCOUNTS__DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", str(chrome.port))
    monkeypatch.setenv("DATAPORTER_TIMEOUTS__CDP_CALL_S", "2")
    return settings


def source_settings(tmp_path: Path, port: int, account: str = ACCOUNT) -> Settings:
    """Return the same settings a `--account` invocation resolves to."""
    settings = make_settings(tmp_path, port).model_copy(
        update={"accounts": AccountsSettings(dir=tmp_path / "accounts")}
    )
    return with_account(settings, "claude", account)


def adopt_for(settings: Settings, chrome: FakeChrome) -> Path:
    profile = launcher.ensure_profile(settings)
    launcher.write_marker(
        profile,
        launcher.ProfileMarker(port=chrome.port, browser_id=chrome.browser_id, pid=1, started="now"),
    )
    return profile


# --------------------------------------------------------------------------- #
# Where the source profile lives
# --------------------------------------------------------------------------- #


def test_the_source_profile_is_in_the_account_home(tmp_path: Path) -> None:
    source = source_settings(tmp_path, free_port())

    assert source.browser_profile_dir == (tmp_path / "accounts" / "claude" / ACCOUNT / "browser-profile")
    assert make_settings(tmp_path, 0).browser_profile_dir == (tmp_path / "migration" / "browser-profile")


def test_login_with_an_account_never_touches_the_destination_profile(
    runner: CliRunner,
    chrome: FakeChrome,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = account_env(chrome, tmp_path, monkeypatch)
    source = source_settings(tmp_path, chrome.port)
    adopt_for(source, chrome)

    result = runner.invoke(cli.app, ["login", "--account", ACCOUNT], catch_exceptions=False)

    assert result.exit_code == ExitCode.OK
    assert result.stdout == (f"Signed in to Claude — {ACCOUNT}\nSession stored in {source.browser_profile_dir}/.\n")
    assert source.browser_profile_dir.exists()
    assert not destination.browser_profile_dir.exists()


def test_a_signed_out_source_account_names_its_own_login(
    runner: CliRunner,
    chrome: FakeChrome,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`52`: the remedy carries the flags, or it signs in the wrong profile."""
    account_env(chrome, tmp_path, monkeypatch)
    source = source_settings(tmp_path, chrome.port)
    adopt_for(source, chrome)
    chrome.targets[0].evaluate = page_state(url="https://claude.ai/login", composer_present=False)

    result = runner.invoke(cli.app, ["session", "status", "--account", ACCOUNT], catch_exceptions=False)

    assert result.exit_code == ExitCode.NOT_AUTHENTICATED
    assert result.stdout == f"not logged in — run: dataporter login --source claude --account {ACCOUNT}\n"


def test_a_source_profile_writes_no_gitignore_into_a_workspace(
    tmp_path: Path,
) -> None:
    """`07` writes one because the destination's profile is inside the operator's own directory.

    An account home is under `~/.dataporter/accounts`, which is nobody's checkout.
    """
    source = source_settings(tmp_path, free_port())
    launcher.ensure_profile(source)

    assert not (source.workspace / ".gitignore").exists()
    assert (source.browser_profile_dir).exists()


def test_session_status_and_sign_out_act_on_the_account(
    runner: CliRunner,
    chrome: FakeChrome,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_env(chrome, tmp_path, monkeypatch)
    source = source_settings(tmp_path, chrome.port)
    adopt_for(source, chrome)

    status = runner.invoke(
        cli.app,
        ["session", "status", "--source", "claude", "--account", ACCOUNT],
        catch_exceptions=False,
    )
    assert status.exit_code == ExitCode.OK
    assert status.stdout == "logged in\n"

    chrome.stop_http()
    logout = runner.invoke(cli.app, ["logout", "--account", ACCOUNT], catch_exceptions=False)
    assert logout.exit_code == ExitCode.OK
    assert logout.stdout == (f"Signed out of Claude — {ACCOUNT}\nRemoved {source.account_home}/, except its logs.\n")
    assert not source.browser_profile_dir.exists()


@pytest.mark.parametrize("command", [["session", "status"], ["logout"]])
def test_the_session_commands_name_an_account(
    runner: CliRunner, command: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§86 ends §35's "absent means the destination" for both of them.

    The refusal is click's own and arrives before anything is resolved, which is why
    neither needs a message of its own.
    """
    settings = make_settings(tmp_path, free_port())
    monkeypatch.setenv("DATAPORTER_WORKSPACE", str(settings.workspace))
    monkeypatch.setenv("DATAPORTER_ACCOUNTS__DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", str(settings.browser.cdp_port))

    result = runner.invoke(cli.app, command, catch_exceptions=False)

    assert result.exit_code == ExitCode.USAGE
    assert "Missing option '--account'" in result.stderr


def test_a_source_without_a_label_is_refused(
    runner: CliRunner, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A flag accepted and quietly dropped is what `12` ruled out for `--pilot`.

    `login` is the one command still able to reach this: the other two require a label
    of their own (§86), so click refuses them first.
    """
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", str(free_port()))
    result = runner.invoke(cli.app, ["login", "--source", "claude"], catch_exceptions=False)

    assert result.exit_code == ExitCode.USAGE
    assert result.stderr == ("error: --source names the vendor of an account; give --account LABEL\n")


def test_a_label_that_is_not_one_is_refused(
    runner: CliRunner, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", str(free_port()))
    result = runner.invoke(cli.app, ["login", "--account", "../elsewhere"], catch_exceptions=False)

    assert result.exit_code == ExitCode.USAGE
    assert result.stderr.startswith("error: account label must be")


def test_a_destination_browser_on_the_port_refuses_a_source_login(
    runner: CliRunner,
    chrome: FakeChrome,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One port, sequential sessions (`31`).

    The destination's Chrome is still on it, so the source's `login` is `PortInUseError` and
    the existing message.
    """
    destination = account_env(chrome, tmp_path, monkeypatch)
    adopt_for(destination, chrome)

    result = runner.invoke(cli.app, ["login", "--account", ACCOUNT], catch_exceptions=False)

    assert result.exit_code == ExitCode.USAGE
    assert result.stderr == f"error: port {chrome.port} is used by another browser\n"


def test_the_run_log_of_a_source_command_is_in_the_account_home(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    account_env(FakeChromeless(), tmp_path, monkeypatch)
    source = source_settings(tmp_path, free_port())
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", str(source.browser.cdp_port))
    launcher.ensure_profile(source)

    result = runner.invoke(
        cli.app,
        ["-v", "logout", "--account", ACCOUNT],
        catch_exceptions=False,
    )

    assert result.exit_code == ExitCode.OK
    assert (source.account_home or tmp_path).joinpath("logs").exists()
    assert not (source.workspace / "logs").exists()


class FakeChromeless:
    """A stand-in for the `chrome` fixture where no browser is wanted at all.

    `account_env` reads two attributes off it and nothing else; a test about
    where a *file* lands should not pay for two sockets.
    """

    port = 0
    browser_id = "none"


# --------------------------------------------------------------------------- #
# §36: the two sessions cannot reach each other's pages
# --------------------------------------------------------------------------- #

TAKES_AN_ACCOUNT = "with_session_account"
"""The call that points a command at a source account it may or may not have been
given. `with_account` is the other, and since §86 it is the one three commands make:
`extract`, `session status` and `logout` all require a label. `login` is the only
caller of this one left."""


def command_body(name: str) -> ast.FunctionDef:
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"no command named {name} in cli.py")


@pytest.mark.parametrize("command", ["import_cmd", "resume", "verify", "followup"])
def test_the_migration_commands_never_take_an_account(command: str) -> None:
    """§36, checkable by reading: the source session never imports.

    A migration command that could be pointed at an account would put the
    importer behind a source account's composer — the one thing this brief
    promises cannot happen — and it would do it by calling one of two functions,
    which is what this looks for.
    """
    called = {
        node.func.id
        for node in ast.walk(command_body(command))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert called & {TAKES_AN_ACCOUNT, "with_account"} == set()


def test_the_session_commands_are_the_only_ones_that_take_an_account() -> None:
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    takes = {
        function.name
        for function in ast.walk(tree)
        if isinstance(function, ast.FunctionDef)
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {TAKES_AN_ACCOUNT, "with_account"}
    }

    assert takes == {"login", "session_status", "logout", "extract"}


def test_neither_surface_admits_the_other_s_pages() -> None:
    """The two walls, held to each other in one place (§36)."""
    assert not helpers.CLAUDE.permits(export_page.EXPORT_PAGE_URL)
    assert not export_page.EXTRACTION_SURFACE.permits(probe.NEW_CHAT_URL)
