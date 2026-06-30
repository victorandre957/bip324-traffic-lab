import os
import random
import socket
import time


SERVER = os.environ["SERVER"]
PORT = int(os.environ["PORT"])
MIN_SLEEP_MS = int(os.environ["MIN_SLEEP_MS"])
MAX_SLEEP_MS = int(os.environ["MAX_SLEEP_MS"])
MIN_BYTES = int(os.environ["MIN_BYTES"])
MAX_BYTES = int(os.environ["MAX_BYTES"])
SEED = os.environ["SEED"]


class Obfs4NoiseClient:
    def __init__(self):
        self.rng = random.Random(SEED)

    def run_forever(self):
        print(f"[obfs4-noise-client] target {SERVER}:{PORT}", flush=True)
        while True:
            try:
                self.run_session()
            except OSError as exception:
                print(f"[obfs4-noise-client] retrying after error: {exception}", flush=True)
                time.sleep(2)

    def run_session(self):
        with socket.create_connection((SERVER, PORT), timeout=5) as conn:
            conn.settimeout(2.0)
            conn.sendall(self.random_payload(64, 1536))
            try:
                conn.recv(4096)
            except socket.timeout:
                pass
            while True:
                conn.sendall(self.random_payload(MIN_BYTES, MAX_BYTES))
                try:
                    conn.recv(4096)
                except socket.timeout:
                    pass
                sleep_ms = self.rng.randint(MIN_SLEEP_MS, MAX_SLEEP_MS)
                time.sleep(sleep_ms / 1000.0)

    def random_payload(self, min_bytes, max_bytes):
        size = self.rng.randint(min_bytes, max_bytes)
        return bytes(self.rng.getrandbits(8) for _ in range(size))


Obfs4NoiseClient().run_forever()
