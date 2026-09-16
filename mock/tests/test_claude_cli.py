"""The blocks the mock claude.ai prints, and the refusals that keep it honest.

What the core prints for every mock — the proxy note's head, the link note, the
refusals — is tested once in `test_core_cli.py`; what is here is this site's: the
block an operator pastes, and the links its listings print.
"""

import pytest
from claudemock import cli, server
from claudemock.site import Site
from mockcore import wire


def test_the_reachability_block_is_the_one_an_operator_reads() -> None:
    """The golden string, and it is two lines now.

    §21 said what the lines must *do* — send the host to the mock, trust its key
    and never every certificate — and left the rest to the slice. `65` answers
    both by needing neither: the mock is at `http://127.0.0.1:8443` and the tool
    is told so by `--mock`, so there is no `config.toml` table to paste, no
    resolver rule and no pin (ADR 0010).
    """
    assert cli.reachability(host="127.0.0.1", port=8443) == (
        "Mock claude.ai listening on http://127.0.0.1:8443\n"
        "\n"
        "Run the tool with --mock to reach it: dataporter --mock login --account <label>\n"
        "\n"
    )


def test_nothing_outside_the_flag_is_configured_any_more() -> None:
    """Everything `26` and `32` asked an operator to write down is gone with TLS."""
    block = cli.reachability(host="127.0.0.1", port=8443)
    for absent in ("SSL_CERT_FILE", "config.toml", "extra_args", "--host-resolver-rules", "spki"):
        assert absent not in block
    for gone in ("HOST_NOTE", "FETCH_PROXY_NOTE", "proxy_note"):
        assert not hasattr(cli, gone)


def test_a_ledger_nobody_is_serving_is_an_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.ledger(host="127.0.0.1", port=1) == 1
    assert "claude-mock:" in capsys.readouterr().err


def test_sign_in_links_is_this_sites_own_command(capsys: pytest.CaptureFixture[str]) -> None:
    """`49`: the fifth command, and the path it reads."""
    assert cli.parser().parse_args(["sign-in-links"]).command == "sign-in-links"
    assert cli.sign_in_links(host="127.0.0.1", port=1) == 1
    assert capsys.readouterr().err.startswith("claude-mock: http://127.0.0.1:1/__mock/sign-in-links:")


def test_exports_prints_the_links_a_running_mock_handed_out(site: Site, capsys: pytest.CaptureFixture[str]) -> None:
    """`claude-mock exports` says to another terminal what `serve` printed in its own.

    On the address the socket really bound (`65`): there is no resolver rule any
    more, so a link is where the browser can actually reach it. It names the
    index, which has no `.zip` on the end of it — the zips are what the index
    names.
    """
    started = server.serve(site, port=0)
    port = started.port
    try:
        first = site.request_export()
        second = site.request_export()
        assert cli.exports(host="127.0.0.1", port=port) == 0
    finally:
        started.close()
    base = wire.origin_of("127.0.0.1", port)
    assert capsys.readouterr().out == (f"{base}/__mock/exports/{first.token}\n{base}/__mock/exports/{second.token}\n")


def test_exports_nobody_is_serving_is_an_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.exports(host="127.0.0.1", port=1) == 1
    assert "claude-mock:" in capsys.readouterr().err


def test_rows_prints_every_citation(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.rows() == 0
    printed = capsys.readouterr().out
    assert "rename affordance" in printed
    assert "sign-in form" in printed
    assert "export requested" in printed
    assert "involuntary sign-out" in printed
