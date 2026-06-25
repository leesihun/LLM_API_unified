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

auto_detect_offline_deps_dir() {
    [[ -n "${OFFLINE_DEPS_DIR:-}" ]] && return 0

    local candidates=(
        "$SCRIPT_DIR/../llm_api_fast_airgap"
        "$SCRIPT_DIR/../offline_deps"
        "$SCRIPT_DIR/../.offline_deps"
        "$SCRIPT_DIR/../airgap"
        "$(dirname "$SCRIPT_DIR")/llm_api_fast_airgap"
        "$HOME/llm_api_fast_airgap"
    )

    local candidate
    for candidate in "${candidates[@]}"; do
        if [[ -d "$candidate" ]]; then
            export OFFLINE_DEPS_DIR="$candidate"
            echo "[config] OFFLINE_DEPS_DIR auto-detected: $OFFLINE_DEPS_DIR"
            return 0
        fi
    done
    return 1
}

auto_detect_offline_deps_dir >/dev/null 2>&1 || true

install_python_requirements() {
    echo "[skip] Linux start script: skipping Python install for deps/requirements.txt"
}

echo "=================================================="
echo "  LLM API"
echo "=================================================="

if $BUILD; then
    echo "[build] Installing Python dependencies..."
    install_python_requirements
fi

if [[ ! -f "config.py" ]]; then
    echo "[ERROR] config.py not found. Run this from llm-api/."
    exit 1
fi

VLLM_HOST=$("$PYTHON_BIN" -c "import config; print(getattr(config, 'VLLM_HOST', 'http://127.0.0.1:10000'))")
SERVER_PORT=$("$PYTHON_BIN" -c "import config; print(getattr(config, 'SERVER_PORT', 10002))")
LOG_FILE=$("$PYTHON_BIN" -c "import config; print(config.LOG_DIR / 'llm_api.log')")

echo "[check] vLLM: $VLLM_HOST"
if curl -fsS "${VLLM_HOST}/health" >/dev/null 2>&1; then
    echo "[ok] vLLM reachable."
else
    echo "[warn] inference will fail until vLLM is reachable."
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
