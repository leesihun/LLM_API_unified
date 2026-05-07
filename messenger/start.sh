#!/usr/bin/env bash
# Messenger Linux build-and-launch script.
# Usage: ./start.sh [--build] [--background] [--prod]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BUILD=false
BACKGROUND=false
PROD=false
for arg in "$@"; do
    case "$arg" in
        --build) BUILD=true ;;
        --background) BACKGROUND=true ;;
        --prod) PROD=true ;;
        *)
            echo "[ERROR] Unknown option: $arg"
            echo "Usage: ./start.sh [--build] [--background] [--prod]"
            exit 1
            ;;
    esac
done

PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "[ERROR] python3 not found. Messenger config is config.py, so Python is required."
    exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
    echo "[ERROR] npm not found. Install Node/npm first."
    exit 1
fi

eval "$("$PYTHON_BIN" config.py --ensure-dirs --export bash)"
PORT="$("$PYTHON_BIN" config.py --get PORT)"
LOG_FILE="$("$PYTHON_BIN" config.py --get MESSENGER_LOG_FILE)"

echo "=================================================="
echo "  Huni Messenger"
echo "=================================================="

if $BUILD || [[ ! -d "node_modules" ]]; then
    echo "[build] Installing npm dependencies..."
    npm install
fi

if $BUILD || [[ ! -f "client/dist-web/index.html" ]]; then
    echo "[build] Building web client..."
    npm run build:web
fi

mkdir -p "$(dirname "$LOG_FILE")"

if $PROD; then
    NPM_ARGS=(run start --workspace=server)
else
    NPM_ARGS=(run dev:server)
fi

if $BACKGROUND; then
    echo "[run] Starting in background. Logs: $LOG_FILE"
    nohup npm "${NPM_ARGS[@]}" > "$LOG_FILE" 2>&1 &
    PID=$!
    for _ in $(seq 1 20); do
        if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
            echo "[ok] PID $PID ready at http://127.0.0.1:${PORT}"
            exit 0
        fi
        sleep 1
    done
    echo "[warn] Started PID $PID, but health check did not pass yet."
else
    echo "[run] Starting foreground on http://127.0.0.1:${PORT}"
    npm "${NPM_ARGS[@]}"
fi
