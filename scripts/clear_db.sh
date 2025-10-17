#!/usr/bin/env bash

set -euo pipefail

usage() {
    cat <<'EOF'
Usage: clear_db.sh [options]

Options (aliases supported):
  --wallet.name NAME     Wallet coldkey name (alias: --wallet)
  --wallet.hotkey NAME   Wallet hotkey name (alias: --hotkey)
  --netuid NUM           Netuid number (default: 117)
  --neuron.name NAME     Neuron name (alias: --neuron)
  --logging-dir PATH     Root logging directory (default: ~/.bittensor/miners)
  --dry-run              Show what would be removed without deleting files
  -h, --help             Show this help message

Environment overrides:
  WALLET_NAME, HOTKEY_NAME, NETUID, NEURON_NAME, LOGGING_DIR
EOF
}

WALLET_NAME="${WALLET_NAME:-owner}"
HOTKEY_NAME="${HOTKEY_NAME:-default}"
NETUID_VALUE="${NETUID:-117}"
NEURON_NAME="${NEURON_NAME:-validator}"
LOGGING_DIR="${LOGGING_DIR:-$HOME/.bittensor/miners}"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --wallet|--wallet.name)
            WALLET_NAME="$2"
            shift 2
            ;;
        --wallet.hotkey|--hotkey)
            HOTKEY_NAME="$2"
            shift 2
            ;;
        --netuid)
            NETUID_VALUE="$2"
            shift 2
            ;;
        --neuron|--neuron.name)
            NEURON_NAME="$2"
            shift 2
            ;;
        --logging-dir)
            LOGGING_DIR="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            exit 2
            ;;
    esac
done

NETUID_DIR="$NETUID_VALUE"
if [[ "$NETUID_DIR" != netuid* ]]; then
    NETUID_DIR="netuid${NETUID_DIR}"
fi

DB_DIR="${LOGGING_DIR}/${WALLET_NAME}/${HOTKEY_NAME}/${NETUID_DIR}/${NEURON_NAME}"
DB_FILE="${DB_DIR}/scores.db"

if [[ ! -f "$DB_FILE" ]]; then
    echo "No scores.db found at ${DB_FILE}"
    exit 0
fi

echo "Clearing validator score database at ${DB_FILE}"
if [[ "$DRY_RUN" == true ]]; then
    echo "[dry-run] Would remove:"
    printf '  %s\n' "$DB_FILE" "${DB_FILE}-shm" "${DB_FILE}-wal"
    exit 0
fi

rm -f -- "$DB_FILE" "${DB_FILE}-shm" "${DB_FILE}-wal"
echo "Removed scores.db and related WAL/SHM files."
