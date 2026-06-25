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
# NODE_NAME comes from cluster_config.py (NAME) unless already set in the env.
[[ -n "${NODE_NAME:-}" ]] && export NODE_NAME || true
PYTHON_BIN="${PYTHON:-python3}"

"$PYTHON_BIN" -c "import cluster_config; cluster_config.require_valid_advertised_urls(); print('starting master:', cluster_config.NODE_NAME, cluster_config.MASTER_LLM_API_URL)"
NODE_NAME="$("$PYTHON_BIN" -c "import cluster_config; print(cluster_config.NODE_NAME)")"

auto_detect_offline_deps_dir() {
  if [[ -n "${OFFLINE_DEPS_DIR:-}" && -d "$OFFLINE_DEPS_DIR" ]]; then
    return 0
  fi

  local candidates=(
    "${OFFLINE_DEPS_DIR:-}"
    "$ROOT_DIR/llm_api_fast_airgap"
    "$ROOT_DIR/offline_deps"
    "$ROOT_DIR/.offline_deps"
    "$ROOT_DIR/airgap"
    "$(dirname "$ROOT_DIR")/llm_api_fast_airgap"
    "$(dirname "$ROOT_DIR")/offline_deps"
    "$HOME/llm_api_fast_airgap"
  )

  local candidate ext parent
  for candidate in "${candidates[@]}"; do
    [[ -z "$candidate" || -d "$candidate" ]] && continue
    for ext in tar.gz tgz tar.xz; do
      if [[ -f "$candidate.$ext" ]]; then
        parent="$(dirname "$candidate")"
        echo "[config] Extracting offline bundle: $candidate.$ext -> $parent/"
        mkdir -p "$parent"
        tar -xf "$candidate.$ext" -C "$parent" \
          || { echo "[ERROR] Failed to extract $candidate.$ext" >&2; exit 1; }
        break
      fi
    done
  done

  for candidate in "${candidates[@]}"; do
    if [[ -n "$candidate" && -d "$candidate" ]]; then
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

# Kill any stale cluster processes that might be holding ports
if [[ -x "$ROOT_DIR/stop-cluster.sh" ]]; then
  "$ROOT_DIR/stop-cluster.sh" --force >/dev/null 2>&1 || true
fi

cleanup() {
  trap '' INT TERM
  echo
  echo "[shutdown] stopping services..."
  kill -TERM 0 2>/dev/null || true
  wait 2>/dev/null || true
  exit 130
}
trap cleanup INT TERM

(cd messenger && ./start.sh --prod) &
MESSENGER_PID=$!
(cd llm-api && ./start.sh) &
LLM_API_PID=$!
(cd hoonbot && ./start.sh) &
HOONBOT_PID=$!

echo "[ok] Master '$NODE_NAME' running. Ctrl+C to stop."
echo "[ok]   messenger PID $MESSENGER_PID, llm-api PID $LLM_API_PID, hoonbot PID $HOONBOT_PID"
wait
