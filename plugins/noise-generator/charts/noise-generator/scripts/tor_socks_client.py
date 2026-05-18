import os
import random
import socket
import time


SOCKS_HOST = "127.0.0.1"
SOCKS_PORT = 9050
TARGET_HOST = os.environ["TARGET_HOST"]
TARGET_PORT = int(os.environ["TARGET_PORT"])
MIN_SLEEP = int(os.environ["MIN_SLEEP_MS"]) / 1000.0
MAX_SLEEP = int(os.environ["MAX_SLEEP_MS"]) / 1000.0
SEED = os.environ["SEED"]


class TorSocksClient:
    def __init__(self):
        self.rng = random.Random(SEED)

    def run_forever(self):
        print(f"[tor-app-client] target {TARGET_HOST}:{TARGET_PORT} via SOCKS", flush=True)
        while True:
            try:
                self.fetch_once()
            except Exception as exception:
                print(f"[tor-app-client] retrying after error: {exception}", flush=True)
                time.sleep(3)
            time.sleep(self.rng.uniform(MIN_SLEEP, MAX_SLEEP))

    def fetch_once(self):
        with socket.create_connection((SOCKS_HOST, SOCKS_PORT), timeout=10) as sock:
            sock.settimeout(10)
            sock.sendall(b"\x05\x01\x00")
            if sock.recv(2) != b"\x05\x00":
                raise RuntimeError("SOCKS authentication negotiation failed")
            host = TARGET_HOST.encode("idna")
            request = b"\x05\x01\x00\x03" + bytes([len(host)]) + host + TARGET_PORT.to_bytes(2, "big")
            sock.sendall(request)
            response = sock.recv(10)
            if len(response) < 2 or response[1] != 0:
                raise RuntimeError(f"SOCKS connect failed: {response.hex()}")
            http = (
                f"GET /tor-noise-{self.rng.randint(1, 1000000)} HTTP/1.1\r\n"
                f"Host: {TARGET_HOST}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            sock.sendall(http)
            while sock.recv(4096):
                pass


TorSocksClient().run_forever()
