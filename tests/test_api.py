"""`68`: the facade is settings plumbing, and the operations do the work.

Three claims, and a test for each kind.

*Equality*: a facade method produces the outcome and the bytes the operation
produces when it is handed the settings the command line would have layered. The
operations are already proved equal to the CLI in `test_operations.py`, so this
file compares against the operations rather than running every command twice
more.

*Shape*: no method of `Dataporter` contains a loop, a branch, a lock or a
`try`, which is `23`'s own test for `cli.py` pointed at the second interface.
That is what keeps a facade from growing logic the CLI does not run, which is
the specific way a second API surface starts disagreeing with the first.

*Construction*: the settings a `Dataporter` resolves are the settings the flags
resolve — the mock's workspace above all, because getting that wrong puts a
rehearsal's state where a real run reads it.
"""

import ast
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

import dataporter
from dataporter import Dataporter, api, console, sources
from dataporter import extract as extracting
from dataporter import extract_skills as skills_extracting
from dataporter.browser import session as browser_session
from dataporter.config import (
    MOCK_WORKSPACE,
    BrowserSettings,
    ConfigError,
    Settings,
    TimeoutSettings,
    load_settings,
    with_account,
    with_store_dir,
)
from dataporter.errors import UsageError
from dataporter.exit_codes import ExitCode
from dataporter.hermes import doctor as hermes_doctor
from dataporter.sources.claude import CLAUDE
from fake_export_page import FakeExportPage, browser
from fake_skills_page import FakeSkillsPage, entry
from fake_skills_page import browser as skills_browser
from test_extract import BROWSERLESS, LINK, opener
from test_operations import blanked, fake_launch, without_account, without_seconds

LOGIC = (ast.For, ast.While, ast.Try, ast.With, ast.If, ast.AsyncFor, ast.AsyncWith)

OPERATIONS = (
    "login",
    "spend_link",
    "logout",
    "ask",
    "fetch",
    "file",
    "abandon",
    "extract_skills",
    "doctor",
)
"""The five commands as methods. `extract`'s four modes are four of them (`68`)."""


# --------------------------------------------------------------------------- #
# Shape
# --------------------------------------------------------------------------- #


def methods(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    """Every method defined on `Dataporter`, by name."""
    found: dict[str, ast.FunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Dataporter":
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    found[item.name] = item
    return found


def test_every_operation_is_plumbing() -> None:
    """`68`'s acceptance criterion: a method layers settings and makes one call.

    `__init__` and `from_config` are excluded because choosing between a handed
    `Settings` and built one is the branch they exist to make.
    """
    tree = ast.parse(Path(api.__file__).read_text(encoding="utf-8"))
    found = methods(tree)
    assert set(found) >= set(OPERATIONS)
    offenders = [
        f"{name}:{node.lineno}" for name in OPERATIONS for node in ast.walk(found[name]) if isinstance(node, LOGIC)
    ]
    assert offenders == []


def test_every_operation_returns_the_operations_own_outcome() -> None:
    """No second set of result types: the annotations name the modules that own them."""
    tree = ast.parse(Path(api.__file__).read_text(encoding="utf-8"))
    found = methods(tree)
    returns = {name: ast.unparse(found[name].returns) for name in OPERATIONS if found[name].returns is not None}
    assert returns == {
        "login": "browser_session.LoginOutcome",
        "spend_link": "browser_session.LoginOutcome",
        "logout": "browser_session.LogoutOutcome",
        "ask": "extracting.ExtractOutcome",
        "fetch": "extracting.ExtractOutcome",
        "file": "extracting.ExtractOutcome",
        "abandon": "extracting.ExtractOutcome",
        "extract_skills": "skills_extracting.SkillsOutcome",
        "doctor": "hermes_doctor.DoctorOutcome",
    }


def test_the_facade_is_the_one_name_the_package_exports() -> None:
    """`Dataporter` is reachable from the top, and nothing else was added beside it."""
    assert dataporter.Dataporter is api.Dataporter
    assert set(dataporter.__all__) == {"PROGRAM_NAME", "Dataporter", "__version__"}


def test_the_hook_refuses_every_other_name() -> None:
    """Why `from dataporter import console` still works.

    `from package import name` asks for the attribute before it tries the
    submodule, so a hook that answered for `console` would shadow the module. It
    refuses, and the import machinery falls through.
    """
    hook = vars(dataporter)["__getattr__"]
    with pytest.raises(AttributeError, match="no attribute 'nonesuch'"):
        hook("nonesuch")
    with pytest.raises(AttributeError):
        hook("console")
    assert dataporter.console is console


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #


def test_it_reads_no_config_file(workspace: Path) -> None:
    """`68`: a `config.toml` in the working directory configures the CLI, not a caller.

    The same file, through both doors: `from_config` obeys it and the
    constructor does not.
    """
    (workspace / "migration").mkdir()
    (workspace / "migration" / "config.toml").write_text("[browser]\ncdp_port = 9333\n", encoding="utf-8")

    assert Dataporter().settings.browser.cdp_port == 9222
    assert Dataporter.from_config().settings.browser.cdp_port == 9333


def test_the_environment_still_fills_in_what_nobody_named(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Init outranks the environment; the environment outranks the defaults."""
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", "9444")
    assert Dataporter().settings.browser.cdp_port == 9444
    assert Dataporter(workspace=workspace / "named").settings.workspace == workspace / "named"


def test_mock_moves_the_workspace_as_the_flag_does(workspace: Path) -> None:
    """ADR 0010: a rehearsal never writes where a real run reads.

    `load_settings` moved the default with the flag; a facade that built
    `Settings` itself and forgot would put `--mock` state in `./migration`.
    """
    assert Dataporter(mock=True).settings.workspace == workspace / MOCK_WORKSPACE
    assert Dataporter(mock=True).settings.mock
    assert Dataporter(mock=True, workspace=workspace / "named").settings.workspace == workspace / "named"
    assert Dataporter().settings.workspace == workspace / "migration"


def test_a_store_and_a_source_are_carried(workspace: Path) -> None:
    dp = Dataporter(store=workspace / "snapshots", source="chatgpt")
    assert dp.settings.store_dir == workspace / "snapshots"
    assert dp.settings.source == "chatgpt"


def test_a_source_that_does_not_exist_is_refused_where_it_is_named(workspace: Path) -> None:
    """`68`'s "the source is checked in the constructor": the traceback points at the typo."""
    with pytest.raises(ConfigError, match="no such source: claude-ai"):
        Dataporter(source="claude-ai")


def test_a_label_that_could_not_be_a_directory_is_refused_at_the_call(workspace: Path) -> None:
    with pytest.raises(ConfigError, match="account label must be"):
        Dataporter().logout("../escape")


def test_settings_is_the_whole_configuration(workspace: Path) -> None:
    """`settings=` is refused beside a value, rather than one of them winning quietly."""
    built = load_settings()
    assert Dataporter(settings=built).settings is built
    with pytest.raises(UsageError, match="pass it alone"):
        Dataporter(settings=built, workspace=workspace / "named")
    with pytest.raises(UsageError, match="pass it alone"):
        Dataporter(settings=built, mock=True)


def test_from_config_takes_the_store_and_the_source_too(workspace: Path) -> None:
    dp = Dataporter.from_config(store=workspace / "snapshots", source="chatgpt")
    assert (dp.settings.store_dir, dp.settings.source) == (workspace / "snapshots", "chatgpt")


def test_one_facade_serves_many_accounts(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each call derives its own settings; the facade's own are never mutated."""
    monkeypatch.setenv("DATAPORTER_ACCOUNTS__DIR", str(workspace / "accounts"))
    dp = Dataporter()
    dp.logout("one")
    dp.logout("two")
    assert dp.settings.account is None


def test_non_interactive_reaches_the_settings(workspace: Path) -> None:
    """`24`'s mode is a constructor value; `24`'s credentials are not (`68`, *Out of scope*)."""
    assert Dataporter(non_interactive=True).settings.non_interactive
    assert not Dataporter().settings.non_interactive


def test_a_value_no_settings_would_accept_is_a_config_error(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The same words `load_settings` uses, for the same failure.

    Both of the ways a value can be refused: one the model rejects, and one
    pydantic-settings cannot parse into the field at all.
    """
    monkeypatch.setenv("DATAPORTER_BROWSER__CDP_PORT", "nope")
    with pytest.raises(ConfigError, match=r"invalid configuration: browser\.cdp_port"):
        Dataporter()

    monkeypatch.delenv("DATAPORTER_BROWSER__CDP_PORT")
    monkeypatch.setenv("DATAPORTER_BROWSER__EXTRA_ARGS", "[not json")
    with pytest.raises(ConfigError, match="invalid configuration: error parsing value"):
        Dataporter()


# --------------------------------------------------------------------------- #
# Delegation
#
# The three commands that cannot be run twice and compared — `login` waits for a
# person, `spend_link` for another process, `doctor` for a Hermes subprocess —
# and `fetch`, which wants a vendor's link. What the facade is answerable for is
# the settings it layers and the arguments it forwards, and that is what these
# assert: the operation stands in for itself and says what it was handed.
# --------------------------------------------------------------------------- #


def recorder(seen: dict[str, Any], outcome: object) -> Callable[..., object]:
    """Stand where an operation stands, remember what it was handed, return `outcome`."""

    def call(settings: Settings, *args: Any, **kwargs: Any) -> object:
        seen["settings"] = settings
        seen["args"] = args
        seen["kwargs"] = kwargs
        return outcome

    return call


def test_login_means_the_destination_unless_a_label_says_otherwise(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§86: absent `--account` is the one place that still means the destination."""
    seen: dict[str, Any] = {}
    expected = browser_session.LoginOutcome()
    monkeypatch.setattr(browser_session, "login", recorder(seen, expected))

    assert Dataporter().login() is expected
    assert seen["settings"].account is None
    assert "link" not in seen["kwargs"]

    Dataporter().login("work", source="chatgpt")
    assert (seen["settings"].account, seen["settings"].source) == ("work", "chatgpt")


def test_spend_link_is_the_same_operation_carrying_the_link(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`53`: the second terminal's command, which is the first one's function plus a link."""
    seen: dict[str, Any] = {}
    expected = browser_session.LoginOutcome()
    monkeypatch.setattr(browser_session, "login", recorder(seen, expected))

    assert Dataporter().spend_link("https://claude.ai/magic#token") is expected
    assert seen["kwargs"]["link"] == "https://claude.ai/magic#token"
    assert seen["settings"].account is None


def test_fetch_forwards_the_link_and_the_quiet(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    expected = extracting.ExtractOutcome()
    monkeypatch.setattr(extracting, "fetch", recorder(seen, expected))

    assert Dataporter(store=workspace / "s").fetch("work", "https://x/y", quiet=True) is expected
    assert seen["args"] == ("https://x/y",)
    assert seen["kwargs"]["quiet"]
    assert (seen["settings"].account, seen["settings"].store_dir) == ("work", workspace / "s")


def test_doctor_is_about_the_environment_and_takes_no_label(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    expected = hermes_doctor.DoctorOutcome(checks=(), exit_code=ExitCode.OK)
    monkeypatch.setattr(hermes_doctor, "run_doctor", recorder(seen, expected))

    assert Dataporter(workspace=workspace / "w").doctor() is expected
    assert seen["settings"].account is None
    assert seen["settings"].workspace == workspace / "w"


def test_no_operation_is_told_which_flags_were_typed(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`68`: nobody typed any, so a trace's header records none."""
    seen: dict[str, Any] = {}
    monkeypatch.setattr(browser_session, "login", recorder(seen, browser_session.LoginOutcome()))
    Dataporter().login()
    assert seen["kwargs"].get("flags", ()) == ()


# --------------------------------------------------------------------------- #
# Equality with the operations
# --------------------------------------------------------------------------- #


def accounts_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATAPORTER_ACCOUNTS__DIR", str(tmp_path / "accounts"))


def test_logout_is_the_operation(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    accounts_at(workspace, monkeypatch)
    home = with_account(load_settings(), "claude", "a").account_home
    assert home is not None

    (home / "browser-profile").mkdir(parents=True)
    through_facade = console.Collected()
    facade = Dataporter().logout("a", sink=through_facade)

    (home / "browser-profile").mkdir(parents=True)
    direct = console.Collected()
    operation = browser_session.logout(with_account(load_settings(), "claude", "a"), sink=direct)

    assert (facade.removed, facade.exit_code) == (operation.removed, operation.exit_code)
    assert through_facade.stdout == direct.stdout
    assert facade.removed


def test_file_is_the_operation(workspace: Path, export_zip: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`extract --from`, through both doors, into two stores a moment apart."""
    accounts_at(workspace, monkeypatch)
    through_facade = console.Collected()
    facade = Dataporter(store=workspace / "store-library").file("a", export_zip, sink=through_facade)

    direct = console.Collected()
    operation = extracting.file(
        with_account(with_store_dir(load_settings(), workspace / "store-cli"), "claude", "a"),
        export_zip,
        sink=direct,
    )

    assert facade.exit_code == operation.exit_code
    assert blanked(through_facade.stdout, workspace) == blanked(direct.stdout, workspace)
    assert facade.snapshot is not None


def test_fetch_is_the_operation(workspace: Path, export_zip: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The sixth of the byte-equality set, through the seam both sides share.

    `fetch`'s opener and clock are injectable and the facade does not expose
    either — they are `30`'s test seams, not part of the surface `68` offers. So
    the seam is filled once, here, and both the facade's call and the operation's
    own go through the same filling: what is being compared is still the settings
    the facade layered and the bytes they produce.

    Claude's own fetch goes through the source session, so the registry is
    pointed at `test_extract`'s browserless source for the length of the test,
    which is the same thing that module does for the same reason.
    """
    monkeypatch.setattr(sources, "REGISTRY", MappingProxyType({**sources.REGISTRY, CLAUDE.name: BROWSERLESS}))
    accounts_at(workspace, monkeypatch)
    body = export_zip.read_bytes()
    real = extracting.fetch

    def through_the_seam(settings: Settings, link: str, **kwargs: Any) -> extracting.ExtractOutcome:
        return real(settings, link, open_url=opener(body), clock=iter((0.0, 66.4)).__next__, **kwargs)

    monkeypatch.setattr(extracting, "fetch", through_the_seam)
    collected = console.Collected()
    facade = Dataporter(store=workspace / "store-library").fetch("a", LINK, sink=collected)

    direct = console.Collected()
    operation = through_the_seam(
        with_account(with_store_dir(load_settings(), workspace / "store-cli"), "claude", "a"),
        LINK,
        sink=direct,
    )

    assert facade.exit_code == operation.exit_code
    assert blanked(collected.stdout, workspace) == blanked(direct.stdout, workspace)
    assert facade.snapshot is not None
    # §32, through the new door as through the old: the link is never written down.
    assert LINK not in collected.stdout + collected.stderr


def test_abandon_is_the_operation(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    accounts_at(workspace, monkeypatch)
    settings = with_account(load_settings(), "claude", "a")

    extracting.write_ask(settings, datetime.now(UTC))
    through_facade = console.Collected()
    facade = Dataporter().abandon("a", sink=through_facade)

    extracting.write_ask(settings, datetime.now(UTC))
    direct = console.Collected()
    operation = extracting.abandon(settings, sink=direct)

    assert (facade.exit_code, through_facade.stdout) == (operation.exit_code, direct.stdout)


def test_the_four_extract_modes_are_four_methods() -> None:
    """`68`'s "four methods for `extract`": what `ExtractRequest` refuses is unspellable here."""
    assert not hasattr(Dataporter, "extract")
    for name in ("ask", "fetch", "file", "abandon"):
        assert callable(getattr(Dataporter, name))


def has_a_session(*accounts: str) -> None:
    """Give each account the profile a signed-in operator would have left (`69`).

    The fake browser these tests put on the port stands in for one already
    running, and a browser on the port means a profile on disk. Without it the
    preflight refuses before either door is reached, which is the check working
    rather than failing.
    """
    for name in accounts:
        with_account(load_settings(), "claude", name).browser_profile_dir.mkdir(parents=True, exist_ok=True)


@pytest.mark.slow
def test_the_ask_is_the_operation(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`31`'s ask, through both doors: two browsers, because an ask closes its own."""
    accounts_at(workspace, monkeypatch)
    has_a_session("library", "cli")
    page = FakeExportPage()
    with browser(page) as chrome:
        fake_launch(monkeypatch, chrome.port)
        through_facade = console.Collected()
        facade = Dataporter(settings=pointed_at(chrome.port)).ask("library", sink=through_facade)

    page = FakeExportPage()
    with browser(page, port=chrome.port) as second:
        fake_launch(monkeypatch, second.port)
        direct = console.Collected()
        operation = extracting.ask(with_account(pointed_at(second.port), "claude", "cli"), sink=direct)

    assert facade.exit_code == operation.exit_code
    assert without_account(through_facade.stdout, "library") == without_account(direct.stdout, "cli")


@pytest.mark.slow
def test_extract_skills_is_the_operation(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`66`, through both doors: two browsers and two stores, as the CLI's twin needs."""
    accounts_at(workspace, monkeypatch)
    has_a_session("library", "cli")
    bodies = {"skill_01a": b"PK\x03\x04 one"}
    page = FakeSkillsPage(entries=[entry("skill_01a", "research-helper")], bodies=bodies)
    with skills_browser(page) as chrome:
        fake_launch(monkeypatch, chrome.port)
        through_facade = console.Collected()
        facade = Dataporter(
            settings=with_store_dir(pointed_at(chrome.port), workspace / "store-library")
        ).extract_skills("library", sink=through_facade)

    page = FakeSkillsPage(entries=[entry("skill_01a", "research-helper")], bodies=bodies)
    with skills_browser(page, port=chrome.port) as second:
        fake_launch(monkeypatch, second.port)
        direct = console.Collected()
        operation = skills_extracting.extract_skills_command(
            with_account(with_store_dir(pointed_at(second.port), workspace / "store-cli"), "claude", "cli"),
            skills_extracting.SkillsRequest(),
            sink=direct,
        )

    assert (facade.exit_code, facade.skills) == (operation.exit_code, operation.skills)
    assert normalised(through_facade.stdout, workspace, "library") == normalised(direct.stdout, workspace, "cli")
    assert facade.skills == 1


@pytest.mark.slow
def test_a_stamp_files_the_skills_beside_an_archive(
    workspace: Path, export_zip: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§89's `--stamp`, as a keyword: one moment of an account is one directory."""
    accounts_at(workspace, monkeypatch)
    has_a_session("a")
    dp = Dataporter(store=workspace / "store")
    filed = dp.file("a", export_zip)
    assert filed.snapshot is not None

    page = FakeSkillsPage(entries=[entry("skill_01a", "research-helper")], bodies={"skill_01a": b"PK\x03\x04 one"})
    with skills_browser(page) as chrome:
        fake_launch(monkeypatch, chrome.port)
        outcome = Dataporter(settings=with_store_dir(pointed_at(chrome.port), workspace / "store")).extract_skills(
            "a", stamp=filed.snapshot.stamp
        )

    assert outcome.snapshot is not None
    assert outcome.snapshot.stamp == filed.snapshot.stamp
    assert outcome.path is not None
    assert outcome.path.parent == filed.path


def test_nothing_prints_unless_a_sink_is_given(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`23`'s rule, kept: the default is `DISCARD`, not `Terminal`."""
    accounts_at(workspace, monkeypatch)
    outcome = Dataporter().logout("a")
    assert outcome.exit_code == ExitCode.OK
    assert not capsys.readouterr().out


def pointed_at(port: int) -> Settings:
    """One invocation aimed at a fake browser, with the ask's timeouts shortened."""
    return load_settings().model_copy(
        update={
            "browser": BrowserSettings(cdp_port=port),
            "timeouts": TimeoutSettings(cdp_call_s=2.0, ask_s=0.3, login_s=0.1),
        }
    )


def normalised(text: str, tmp_path: Path, account: str) -> str:
    """Return a skills block with the moment, the store and the label taken out."""
    return re.sub(r"\d+ skills?", "<n> skills", without_seconds(blanked(without_account(text, account), tmp_path)))
