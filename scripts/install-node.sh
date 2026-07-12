#!/usr/bin/env bash
# Shared node install step (Linux, airgapped). Invoked by
# scripts/start-node.sh on --build — not user-facing.
#   Usage: install-node.sh <master|slave>
#
# Python package installation is intentionally skipped on Linux: the target
# server's Python environment is assumed to be provisioned already. The master
# additionally stages the Messenger runtime from OFFLINE_DEPS_DIR and refuses
# any online npm fallback.
set -euo pipefail

ROLE="${1:?Usage: install-node.sh <master|slave>}"
[[ "$ROLE" == "master" || "$ROLE" == "slave" ]] || { echo "[ERROR] Role must be master or slave, got: $ROLE"; exit 1; }

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export CLUSTER_ROLE="$ROLE"
# NODE_NAME comes from cluster_config.py (NAME) unless already set in the env.
[[ -n "${NODE_NAME:-}" ]] && export NODE_NAME || true
PYTHON_BIN="${PYTHON:-python3}"
MESSENGER_DIR="$ROOT_DIR/messenger"

if [[ "$ROLE" == "master" ]]; then
  "$PYTHON_BIN" -c "import cluster_config; cluster_config.require_valid_advertised_urls(); print('cluster config ok:', cluster_config.NODE_ROLE, cluster_config.NODE_NAME)"
else
  "$PYTHON_BIN" -c "import cluster_config; print('cluster config:', cluster_config.NODE_ROLE, cluster_config.NODE_NAME, 'master=', cluster_config.CLUSTER_MASTER_API_URL)"
fi
NODE_NAME="$("$PYTHON_BIN" -c "import cluster_config; print(cluster_config.NODE_NAME)")"

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
          || die "Failed to extract $candidate.$ext"
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

ensure_offline_dir() {
  auto_detect_offline_deps_dir >/dev/null 2>&1 || true
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
  echo "[skip] Linux install script: skipping Python install for $requirements"
}

install_messenger_runtime() {
  (
    cd "$MESSENGER_DIR"

    # If the built dist files are present, skip staging (node_modules only needed for terminals).
    if [[ -f "server/dist/server.cjs" && -f "client/dist-web/index.html" ]]; then
      echo "[ok] Messenger dist already present — skipping bundle copy."
      [[ -d "node_modules" ]] || echo "[warn] node_modules absent — terminal features (/claude, /opencode) will be unavailable."
    elif ensure_offline_dir; then
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
      require_file "server/dist/server.cjs" "Messenger production server bundle"
      require_file "client/dist-web/index.html" "Messenger web bundle"
    else
      die "Offline bundle not found. Refusing to let npm access the internet. Stage llm_api_fast_airgap or set OFFLINE_DEPS_DIR to a staged bundle."
    fi
  )
}

echo "[install] LLM API dependencies"
install_python_requirements "llm-api/deps/requirements.txt"

echo "[install] Hoonbot dependencies"
install_python_requirements "hoonbot/deps/requirements.txt"

if [[ "$ROLE" == "master" ]]; then
  configure_npm_offline
  echo "[install] Messenger runtime"
  install_messenger_runtime
fi

echo "[ok] ${ROLE^} node '$NODE_NAME' installed."
