#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

BUILD=false
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=true ;;
    *) echo "[ERROR] Unknown option: $arg"; exit 1 ;;
  esac
done

export CLUSTER_ROLE=slave
export NODE_NAME="${NODE_NAME:-slave-01}"
PYTHON_BIN="${PYTHON:-python3}"

"$PYTHON_BIN" -c "import cluster_config; print('starting slave:', cluster_config.NODE_NAME, 'master=', cluster_config.CLUSTER_MASTER_API_URL)"

auto_detect_offline_deps_dir() {
  [[ -n "${OFFLINE_DEPS_DIR:-}" ]] && return 0

  local candidates=(
    "$ROOT_DIR/llm_api_fast_airgap"
    "$ROOT_DIR/offline_deps"
    "$ROOT_DIR/.offline_deps"
    "$ROOT_DIR/airgap"
    "$(dirname "$ROOT_DIR")/llm_api_fast_airgap"
    "$(dirname "$ROOT_DIR")/offline_deps"
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

if $BUILD; then
  ./install-slave.sh
fi

(cd llm-api && ./start.sh --background)
(cd hoonbot && ./start.sh --background)

echo "[ok] Slave node '$NODE_NAME' startup requested."
