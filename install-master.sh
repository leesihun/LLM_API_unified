#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

export CLUSTER_ROLE=master
export NODE_NAME="${NODE_NAME:-master}"
PYTHON_BIN="${PYTHON:-python3}"
NPM_BIN="${NPM:-npm}"

"$PYTHON_BIN" -c "import cluster_config; cluster_config.require_valid_advertised_urls(); print('cluster config ok:', cluster_config.NODE_ROLE, cluster_config.NODE_NAME)"

install_python_requirements() {
  local requirements="$1"
  if [[ -n "${OFFLINE_DEPS_DIR:-}" ]]; then
    local wheelhouse="${OFFLINE_DEPS_DIR}/wheels"
    [[ -d "$wheelhouse" ]] || wheelhouse="$OFFLINE_DEPS_DIR"
    "$PYTHON_BIN" -m pip install --no-index --find-links "$wheelhouse" -r "$requirements"
  else
    "$PYTHON_BIN" -m pip install -r "$requirements"
  fi
}

install_messenger_node_modules() {
  (
    cd messenger
    local offline_node_modules="${MESSENGER_NODE_MODULES_DIR:-}"
    if [[ -z "$offline_node_modules" && -n "${OFFLINE_DEPS_DIR:-}" && -d "${OFFLINE_DEPS_DIR}/node_modules" ]]; then
      offline_node_modules="${OFFLINE_DEPS_DIR}/node_modules"
    fi
    if [[ -n "$offline_node_modules" && -d "$offline_node_modules" && ! -d node_modules ]]; then
      cp -a "$offline_node_modules" node_modules
    else
      "$NPM_BIN" install
    fi
    "$NPM_BIN" run build:web
  )
}

echo "[install] LLM API dependencies"
install_python_requirements "llm-api/deps/requirements.txt"

echo "[install] Hoonbot dependencies"
install_python_requirements "hoonbot/deps/requirements.txt"

echo "[install] Messenger dependencies"
install_messenger_node_modules

echo "[ok] Master node '$NODE_NAME' installed."
