import http.server
import os
import random
import ssl


MIN_BYTES = int(os.environ["MIN_BYTES"])
MAX_BYTES = int(os.environ["MAX_BYTES"])
PORT = int(os.environ["PORT"])
SEED = os.environ["SEED"]


class Payload:
    def __init__(self, min_bytes, max_bytes, seed):
        self.min_bytes = min_bytes
        self.max_bytes = max_bytes
        self.rng = random.Random(seed)

    def build(self):
        size = self.rng.randint(self.min_bytes, self.max_bytes)
        return bytes(self.rng.getrandbits(8) for _ in range(size))


class Handler(http.server.BaseHTTPRequestHandler):
    payload = Payload(MIN_BYTES, MAX_BYTES, SEED)

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


context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.minimum_version = ssl.TLSVersion.TLSv1_3
context.maximum_version = ssl.TLSVersion.TLSv1_3
context.load_cert_chain("/tls/tls.crt", "/tls/tls.key")
server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
server.socket = context.wrap_socket(server.socket, server_side=True)
print(f"[https-server] listening on {PORT} with TLS 1.3", flush=True)
server.serve_forever()
