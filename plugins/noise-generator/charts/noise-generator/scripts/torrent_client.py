import os
import shutil
import time
import urllib.request
from pathlib import Path

import libtorrent as lt


SERVER = os.environ["SERVER"]
PORT = int(os.environ["PORT"])
METADATA_PORT = int(os.environ["METADATA_PORT"])
CONNECTIONS = int(os.environ["CONNECTIONS"])
WORK = Path("/downloads")
TORRENT = WORK / "seed-payload.torrent"


def fetch_torrent():
    WORK.mkdir(parents=True, exist_ok=True)
    url = f"http://{SERVER}:{METADATA_PORT}/seed-payload.torrent"
    print(f"[torrent-client] fetching {url}", flush=True)
    with urllib.request.urlopen(url, timeout=10) as response:
        TORRENT.write_bytes(response.read())


def download_once(index):
    target = WORK / f"run-{index}"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    settings = {
        "listen_interfaces": "0.0.0.0:0",
        "enable_dht": False,
        "enable_lsd": False,
        "enable_upnp": False,
        "enable_natpmp": False,
        "connections_limit": CONNECTIONS + 8,
    }
    session = lt.session(settings)
    info = lt.torrent_info(str(TORRENT))
    handle = session.add_torrent({"ti": info, "save_path": str(target)})
    handle.connect_peer((SERVER, PORT))
    started = time.time()
    while not handle.status().is_seeding:
        status = handle.status()
        print(
            f"[torrent-client] run={index} progress={status.progress:.3f} "
            f"down={status.total_download} peers={status.num_peers}",
            flush=True,
        )
        if time.time() - started > 180:
            raise TimeoutError("torrent download timed out")
        time.sleep(5)
    print(f"[torrent-client] run={index} complete", flush=True)
    session.remove_torrent(handle)


fetch_torrent()
run_index = 0
while True:
    try:
        run_index += 1
        download_once(run_index)
    except Exception as exception:
        print(f"[torrent-client] retrying after error: {exception}", flush=True)
        time.sleep(5)
