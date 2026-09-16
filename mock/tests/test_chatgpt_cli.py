"""The block the mock chatgpt.com prints, and the two commands that ask it questions."""

import json

import pytest
from chatgptmock import AUTH_ORIGIN, AUTH_PORT, DEFAULT_PORT, SITE_ORIGIN, cli, server
from chatgptmock.site import Site
from mockcore import wire
from test_chatgpt_server import sign_in

from conftest import Client


def test_the_reachability_block_names_the_address_and_the_flag() -> None:
    """`39`'s golden string, as `65` leaves it.

    §54 said the lines send both host names to the mock and trust its key. There
    is no rule and no key now: the mock is two plain-HTTP sockets and the tool is
    told by `--mock` (ADR 0010). Only the site's is printed — the second stands in
    for the auth host, and a sign-in reaches it by a redirect and nothing else.
    """
    assert cli.reachability(host="127.0.0.1", port=8444) == (
        "Mock chatgpt.com listening on http://127.0.0.1:8444\n"
        "\n"
        "Run the tool with --mock to reach it: dataporter --mock login --account <label>\n"
        "\n"
    )


def test_the_two_origins_are_two_ports() -> None:
    """The second socket is what the resolver rule's second name used to be."""
    assert AUTH_PORT == DEFAULT_PORT + 1
    assert SITE_ORIGIN == "http://127.0.0.1:8444"
    assert AUTH_ORIGIN == "http://127.0.0.1:8445"
    assert SITE_ORIGIN != AUTH_ORIGIN


@pytest.mark.parametrize(
    ("argv", "reason"),
    [
        (["serve", "--reply-delay-s", "0"], "a reply delay is more than zero"),
        (["serve", "--reply-steps", "1"], "at least two steps"),
    ],
)
def test_a_reply_that_would_not_be_waited_for_is_refused(
    argv: list[str], reason: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(argv) == 2
    assert reason in capsys.readouterr().err


def test_the_defaults_are_the_sites(capsys: pytest.CaptureFixture[str]) -> None:
    arguments = cli.parser().parse_args(["serve"])
    assert (arguments.port, arguments.email, arguments.password) == (
        8444,
        "rehearsal@example.invalid",
        "rehearsal-not-a-real-password",
    )
    assert cli.main(["ledger", "--port", "1"]) == 1
    assert "chatgpt-mock:" in capsys.readouterr().err


def test_exports_prints_the_links_a_running_mock_handed_out(
    chatgpt_site: Site, capsys: pytest.CaptureFixture[str]
) -> None:
    """`chatgpt-mock exports` says to another terminal what `serve` printed in its own."""
    started = server.serve(chatgpt_site, port=0)
    port = started.port
    try:
        first = chatgpt_site.request_export()
        second = chatgpt_site.request_export()
        assert cli.main(["exports", "--port", str(port)]) == 0
        assert capsys.readouterr().out == (
            f"{SITE_ORIGIN}/__mock/exports/{first.token}.zip\n{SITE_ORIGIN}/__mock/exports/{second.token}.zip\n"
        )
        assert cli.main(["ledger", "--port", str(port)]) == 0
        assert capsys.readouterr().out.startswith("Mock chatgpt.com — ledger\n\nSign-ins:                      0\n")
    finally:
        started.close()


def test_a_link_is_announced_as_it_is_minted(chatgpt_site: Site) -> None:
    announced: list[str] = []
    started = server.serve(chatgpt_site, port=0, announce=announced.append)
    try:
        client = Client(wire.origin_of("127.0.0.1", started.port))
        sign_in(client)
        _, body, _ = client.post_json("/api/exports", {})
    finally:
        started.close()
    assert announced == [json.loads(body)["link"]]


def test_rows_prints_every_citation(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["rows"]) == 0
    printed = capsys.readouterr().out
    assert printed.startswith("Mock chatgpt.com — the UI map rows it is built out of\n")
    for row in ("auth host", "paste over the threshold", "download needs session", "rename affordance"):
        assert f"\n{row}\n  " in printed
