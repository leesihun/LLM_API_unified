#!/usr/bin/env bash
# =============================================================
#  Huni Messenger — Installer
#  Run once after cloning or on a new machine.
#  Usage: ./install.sh
# =============================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================="
echo "  Huni Messenger — Installing"
echo "=================================================="
echo

# --- Node version check ---
if ! command -v node &>/dev/null; then
    echo "[ERROR] Node.js not found. Install Node >= 20 first."
    exit 1
fi
NODE_VER=$(node -e "process.stdout.write(process.versions.node)")
NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
if [[ "$NODE_MAJOR" -lt 20 ]]; then
    echo "[WARN] Node >= 20 recommended. Found: $NODE_VER"
fi
echo "[OK] Node $NODE_VER"

if ! command -v npm &>/dev/null; then
    echo "[ERROR] npm not found."
    exit 1
fi

# --- npm install ---
echo "[1/3] Installing npm dependencies (workspaces: server, client, shared)..."
npm install
echo "[OK] npm install done."
echo

# --- Build web client ---
echo "[2/3] Building web client (client/dist-web/)..."
npm run build:web
echo "[OK] Web client built."
echo

# --- Create data directories ---
echo "[3/3] Creating runtime directories..."
mkdir -p data/uploads server/chunks server/storage server/public
echo "[OK] Directories ready."
echo

# --- .env setup hint ---
if [[ ! -f ".env" ]]; then
    echo "[*] No .env found. Creating from .env.example..."
    cp ".env.example" ".env"
    echo "    Edit .env to customise ports, paths, and SECRET_TOKEN."
else
    echo "[OK] .env already exists."
fi
echo

echo "=================================================="
echo "  Installation complete! Run: ./start.sh"
echo "=================================================="
