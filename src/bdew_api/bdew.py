from bdew_api import answer_state_handler
from bdew_api import answer_state_server
from bdew_api import control_demand_handler
from bdew_api import control_demand_server
from bdew_api import id_generator
from bdew_api import tls_config
from bdew_api import utils

ROLE_AEMT = "aemt"
ROLE_PEMT = "pemt"
ROLE_BOTH = "both"
_ROLES = (ROLE_AEMT, ROLE_PEMT, ROLE_BOTH)


class BDEW:
    """BDEW API between pEMT and aEMT (Universalbestellprozess, BK6-22-128).

    Each side only runs its own half of the API:

    * ``role="aemt"`` — serves control demands on ``aemt_host:aemt_port`` and
      sends the delivery-status answers to ``pemt_host:pemt_port``.
    * ``role="pemt"`` — serves the answers on ``pemt_host:pemt_port`` and sends
      control demands to ``aemt_host:aemt_port``.
    * ``role="both"`` — both halves in one process (local demo / tests).

    So for the own side the host is the bind address, for the other side it is
    the address to send to.

    Callbacks:
        control_demand_callback(location_id, command, kind, remote_addr) — aEMT
            side, for every validated control demand (kind: "control" | "regular").
        answer_callback(route, body) — pEMT side, for every answer of the aEMT.

    With ``answer_to_sender=True`` (aEMT side) the answers go to the address
    the last control demand came from instead of the fixed ``pemt_host``, so
    the aEMT does not need to know the pEMT's IP up front.

    TLS (both legs, see :mod:`bdew_api.tls_config`): mutually authenticated
    TLS 1.2 with the TR-03116-3 profile. Each side uses its own certificate —
    ``aemt_certfile``/``aemt_keyfile`` and ``pemt_certfile``/``pemt_keyfile``,
    by default ``aemt-cert.pem``/``aemt-key.pem`` and ``pemt-cert.pem``/
    ``pemt-key.pem`` in the working directory — and both verify the peer
    against ``cafile`` (default ``wan-ca.pem``). If a side's TLS material
    cannot be loaded, a warning is logged and that side stays inactive: its
    server does not start and its requests are not sent (each logs why).
    """

    def __init__(self, aemt_id: str, aemt_host: str, aemt_port: int, pemt_id: str, pemt_host: str, pemt_port: int,
                 role: str = ROLE_BOTH, control_demand_callback=None, answer_callback=None,
                 answer_to_sender: bool = False, autostart: bool = True,
                 aemt_certfile: str = None, aemt_keyfile: str = None,
                 pemt_certfile: str = None, pemt_keyfile: str = None, cafile: str = None):
        if role not in _ROLES:
            raise ValueError(f"role must be one of {_ROLES}, not {role!r}")

        self.aemt_id = aemt_id
        self.aemt_host = aemt_host
        self.aemt_port = aemt_port
        self.pemt_id = pemt_id
        self.pemt_host = pemt_host
        self.pemt_port = pemt_port
        self.role = role
        self.control_demand_callback = control_demand_callback
        self.answer_callback = answer_callback
        self.answer_to_sender = answer_to_sender
        self.logger = utils.setup_logger("BDEW", pemt_id if role == ROLE_PEMT else aemt_id)

        self.control_demand_server = None
        self.answer_state_handler = None
        self.answer_state_server = None
        self.control_demand_handler = None

        if role in (ROLE_AEMT, ROLE_BOTH):
            aemt_ctx, aemt_session = self._load_tls("aemt", aemt_certfile, aemt_keyfile, cafile)
            self.control_demand_server = control_demand_server.ControlDemandServer(
                aemt_id=self.aemt_id, host=self.aemt_host, port=self.aemt_port,
                logic_callback=self._on_control_demand, ssl_context=aemt_ctx)
            self.answer_state_handler = answer_state_handler.AnswerStateHandler(
                aemt_id=self.aemt_id, pemt_id=self.pemt_id, pemt_host=self.pemt_host, pemt_port=self.pemt_port,
                logic_callback=None, session=aemt_session)
        if role in (ROLE_PEMT, ROLE_BOTH):
            pemt_ctx, pemt_session = self._load_tls("pemt", pemt_certfile, pemt_keyfile, cafile)
            self.answer_state_server = answer_state_server.AnswerStateServer(
                pemt_id=self.pemt_id, host=self.pemt_host, port=self.pemt_port,
                logic_callback=self._on_answer, ssl_context=pemt_ctx)
            self.control_demand_handler = control_demand_handler.ControlDemandHandler(
                pemt_id=self.pemt_id, aemt_id=self.aemt_id, aemt_host=self.aemt_host, aemt_port=self.aemt_port,
                logic_callback=None, session=pemt_session)

        if autostart:
            self.start()

    def _load_tls(self, side: str, certfile: str, keyfile: str, cafile: str):
        """(server context, client session) of one side, or (None, None) with a warning."""
        try:
            return tls_config.load_side(side, certfile, keyfile, cafile)
        except OSError as e:  # includes ssl.SSLError
            self.logger.warning(
                f"TLS setup of the {side} side failed ({e}) — BDEW API {side} side inactive: "
                "its server will not start and its requests will not be sent."
            )
            return None, None

    def start(self):
        """Start the server(s) of this side (background threads)."""
        if self.control_demand_server is not None:
            self.control_demand_server.start()
        if self.answer_state_server is not None:
            self.answer_state_server.start()

    # server callbacks
    def _on_control_demand(self, location_id: str, command: dict, kind: str, remote_addr: str = None):
        if self.answer_to_sender and remote_addr:
            self.answer_state_handler.pemt_host = remote_addr
        if self.control_demand_callback is not None:
            self.control_demand_callback(location_id, command, kind, remote_addr)

    def _on_answer(self, route: str, body: dict):
        if self.answer_callback is not None:
            self.answer_callback(route, body)

    # logic of api
    def send_control_request(self, command_control: dict, location_id: str):
        """pEMT side: report a control demand to the aEMT."""
        if self.control_demand_handler is None:
            raise RuntimeError(f"send_control_request is not available for role {self.role!r}")
        self.control_demand_handler.send_demand_control(command_control, location_id)

    def send_control_status(self, result: object):
        """aEMT side: answer the pEMT with the delivery status of a control command."""
        if self.answer_state_handler is None:
            raise RuntimeError(f"send_control_status is not available for role {self.role!r}")
        self.answer_state_handler.send_answer(result)
