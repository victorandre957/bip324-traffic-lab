#!/usr/bin/env bash
set -e

if [[ "${1:0:1}" == "-" ]]; then
  set -- bitcoind "$@"
fi

if [[ "${1:0:1}" == "-" || "$1" == "bitcoind" ]]; then
  mkdir -p "$BITCOIN_DATA"
  chmod 700 "$BITCOIN_DATA"
  echo "$0: setting data directory to $BITCOIN_DATA"
  set -- "$@" -datadir="$BITCOIN_DATA"
fi

if [[ -n "${BITCOIN_ARGS:-}" ]]; then
  read -r -a arg_array <<< "$BITCOIN_ARGS"
  set -- "$@" "${arg_array[@]}"
fi

echo
exec "$@"
