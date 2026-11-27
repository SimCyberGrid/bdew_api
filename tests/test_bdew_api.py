"""Functional tests for the bdew_api package.

Each test starts the real HTTPS servers on free localhost ports and talks to
them with the real handlers, so a passing run means pEMT -> aEMT control
demands and aEMT -> pEMT answers really go over the wire.

Run them against the *installed* package (``pip install bdew-api[test]``)
to test what gets published rather than the source tree.

Both legs use mutually authenticated TLS (bdew_api.tls_config, TR-03116-3);
conftest.py generates a test PKI and runs every test in a directory that
holds it.
"""
import socket
import ssl
import time

import pytest
import requests
import urllib3

from bdew_api.answer_state_handler import AnswerStateHandler
from bdew_api.answer_state_server import AnswerStateServer
from bdew_api.bdew import BDEW
from bdew_api.control_demand_handler import ControlDemandHandler
from bdew_api.control_demand_server import ControlDemandServer
from bdew_api import tls_config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

AEMT_ID = "9900000000001"
PEMT_ID = "9900000000002"
HOST = "127.0.0.1"

def _free_port() -> int:
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def _client(role: str = "pemt") -> requests.Session:
    """A mutual-TLS client session presenting <role>'s certificate."""
    return tls_config.requests_session(f"{role}-cert.pem", f"{role}-key.pem", "wan-ca.pem")


def _server_ctx(role: str):
    return tls_config.server_context(f"{role}-cert.pem", f"{role}-key.pem", "wan-ca.pem")


def _wait_healthy(port: int, timeout: float = 10.0) -> None:
    session = _client()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if session.get(f"https://{HOST}:{port}/health", timeout=1).status_code == 200:
                return
        except requests.exceptions.RequestException:
            pass
        time.sleep(0.1)
    pytest.fail(f"server on port {port} did not become healthy within {timeout}s")


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)


def _headers() -> dict:
    return {"transactionId": "t-1", "creationDateTime": "2026-01-01T00:00:00Z", "initialTransactionId": "t-1"}


# ── pEMT -> aEMT: control demand ──────────────────────────────────────────────

@pytest.fixture
def aemt_server():
    port = _free_port()
    recorder = Recorder()
    ControlDemandServer(aemt_id=AEMT_ID, host=HOST, port=port, logic_callback=recorder,
                        ssl_context=_server_ctx("aemt")).start()
    _wait_healthy(port)
    return port, recorder


def test_control_demand_reaches_aemt(aemt_server):
    port, recorder = aemt_server
    command = {"maximumPowerValue": "4.200", "executionTimeFrom": "2026-01-01T00:00:00Z",
               "executionTimeUntil": "2026-01-01T00:15:00Z"}
    handler = ControlDemandHandler(pemt_id=PEMT_ID, aemt_id=AEMT_ID, aemt_host=HOST, aemt_port=port,
                                   session=_client("pemt"))
    handler.send_demand_control(command_control=command, location_id="41373559241")

    assert len(recorder.calls) == 1
    location_id, received, kind, _remote = recorder.calls[0]
    assert (location_id, received, kind) == ("41373559241", command, "control")


def test_command_regular_reaches_aemt(aemt_server):
    port, recorder = aemt_server
    handler = ControlDemandHandler(pemt_id=PEMT_ID, aemt_id=AEMT_ID, aemt_host=HOST, aemt_port=port,
                                   session=_client("pemt"))
    handler.send_demand_control(command_control={"executionTimeFrom": "2026-01-01T00:00:00Z"},
                                location_id="41373559241")

    assert [call[2] for call in recorder.calls] == ["regular"]


def test_control_demand_without_default_command_is_valid(aemt_server):
    port, recorder = aemt_server
    ControlDemandHandler(pemt_id=PEMT_ID, aemt_id=AEMT_ID, aemt_host=HOST, aemt_port=port,
                                   session=_client("pemt")).send_demand_control()

    assert [call[2] for call in recorder.calls] == ["control"]


@pytest.mark.parametrize("drop_header", ["transactionId", "creationDateTime", "initialTransactionId"])
def test_control_demand_missing_header_rejected(aemt_server, drop_header):
    port, recorder = aemt_server
    headers = {k: v for k, v in _headers().items() if k != drop_header}
    body = {"locationId": "41373559241", "commandControl": {"executionTimeFrom": "2026-01-01T00:00:00Z"}}
    response = _client().post(f"https://{HOST}:{port}/command-control", headers=headers, json=body, timeout=5)

    assert response.status_code == 400
    assert recorder.calls == []


def test_control_demand_missing_location_rejected(aemt_server):
    port, recorder = aemt_server
    body = {"commandControl": {"executionTimeFrom": "2026-01-01T00:00:00Z"}}
    response = _client().post(f"https://{HOST}:{port}/command-control", headers=_headers(), json=body, timeout=5)

    assert response.status_code == 400
    assert recorder.calls == []


# ── aEMT -> pEMT: answers ─────────────────────────────────────────────────────

@pytest.mark.parametrize("result, route", [
    ("positive", "positive-answer"),
    ("preliminary_positive", "preliminary-positive-answer"),
    ("preliminary_negative", "preliminary-negative-answer"),
    ("negative", "negative-answer"),
    ("unknown", "unknown-answer"),
    ("information", "information-control-signal"),
])
def test_answer_reaches_pemt(result, route):
    port = _free_port()
    recorder = Recorder()
    AnswerStateServer(pemt_id=PEMT_ID, host=HOST, port=port, logic_callback=recorder,
                      ssl_context=_server_ctx("pemt")).start()
    _wait_healthy(port)

    handler = AnswerStateHandler(aemt_id=AEMT_ID, pemt_id=PEMT_ID, pemt_host=HOST, pemt_port=port,
                                 logic_callback=None, session=_client("aemt"))
    handler.send_answer(result)

    assert [call[0] for call in recorder.calls] == [route]
    body = recorder.calls[0][1]
    assert body["referenceId"] and body["locationId"]


# ── BDEW facade ──────────────────────────────────────────────────────────────

@pytest.fixture
def bdew():
    aemt_port, pemt_port = _free_port(), _free_port()
    api = BDEW(aemt_id=AEMT_ID, aemt_host=HOST, aemt_port=aemt_port,
               pemt_id=PEMT_ID, pemt_host=HOST, pemt_port=pemt_port)
    _wait_healthy(aemt_port)
    _wait_healthy(pemt_port)
    return api


def test_bdew_facade_roundtrip(bdew):
    demands, answers = Recorder(), Recorder()
    bdew.control_demand_callback = demands
    bdew.answer_callback = answers

    bdew.send_control_request(command_control=None, location_id="41373559241")
    bdew.send_control_status("positive")

    assert [(c[0], c[2]) for c in demands.calls] == [("41373559241", "control")]
    assert [c[0] for c in answers.calls] == ["positive-answer"]


def test_bdew_aemt_and_pemt_roles_talk_to_each_other():
    """One instance per side, as in a real deployment. The aEMT does not
    know the pEMT's address (unroutable placeholder) and answers the sender."""
    aemt_port, pemt_port = _free_port(), _free_port()
    demands, answers = Recorder(), Recorder()
    aemt = BDEW(aemt_id=AEMT_ID, aemt_host=HOST, aemt_port=aemt_port,
                pemt_id=PEMT_ID, pemt_host="192.0.2.1", pemt_port=pemt_port,
                role="aemt", control_demand_callback=demands, answer_to_sender=True)
    pemt = BDEW(aemt_id=AEMT_ID, aemt_host=HOST, aemt_port=aemt_port,
                pemt_id=PEMT_ID, pemt_host=HOST, pemt_port=pemt_port,
                role="pemt", answer_callback=answers)
    _wait_healthy(aemt_port)
    _wait_healthy(pemt_port)

    pemt.send_control_request(command_control=None, location_id="41373559241")
    assert [(c[0], c[2], c[3]) for c in demands.calls] == [("41373559241", "control", HOST)]

    aemt.send_control_status("preliminary_positive")
    assert [c[0] for c in answers.calls] == ["preliminary-positive-answer"]


def test_bdew_role_starts_only_its_own_server():
    aemt_port, pemt_port = _free_port(), _free_port()
    BDEW(aemt_id=AEMT_ID, aemt_host=HOST, aemt_port=aemt_port,
         pemt_id=PEMT_ID, pemt_host=HOST, pemt_port=pemt_port, role="aemt")
    _wait_healthy(aemt_port)

    with socket.socket() as s:
        s.bind((HOST, pemt_port))  # still free: the aEMT side must not bind the pEMT port


def test_bdew_role_rejects_the_other_sides_calls():
    aemt = BDEW(aemt_id=AEMT_ID, aemt_host=HOST, aemt_port=_free_port(),
                pemt_id=PEMT_ID, pemt_host=HOST, pemt_port=_free_port(), role="aemt", autostart=False)
    pemt = BDEW(aemt_id=AEMT_ID, aemt_host=HOST, aemt_port=_free_port(),
                pemt_id=PEMT_ID, pemt_host=HOST, pemt_port=_free_port(), role="pemt", autostart=False)

    with pytest.raises(RuntimeError):
        aemt.send_control_request(command_control=None, location_id="41373559241")
    with pytest.raises(RuntimeError):
        pemt.send_control_status("positive")
    with pytest.raises(ValueError):
        BDEW(aemt_id=AEMT_ID, aemt_host=HOST, aemt_port=1, pemt_id=PEMT_ID, pemt_host=HOST, pemt_port=2,
             role="gwa", autostart=False)


def test_bdew_facade_accepts_control_demand_without_callback(bdew):
    """BDEW may be constructed without any callback; an incoming valid
    control demand must still be answered with 202, not crash the request."""
    body = {"locationId": "41373559241", "commandControl": {"executionTimeFrom": "2026-01-01T00:00:00Z"}}
    response = _client().post(f"https://{HOST}:{bdew.aemt_port}/command-control", headers=_headers(), json=body,
                              timeout=5)

    assert response.status_code == 202


# ── TLS profile ───────────────────────────────────────────────────────────────

def test_plain_https_client_is_rejected(aemt_server):
    """Regression: a default client (what the package used to send with) can
    not negotiate the brainpool/ECDSA profile, and a client without a
    certificate must be refused anyway (mutual TLS)."""
    port, recorder = aemt_server
    with pytest.raises(requests.exceptions.SSLError):
        requests.get(f"https://{HOST}:{port}/health", verify=False, timeout=5)
    assert recorder.calls == []


def test_client_without_certificate_is_rejected(aemt_server):
    """Right profile, but no client certificate: the server requires one."""
    port, _ = aemt_server
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers(tls_config.TLS12_ECDSA_CIPHERS)
    ctx.set_ecdh_curve(tls_config.TLS_CURVE)
    ctx.load_verify_locations("wan-ca.pem")
    ctx.check_hostname = False
    with pytest.raises((ssl.SSLError, ConnectionError)):
        with socket.create_connection((HOST, port), timeout=5) as raw, ctx.wrap_socket(raw) as tls:
            tls.sendall(b"GET /health HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
            if not tls.recv(1):  # TLS 1.2: the server's alert may only surface on read
                raise ConnectionError("server closed the connection")


@pytest.mark.parametrize("role", ["aemt", "pemt"])
def test_missing_tls_material_warns_and_disables_the_side(tmp_path, monkeypatch, capsys, role):
    """No certificates: BDEW must not crash — it warns, starts no server, and
    the send calls log a warning instead of raising."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    aemt_port, pemt_port = _free_port(), _free_port()
    api = BDEW(aemt_id=AEMT_ID, aemt_host=HOST, aemt_port=aemt_port,
               pemt_id=PEMT_ID, pemt_host=HOST, pemt_port=pemt_port, role=role)
    if role == "aemt":
        api.send_control_status("positive")
    else:
        api.send_control_request(command_control=None, location_id="41373559241")
    time.sleep(0.3)

    err = capsys.readouterr().err
    assert f"TLS setup of the {role} side failed" in err
    assert "not started — no TLS context" in err
    assert "not sent — no TLS session" in err
    with socket.socket() as s:
        s.bind((HOST, aemt_port if role == "aemt" else pemt_port))  # still free: no server started


def test_client_from_untrusted_ca_is_rejected(aemt_server):
    """A client certificate that is valid but signed by a CA the aEMT does not
    trust must not get through."""
    port, recorder = aemt_server
    body = {"locationId": "41373559241", "commandControl": {"executionTimeFrom": "2026-01-01T00:00:00Z"}}
    session = tls_config.requests_session("rogue-cert.pem", "rogue-key.pem", "wan-ca.pem")
    with pytest.raises(requests.exceptions.RequestException):
        session.post(f"https://{HOST}:{port}/command-control", headers=_headers(), json=body, timeout=5)
    assert recorder.calls == []
