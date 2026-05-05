#!/usr/bin/env bash
# =============================================================
#  Hoonbot — Start Script
#  Usage: ./start.sh [--background]
# =============================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BACKGROUND=false
for arg in "$@"; do
    [[ "$arg" == "--background" ]] && BACKGROUND=true
done

echo "=================================================="
echo "  Hoonbot — Starting"
echo "=================================================="
echo

# --- Read config values ---
MESSENGER_URL=$(python3 -c "import config; print(config.MESSENGER_URL)" 2>/dev/null || echo "http://localhost:10006")
LLM_API_URL=$(python3 -c "import config; print(config.LLM_API_URL)" 2>/dev/null || echo "http://localhost:10007")
HOONBOT_PORT=$(python3 -c "import config; print(config.HOONBOT_PORT)" 2>/dev/null || echo "3939")

# --- Preflight: credentials ---
if [[ ! -f "data/.llm_key" || ! -f "data/.llm_model" ]]; then
    echo "[WARN] LLM credentials not found. Running setup..."
    mkdir -p data
    python3 scripts/setup_credentials.py
fi

# --- Preflight: service reachability ---
echo "[*] Checking Messenger at $MESSENGER_URL..."
if curl -fsS "${MESSENGER_URL}/health" >/dev/null 2>&1; then
    echo "[OK] Messenger reachable."
else
    echo "[WARN] Messenger not reachable at ${MESSENGER_URL}."
    echo "       Hoonbot will retry registration on startup."
fi

echo "[*] Checking LLM API at $LLM_API_URL..."
if curl -fsS "${LLM_API_URL}/health" >/dev/null 2>&1; then
    echo "[OK] LLM API reachable."
else
    echo "[WARN] LLM API not reachable at ${LLM_API_URL}."
fi
echo

# --- Launch ---
LOG_FILE="data/hoonbot.log"
mkdir -p data

if $BACKGROUND; then
    echo "[*] Starting Hoonbot in background (logs → $LOG_FILE)..."
    nohup python3 hoonbot.py > "$LOG_FILE" 2>&1 &
    echo "[OK] PID $! — Hoonbot listening on http://0.0.0.0:${HOONBOT_PORT}"
    echo "     Health: http://localhost:${HOONBOT_PORT}/health"
else
    echo "[*] Starting Hoonbot (foreground, Ctrl+C to stop)..."
    echo "    Port: ${HOONBOT_PORT} | Health: http://localhost:${HOONBOT_PORT}/health"
    echo
    python3 hoonbot.py
fi
