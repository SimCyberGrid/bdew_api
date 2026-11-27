from bdew_api.utils import setup_logger
from flask import Flask, request, jsonify
from datetime import datetime
import threading

#formerly BDEW API Server
# BDEW API server of the aEMT (EDI@Energy Universalbestellprozess,
# BNetzA ruling BK6-22-128).
#
# The pEMT reports a control demand here when the grid-state estimation
# detects a grid congestion:
#   POST /command-control  — power limitation (commandControl)
#   POST /command-regular  — return to the normal state (commandRegular)
#
# Required headers: transactionId, creationDateTime, initialTransactionId.
# Required body:    locationId + commandControl / commandRegular.
# locationId identifies the resource the control command acts on — the
# affected device (mME) as listed in the routing table, so the aEMT can
# resolve the household group and its controlbox.

_REQUIRED_HEADERS = ("transactionId", "creationDateTime", "initialTransactionId")


class ControlDemandServer:
    def __init__(self, aemt_id: str, host: str, port: int, logic_callback,
                 ssl_context=None) -> None:
        """
        Args:
            aemt_id:        ID of this aEMT (13-digit BDEW MP-ID)
            host:           bind address
            port:           HTTPS port of the BDEW API (aEMT range, :8301)
            logic_callback: called as logic_callback(location_id, command, kind)
                            with kind in {"control", "regular"} after a request
                            passed validation
            ssl_context:    mutual-TLS server context (tls_config.server_context);
                            without one the server does not start
        """
        self.aemt_id = aemt_id
        self.host = host
        self.port = port
        self.logic_callback = logic_callback
        self.ssl_context = ssl_context

        self.logger = setup_logger("ControlDemandServer", aemt_id)

        self.app = Flask(__name__)
        self._setup_flask_routes()

    def start(self):
        if self.ssl_context is None:
            self.logger.warning("Control Demand Server not started — no TLS context (TLS setup failed).")
            return
        self.logger.info("━" * 100)
        self.logger.info(" " * 42 + "Control Demand Server")
        self.logger.info("━" * 100)
        flask_thread = threading.Thread(target=self._run_https_server, daemon=True)
        flask_thread.start()
        self.logger.info(f"BDEW control demand endpoint listening on {self.host}:{self.port} (HTTPS)")

    def _validate(self, body: dict, command_key: str):
        """Validate headers and body of a Universalbestellprozess request.

        Returns (error_response, status) on failure, (None, None) on success.
        """
        missing = [h for h in _REQUIRED_HEADERS if not request.headers.get(h)]
        if missing:
            return jsonify({"error": f"missing headers: {', '.join(missing)}"}), 400
        if not isinstance(body, dict):
            return jsonify({"error": "request body must be a JSON object"}), 400
        if not body.get("locationId"):
            return jsonify({"error": "missing locationId"}), 400
        command = body.get(command_key)
        if not isinstance(command, dict) or not command.get("executionTimeFrom"):
            return jsonify(
                {"error": f"missing or invalid {command_key} (executionTimeFrom required)"}
            ), 400
        return None, None

    def _setup_flask_routes(self):
        @self.app.route("/command-control", methods=["POST"])
        def handle_command_control():
            body = request.get_json(silent=True)
            error, status = self._validate(body, "commandControl")
            if error is not None:
                self.logger.warning(f"Rejected /command-control request: {error.get_json()}")
                return error, status
            self.logger.info(
                f"Control demand received (locationId={body['locationId']}, "
                f"transactionId={request.headers['transactionId']})"
            )
            if self.logic_callback is not None:
                self.logic_callback(body["locationId"], body["commandControl"], "control", request.remote_addr)
            return jsonify({"status": "accepted"}), 202

        @self.app.route("/command-regular", methods=["POST"])
        def handle_command_regular():
            body = request.get_json(silent=True)
            error, status = self._validate(body, "commandRegular")
            if error is not None:
                self.logger.warning(f"Rejected /command-regular request: {error.get_json()}")
                return error, status
            self.logger.info(
                f"Regular-state command received (locationId={body['locationId']})"
            )
            if self.logic_callback is not None:
                self.logic_callback(body["locationId"], body["commandRegular"], "regular", request.remote_addr)
            return jsonify({"status": "accepted"}), 202

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
            self.logger.error(f"Control Demand Server failure: {e}")