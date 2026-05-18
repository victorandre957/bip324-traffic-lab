import http.server
import os
import random
import socketserver
import threading
import time
from pathlib import Path

import libtorrent as lt


LISTEN_PORT = int(os.environ["LISTEN_PORT"])
METADATA_PORT = int(os.environ["METADATA_PORT"])
PAYLOAD_BYTES = int(os.environ["PAYLOAD_BYTES"])
PIECE_BYTES = int(os.environ["PIECE_BYTES"])
SEED = os.environ["SEED"]
DATA_DIR = Path("/data")
PAYLOAD = DATA_DIR / "seed-payload.bin"
TORRENT = DATA_DIR / "seed-payload.torrent"


def write_payload():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    remaining = PAYLOAD_BYTES
    with PAYLOAD.open("wb") as file_obj:
        while remaining > 0:
            chunk_size = min(65536, remaining)
            file_obj.write(bytes(rng.getrandbits(8) for _ in range(chunk_size)))
            remaining -= chunk_size


def write_torrent():
    os.chdir(DATA_DIR)
    storage = lt.file_storage()
    lt.add_files(storage, PAYLOAD.name)
    torrent = lt.create_torrent(storage, PIECE_BYTES)
    torrent.set_creator("bip324-traffic-lab-libtorrent")
    lt.set_piece_hashes(torrent, str(DATA_DIR))
    TORRENT.write_bytes(lt.bencode(torrent.generate()))


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return


def serve_metadata():
    os.chdir(DATA_DIR)
    server = socketserver.TCPServer(("0.0.0.0", METADATA_PORT), QuietHandler)
    print(f"[torrent-server] metadata on {METADATA_PORT}", flush=True)
    server.serve_forever()


def seed_forever():
    settings = {
        "listen_interfaces": f"0.0.0.0:{LISTEN_PORT}",
        "enable_dht": False,
        "enable_lsd": False,
        "enable_upnp": False,
        "enable_natpmp": False,
    }
    session = lt.session(settings)
    info = lt.torrent_info(str(TORRENT))
    params = {
        "ti": info,
        "save_path": str(DATA_DIR),
        "flags": lt.torrent_flags.seed_mode,
    }
    handle = session.add_torrent(params)
    print(f"[torrent-server] seeding {PAYLOAD_BYTES} bytes on {LISTEN_PORT}", flush=True)
    while True:
        status = handle.status()
        print(f"[torrent-server] peers={status.num_peers} up={status.total_upload}", flush=True)
        time.sleep(30)


write_payload()
write_torrent()
threading.Thread(target=serve_metadata, daemon=True).start()
seed_forever()
