import os
import socket
import time


SERVER = os.environ["SERVER"]
PORT = int(os.environ["PORT"])
HELLO_EVERY = int(os.environ["HELLO_EVERY"])


class StreamingClient:
    def __init__(self, server, port, hello_interval):
        self.server = server
        self.port = port
        self.hello_interval = hello_interval
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("0.0.0.0", 0))
        self.socket.settimeout(2.0)
        self.last_hello = 0

    def run_forever(self):
        print(f"[streaming-client] target {self.server}:{self.port}", flush=True)
        while True:
            try:
                self.send_hello_when_needed()
                self.receive_stream()
            except OSError as exception:
                # The client pod may start before the Kubernetes Service is in DNS.
                print(f"[streaming-client] retrying after error: {exception}", flush=True)
                time.sleep(2)

    def send_hello_when_needed(self):
        now = time.time()
        if now - self.last_hello >= self.hello_interval:
            self.socket.sendto(b"hello", (self.server, self.port))
            self.last_hello = now

    def receive_stream(self):
        try:
            self.socket.recvfrom(2048)
        except socket.timeout:
            return


StreamingClient(SERVER, PORT, HELLO_EVERY).run_forever()
