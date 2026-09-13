"""The key each mock serves TLS with: one per program, naming every host it answers as."""

from pathlib import Path

import pytest
from chatgptmock import IDENTITY as CHATGPT
from claudemock import IDENTITY as CLAUDE
from cryptography import x509
from cryptography.x509.oid import NameOID
from mockcore import certificate


def test_the_key_is_kept_between_runs(tmp_path: Path) -> None:
    """So that a flag an operator wrote into a config keeps working."""
    first = certificate.ensure(CLAUDE, tmp_path)
    again = certificate.ensure(CLAUDE, tmp_path)
    assert first.spki_sha256 == again.spki_sha256
    assert first.cert_path == tmp_path / "claude-mock.pem"
    assert first.key_path == tmp_path / "claude-mock.key"


def test_the_pin_is_a_sha256_and_the_flag_is_scoped_to_it(tmp_path: Path) -> None:
    """Never `--ignore-certificate-errors`: the pin is the smallest thing that works."""
    material = certificate.ensure(CLAUDE, tmp_path)
    assert len(material.spki_sha256) == 44  # base64 of a sha-256
    assert material.flag == f"--ignore-certificate-errors-spki-list={material.spki_sha256}"


def test_the_certificate_names_every_host_and_the_loopback_address(tmp_path: Path) -> None:
    """§54: the mock chatgpt.com answers two names, and its certificate names both."""
    material = certificate.ensure(CHATGPT, tmp_path)
    loaded = x509.load_pem_x509_certificate(material.cert_path.read_bytes())
    names = loaded.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert set(names.get_values_for_type(x509.DNSName)) == {
        "chatgpt.com",
        "*.chatgpt.com",
        "auth.openai.com",
        "*.auth.openai.com",
    }
    assert [str(address) for address in names.get_values_for_type(x509.IPAddress)] == ["127.0.0.1"]
    assert loaded.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "chatgpt.com"
    # The organisation is the program's: how a trace tells a mock's certificate
    # from the site's (brief `04` §47).
    assert loaded.subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)[0].value == "chatgpt-mock"
    assert loaded.issuer == loaded.subject
    assert material.cert_path.name == "chatgpt-mock.pem"


def test_two_mocks_keep_two_keys(tmp_path: Path) -> None:
    """Each mock keeps a certificate of its own, even in one directory."""
    claude = certificate.ensure(CLAUDE, tmp_path)
    chatgpt = certificate.ensure(CHATGPT, tmp_path)
    assert claude.spki_sha256 != chatgpt.spki_sha256
    assert {claude.cert_path.name, chatgpt.cert_path.name} == {"claude-mock.pem", "chatgpt-mock.pem"}


def test_a_default_directory_is_the_programs_own(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert certificate.default_directory(CLAUDE) == tmp_path / "claude-mock"
    assert certificate.default_directory(CHATGPT) == tmp_path / "chatgpt-mock"
