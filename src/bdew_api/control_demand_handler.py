from bdew_api.utils import setup_logger
from bdew_api import id_generator as id_gen

#formerly AEMTHandler
#api between pemt and aemt
#pemt sends message with need for regulation command to aemt
#(aemt requests regulation command, sends request to gwa, smgw: establish cls channel to controlbox)
#aemt answers with command request delivered successfully or not delivered
#API (Application Programming Interface) implements BNetzA ruling BK6-22-128
#specs: openapi 3.0.0, version 1.0.0. Official title (German): "EDI@Energy
#API-Webdienste zur prozessualen Abwicklung von Steuerungshandlungen in
#Verbindung mit intelligenten Messsystemen (iMS) - Universalbestellprozess"

class ControlDemandHandler:
    def __init__(self, pemt_id: str, aemt_id: str, aemt_host: str, aemt_port: int, logic_callback=None,
                 session=None):
        self.pemt_id = pemt_id
        self.aemt_id = aemt_id
        self.aemt_host = aemt_host
        self.aemt_port = aemt_port
        # Setup logging
        self.logger = setup_logger("AEMT", pemt_id)
        self.logic_callback = logic_callback
        # Mutual-TLS client session (tls_config.requests_session); None = TLS setup failed
        self.session = session

    def send_demand_control(self, command_control: dict = None, location_id: str = None):
        """Report control demand to the aEMT (universal ordering process).

        Triggered by the pEMT when the grid-state estimation reports a
        congestion. Without ``command_control`` a default control command
        (power limitation) is sent; a dict with only ``executionTimeFrom``
        triggers ``command-regular`` instead (return to normal state).

        ``location_id`` identifies the affected device (mME ID from the routing
        table), so the aEMT can resolve the household group and controlbox;
        without it, a generated location ID is sent.
        """
        if self.session is None:
            self.logger.warning("Control demand not sent — no TLS session (TLS setup failed).")
            return None
        self.logger.info("━" * 100)
        self.logger.info(" " * 44 + "Control Demand Handler")
        self.logger.info("━" * 100)

        self.logger.info(
            f"Sending control demand to {self.aemt_host}:{self.aemt_port} - Control Signal needs to be send to Control Box.")

        id_generator = id_gen.IDGenerator
        #ID format: string($UUID RFC9562)
        #transactionId: external, unique, info about a control command confirmed by the GWA?
        transaction_id = id_generator.generate_transaction_id()
        #timestamp of (this?) call
        creation_date_time = id_generator.generate_datetimestamp()
        #idempotency key, provided in case of a retry
        initial_transaction_id = transaction_id
        #locationId: identifies the resource the control command acts on
        if location_id is None:
            location_id = id_generator.generate_location_id()

        #commandControl: default control command (power limitation)
        if command_control is None:
            command_control = {
                "maximumPowerValue": "24.123",
                "executionTimeFrom": id_generator.generate_datetimestamp(),
                "executionTimeUntil": id_generator.generate_datetimestamp(),
            }

        try:
            #build header and query for http request
            headers = {'transactionId':transaction_id, 'creationDateTime':creation_date_time,
                       'initialTransactionId':initial_transaction_id}
            if len(command_control.keys()) > 1:
                query = {'locationId':location_id,'commandControl':command_control}
                url = f"https://{self.aemt_host}:{self.aemt_port}/command-control"
            else:
                #command: set to initial state
                query = {'locationId': location_id, 'commandRegular': command_control}
                url = f"https://{self.aemt_host}:{self.aemt_port}/command-regular"

            # Attempt POST to the aEMT (HTTPS)
            response = self.session.post(
                url,
                headers=headers,
                json=query,
                timeout=5,
            )
            self.logger.info(f"Control demand sent to aEMT ({url}), HTTP {response.status_code}.")

        except Exception as e:
            self.logger.error(f"AEMT-Answer error: {e}")
            return None
