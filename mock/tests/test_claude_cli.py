"""The blocks the mock claude.ai prints, and the refusals that keep it honest.

What the core prints for every mock — the proxy note's head, the link note, the
refusals — is tested once in `test_core_cli.py`; what is here is this site's: the
block with its `SSL_CERT_FILE` tail, and the notes about the tool's own fetch.
"""

import pytest
from claudemock import cli, server
from claudemock.site import Site
from mockcore import certificate


def test_the_reachability_block_is_the_one_an_operator_pastes(
    material: certificate.Material,
) -> None:
    """`26`'s golden string.

    §21 says what the lines must do — send the host to the mock, trust its key and never
    every certificate — and leaves the port, the mechanism and the lines themselves to
    the slice; this is where they are pinned.
    """
    block = cli.reachability(host="127.0.0.1", port=8443, material=material)
    assert block == (
        "Mock claude.ai listening on https://127.0.0.1:8443\n"
        "\n"
        "Add to <workspace>/config.toml before running the tool:\n"
        "\n"
        "[browser]\n"
        "extra_args = [\n"
        '  "--host-resolver-rules=MAP claude.ai 127.0.0.1:8443",\n'
        f'  "--ignore-certificate-errors-spki-list={material.spki_sha256}",\n'
        "]\n"
        "\n"
        "Set in the tool's environment before fetching an export link from it:\n"
        "\n"
        f"  SSL_CERT_FILE={material.cert_path}\n"
        "\n"
    )


def test_the_proxy_note_tells_the_fetch_too() -> None:
    """`32`: the tool downloads a link with Python, which reads the same proxy Chrome does."""
    note = cli.proxy_note(["https_proxy"])
    assert note.startswith(
        "This machine has a proxy in its environment (https_proxy), which Chrome reads and\nwhich would resolve claude.ai itself."
    )
    assert '"--no-proxy-server",' in note
    assert note.endswith("Set beside SSL_CERT_FILE:\n\n  no_proxy=127.0.0.1\n\n")


def test_the_host_note_is_the_golden_string() -> None:
    """`--host` is `26`'s; what `32` adds is the warning that a link from elsewhere is unfetchable."""
    assert cli.HOST_NOTE.format(host="192.0.2.7") == (
        "The mock is listening on 192.0.2.7, and the tool cannot fetch an export link from\n"
        "there: its certificate names 127.0.0.1 alone. Chrome is unaffected — it trusts\n"
        "the key, not the name — so a migration rehearses; an extraction needs the\n"
        "default host.\n"
        "\n"
    )


def test_the_trust_is_scoped_to_the_mocks_own_key(
    material: certificate.Material,
) -> None:
    """Never `--ignore-certificate-errors`.

    A rehearsal browser that trusted every certificate would be a much larger thing to
    switch off.
    """
    block = cli.reachability(host="127.0.0.1", port=8443, material=material)
    assert "--ignore-certificate-errors=" not in block
    assert len(material.spki_sha256) == 44  # base64 of a sha-256


def test_a_ledger_nobody_is_serving_is_an_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.ledger(host="127.0.0.1", port=1) == 1
    assert "claude-mock:" in capsys.readouterr().err


def test_sign_in_links_is_this_sites_own_command(capsys: pytest.CaptureFixture[str]) -> None:
    """`49`: the fifth command, and the path it reads."""
    assert cli.parser().parse_args(["sign-in-links"]).command == "sign-in-links"
    assert cli.sign_in_links(host="127.0.0.1", port=1) == 1
    assert capsys.readouterr().err.startswith("claude-mock: https://127.0.0.1:1/__mock/sign-in-links:")


def test_exports_prints_the_links_a_running_mock_handed_out(
    site: Site, material: certificate.Material, capsys: pytest.CaptureFixture[str]
) -> None:
    """`claude-mock exports` says to another terminal what `serve` printed in its own."""
    started = server.serve(site, port=0, material=material)
    port = started.port
    try:
        first = site.request_export()
        second = site.request_export()
        assert cli.exports(host="127.0.0.1", port=port) == 0
    finally:
        started.close()
    assert capsys.readouterr().out == (
        f"https://127.0.0.1:{port}/__mock/exports/{first.token}.zip\n"
        f"https://127.0.0.1:{port}/__mock/exports/{second.token}.zip\n"
    )


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
