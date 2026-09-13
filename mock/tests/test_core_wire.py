"""The wire every mock shares: the server on its thread, and the witness routes."""

import socket
from pathlib import Path

import pytest
from claudemock import server
from claudemock.site import Site
from mockcore import certificate, wire


def test_a_server_that_cannot_start_releases_its_port(
    site: Site, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key that is not there.

    Uvicorn fails to start, and the socket `serve` bound before handing it over is
    closed rather than left holding the port.
    """
    bound: list[socket.socket] = []
    listen = wire.listen

    def listen_and_remember(host: str, port: int) -> socket.socket:
        bound.append(listen(host, port))
        return bound[-1]

    monkeypatch.setattr(wire, "listen", listen_and_remember)
    missing = certificate.Material(cert_path=tmp_path / "cert.pem", key_path=tmp_path / "key.pem", spki_sha256="")
    with pytest.raises(RuntimeError, match="stopped before it started") as caught:
        server.serve(site, port=0, material=missing)
    assert isinstance(caught.value.__cause__, OSError)
    assert [sock.fileno() for sock in bound] == [-1]


def test_the_server_knows_the_address_it_bound(site: Site, material: certificate.Material) -> None:
    started = server.serve(site, port=0, material=material)
    try:
        assert started.host == "127.0.0.1"
        assert started.port > 0
    finally:
        started.close()


def test_the_witness_paths_are_on_no_site() -> None:
    """`/__mock/` is a path no helper will drive, which keeps the witness independent."""
    for path in (wire.LEDGER_PATH, wire.LEDGER_JSON_PATH, wire.EXPORTS_PATH, wire.EXPORTS_JSON_PATH, wire.ARCHIVE_PATH):
        assert path.startswith("/__mock/")
    assert wire.ARCHIVE_PATH.format(token="abc") == "/__mock/exports/abc.zip"
