# BIP324 Traffic Lab

Warnet lab for generating controlled Bitcoin P2P v2/BIP324 packet captures.

This project creates PCAPs, Bitcoin Core logs, IP maps, and reproducibility
metadata. It does not analyze captures. Analysis remains a separate step in
`bip324-traffic-analysis`.

## Scenario

The default scenario contains:

- five Bitcoin regtest nodes using P2P v2;
- sparse connections, delayed joins, and different traffic roles;
- configurable transaction and block load;
- deterministic delay, jitter, and optional packet loss;
- HTTP, HTTPS, Tor, obfs4-shaped, BitTorrent, and UDP noise;
- one passive bridge-interface sniffer.

Node profiles and noise settings are stored in `metadata.json`. They are lab
inputs and must not be used by passive detection.

## Requirements

- Python 3.11 or newer;
- `kubectl` and `helm`;
- a running Kubernetes cluster, such as Minikube;
- Warnet cloned as `../warnet`;
- Bitcoin Core available in `../bitcoin`.

Expected layout:

```text
folder/
  bitcoin/
  bip324-traffic-lab/
  warnet/
```

## Setup

From `folder/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e warnet
warnet setup
```

Build and load the Bitcoin image:

```bash
bip324-traffic-lab/scripts/build_bitcoin_image.sh
minikube image load bip324-traffic-lab-bitcoin:28.1.0-decoy
```

For Kind, replace the last command with:

```bash
kind load docker-image bip324-traffic-lab-bitcoin:28.1.0-decoy
```

## Run

Example 15-minute run with a fixed seed and larger blocks:

```bash
bip324-traffic-lab/scripts/run_simulation.sh 15 \
  --block-profile mainnet-like \
  --seed mainnet-like-01
```

Shorter default run:

```bash
python bip324-traffic-lab/scripts/run_simulation.py 10
```

Available block profiles:

| Profile | Intended use |
| --- | --- |
| `small` | quick checks |
| `medium` | default workload |
| `mainnet-like` | larger synthetic blocks |

These are workload targets, not guarantees about final serialized block size.

## Output

Each run creates:

```text
bip324-traffic-lab/results/run-YYYYMMDDHHMMSS/
  isp-capture.pcap
  tank-0001-debug.log
  ...
  tank-0005-debug.log
  ip-map.txt
  metadata.json
  tcpdump-stats.log
  capture-environment.txt
```

The obfs4 client starts after the initial Bitcoin setup so its connection should
fall inside the useful validation interval. The runner records the actual
startup order in `metadata.json`.

## Reproducibility

`--seed` fixes generated payloads and configured pseudo-random choices. Exact
PCAP bytes can still differ because Kubernetes scheduling and packet timing are
not fully deterministic.
