#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LAB_DIR="$WORKSPACE_DIR/bip324-traffic-lab"
IMAGE_TAG="${1:-bip324-traffic-lab-bitcoin:28.1.0-decoy}"
BUILD_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$BUILD_DIR"
}
trap cleanup EXIT

mkdir -p "$BUILD_DIR/bin"
cp "$WORKSPACE_DIR/bitcoin/build/bin/bitcoind" "$BUILD_DIR/bin/bitcoind"
cp "$WORKSPACE_DIR/bitcoin/build/bin/bitcoin-cli" "$BUILD_DIR/bin/bitcoin-cli"
cp "$LAB_DIR/docker/bitcoin/Dockerfile" "$BUILD_DIR/Dockerfile"
cp "$LAB_DIR/docker/bitcoin/entrypoint.sh" "$BUILD_DIR/entrypoint.sh"

docker build -t "$IMAGE_TAG" "$BUILD_DIR"
