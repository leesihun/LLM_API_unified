#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

export CLUSTER_ROLE=slave
export NODE_NAME="${NODE_NAME:-slave-01}"
PYTHON_BIN="${PYTHON:-python3}"

"$PYTHON_BIN" -c "import cluster_config; print('cluster config:', cluster_config.NODE_ROLE, cluster_config.NODE_NAME, 'master=', cluster_config.CLUSTER_MASTER_API_URL)"

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

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

ensure_offline_dir() {
  auto_detect_offline_deps_dir >/dev/null 2>&1 || true
  [[ -n "${OFFLINE_DEPS_DIR:-}" ]] || return 1
  [[ -d "$OFFLINE_DEPS_DIR" ]] || die "OFFLINE_DEPS_DIR does not exist: $OFFLINE_DEPS_DIR"
}

install_python_requirements() {
  local requirements="$1"
  if ensure_offline_dir; then
    local wheelhouse="${OFFLINE_DEPS_DIR}/wheels"
    [[ -d "$wheelhouse" ]] || wheelhouse="$OFFLINE_DEPS_DIR"
    [[ -d "$wheelhouse" ]] || die "Offline wheelhouse not found under OFFLINE_DEPS_DIR: $OFFLINE_DEPS_DIR"
    "$PYTHON_BIN" -m pip install --no-index --find-links "$wheelhouse" -r "$requirements"
  else
    "$PYTHON_BIN" -m pip install -r "$requirements"
  fi
}

echo "[install] LLM API dependencies"
install_python_requirements "llm-api/deps/requirements.txt"

echo "[install] Hoonbot dependencies"
install_python_requirements "hoonbot/deps/requirements.txt"

echo "[ok] Slave node '$NODE_NAME' installed."
