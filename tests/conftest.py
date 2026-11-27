"""Test PKI for the bdew_api tests, generated per test session.

The package speaks mutually authenticated TLS 1.2 with the TR-03116-3 profile
(ECDSA on brainpoolP256r1, see bdew_api.tls_config), so the tests need
certificates of that kind. They are generated here with ``cryptography``
(test dependency, ``pip install bdew-api[test]``), so the tests depend on no
external files:

* ``wan-ca.pem``                      — test CA both sides trust
* ``aemt-cert.pem`` / ``aemt-key.pem`` — aEMT leaf, signed by the CA
* ``pemt-cert.pem`` / ``pemt-key.pem`` — pEMT leaf, signed by the CA
* ``rogue-cert.pem`` / ``rogue-key.pem`` — leaf signed by a *different* CA,
  to check that untrusted peers are rejected

Every test runs in a fresh working directory holding these files, because the
package looks for them there by default.
"""

import datetime
import ipaddress
import shutil

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CURVE = ec.BrainpoolP256R1


def _name(common_name: str, unit: str = None) -> x509.Name:
    attrs = [x509.NameAttribute(NameOID.COMMON_NAME, common_name)]
    if unit:
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, unit))
    return x509.Name(attrs)


def _validity(builder: x509.CertificateBuilder) -> x509.CertificateBuilder:
    now = datetime.datetime.now(datetime.timezone.utc)
    return builder.not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=30))


def _make_ca(common_name: str):
    key = ec.generate_private_key(CURVE())
    name = _name(common_name)
    cert = (
        _validity(x509.CertificateBuilder())
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                     content_commitment=False, key_encipherment=False, data_encipherment=False,
                                     key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _make_leaf(role: str, ca_key, ca_cert):
    key = ec.generate_private_key(CURVE())
    cert = (
        _validity(x509.CertificateBuilder())
        .subject_name(_name(f"{role}-test", unit=role)).issuer_name(ca_cert.subject)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_agreement=True, key_cert_sign=False, crl_sign=False,
                                     content_commitment=False, key_encipherment=False, data_encipherment=False,
                                     encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]),
                       critical=False)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                                                    x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                       critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def _write(directory, stem: str, key, cert) -> None:
    (directory / f"{stem}-cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    if key is not None:
        (directory / f"{stem}-key.pem").write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


@pytest.fixture(scope="session")
def pki_dir(tmp_path_factory):
    """Directory with the generated test PKI (created once per session)."""
    directory = tmp_path_factory.mktemp("pki")
    ca_key, ca_cert = _make_ca("bdew-api test CA")
    (directory / "wan-ca.pem").write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    for role in ("aemt", "pemt"):
        _write(directory, role, *_make_leaf(role, ca_key, ca_cert))
    rogue_ca_key, rogue_ca_cert = _make_ca("untrusted test CA")
    _write(directory, "rogue", *_make_leaf("pemt", rogue_ca_key, rogue_ca_cert))
    return directory


@pytest.fixture(autouse=True)
def certs_in_cwd(pki_dir, tmp_path, monkeypatch):
    """Run every test in a fresh directory that holds the test PKI."""
    for path in pki_dir.iterdir():
        shutil.copy(path, tmp_path / path.name)
    monkeypatch.chdir(tmp_path)
