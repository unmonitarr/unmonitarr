#!/bin/bash
# Run unmonitarr locally using the .env file in the repo root.
set -e
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "Error: .env not found. Copy .env.example to .env and fill it in."
    exit 1
fi

# Load .env (shell syntax: inline comments and quoted values are fine).
# Sourced directly because macOS /bin/bash 3.2 can't source process substitution.
set -a
# shellcheck disable=SC1091
. ./.env
set +a

export PYTHONPATH=src
exec python3 src/main.py
