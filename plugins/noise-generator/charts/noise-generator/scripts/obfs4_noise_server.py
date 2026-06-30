import os
import random
import socket
import threading
import time


PORT = int(os.environ["PORT"])
MIN_BYTES = int(os.environ["MIN_BYTES"])
MAX_BYTES = int(os.environ["MAX_BYTES"])
INTERVAL_MS = int(os.environ["INTERVAL_MS"])
SEED = os.environ["SEED"]


class Obfs4NoiseServer:
    def __init__(self):
        self.rng = random.Random(SEED)
        self.interval_seconds = INTERVAL_MS / 1000.0
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(("0.0.0.0", PORT))
        self.socket.listen(8)

    def run_forever(self):
        print(f"[obfs4-noise-server] listening on {PORT}", flush=True)
        while True:
            conn, address = self.socket.accept()
            print(f"[obfs4-noise-server] client {address}", flush=True)
            thread = threading.Thread(target=self.handle_client, args=(conn, address), daemon=True)
            thread.start()

    def handle_client(self, conn, address):
        local_rng = random.Random(f"{SEED}:{address}")
        conn.settimeout(2.0)
        try:
            conn.recv(4096)
            conn.sendall(self.random_payload(local_rng, 64, 1536))
            while True:
                conn.sendall(self.random_payload(local_rng, MIN_BYTES, MAX_BYTES))
                try:
                    conn.recv(4096)
                except socket.timeout:
                    pass
                time.sleep(self.interval_seconds)
        except OSError as exception:
            print(f"[obfs4-noise-server] closed {address}: {exception}", flush=True)
        finally:
            conn.close()

    @staticmethod
    def random_payload(rng, min_bytes, max_bytes):
        size = rng.randint(min_bytes, max_bytes)
        return bytes(rng.getrandbits(8) for _ in range(size))


Obfs4NoiseServer().run_forever()
