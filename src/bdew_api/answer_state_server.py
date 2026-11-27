from bdew_api.utils import setup_logger
from flask import Flask, request, jsonify
from datetime import datetime
import threading

#formerly AnswerServer
# Answer endpoint of the pEMT (EDI@Energy Universalbestellprozess,
# BNetzA-Beschluss BK6-22-128).
#
# After the pEMT reported a control demand via the aEMT's BDEW API, the aEMT
# answers here with the delivery status of the control command:
#   POST /preliminary-positive-answer — command can be executed
#   POST /preliminary-negative-answer — command cannot be executed
#   POST /positive-answer             — command arrived at the controlbox
#   POST /negative-answer             — command did not arrive
#   POST /unknown-answer              — final status unknown
#   POST /information-control-signal  — begin/end of the control action

_ANSWER_ROUTES = (
    "positive-answer",
    "preliminary-positive-answer",
    "preliminary-negative-answer",
    "negative-answer",
    "unknown-answer",
    "information-control-signal",
)


class AnswerStateServer:
    def __init__(self, pemt_id: str, host: str, port: int, logic_callback=None,
                 ssl_context=None) -> None:
        """
        Args:
            pemt_id:        ID of this pEMT (13-digit BDEW MP-ID)
            host:           bind address
            port:           HTTPS port for the aEMT's answers (pEMT range, :8202)
            logic_callback: optional, called as logic_callback(route, body)
                            for every received answer
            ssl_context:    mutual-TLS server context (tls_config.server_context);
                            without one the server does not start
        """
        self.pemt_id = pemt_id
        self.host = host
        self.port = port
        self.logic_callback = logic_callback
        self.ssl_context = ssl_context

        self.logger = setup_logger("AnswerStateServer", pemt_id)

        self.app = Flask(__name__)
        self._setup_flask_routes()

    def start(self):
        if self.ssl_context is None:
            self.logger.warning("Answer state server not started — no TLS context (TLS setup failed).")
            return
        flask_thread = threading.Thread(target=self._run_https_server, daemon=True)
        flask_thread.start()
        self.logger.info(f"BDEW answer endpoint listening on {self.host}:{self.port} (HTTPS)")

    def _setup_flask_routes(self):
        def _make_handler(route: str):
            def handler():
                body = request.get_json(silent=True) or {}
                self.logger.info(
                    f"aEMT answer '{route}' received "
                    f"(referenceId={body.get('referenceId')}, locationId={body.get('locationId')})"
                )
                self.logger.debug(f"Answer body: {body}")
                if self.logic_callback is not None:
                    self.logic_callback(route, body)
                return jsonify({"status": "received"}), 200
            return handler

        for route in _ANSWER_ROUTES:
            self.app.add_url_rule(
                f"/{route}", endpoint=route, view_func=_make_handler(route), methods=["POST"]
            )

        @self.app.route("/health", methods=["GET"])
        def health():
            return jsonify({"status": "HEALTHY", "timestamp": datetime.now().isoformat()}), 200

    def _run_https_server(self):
        try:
            self.app.run(
                host=self.host,
                port=self.port,
                ssl_context=self.ssl_context,
                debug=False,
                use_reloader=False,
                threaded=True,
            )
        except Exception as e:
            self.logger.error(f"Answer state server failure: {e}")
