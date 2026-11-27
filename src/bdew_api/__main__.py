import sys
import argparse
import socket
import time

from bdew_api.bdew import BDEW


def _wait_until_listening(host: str, port: int, timeout: float = 5.0) -> bool:
    """Wait until a server accepts TCP connections (servers start in background threads)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


#aemt_id: str, aemt_host: str, aemt_port: int, pemt_id:str, pemt_host: str, pemt_port: int
def main():
    parser = argparse.ArgumentParser(description='establish bdew api communication')
    parser.add_argument('aemt_id',
                        metavar='aemt_id',
                        type=str,
                        help='id of the aemt component')
    parser.add_argument('aemt_host',
                        metavar='aemt_host',
                        type=str,
                        help='host of the aemt component')
    parser.add_argument('aemt_port',
                        metavar='aemt_port',
                        type=int,
                        help='port of the aemt component')
    parser.add_argument('pemt_id',
                        metavar='pemt_id',
                        type=str,
                        help='id of the pemt component')
    parser.add_argument('pemt_host',
                        metavar='pemt_host',
                        type=str,
                        help='host of the pemt component')
    parser.add_argument('pemt_port',
                        metavar='pemt_port',
                        type=int,
                        help='port of the pemt component')

    argvs = sys.argv
    aemt_id = argvs[1]
    aemt_host = argvs[2]
    aemt_port = int(argvs[3])
    pemt_id = argvs[4]
    pemt_host = argvs[5]
    pemt_port = int(argvs[6])
    bdew = BDEW(aemt_id,aemt_host,aemt_port,pemt_id,pemt_host,pemt_port)
    # Demo of both sides in one process: wait for the servers that did start
    # (a side without TLS material stays inactive and only logs warnings).
    for server, host, port in ((bdew.control_demand_server, aemt_host, aemt_port),
                               (bdew.answer_state_server, pemt_host, pemt_port)):
        if server.ssl_context is not None and not _wait_until_listening(host, port):
            print(f"server on {host}:{port} did not come up", file=sys.stderr)
    bdew.send_control_request(None,None)
    bdew.send_control_status("positive")

if __name__ == "__main__":
    main()
