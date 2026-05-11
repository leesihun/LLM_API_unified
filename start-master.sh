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

export CLUSTER_ROLE=master
export NODE_NAME="${NODE_NAME:-master}"
PYTHON_BIN="${PYTHON:-python3}"

"$PYTHON_BIN" -c "import cluster_config; cluster_config.require_valid_advertised_urls(); print('starting master:', cluster_config.NODE_NAME, cluster_config.MASTER_LLM_API_URL)"

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
  ./install-master.sh
fi

(cd messenger && ./start.sh --background --prod)
(cd llm-api && ./start.sh --background)
(cd hoonbot && ./start.sh --background)

echo "[ok] Master node '$NODE_NAME' startup requested."
