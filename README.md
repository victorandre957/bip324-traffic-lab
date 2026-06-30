# BIP324 Traffic Lab

Warnet-based traffic lab for passive Bitcoin P2P v2/BIP324 analysis.

The runner starts the ISP sniffer first, then the background noise, then the
Bitcoin nodes. Results are written to `bip324-traffic-lab/results/`.

## Requirements

- Python 3.11 or newer
- `kubectl` access to a Kubernetes cluster
- `helm`
- Docker images used by the Helm charts available to the cluster
- Warnet cloned as a sibling directory of `bip324-traffic-lab/`
- a local Bitcoin Core build in `bitcoin/build/bin/`

This project depends on the local Warnet checkout through `../warnet`, so the
directory layout should look like this:

```text
folder/
  bitcoin/
  bip324-traffic-lab/
  warnet/
```

Clone Warnet if it is not present yet:

```bash
git clone https://github.com/bitcoin-dev-project/warnet.git
```

## Setup

From the directory that contains `bitcoin/`, `bip324-traffic-lab/`, and
`warnet/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e warnet
warnet setup
```

Build the Bitcoin Core image used by the tanks:

```bash
bip324-traffic-lab/scripts/build_bitcoin_image.sh
```

Load it into the Kubernetes cluster if the cluster does not use the local
Docker image store:

```bash
minikube image load bip324-traffic-lab-bitcoin:28.1.0-decoy
```

For Kind, use:

```bash
kind load docker-image bip324-traffic-lab-bitcoin:28.1.0-decoy
```

## Run

Run a 10-minute simulation:

```bash
source .venv/bin/activate
python bip324-traffic-lab/scripts/run_simulation.py 10
```

Run with a reproducible seed:

```bash
source .venv/bin/activate
python bip324-traffic-lab/scripts/run_simulation.py 10 --seed demo-seed-001
```

The Bash wrapper is also available:

```bash
bip324-traffic-lab/scripts/run_simulation.sh 10 --seed demo-seed-001
```

## Outputs

Default output:

```text
bip324-traffic-lab/results/
  run-YYYYMMDDHHMMSS/
    isp-capture.pcap
    tank-0001-debug.log
    tank-0002-debug.log
    tank-0003-debug.log
    tank-0004-debug.log
    tank-0005-debug.log
    ip-map.txt
    metadata.json
```

After installing the analyzer dependencies, analyze the generated data with:

```bash
cd bip324-traffic-analysis
python run_analysis.py --data-dir ../bip324-traffic-lab/results
```

## Reproducibility

If `--seed` is provided, the run uses that exact seed. Otherwise, the runner
generates one and stores it in `metadata.json`.

The seed fixes generated payloads, BitTorrent file contents, noise parameters,
Bitcoin transaction profiles, jittered block/transaction timing, and
per-component derived seeds. Exact PCAP bytes can still vary because Kubernetes
scheduling and packet timing are not fully deterministic.

## Traffic

- Five Bitcoin regtest tanks with P2P v2/BIP324 enabled. The first three form
  the initial mesh; `tank-0004` and `tank-0005` join the original three halfway
  through the capture window.
- The tanks use the custom local Bitcoin Core image. The runner connects tanks
  by pod IP and the P2P port reported by Bitcoin Core settings when available,
  falling back to regtest's default `18444`.
- Bitcoin traffic uses deterministic node profiles: a miner, a heavy sender, a
  light sender, a delayed bursty sender, and a delayed quiet peer. The runner
  adds seeded jitter to block and transaction intervals, and varies transaction
  output counts and amounts by profile. These profiles are recorded in
  `metadata.json` for reproducibility.
- HTTP on `8080`
- HTTPS/TLS 1.3 on `8443`
- UDP streaming on `5000`
- obfs4-shaped TCP noise on `14444`
- private/local Tor traffic
- BitTorrent traffic with `libtorrent` on `6881`

## Example result

A completed run produces one capture, one Bitcoin Core debug log per tank,
`ip-map.txt`, and `metadata.json` with the seed and delayed-node join metadata
used for the run.
