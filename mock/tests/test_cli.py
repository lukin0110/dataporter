"""The two blocks the mock prints, and the refusals that keep it honest."""

from pathlib import Path

import pytest
from claudemock import certificate, cli


def test_the_reachability_block_is_the_one_an_operator_pastes(
    material: certificate.Material,
) -> None:
    """§21's block, whose shape is specified even though the mechanism is not."""
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
    )


def test_the_trust_is_scoped_to_the_mocks_own_key(
    material: certificate.Material,
) -> None:
    """Never `--ignore-certificate-errors`: a rehearsal browser that trusted
    every certificate would be a much larger thing to switch off."""
    block = cli.reachability(host="127.0.0.1", port=8443, material=material)
    assert "--ignore-certificate-errors=" not in block
    assert len(material.spki_sha256) == 44  # base64 of a sha-256


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


def test_the_key_is_kept_between_runs(tmp_path: Path) -> None:
    """So that a flag an operator wrote into a config keeps working."""
    first = certificate.ensure(tmp_path)
    again = certificate.ensure(tmp_path)
    assert first.spki_sha256 == again.spki_sha256


def test_a_ledger_nobody_is_serving_is_an_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.ledger(host="127.0.0.1", port=1) == 1
    assert "claude-mock:" in capsys.readouterr().err


def test_rows_prints_every_citation(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.rows() == 0
    printed = capsys.readouterr().out
    assert "rename affordance" in printed
    assert "sign-in form" in printed
