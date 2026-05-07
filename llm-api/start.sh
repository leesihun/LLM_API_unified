#!/usr/bin/env bash
# LLM API Linux build-and-launch script.
# Usage: ./start.sh [--build] [--background]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BUILD=false
BACKGROUND=false
for arg in "$@"; do
    case "$arg" in
        --build) BUILD=true ;;
        --background) BACKGROUND=true ;;
        *)
            echo "[ERROR] Unknown option: $arg"
            echo "Usage: ./start.sh [--build] [--background]"
            exit 1
            ;;
    esac
done

PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "[ERROR] python3 not found. Install Python >= 3.10 first."
    exit 1
fi

echo "=================================================="
echo "  LLM API"
echo "=================================================="

if $BUILD; then
    echo "[build] Installing Python dependencies..."
    "$PYTHON_BIN" -m pip install -r "deps/requirements.txt"
fi

if [[ ! -f "config.py" ]]; then
    echo "[ERROR] config.py not found. Run this from llm-api/."
    exit 1
fi

LLAMACPP_HOST=$("$PYTHON_BIN" -c "import config; print(getattr(config, 'LLAMACPP_HOST', 'http://127.0.0.1:5905'))")
LLAMACPP_BACKUP_HOST=$("$PYTHON_BIN" -c "import config; print(getattr(config, 'LLAMACPP_BACKUP_HOST', 'http://127.0.0.1:10000'))")
SERVER_PORT=$("$PYTHON_BIN" -c "import config; print(getattr(config, 'SERVER_PORT', 10007))")
LOG_FILE=$("$PYTHON_BIN" -c "import config; print(config.LOG_DIR / 'llm_api.log')")

echo "[check] llama.cpp primary: $LLAMACPP_HOST"
if curl -fsS "${LLAMACPP_HOST}/health" >/dev/null 2>&1; then
    echo "[ok] primary llama.cpp reachable."
else
    echo "[warn] primary llama.cpp not reachable."
    if [[ -n "$LLAMACPP_BACKUP_HOST" ]] && curl -fsS "${LLAMACPP_BACKUP_HOST}/health" >/dev/null 2>&1; then
        echo "[ok] backup llama.cpp reachable: $LLAMACPP_BACKUP_HOST"
    else
        echo "[warn] inference will fail until llama.cpp is reachable."
    fi
fi

mkdir -p "$(dirname "$LOG_FILE")"

if $BACKGROUND; then
    echo "[run] Starting in background. Logs: $LOG_FILE"
    nohup "$PYTHON_BIN" run_backend.py > "$LOG_FILE" 2>&1 &
    echo "[ok] PID $! listening on http://127.0.0.1:${SERVER_PORT}"
else
    echo "[run] Starting foreground on http://127.0.0.1:${SERVER_PORT}"
    "$PYTHON_BIN" run_backend.py
fi
