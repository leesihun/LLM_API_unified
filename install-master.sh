#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

export CLUSTER_ROLE=master
export NODE_NAME="${NODE_NAME:-master}"
PYTHON_BIN="${PYTHON:-python3}"
NPM_BIN="${NPM:-npm}"
MESSENGER_DIR="$ROOT_DIR/messenger"

"$PYTHON_BIN" -c "import cluster_config; cluster_config.require_valid_advertised_urls(); print('cluster config ok:', cluster_config.NODE_ROLE, cluster_config.NODE_NAME)"

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

ensure_offline_dir() {
  [[ -n "${OFFLINE_DEPS_DIR:-}" ]] || return 1
  [[ -d "$OFFLINE_DEPS_DIR" ]] || die "OFFLINE_DEPS_DIR does not exist: $OFFLINE_DEPS_DIR"
}

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

require_file() {
  local path="$1"
  local label="$2"
  [[ -f "$path" ]] || die "$label not found: $path"
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

install_messenger_runtime() {
  (
    cd "$MESSENGER_DIR"

    if ensure_offline_dir; then
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

      if [[ -n "$offline_node_modules" ]]; then
        echo "[stage] Messenger node_modules <= $offline_node_modules"
        overlay_dir "$offline_node_modules" "node_modules"
      elif [[ ! -d "node_modules" ]]; then
        die "Messenger node_modules missing. Expected messenger/node_modules in OFFLINE_DEPS_DIR or a local messenger/node_modules directory."
      fi

      if [[ -n "$offline_server_dist" ]]; then
        echo "[stage] Messenger server dist <= $offline_server_dist"
        overlay_dir "$offline_server_dist" "server/dist"
      fi
      if [[ -n "$offline_web_dist" ]]; then
        echo "[stage] Messenger web dist <= $offline_web_dist"
        overlay_dir "$offline_web_dist" "client/dist-web"
      fi

      [[ -d "node_modules" ]] || die "Messenger node_modules missing. Expected messenger/node_modules in OFFLINE_DEPS_DIR or a local messenger/node_modules directory."
      if [[ ! -f "server/dist/server.cjs" || ! -f "client/dist-web/index.html" ]]; then
        echo "[info] Messenger production bundles are not fully staged; messenger/start.sh will build them locally if Node/npm are available."
      fi
    else
      "$NPM_BIN" install
      "$NPM_BIN" run build --workspace=server
      "$NPM_BIN" run build:web
    fi
  )
}

echo "[install] LLM API dependencies"
install_python_requirements "llm-api/deps/requirements.txt"

echo "[install] Hoonbot dependencies"
install_python_requirements "hoonbot/deps/requirements.txt"

echo "[install] Messenger runtime"
install_messenger_runtime

echo "[ok] Master node '$NODE_NAME' installed."
