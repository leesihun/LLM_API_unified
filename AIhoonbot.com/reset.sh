#!/bin/bash
set -euo pipefail

# Full local runtime reset for AIhoonbot.com.
# This removes generated state (databases, logs, uploads, caches),
# but keeps source code and dependency installs.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS_FILE="$SCRIPT_DIR/settings.txt"

if [[ ! -f "$SETTINGS_FILE" ]]; then
    echo "[ERROR] settings.txt not found at: $SETTINGS_FILE"
    exit 1
fi

source "$SETTINGS_FILE"

ASSUME_YES=false
if [[ "${1:-}" == "-y" || "${1:-}" == "--yes" ]]; then
    ASSUME_YES=true
fi

if [[ "$ASSUME_YES" != "true" ]]; then
    echo "This will permanently delete local runtime data:"
    echo "  - ./logs"
    echo "  - ./Hoonbot/data (including hoonbot.db and .apikey)"
    echo "  - ./Messenger/server/data (including messenger.db)"
    echo "  - ./Messenger/server/uploads"
    echo "  - ./ClaudeCodeWrapper/logs"
    echo "  - Python cache files (__pycache__, *.pyc)"
    echo
    read -r -p "Type RESET to continue: " CONFIRM
    if [[ "$CONFIRM" != "RESET" ]]; then
        echo "Cancelled."
        exit 0
    fi
fi

echo "[1/4] Stopping running services..."
pkill -f "python3 hoonbot.py" 2>/dev/null || true
pkill -f "python hoonbot.py" 2>/dev/null || true
pkill -f "run_backend.py" 2>/dev/null || true
pkill -f "tools_server.py" 2>/dev/null || true
pkill -f "npm run dev:server" 2>/dev/null || true
pkill -f "ClaudeCodeWrapper/run.py" 2>/dev/null || true
pkill -f "cloudflared" 2>/dev/null || true
sleep 1

echo "[2/4] Removing runtime data..."
rm -rf "$SCRIPT_DIR/logs"
rm -rf "$SCRIPT_DIR/Hoonbot/data"
rm -rf "$SCRIPT_DIR/Messenger/server/data"
rm -rf "$SCRIPT_DIR/Messenger/server/uploads"
rm -rf "$SCRIPT_DIR/ClaudeCodeWrapper/logs"

echo "[3/4] Removing Python caches..."
find "$SCRIPT_DIR" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "$SCRIPT_DIR" -type f -name "*.pyc" -delete

echo "[4/4] Recreating clean directories..."
mkdir -p "$SCRIPT_DIR/logs"
mkdir -p "$SCRIPT_DIR/Hoonbot/data"
mkdir -p "$SCRIPT_DIR/Messenger/server/data"
mkdir -p "$SCRIPT_DIR/Messenger/server/uploads"
mkdir -p "$SCRIPT_DIR/ClaudeCodeWrapper/logs"

echo
echo "Reset complete."
echo "You can start fresh with: ./start-all.sh"
