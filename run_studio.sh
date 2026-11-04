#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 not found on your system."
    exit 1
fi

echo "==============================================================================="
echo "               PrimeFilm 1800u / 1800i Studio Desktop UI"
echo "==============================================================================="
exec python3 "${SCRIPT_DIR}/scripts/primefilm_studio_app.py" "$@"
