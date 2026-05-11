#!/usr/bin/env bash
# Hoonbot Linux build-and-launch script.
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

install_python_requirements() {
    if [[ -n "${OFFLINE_DEPS_DIR:-}" ]]; then
        if [[ ! -d "$OFFLINE_DEPS_DIR" ]]; then
            echo "[ERROR] OFFLINE_DEPS_DIR does not exist: $OFFLINE_DEPS_DIR"
            exit 1
        fi
        local wheelhouse="${OFFLINE_DEPS_DIR}/wheels"
        [[ -d "$wheelhouse" ]] || wheelhouse="$OFFLINE_DEPS_DIR"
        if [[ ! -d "$wheelhouse" ]]; then
            echo "[ERROR] Offline wheelhouse not found under OFFLINE_DEPS_DIR: $OFFLINE_DEPS_DIR"
            exit 1
        fi
        "$PYTHON_BIN" -m pip install --no-index --find-links "$wheelhouse" -r "deps/requirements.txt"
    else
        "$PYTHON_BIN" -m pip install -r "deps/requirements.txt"
    fi
}

echo "=================================================="
echo "  Hoonbot"
echo "=================================================="

if $BUILD; then
    echo "[build] Installing Python dependencies..."
    install_python_requirements
fi

MESSENGER_URL=$("$PYTHON_BIN" -c "import config; print(config.MESSENGER_URL)")
LLM_API_URL=$("$PYTHON_BIN" -c "import config; print(config.LLM_API_URL)")
HOONBOT_PORT=$("$PYTHON_BIN" -c "import config; print(config.HOONBOT_PORT)")
LOG_FILE=$("$PYTHON_BIN" -c "import config; from pathlib import Path; print(Path(config.DATA_DIR) / 'hoonbot.log')")

if [[ ! -f "data/.llm_key" || ! -f "data/.llm_model" ]]; then
    echo "[setup] LLM credentials not found. Running setup..."
    mkdir -p data
    "$PYTHON_BIN" scripts/setup_credentials.py
fi

echo "[check] Messenger: $MESSENGER_URL"
if curl -fsS "${MESSENGER_URL}/health" >/dev/null 2>&1; then
    echo "[ok] Messenger reachable."
else
    echo "[warn] Messenger not reachable. Hoonbot will retry on startup."
fi

echo "[check] LLM API: $LLM_API_URL"
if curl -fsS "${LLM_API_URL}/health" >/dev/null 2>&1; then
    echo "[ok] LLM API reachable."
else
    echo "[warn] LLM API not reachable."
fi

mkdir -p "$(dirname "$LOG_FILE")"

if $BACKGROUND; then
    echo "[run] Starting in background. Logs: $LOG_FILE"
    nohup "$PYTHON_BIN" hoonbot.py > "$LOG_FILE" 2>&1 &
    echo "[ok] PID $! listening on http://127.0.0.1:${HOONBOT_PORT}"
else
    echo "[run] Starting foreground on http://127.0.0.1:${HOONBOT_PORT}"
    "$PYTHON_BIN" hoonbot.py
fi
