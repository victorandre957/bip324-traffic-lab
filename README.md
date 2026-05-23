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

This project depends on the local Warnet checkout through `../warnet`, so the
directory layout should look like this:

```text
folder/
  bip324-traffic-lab/
  warnet/
```

Clone Warnet if it is not present yet:

```bash
git clone https://github.com/bitcoin-dev-project/warnet.git
```

## Setup

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e warnet
warnet setup
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
Bitcoin transaction values, and per-component derived seeds. Exact PCAP bytes
can still vary because Kubernetes scheduling and packet timing are not fully
deterministic.

## Traffic

- Bitcoin regtest tanks with P2P v2/BIP324 enabled
- HTTP on `8080`
- HTTPS/TLS 1.3 on `8443`
- UDP streaming on `5000`
- private/local Tor traffic
- BitTorrent traffic with `libtorrent` on `6881`

## Example result

A completed run produces one capture, one Bitcoin Core debug log per tank,
`ip-map.txt`, and `metadata.json` with the seed used for the run.
