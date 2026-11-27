"""TLS profile of the BDEW API (TR-03116-3, mutually authenticated TLS 1.2).

Both legs of the API are HTTPS between WAN participants of the smart-metering
system — pEMT -> aEMT (control demands, :8301) and aEMT -> pEMT (answers,
:8202) — so they use the TR-03116-3 profile for the smart-metering WAN:

  * TLS 1.2 only, renegotiation disabled.
  * ECDHE_ECDSA cipher suites with AES-GCM/CBC (TR-03116-3 Tab. 7/8) and the
    brainpoolP256r1 curve. Both sides must set the curve: with OpenSSL's
    default groups a brainpool certificate cannot be negotiated, and the
    handshake fails with ``handshake failure`` / ``no shared cipher``.
  * Mutual authentication: server and client each present a certificate and
    verify the peer's chain against the WAN CA (``CERT_REQUIRED``).

``check_hostname`` is off: peers are typically addressed by IP, and identity
is established by the CA, not the host name.
"""

import ssl

# TR-03116-3 Tab. 7/8: ECDHE_ECDSA with AES-128/256 GCM (and CBC for breadth).
TLS12_ECDSA_CIPHERS = (
    "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-AES128-SHA256:ECDHE-ECDSA-AES256-SHA384"
)
# TR-03116-3 Tab. 7/8 curve for the German smart-metering TLS profile.
TLS_CURVE = "brainpoolP256r1"

# Default CA file, relative to the working directory.
DEFAULT_CAFILE = "wan-ca.pem"


def _configure(ctx: ssl.SSLContext, certfile: str, keyfile: str, cafile: str) -> ssl.SSLContext:
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers(TLS12_ECDSA_CIPHERS)
    # Required on both sides: without it a brainpool certificate cannot be negotiated.
    ctx.set_ecdh_curve(TLS_CURVE)
    ctx.options |= ssl.OP_NO_RENEGOTIATION
    # Own identity — both sides present a certificate, so auth is mutual.
    ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)
    # Trust anchor: the WAN CA.
    ctx.load_verify_locations(cafile)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def server_context(certfile: str, keyfile: str, cafile: str = DEFAULT_CAFILE) -> ssl.SSLContext:
    """TLS 1.2 **server** context that requires a client certificate."""
    return _configure(ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER), certfile, keyfile, cafile)


def client_context(certfile: str, keyfile: str, cafile: str = DEFAULT_CAFILE) -> ssl.SSLContext:
    """TLS 1.2 **client** context that presents a client certificate."""
    return _configure(ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT), certfile, keyfile, cafile)


def requests_session(certfile: str, keyfile: str, cafile: str = DEFAULT_CAFILE):
    """A ``requests.Session`` that speaks this profile (client cert, WAN CA)."""
    import requests
    from requests.adapters import HTTPAdapter

    client_ctx = client_context(certfile, keyfile, cafile)

    class _MutualTLSAdapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            kwargs["ssl_context"] = client_ctx
            kwargs["assert_hostname"] = False  # identity is the CA, not the host
            return super().init_poolmanager(*args, **kwargs)

    session = requests.Session()
    session.mount("https://", _MutualTLSAdapter())
    return session


def load_side(role: str, certfile: str = None, keyfile: str = None, cafile: str = None):
    """Server context + client session for one side ("aemt" or "pemt").

    Defaults: ``<role>-cert.pem``, ``<role>-key.pem``, ``wan-ca.pem`` in the
    working directory. Raises ``OSError`` (``ssl.SSLError`` is one) naming the
    files if the material is missing or unusable.
    """
    certfile, keyfile = certfile or f"{role}-cert.pem", keyfile or f"{role}-key.pem"
    cafile = cafile or DEFAULT_CAFILE
    try:
        return server_context(certfile, keyfile, cafile), requests_session(certfile, keyfile, cafile)
    except OSError as e:
        raise OSError(f"{e.strerror or e}; cert={certfile}, key={keyfile}, ca={cafile}") from e
