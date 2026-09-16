"""What every mock's command prints and refuses, tested once."""

import argparse

import pytest
from chatgptmock import IDENTITY as CHATGPT
from claudemock import IDENTITY as CLAUDE
from mockcore import Identity, cli


def test_the_block_names_the_address_and_the_flag() -> None:
    """Two lines since `65`: where the mock is, and how to reach it.

    The resolver rule and the pin are gone with TLS — there is no name to map and
    no key to trust — and so is the proxy note that existed because a proxy would
    have resolved the mapped name itself (ADR 0010).
    """
    block = cli.reachability(CHATGPT, host="127.0.0.1", port=8444)
    assert block == (
        "Mock chatgpt.com listening on http://127.0.0.1:8444\n"
        "\n"
        "Run the tool with --mock to reach it: dataporter --mock login --account <label>\n"
        "\n"
    )
    assert cli.reachability(CLAUDE, host="127.0.0.1", port=8443).startswith(
        "Mock claude.ai listening on http://127.0.0.1:8443"
    )


def test_what_the_host_mapping_needed_is_gone_with_it() -> None:
    for name in ("resolver_rule", "proxy_note", "proxies", "PROXY_ENV", "PROXY_NOTE"):
        assert not hasattr(cli, name)


def test_three_hosts_are_spelled_with_commas() -> None:
    three = Identity(program="x-mock", site="x", hosts=("a", "b", "c"), port=1)
    assert three.spelled_hosts == "a, b and c"
    assert three.heading == "Mock x — ledger"


def test_the_link_note_is_the_golden_string() -> None:
    assert cli.link_note("http://127.0.0.1:8443/__mock/exports/abc") == (
        "Export requested — the link, instead of an email:\n\n  http://127.0.0.1:8443/__mock/exports/abc\n\n"
    )


def test_announce_prints_the_link_note(capsys: pytest.CaptureFixture[str]) -> None:
    cli.announce("https://chatgpt.com/__mock/exports/abc.zip")
    assert capsys.readouterr().out == cli.link_note("https://chatgpt.com/__mock/exports/abc.zip")


def test_the_sign_in_link_note_is_the_golden_string(capsys: pytest.CaptureFixture[str]) -> None:
    """`49`: the same shape as an export's, for the same reader, where an email would arrive."""
    assert cli.sign_in_link_note("https://claude.ai/magic-link#abc:ZQ") == (
        "Sign-in requested — the link, instead of an email:\n\n  https://claude.ai/magic-link#abc:ZQ\n\n"
    )
    cli.announce_sign_in("https://claude.ai/magic-link#abc:ZQ")
    assert capsys.readouterr().out == cli.sign_in_link_note("https://claude.ai/magic-link#abc:ZQ")


def test_a_site_may_add_listing_commands_beside_exports() -> None:
    parser = cli.parser(CLAUDE, description=None, email="e", password="p", listings=(("sign-in-links", "help"),))
    listed = parser.parse_args(["sign-in-links", "--port", "9"])
    assert (listed.command, listed.host, listed.port) == ("sign-in-links", "127.0.0.1", 9)
    assert parser.parse_args(["sign-in-links"]).port == 8443


@pytest.mark.parametrize(
    ("delay", "steps", "reason"),
    [
        (0.0, 2, "a reply delay is more than zero"),
        (1.0, 1, "at least two steps"),
    ],
)
def test_a_reply_that_would_not_be_waited_for_is_refused(
    delay: float, steps: int, reason: str, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = argparse.Namespace(reply_delay_s=delay, reply_steps=steps)
    assert cli.refused_reply(CHATGPT, arguments) == 2
    assert reason in capsys.readouterr().err


def test_a_reply_that_would_be_waited_for_is_not_refused() -> None:
    assert cli.refused_reply(CLAUDE, argparse.Namespace(reply_delay_s=0.5, reply_steps=3)) is None


def test_the_parser_has_the_four_commands_with_the_sites_defaults() -> None:
    parser = cli.parser(CHATGPT, description=None, email="e@example.invalid", password="p")
    serve = parser.parse_args(["serve"])
    assert (serve.command, serve.host, serve.port, serve.email, serve.password) == (
        "serve",
        "127.0.0.1",
        8444,
        "e@example.invalid",
        "p",
    )
    assert (serve.reply_delay_s, serve.reply_steps, serve.cert_dir) == (1.0, 2, None)
    assert parser.parse_args(["ledger"]).port == 8444
    assert parser.parse_args(["exports", "--port", "9"]).port == 9
    assert parser.parse_args(["rows"]).command == "rows"
    assert parser.prog == "chatgpt-mock"


def test_a_bare_command_is_usage_not_a_crash(capsys: pytest.CaptureFixture[str]) -> None:
    """No subcommand is a usage error, exit `2` — never `serve` with nothing parsed."""
    parser = cli.parser(CLAUDE, description=None, email="e@example.invalid", password="p")
    with pytest.raises(SystemExit) as caught:
        parser.parse_args([])
    assert caught.value.code == 2
    assert "usage: claude-mock" in capsys.readouterr().err


def test_a_mock_nobody_is_serving_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.ledger(CHATGPT, host="127.0.0.1", port=1) == 1
    assert capsys.readouterr().err.startswith("chatgpt-mock: http://127.0.0.1:1/__mock/ledger:")
    assert cli.exports(CHATGPT, host="127.0.0.1", port=1) == 1
    assert capsys.readouterr().err.startswith("chatgpt-mock: http://127.0.0.1:1/__mock/exports:")


def test_rows_prints_the_title_and_each_citation(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.rows(CHATGPT, ["a row"], {"a row": "what the mock did"}) == 0
    assert (
        capsys.readouterr().out
        == "Mock chatgpt.com — the UI map rows it is built out of\n\na row\n  what the mock did\n\n"
    )
