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

build_arg=()
if $BUILD; then
  build_arg=(--build)
fi

(cd llm-api && ./start.sh "${build_arg[@]}" --background)
(cd hoonbot && ./start.sh "${build_arg[@]}" --background)

echo "[ok] Slave node '$NODE_NAME' startup requested."
