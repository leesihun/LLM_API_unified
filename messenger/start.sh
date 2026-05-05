#!/usr/bin/env bash
# =============================================================
#  Huni Messenger — Start Script
#  Usage: ./start.sh [--background] [--prod]
# =============================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BACKGROUND=false
PROD=false
for arg in "$@"; do
    [[ "$arg" == "--background" ]] && BACKGROUND=true
    [[ "$arg" == "--prod" ]] && PROD=true
done

echo "=================================================="
echo "  Huni Messenger — Starting"
echo "=================================================="
echo

# --- Preflight: .env ---
if [[ ! -f ".env" ]]; then
    if [[ -f ".env.example" ]]; then
        echo "[*] No .env found. Copying from .env.example..."
        cp ".env.example" ".env"
    else
        echo "[ERROR] Neither .env nor .env.example found."
        exit 1
    fi
fi

# Source .env so PORT etc are available in this script
set -a; source ".env"; set +a

PORT="${PORT:-10006}"

# --- Preflight: built client ---
if [[ ! -f "client/dist-web/index.html" ]]; then
    echo "[*] Web client not built. Running npm run build:web..."
    npm run build:web
fi

# --- Preflight: node_modules ---
if [[ ! -d "node_modules" ]]; then
    echo "[*] node_modules missing. Running npm install..."
    npm install
fi

echo "[*] Messenger port: $PORT"
echo

# --- Launch ---
LOG_FILE="data/messenger.log"
mkdir -p data

if $BACKGROUND; then
    echo "[*] Starting Messenger in background (logs → $LOG_FILE)..."
    if $PROD; then
        nohup npm start > "$LOG_FILE" 2>&1 &
    else
        nohup npm run dev:server > "$LOG_FILE" 2>&1 &
    fi
    PID=$!
    # Wait for health endpoint
    echo "[*] Waiting for Messenger to be ready..."
    for i in $(seq 1 20); do
        if curl -fsS "http://localhost:${PORT}/health" >/dev/null 2>&1; then
            echo "[OK] PID $PID — Messenger ready at http://localhost:${PORT}"
            break
        fi
        sleep 1
    done
else
    echo "[*] Starting Messenger (foreground, Ctrl+C to stop)..."
    echo "    URL: http://localhost:${PORT}"
    echo
    if $PROD; then
        npm start
    else
        npm run dev:server
    fi
fi
