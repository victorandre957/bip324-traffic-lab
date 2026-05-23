import http.client
import os
import random
import time


SERVER = os.environ["SERVER"]
PORT = int(os.environ["PORT"])
MIN_SLEEP = int(os.environ["MIN_SLEEP"])
MAX_SLEEP = int(os.environ["MAX_SLEEP"])
SEED = os.environ["SEED"]


class NoiseClient:
    def __init__(self, server, port, min_sleep, max_sleep, seed):
        self.server = server
        self.port = port
        self.min_sleep = min_sleep
        self.max_sleep = max_sleep
        self.request_count = 0
        self.rng = random.Random(seed)

    def run_forever(self):
        print(f"[http-client] target {self.server}:{self.port}", flush=True)
        while True:
            self.request_count += 1
            self.get_payload()
            if self.request_count % 5 == 0:
                self.post_payload()
            time.sleep(self.rng.randint(self.min_sleep, self.max_sleep))

    def get_payload(self):
        connection = self.connection()
        connection.request("GET", "/")
        connection.getresponse().read()
        connection.close()

    def post_payload(self):
        size = self.rng.randint(512, 4096)
        payload = bytes(self.rng.getrandbits(8) for _ in range(size))
        connection = self.connection()
        connection.request(
            "POST",
            "/",
            body=payload,
            headers={"Content-Type": "application/octet-stream"},
        )
        connection.getresponse().read()
        connection.close()

    def connection(self):
        return http.client.HTTPConnection(self.server, self.port, timeout=5)


NoiseClient(SERVER, PORT, MIN_SLEEP, MAX_SLEEP, SEED).run_forever()
