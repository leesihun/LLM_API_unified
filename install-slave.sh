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

ensure_offline_dir() {
  [[ -n "${OFFLINE_DEPS_DIR:-}" ]] || return 1
  [[ -d "$OFFLINE_DEPS_DIR" ]] || die "OFFLINE_DEPS_DIR does not exist: $OFFLINE_DEPS_DIR"
}

ensure_python_venv() {
  local app_dir="$1"
  local venv_dir="$app_dir/.venv"
  local venv_python="$venv_dir/bin/python"
  if [[ -x "$venv_python" ]]; then
    echo "$venv_python"
    return 0
  fi
  echo "[setup] Creating Python venv: $venv_dir"
  "$PYTHON_BIN" -m venv "$venv_dir" || die "Failed to create venv at $venv_dir. Install python3-venv or create the venv manually."
  [[ -x "$venv_python" ]] || die "Venv created but python not found: $venv_python"
  echo "$venv_python"
}

install_python_requirements() {
  local app_dir="$1"
  local requirements="$2"
  local app_python
  app_python="$(ensure_python_venv "$app_dir")"
  if ensure_offline_dir; then
    local wheelhouse="${OFFLINE_DEPS_DIR}/wheels"
    [[ -d "$wheelhouse" ]] || wheelhouse="$OFFLINE_DEPS_DIR"
    [[ -d "$wheelhouse" ]] || die "Offline wheelhouse not found under OFFLINE_DEPS_DIR: $OFFLINE_DEPS_DIR"
    "$app_python" -m pip install --no-index --find-links "$wheelhouse" -r "$requirements"
  else
    "$app_python" -m pip install -r "$requirements"
  fi
}

echo "[install] LLM API dependencies"
install_python_requirements "$ROOT_DIR/llm-api" "llm-api/deps/requirements.txt"

echo "[install] Hoonbot dependencies"
install_python_requirements "$ROOT_DIR/hoonbot" "hoonbot/deps/requirements.txt"

echo "[ok] Slave node '$NODE_NAME' installed."
