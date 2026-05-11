#!/usr/bin/env bash
# Messenger Linux build-and-launch script.
# Usage: ./start.sh [--build] [--background] [--prod]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
OFFLINE_NODE_CACHE_DIR="$SCRIPT_DIR/.offline-runtime/node"

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

die() {
    echo "[ERROR] $*" >&2
    exit 1
}

configure_npm_offline() {
    export npm_config_offline=true
    export npm_config_audit=false
    export npm_config_fund=false
    export npm_config_update_notifier=false
    export npm_config_registry="http://127.0.0.1:9"
}

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

ensure_offline_dir() {
    auto_detect_offline_deps_dir >/dev/null 2>&1 || true
    [[ -n "${OFFLINE_DEPS_DIR:-}" ]] || return 1
    [[ -d "$OFFLINE_DEPS_DIR" ]] || die "OFFLINE_DEPS_DIR does not exist: $OFFLINE_DEPS_DIR"
}

configure_npm_offline

find_first_dir() {
    local candidate
    for candidate in "$@"; do
        if [[ -n "$candidate" && -d "$candidate" ]]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

overlay_dir() {
    local src="$1"
    local dest="$2"
    mkdir -p "$dest"
    cp -a "$src"/. "$dest"/
}

strip_archive_suffix() {
    local name="$1"
    name="${name%.tar.xz}"
    name="${name%.tar.gz}"
    echo "$name"
}

find_node_bin() {
    local candidate

    if [[ -n "${NODE:-}" ]]; then
        if [[ -x "$NODE" ]]; then
            echo "$NODE"
            return 0
        fi
        if command -v "$NODE" >/dev/null 2>&1; then
            command -v "$NODE"
            return 0
        fi
    fi

    if command -v node >/dev/null 2>&1; then
        command -v node
        return 0
    fi

    if ! ensure_offline_dir; then
        return 1
    fi

    for candidate in \
        "${OFFLINE_DEPS_DIR}/node/bin/node" \
        "${OFFLINE_DEPS_DIR}"/node/*/bin/node \
        "${OFFLINE_DEPS_DIR}"/node-v*-linux-*/bin/node; do
        if [[ -x "$candidate" ]]; then
            echo "$candidate"
            return 0
        fi
    done

    local archive
    for archive in \
        "${OFFLINE_DEPS_DIR}"/node/*.tar.xz \
        "${OFFLINE_DEPS_DIR}"/node/*.tar.gz \
        "${OFFLINE_DEPS_DIR}"/node-v*-linux-*.tar.xz \
        "${OFFLINE_DEPS_DIR}"/node-v*-linux-*.tar.gz; do
        [[ -f "$archive" ]] || continue
        local extracted_dir="$OFFLINE_NODE_CACHE_DIR/$(strip_archive_suffix "$(basename "$archive")")"
        if [[ ! -x "$extracted_dir/bin/node" ]]; then
            mkdir -p "$OFFLINE_NODE_CACHE_DIR"
            echo "[stage] Extracting Node runtime from $archive"
            tar -xf "$archive" -C "$OFFLINE_NODE_CACHE_DIR"
        fi
        if [[ -x "$extracted_dir/bin/node" ]]; then
            echo "$extracted_dir/bin/node"
            return 0
        fi
    done

    return 1
}

prepend_node_path() {
    local node_bin="$1"
    [[ -n "$node_bin" ]] || return 0
    export PATH="$(dirname "$node_bin"):$PATH"
}

find_npm_bin() {
    local node_bin="${1:-}"

    if [[ -n "${NPM:-}" ]]; then
        if [[ -x "$NPM" ]]; then
            echo "$NPM"
            return 0
        fi
        if command -v "$NPM" >/dev/null 2>&1; then
            command -v "$NPM"
            return 0
        fi
    fi

    if command -v npm >/dev/null 2>&1; then
        command -v npm
        return 0
    fi

    if [[ -n "$node_bin" ]]; then
        local sibling_npm
        sibling_npm="$(dirname "$node_bin")/npm"
        if [[ -x "$sibling_npm" ]]; then
            echo "$sibling_npm"
            return 0
        fi
    fi

    return 1
}

stage_offline_runtime() {
    ensure_offline_dir || return 1

    local offline_node_modules="${MESSENGER_NODE_MODULES_DIR:-}"
    local offline_server_dist=""
    local offline_web_dist=""

    if [[ -z "$offline_node_modules" ]]; then
        offline_node_modules="$(find_first_dir \
            "${OFFLINE_DEPS_DIR}/messenger/node_modules" \
            "${OFFLINE_DEPS_DIR}/node_modules" \
        )" || true
    fi

    offline_server_dist="$(find_first_dir \
        "${OFFLINE_DEPS_DIR}/messenger/server/dist" \
        "${OFFLINE_DEPS_DIR}/server/dist" \
    )" || true

    offline_web_dist="$(find_first_dir \
        "${OFFLINE_DEPS_DIR}/messenger/client/dist-web" \
        "${OFFLINE_DEPS_DIR}/client/dist-web" \
    )" || true

    if [[ ! -d "node_modules" && -n "$offline_node_modules" ]]; then
        echo "[stage] Messenger node_modules <= $offline_node_modules"
        overlay_dir "$offline_node_modules" "node_modules"
    fi
    if [[ ! -f "server/dist/server.cjs" && -n "$offline_server_dist" ]]; then
        echo "[stage] Messenger server dist <= $offline_server_dist"
        overlay_dir "$offline_server_dist" "server/dist"
    fi
    if [[ ! -f "client/dist-web/index.html" && -n "$offline_web_dist" ]]; then
        echo "[stage] Messenger web dist <= $offline_web_dist"
        overlay_dir "$offline_web_dist" "client/dist-web"
    fi
}

require_prod_runtime() {
    [[ -d "node_modules" ]] || die "Messenger node_modules missing. Run ./install-master.sh or stage OFFLINE_DEPS_DIR/messenger/node_modules."
    [[ -f "server/dist/server.cjs" ]] || die "Messenger production server bundle missing. Expected server/dist/server.cjs."
    [[ -f "client/dist-web/index.html" ]] || die "Messenger web bundle missing. Expected client/dist-web/index.html."
}

eval "$("$PYTHON_BIN" config.py --ensure-dirs --export bash)"
PORT="$("$PYTHON_BIN" config.py --get PORT)"
LOG_FILE="$("$PYTHON_BIN" config.py --get MESSENGER_LOG_FILE)"

echo "=================================================="
echo "  Huni Messenger"
echo "=================================================="

if ensure_offline_dir; then
    stage_offline_runtime
fi

NODE_BIN="$(find_node_bin || true)"
prepend_node_path "$NODE_BIN"
NPM_BIN="$(find_npm_bin "$NODE_BIN" || true)"

if $BUILD; then
    if ensure_offline_dir; then
        echo "[build] Airgapped mode: validating staged Messenger runtime assets."
        require_prod_runtime
    else
        die "Offline bundle not found. Refusing to let npm access the internet. Stage prebuilt messenger/node_modules, server/dist/server.cjs, and client/dist-web first."
    fi
fi

mkdir -p "$(dirname "$LOG_FILE")"

if $PROD; then
    [[ -n "$NODE_BIN" ]] || die "node not found. Install Node.js or stage a Linux Node runtime under OFFLINE_DEPS_DIR/node."
    require_prod_runtime
    RUN_CMD=("$NODE_BIN" "server/dist/server.cjs")
else
    [[ -n "$NPM_BIN" ]] || die "npm not found. Install Node/npm first."
    RUN_CMD=("$NPM_BIN" run dev:server)
fi

if $BACKGROUND; then
    echo "[run] Starting in background. Logs: $LOG_FILE"
    nohup "${RUN_CMD[@]}" > "$LOG_FILE" 2>&1 &
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
    "${RUN_CMD[@]}"
fi
