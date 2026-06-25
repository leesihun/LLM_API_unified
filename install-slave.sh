#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

export CLUSTER_ROLE=slave
# NODE_NAME comes from cluster_config.py (NAME) unless already set in the env.
[[ -n "${NODE_NAME:-}" ]] && export NODE_NAME || true
PYTHON_BIN="${PYTHON:-python3}"

"$PYTHON_BIN" -c "import cluster_config; print('cluster config:', cluster_config.NODE_ROLE, cluster_config.NODE_NAME, 'master=', cluster_config.CLUSTER_MASTER_API_URL)"
NODE_NAME="$("$PYTHON_BIN" -c "import cluster_config; print(cluster_config.NODE_NAME)")"

die() {
  echo "[ERROR] $*" >&2
  exit 1
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

install_python_requirements() {
  local requirements="$1"
  echo "[skip] Linux install script: skipping Python install for $requirements"
}

echo "[install] LLM API dependencies"
install_python_requirements "llm-api/deps/requirements.txt"

echo "[install] Hoonbot dependencies"
install_python_requirements "hoonbot/deps/requirements.txt"

echo "[ok] Slave node '$NODE_NAME' installed."
