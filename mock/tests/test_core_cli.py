"""What every mock's command prints and refuses, tested once."""

import argparse

import pytest
from chatgptmock import IDENTITY as CHATGPT
from claudemock import IDENTITY as CLAUDE
from mockcore import Identity, cli


def test_the_resolver_rule_sends_every_host_to_the_mock() -> None:
    """§54: one rule, both names — Chrome keeps one value per argument."""
    assert cli.resolver_rule(CLAUDE, host="127.0.0.1", port=8443) == "MAP claude.ai 127.0.0.1:8443"
    assert (
        cli.resolver_rule(CHATGPT, host="127.0.0.1", port=8444)
        == "MAP chatgpt.com 127.0.0.1:8444, MAP auth.openai.com 127.0.0.1:8444"
    )


def test_the_block_names_the_site_and_ends_in_a_blank_line() -> None:
    block = cli.reachability(CHATGPT, host="127.0.0.1", port=8444, flag="--ignore-certificate-errors-spki-list=PIN")
    assert block.startswith("Mock chatgpt.com listening on https://127.0.0.1:8444\n\n")
    assert block.endswith("]\n\n")
    assert "--ignore-certificate-errors=" not in block


def test_the_proxy_note_spells_the_hosts() -> None:
    assert cli.proxy_note(CLAUDE, ["https_proxy"]) == (
        "This machine has a proxy in its environment (https_proxy), which Chrome reads and\n"
        "which would resolve claude.ai itself. Add to the same list:\n"
        "\n"
        '  "--no-proxy-server",\n'
        "\n"
    )
    assert "which would resolve chatgpt.com and auth.openai.com itself." in cli.proxy_note(
        CHATGPT, ["https_proxy", "HTTP_PROXY"]
    )
    assert cli.proxy_note(CHATGPT, ["https_proxy", "HTTP_PROXY"]).startswith(
        "This machine has a proxy in its environment (https_proxy, HTTP_PROXY)"
    )


def test_three_hosts_are_spelled_with_commas() -> None:
    three = Identity(program="x-mock", site="x", hosts=("a", "b", "c"), port=1)
    assert three.spelled_hosts == "a, b and c"
    assert three.heading == "Mock x — ledger"


def test_proxies_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in cli.PROXY_ENV:
        monkeypatch.delenv(name, raising=False)
    assert cli.proxies() == []
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    assert cli.proxies() == ["HTTPS_PROXY"]


def test_the_link_note_is_the_golden_string() -> None:
    assert cli.link_note("https://127.0.0.1:8443/__mock/exports/abc.zip") == (
        "Export requested — the link, instead of an email:\n\n  https://127.0.0.1:8443/__mock/exports/abc.zip\n\n"
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
    assert capsys.readouterr().err.startswith("chatgpt-mock: https://127.0.0.1:1/__mock/ledger:")
    assert cli.exports(CHATGPT, host="127.0.0.1", port=1) == 1
    assert capsys.readouterr().err.startswith("chatgpt-mock: https://127.0.0.1:1/__mock/exports:")


def test_rows_prints_the_title_and_each_citation(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.rows(CHATGPT, ["a row"], {"a row": "what the mock did"}) == 0
    assert (
        capsys.readouterr().out
        == "Mock chatgpt.com — the UI map rows it is built out of\n\na row\n  what the mock did\n\n"
    )
