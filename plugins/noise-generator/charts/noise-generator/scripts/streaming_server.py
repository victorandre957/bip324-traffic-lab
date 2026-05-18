import os
import random
import socket
import time


PORT = int(os.environ["PORT"])
MIN_BYTES = int(os.environ["MIN_BYTES"])
MAX_BYTES = int(os.environ["MAX_BYTES"])
INTERVAL_MS = int(os.environ["INTERVAL_MS"])
SEED = os.environ["SEED"]


class StreamingServer:
    def __init__(self, port, min_bytes, max_bytes, interval_ms, seed):
        self.port = port
        self.min_bytes = min_bytes
        self.max_bytes = max_bytes
        self.interval_seconds = interval_ms / 1000.0
        self.rng = random.Random(seed)
        self.client = None
        self.last_hello = 0
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("0.0.0.0", port))
        self.socket.settimeout(1.0)

    def run_forever(self):
        print(f"[streaming-server] listening on {self.port}", flush=True)
        while True:
            self.refresh_client()
            self.send_packet_when_client_exists()

    def refresh_client(self):
        try:
            _, address = self.socket.recvfrom(1024)
            self.client = address
            self.last_hello = time.time()
        except socket.timeout:
            self.clear_stale_client()

    def clear_stale_client(self):
        if self.client and (time.time() - self.last_hello) > 10:
            self.client = None

    def send_packet_when_client_exists(self):
        if not self.client:
            return
        size = self.rng.randint(self.min_bytes, self.max_bytes)
        payload = bytes(self.rng.getrandbits(8) for _ in range(size))
        self.socket.sendto(payload, self.client)
        time.sleep(self.interval_seconds)


StreamingServer(PORT, MIN_BYTES, MAX_BYTES, INTERVAL_MS, SEED).run_forever()
