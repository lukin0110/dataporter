"""The key the mock serves TLS with, and the pin that makes Chrome accept it.

A browser that has been told `claude.ai` is at `127.0.0.1` still expects
`claude.ai`'s certificate, and nobody can produce that. So the mock mints its
own, and prints the one flag that makes Chrome trust *this key and no other*:

    --ignore-certificate-errors-spki-list=<base64 sha-256 of the SPKI>

That is the whole of why this module exists. The alternative — telling Chrome to
ignore certificate errors outright — would take the operator's rehearsal browser
off the internet's trust rules for every host it visits, which is a much larger
thing to switch off than a rehearsal needs (§21, *Reachability*).

The key pair is kept on disk between runs so that the flag an operator has
written into a workspace's `config.toml` keeps working after the mock is
restarted. Delete the directory and the next start mints a new one, and prints a
new pin.
"""

import base64
import datetime as dt
import hashlib
import ipaddress
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from claudemock import HOST

CERT_NAME = "claude-mock.pem"
KEY_NAME = "claude-mock.key"

VALID_DAYS = 90
"""Long enough to stop being a daily chore, short enough that a forgotten key on
a shared machine expires. Well inside the 398 days Chrome refuses beyond."""


def default_directory() -> Path:
    """Where the key lives when nobody says otherwise."""
    cache = os.environ.get("XDG_CACHE_HOME")
    root = Path(cache) if cache else Path.home() / ".cache"
    return root / "claude-mock"


@dataclass(frozen=True)
class Material:
    """A certificate, its key, and the pin that identifies the key."""

    cert_path: Path
    key_path: Path
    spki_sha256: str

    @property
    def flag(self) -> str:
        """The Chrome flag, whole, ready to be pasted into `extra_args`."""
        return f"--ignore-certificate-errors-spki-list={self.spki_sha256}"


def pin_of(certificate: x509.Certificate) -> str:
    """Base64 of the sha-256 of the DER SubjectPublicKeyInfo.

    Exactly what Chrome hashes, which is the public key and not the certificate:
    a certificate reissued for the same key keeps the same pin.
    """
    spki = certificate.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.b64encode(hashlib.sha256(spki).digest()).decode("ascii")


def ensure(directory: Path | None = None) -> Material:
    """Return the key pair in `directory`, minting one if there is none or it expired."""
    root = directory if directory is not None else default_directory()
    root.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = root / CERT_NAME, root / KEY_NAME
    existing = _load(cert_path, key_path)
    if existing is not None:
        return Material(cert_path, key_path, pin_of(existing))
    certificate, key = _mint()
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return Material(cert_path, key_path, pin_of(certificate))


def _load(cert_path: Path, key_path: Path) -> x509.Certificate | None:
    """Return the certificate on disk, or `None` when there is none worth serving."""
    if not cert_path.exists() or not key_path.exists():
        return None
    try:
        certificate = x509.load_pem_x509_certificate(cert_path.read_bytes())
    except ValueError:
        return None
    if certificate.not_valid_after_utc <= dt.datetime.now(dt.UTC):
        return None
    return certificate


def _mint() -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    """Return a self-signed certificate for `claude.ai`, and the key under it.

    P-256 rather than RSA: it is a few milliseconds to generate rather than a
    second, and Chrome is as happy with it.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, HOST),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "claude-mock"),
    ])
    now = dt.datetime.now(dt.UTC)
    certificate = (
        x509
        .CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=VALID_DAYS))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName(HOST),
                x509.DNSName(f"*.{HOST}"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return certificate, key
