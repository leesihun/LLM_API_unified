#!/usr/bin/env bash
# =============================================================
#  LLM API — Start Script
#  Usage: ./start.sh [--background]
# =============================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"   # cwd must be llm-api/ so data/ paths resolve

BACKGROUND=false
for arg in "$@"; do
    [[ "$arg" == "--background" ]] && BACKGROUND=true
done

echo "=================================================="
echo "  LLM API — Starting"
echo "=================================================="
echo

# --- Preflight ---
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] python3 not found. Run ./install.sh first."
    exit 1
fi

if [[ ! -f "config.py" ]]; then
    echo "[ERROR] config.py not found. Are you running from llm-api/ ?"
    exit 1
fi

# Extract LLAMACPP_HOST from config.py for connectivity check
LLAMACPP_HOST=$(python3 -c "import config; print(getattr(config,'LLAMACPP_HOST','http://localhost:5905'))" 2>/dev/null || echo "http://localhost:5905")
SERVER_PORT=$(python3 -c "import config; print(getattr(config,'SERVER_PORT',10007))" 2>/dev/null || echo "10007")

echo "[*] Checking llama.cpp at $LLAMACPP_HOST..."
if curl -fsS "${LLAMACPP_HOST}/health" >/dev/null 2>&1; then
    echo "[OK] llama.cpp is reachable."
else
    echo "[WARN] llama.cpp not reachable at ${LLAMACPP_HOST}."
    echo "       The API will start but inference calls will fail until llama.cpp is running."
fi
echo

# --- Launch ---
LOG_FILE="data/logs/llm_api.log"
mkdir -p "data/logs"

if $BACKGROUND; then
    echo "[*] Starting LLM API in background (logs → $LOG_FILE)..."
    nohup python3 run_backend.py > "$LOG_FILE" 2>&1 &
    echo "[OK] PID $! — API listening on http://0.0.0.0:${SERVER_PORT}"
    echo "     Swagger UI: http://localhost:${SERVER_PORT}/docs"
else
    echo "[*] Starting LLM API (foreground, Ctrl+C to stop)..."
    echo "    Port: ${SERVER_PORT} | Swagger: http://localhost:${SERVER_PORT}/docs"
    echo
    python3 run_backend.py
fi
