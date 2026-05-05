#!/usr/bin/env bash
# =============================================================
#  Hoonbot — Installer
#  Run once after cloning or when setting up a new machine.
#  Usage: ./install.sh
# =============================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=================================================="
echo "  Hoonbot — Installing dependencies"
echo "=================================================="
echo

# --- Python version check ---
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] python3 not found. Install Python >= 3.10 first."
    exit 1
fi
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[OK] Python $PY_VER"

# --- pip install ---
echo "[1/2] Installing Python dependencies..."
pip install -r "$SCRIPT_DIR/deps/requirements.txt"
echo "[OK] Dependencies installed."
echo

# --- Credential setup ---
echo "[2/2] Checking LLM API credentials..."
if [[ ! -f "$SCRIPT_DIR/data/.llm_key" || ! -f "$SCRIPT_DIR/data/.llm_model" ]]; then
    echo "  Credentials not found. Running setup..."
    mkdir -p "$SCRIPT_DIR/data"
    python3 "$SCRIPT_DIR/scripts/setup_credentials.py"
else
    echo "[OK] Credentials already configured (data/.llm_key, data/.llm_model)."
fi
echo

echo "=================================================="
echo "  Installation complete! Run: ./start.sh"
echo "=================================================="
