#!/bin/bash
# TrueNAS Scale RPi - Startup Script
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================="
echo "  TrueNAS Scale RPi Backend v0.1.0"
echo "============================================="

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found"
    exit 1
fi

# Prefer project virtualenv if present
PYTHON="$SCRIPT_DIR/.venv/bin/python3"
if [[ ! -x "$PYTHON" ]]; then
    PYTHON=python3
fi

# Check/install dependencies
echo "Checking dependencies..."
if [[ "$PYTHON" != "python3" ]]; then
    "$PYTHON" -c "import websockets, aiohttp, orjson, psutil, bcrypt" 2>/dev/null \
        || "$PYTHON" -m pip install -q websockets aiohttp orjson psutil bcrypt || true
else
    pip3 install -q websockets aiohttp orjson psutil bcrypt 2>/dev/null || true
fi

# Build Cython extensions if available
if command -v cython &> /dev/null && [ "$BUILD_CYTHON" = "1" ]; then
    echo "Building Cython extensions..."
    "$PYTHON" setup.py build_ext --inplace
fi

# Create data directory
mkdir -p /var/lib/truenas-rpi

# Handle signals
cleanup() {
    echo "Shutting down TrueNAS Scale RPi..."
    kill $(jobs -p) 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM

echo "Starting server on 0.0.0.0:80..."
echo "Web UI should be served at http://$(hostname -I | awk '{print $1}')"
echo ""
echo "Default login: admin / admin"
echo "(Change password immediately!)"
echo ""

"$PYTHON" run.py "$@"
