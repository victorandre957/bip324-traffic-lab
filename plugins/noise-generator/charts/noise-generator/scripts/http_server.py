import http.server
import os
import random


MIN_BYTES = int(os.environ["MIN_BYTES"])
MAX_BYTES = int(os.environ["MAX_BYTES"])
PORT = int(os.environ["PORT"])
SEED = os.environ["SEED"]


class RandomPayload:
    def __init__(self, min_bytes, max_bytes, seed):
        self.min_bytes = min_bytes
        self.max_bytes = max_bytes
        self.rng = random.Random(seed)

    def build(self):
        size = self.rng.randint(self.min_bytes, self.max_bytes)
        return bytes(self.rng.getrandbits(8) for _ in range(size))


class NoiseRequestHandler(http.server.BaseHTTPRequestHandler):
    payload = RandomPayload(MIN_BYTES, MAX_BYTES, SEED)

    def do_GET(self):
        body = self.payload.build()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt, *args):
        return


print(f"[noise-server] listening on {PORT}", flush=True)
server = http.server.HTTPServer(("0.0.0.0", PORT), NoiseRequestHandler)
server.serve_forever()
