"""The block the mock chatgpt.com prints, and the two commands that ask it questions."""

import json

import pytest
from chatgptmock import cli, server
from chatgptmock.site import Site
from mockcore import certificate
from test_chatgpt_server import sign_in

from conftest import Client


def test_the_reachability_block_names_both_hosts_in_one_rule(chatgpt_material: certificate.Material) -> None:
    """`39`'s golden string.

    §54 says the lines send both host names to the mock and trust its key and no
    other; the shape is `26`'s, and there is no tail — the tool cannot fetch this
    site's archive, so there is nothing to tell it.
    """
    block = cli.reachability(host="127.0.0.1", port=8444, material=chatgpt_material)
    assert block == (
        "Mock chatgpt.com listening on https://127.0.0.1:8444\n"
        "\n"
        "Add to <workspace>/config.toml before running the tool:\n"
        "\n"
        "[browser]\n"
        "extra_args = [\n"
        '  "--host-resolver-rules=MAP chatgpt.com 127.0.0.1:8444, MAP auth.openai.com 127.0.0.1:8444",\n'
        f'  "--ignore-certificate-errors-spki-list={chatgpt_material.spki_sha256}",\n'
        "]\n"
        "\n"
    )
    assert "SSL_CERT_FILE" not in block


def test_the_proxy_note_names_both_hosts_and_no_fetch() -> None:
    note = cli.proxy_note(["https_proxy"])
    assert "which would resolve chatgpt.com and auth.openai.com itself." in note
    assert '"--no-proxy-server",' in note
    assert "no_proxy" not in note


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
    chatgpt_site: Site, chatgpt_material: certificate.Material, capsys: pytest.CaptureFixture[str]
) -> None:
    """`chatgpt-mock exports` says to another terminal what `serve` printed in its own."""
    started = server.serve(chatgpt_site, port=0, material=chatgpt_material)
    port = started.port
    try:
        first = chatgpt_site.request_export()
        second = chatgpt_site.request_export()
        assert cli.main(["exports", "--port", str(port)]) == 0
        assert capsys.readouterr().out == (
            f"https://chatgpt.com/__mock/exports/{first.token}.zip\n"
            f"https://chatgpt.com/__mock/exports/{second.token}.zip\n"
        )
        assert cli.main(["ledger", "--port", str(port)]) == 0
        assert capsys.readouterr().out.startswith("Mock chatgpt.com — ledger\n\nSign-ins:                      0\n")
    finally:
        started.close()


def test_a_link_is_announced_as_it_is_minted(chatgpt_site: Site, chatgpt_material: certificate.Material) -> None:
    announced: list[str] = []
    started = server.serve(chatgpt_site, port=0, material=chatgpt_material, announce=announced.append)
    try:
        client = Client(f"https://127.0.0.1:{started.port}")
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
