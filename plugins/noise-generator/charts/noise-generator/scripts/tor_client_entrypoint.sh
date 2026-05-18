#!/bin/bash
set -euo pipefail

until TORDA_IP="$(dig +short "${TORDA_HOST}" | head -n 1)" && [ -n "${TORDA_IP}" ]; do
  echo "[tor-client] waiting for DNS: ${TORDA_HOST}"
  sleep 2
done

cat >/tmp/torrc <<EOF
Log info stdout
DataDirectory /home/debian-tor/.tor
RunAsDaemon 0
SocksPort 127.0.0.1:9050
DirAuthority orport=${TOR_OR_PORT} no-v2 v3ident=${TOR_V3_IDENTITY} ${TORDA_IP}:${TOR_DIR_PORT} ${TOR_FINGERPRINT}
TestingTorNetwork 1
ClientUseIPv6 0
ClientUseIPv4 1
PathsNeededToBuildCircuits 0.25
MaxMemInQueues 64 Mbytes
BridgeRecordUsageByCountry 0
DirReqStatistics 0
EntryStatistics 0
HiddenServiceStatistics 0
OverloadStatistics 0
PaddingStatistics 0
EOF

cat /tmp/torrc
su -s /bin/sh debian-tor -c 'tor -f /tmp/torrc'
