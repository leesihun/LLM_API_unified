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

if $BUILD; then
  ./install-master.sh
fi

(cd messenger && ./start.sh --background --prod)
(cd llm-api && ./start.sh --background)
(cd hoonbot && ./start.sh --background)

echo "[ok] Master node '$NODE_NAME' startup requested."
