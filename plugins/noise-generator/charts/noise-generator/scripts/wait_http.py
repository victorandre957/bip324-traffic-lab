import contextlib
import http.client
import os
import time


SERVER = os.environ["SERVER"]
PORT = int(os.environ["PORT"])


while True:
    connection = None
    try:
        connection = http.client.HTTPConnection(SERVER, PORT, timeout=2)
        connection.request("GET", "/")
        connection.getresponse().read()
        break
    except Exception:
        time.sleep(2)
    finally:
        with contextlib.suppress(Exception):
            connection.close()
