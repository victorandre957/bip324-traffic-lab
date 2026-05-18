#!/bin/sh
set -e
python3 -m pip install --no-cache-dir --quiet libtorrent==2.0.11
exec python3 /scripts/torrent_client.py
