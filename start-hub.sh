#!/usr/bin/env bash
# ============================================================================
# Central Hub — runs Messenger + llama.cpp.
# Farms will reach these services over the network, so both must bind 0.0.0.0.
# ============================================================================
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs/hub"
mkdir -p "$LOG_DIR"

# ---- Config (override via env or edit here) --------------------------------
LLAMACPP_PORT="${LLAMACPP_PORT:-5905}"
LLAMACPP_HOST_BIND="${LLAMACPP_HOST_BIND:-0.0.0.0}"
LLAMACPP_BIN="${LLAMACPP_BIN:-llama-server}"
LLAMACPP_MODEL_PATH="${LLAMACPP_MODEL_PATH:?LLAMACPP_MODEL_PATH (.gguf) must be set}"
LLAMACPP_PARALLEL="${LLAMACPP_PARALLEL:-16}"   # >= sum of LLAMACPP_SLOTS across all farms
LLAMACPP_CTX="${LLAMACPP_CTX:-8192}"
LLAMACPP_EXTRA_ARGS="${LLAMACPP_EXTRA_ARGS:-}"

MESSENGER_DIR="${MESSENGER_DIR:-$SCRIPT_DIR/Bot/Messenger}"
MESSENGER_PORT="${MESSENGER_PORT:-10006}"

# ---- Preflight --------------------------------------------------------------
command -v "$LLAMACPP_BIN" >/dev/null 2>&1 || { echo "[hub] ERROR: $LLAMACPP_BIN not on PATH"; exit 1; }
command -v node           >/dev/null 2>&1 || { echo "[hub] ERROR: node not on PATH"; exit 1; }
[ -f "$LLAMACPP_MODEL_PATH" ] || { echo "[hub] ERROR: model not found: $LLAMACPP_MODEL_PATH"; exit 1; }
[ -d "$MESSENGER_DIR" ]        || { echo "[hub] ERROR: Messenger dir missing: $MESSENGER_DIR"; exit 1; }

pids=()
cleanup() {
  echo "[hub] stopping (pids: ${pids[*]:-none})..."
  for pid in "${pids[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# ---- llama.cpp (GPU inference) ---------------------------------------------
echo "[hub] starting llama.cpp on $LLAMACPP_HOST_BIND:$LLAMACPP_PORT (parallel=$LLAMACPP_PARALLEL)"
"$LLAMACPP_BIN" \
  --model "$LLAMACPP_MODEL_PATH" \
  --host  "$LLAMACPP_HOST_BIND" \
  --port  "$LLAMACPP_PORT" \
  --jinja \
  --cont-batching \
  --parallel "$LLAMACPP_PARALLEL" \
  --ctx-size "$LLAMACPP_CTX" \
  --slot-prompt-similarity 0.5 \
  $LLAMACPP_EXTRA_ARGS \
  > "$LOG_DIR/llamacpp.log" 2>&1 &
pids+=($!)

# Wait for llama.cpp /health (it exposes /health like our API does)
echo "[hub] waiting for llama.cpp health..."
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$LLAMACPP_PORT/health" >/dev/null 2>&1; then
    echo "[hub] llama.cpp ready"
    break
  fi
  sleep 1
  if [ "$i" = 30 ]; then
    echo "[hub] ERROR: llama.cpp did not come up; see $LOG_DIR/llamacpp.log"
    exit 1
  fi
done

# ---- Messenger (Node/TypeScript chat platform) ------------------------------
echo "[hub] starting Messenger on :$MESSENGER_PORT"
(
  cd "$MESSENGER_DIR"
  [ -d node_modules ] || npm install
  [ -f client/dist-web/index.html ] || npm run build:web
  PORT="$MESSENGER_PORT" npm run dev:server
) > "$LOG_DIR/messenger.log" 2>&1 &
pids+=($!)

echo "[hub] waiting for Messenger /health..."
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$MESSENGER_PORT/health" >/dev/null 2>&1; then
    echo "[hub] Messenger ready"
    break
  fi
  sleep 1
  if [ "$i" = 30 ]; then
    echo "[hub] ERROR: Messenger did not come up; see $LOG_DIR/messenger.log"
    exit 1
  fi
done

cat <<EOF

[hub] ==================================================================
[hub]  llama.cpp : http://$(hostname -f 2>/dev/null || hostname):$LLAMACPP_PORT   (set this as LLAMACPP_HOST on each farm)
[hub]  Messenger : http://$(hostname -f 2>/dev/null || hostname):$MESSENGER_PORT  (set this as MESSENGER_URL on each farm)
[hub]  Logs      : $LOG_DIR
[hub] ==================================================================
[hub]  Ctrl+C to stop everything.

EOF

wait
