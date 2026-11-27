from bdew_api.utils import setup_logger
from bdew_api import id_generator as id_gen
#formerly PEMTHandler
# API between aEMT and pEMT:
# the pEMT reports the need for a regulation command to the aEMT
# (the aEMT requests the regulation command, sends the request to the GWA;
# the SMGW establishes the CLS channel to the controlbox).
# The aEMT answers with the delivery status of the command request
# (delivered successfully or not delivered).
# The API implements BNetzA-Beschluss BK6-22-128.
# Specs: openapi 3.0.0, version 1.0.0, title: EDI@Energy API-Webdienste zur
# prozessualen Abwicklung von Steuerungshandlungen in Verbindung mit
# intelligenten Messsystemen (iMS) - Universalbestellprozess

class AnswerStateHandler:
    def __init__(self, aemt_id: str, pemt_id:str, pemt_host: str, pemt_port: int, logic_callback,
                 session=None):
        self.aemt_id = aemt_id
        self.pemt_id = pemt_id
        # Answers go to the pEMT's IP — BDEW MP-IDs are not resolvable
        # hostnames, so the pEMT id cannot be used as the URL host.
        self.pemt_host = pemt_host
        self.pemt_port = pemt_port
        # Setup logging
        self.logger = setup_logger("PEMT", aemt_id)
        self.logic_callback = logic_callback
        # Mutual-TLS client session (tls_config.requests_session); None = TLS setup failed
        self.session = session

    def send_answer(self,result: object):
        if self.session is None:
            self.logger.warning("Answer not sent — no TLS session (TLS setup failed).")
            return None
        self.logger.info("━" * 100)
        self.logger.info(" " * 44 + "PEMT Handler")
        self.logger.info("━" * 100)

        self.logger.info(
            f"Sending answer to {self.pemt_id}:{self.pemt_port} - Control Signal status")

        id_generator = id_gen.IDGenerator
        # ID format: string($UUID RFC4122)
        # transactionId: external, unique — information about the control
        # command confirmed by the GWA
        transaction_id = id_generator.generate_transaction_id()
        # Time of this call
        creation_date_time = id_generator.generate_datetimestamp()
        # In case of a retry, the idempotency key
        initial_transaction_id = transaction_id
        # External, previous reference (the original control command);
        # value taken from transactionId of step 1 of the use case
        # "control command from NB/LF to MSB"
        reference_id = transaction_id
        # locationId: identifies the resource the control command acts on
        # (e.g. "C1234848431" — a control box)
        location_id = id_generator.generate_location_id()
        partner_id = id_generator.generate_partner_id()

        if result == "positive":
            result_json = {"statePositive": "succeeded"}
            self.logger.info(
                f"Sending positive answer to {self.pemt_id}:{self.pemt_port} - Control Signal arrived at Control Box.")
        elif result == "preliminary_positive":
            result_json = {"preliminaryResultPositive": "possible"}
            # Positive answer: the control command can in principle be executed.
            self.logger.info(
                f"Sending preliminary positive answer to {self.pemt_id}:{self.pemt_port} - Control Signal is able to "
                f"arrive at Control Box.")
        elif result == "preliminary_negative":
            # Negative answer: the control command cannot be executed.
            # reasonNegative gives the reason: communicationFailure = link to
            # the control box disrupted, overload = MSB backend overloaded,
            # unable = MSB procedurally unable to fulfil the request
            # (e.g. maintenance).
            result_json = {"stateNegative": "failed",
                           "reasonNegative": "communicationFailure"}
            self.logger.info(
                f"Sending preliminary negative answer to {self.pemt_id}:{self.pemt_port} - Control Signal failed to "
                f"arrive at Control Box.")
        elif result == "negative":
            result_json = {
                "stateNegative": "failed",
                "reasonNegative": "communicationFailure"}
            self.logger.info(
                f"Sending negative answer to {self.pemt_id}:{self.pemt_port} - Control Signal did not arrive at Control"
                f" Box.")
        elif result == "unknown":
            result_json = {
                "stateUnknown": "unknown"
            }
            self.logger.info(
                f"Sending unknown answer to {self.pemt_id}:{self.pemt_port} - Final status of Control Signal unknown.")
        else:
            command_control = {
                "maximumPowerValue": "24.123",
                "executionTimeFrom": "2023-08-01T12:30:00Z",
                "executionTimeUntil": "2023-08-01T12:30:00Z"
            }
            command_regular = {
                "executionTimeFrom": "2023-08-01T12:30:00Z"
            }
            self.logger.info(
                f"Sending information about answer to {self.pemt_id}:{self.pemt_port} - Begin and End of Control.")


        try:
            #build header and query for http request
            headers = {'transactionId':transaction_id, 'creationDateTime':creation_date_time,
                       'initialTransactionId':initial_transaction_id}
            if result == "positive":
                query = {'referenceId':reference_id,'locationId':location_id,'resultPositive':result_json}
                url = f"https://{self.pemt_host}:{self.pemt_port}/positive-answer"
            elif result == "preliminary_positive":
                query = {'referenceId':reference_id,'locationId':location_id,'preliminaryResultPositive':result_json}
                url = f"https://{self.pemt_host}:{self.pemt_port}/preliminary-positive-answer"
            elif result == "preliminary_negative":
                query = {'referenceId':reference_id,'locationId':location_id,'preliminaryResultNegative':result_json}
                url = f"https://{self.pemt_host}:{self.pemt_port}/preliminary-negative-answer"
            elif result == "negative":
                query = {'referenceId': reference_id, 'locationId': location_id, 'resultNegative': result_json}
                url = f"https://{self.pemt_host}:{self.pemt_port}/negative-answer"
            elif result == "unknown":
                query = {'referenceId': reference_id, 'locationId': location_id, 'stateUnknown': result_json}
                url = f"https://{self.pemt_host}:{self.pemt_port}/unknown-answer"
            else:
                query = {'referenceId': reference_id, 'locationId': location_id, "partnerId": partner_id,
                         'commandControl': command_control, 'commandRegular': command_regular}
                url = f"https://{self.pemt_host}:{self.pemt_port}/information-control-signal"

            # POST to the pEMT (HTTPS)
            response = self.session.post(
                url,
                headers=headers,
                json=query,
                timeout=5,
            )
            self.logger.info(f"Answer sent to pEMT ({url}), HTTP {response.status_code}.")

        except Exception as e:
            self.logger.error(f"PEMT-Answer error: {e}")
            return None