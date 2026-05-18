#!/bin/bash
set -euo pipefail

until TORDA_IP="$(dig +short "${TORDA_HOST}" | head -n 1)" && [ -n "${TORDA_IP}" ]; do
  echo "[tor-da] waiting for DNS: ${TORDA_HOST}"
  sleep 2
done

IP_ADDR="$(ip addr show eth0 | grep "inet\b" | awk '{print $2}' | cut -d/ -f1)"

cat >/tmp/torrc <<EOF
Log info stdout
DataDirectory /home/debian-tor/.tor
RunAsDaemon 0
ControlPort 9051
ORPort ${TOR_OR_PORT} IPv4Only
DirPort ${TOR_DIR_PORT} IPv4Only
Address ${IP_ADDR}
DirAuthority orport=${TOR_OR_PORT} no-v2 v3ident=${TOR_V3_IDENTITY} ${TORDA_IP}:${TOR_DIR_PORT} ${TOR_FINGERPRINT}
AuthoritativeDirectory 1
V3AuthoritativeDirectory 1
ExitPolicy accept *:*
TestingTorNetwork 1
ClientUseIPv6 0
ClientUseIPv4 1
AssumeReachable 1
PathsNeededToBuildCircuits 0.25
TestingDirAuthVoteExit *
TestingDirAuthVoteHSDir *
V3AuthNIntervalsValid 2
MaxMemInQueues 200 Mbytes
BridgeRecordUsageByCountry 0
DirReqStatistics 0
ExtraInfoStatistics 0
HiddenServiceStatistics 0
OverloadStatistics 0
PaddingStatistics 0
ConstrainedSockets 1
ConstrainedSockSize 8192 Bytes
ContactInfo bip324-traffic-lab@warnet.local
EOF

cat /tmp/torrc
su -s /bin/sh debian-tor -c 'tor -f /tmp/torrc'
