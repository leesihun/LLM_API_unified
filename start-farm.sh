#!/usr/bin/env bash
# ============================================================================
# GPU Farm Node — runs LLM API (run_backend.py) + Hoonbot.
# Points at a remote central hub for llama.cpp (inference) and Messenger (UI).
#
# Required env (set before invoking, or export in a wrapper):
#   HUB_HOST              hostname/IP of the central hub (e.g. 10.0.0.5)
#   FARM_ID               short identifier for this farm (e.g. gpu01)
#   FARM_PUBLIC_HOST      hostname/IP the hub can reach this farm on
#                          (used for the webhook URL Messenger calls back)
#
# Optional env:
#   LLAMACPP_PORT (5905)  Messenger PORT (10006)  LLM_API_PORT (10007)  HOONBOT_PORT (3939)
#   TAVILY_API_KEY        JWT_SECRET_KEY
# ============================================================================
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs/farm"
mkdir -p "$LOG_DIR"

: "${HUB_HOST:?HUB_HOST must be set (e.g. export HUB_HOST=10.0.0.5)}"
: "${FARM_ID:?FARM_ID must be set (e.g. export FARM_ID=gpu01)}"
: "${FARM_PUBLIC_HOST:?FARM_PUBLIC_HOST must be set (hostname the hub can reach)}"

LLAMACPP_PORT="${LLAMACPP_PORT:-5905}"
MESSENGER_PORT="${MESSENGER_PORT:-10006}"
LLM_API_PORT="${LLM_API_PORT:-10007}"
HOONBOT_PORT="${HOONBOT_PORT:-3939}"

HUB_LLAMACPP_URL="http://${HUB_HOST}:${LLAMACPP_PORT}"
HUB_MESSENGER_URL="http://${HUB_HOST}:${MESSENGER_PORT}"

# ---- Preflight: reach the hub before starting anything ---------------------
echo "[farm:$FARM_ID] probing hub..."
if ! curl -fsS "$HUB_LLAMACPP_URL/health" >/dev/null 2>&1; then
  echo "[farm:$FARM_ID] ERROR: llama.cpp unreachable at $HUB_LLAMACPP_URL"; exit 1
fi
if ! curl -fsS "$HUB_MESSENGER_URL/health" >/dev/null 2>&1; then
  echo "[farm:$FARM_ID] ERROR: Messenger unreachable at $HUB_MESSENGER_URL"; exit 1
fi
echo "[farm:$FARM_ID] hub reachable"

pids=()
cleanup() {
  echo "[farm:$FARM_ID] stopping (pids: ${pids[*]:-none})..."
  for pid in "${pids[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# ---- LLM API (run_backend.py) -----------------------------------------------
# Override LLAMACPP_HOST via config.py — we edit in a temporary way by
# exporting and letting run_backend pick up a Python env override. Since
# config.py reads the host as a literal, the cleanest seam is a small
# monkey-patch via LLAMACPP_HOST_OVERRIDE read at startup. If you haven't
# added that seam, edit config.py on each farm once to point at the hub.
#
# Recommended one-line seam to add to config.py (do this once per farm):
#     LLAMACPP_HOST = os.environ.get("LLAMACPP_HOST", LLAMACPP_HOST)
# Then this script works as-is by exporting LLAMACPP_HOST below.
export LLAMACPP_HOST="$HUB_LLAMACPP_URL"
export JWT_SECRET_KEY="${JWT_SECRET_KEY:-change-me-$FARM_ID}"
[ -n "${TAVILY_API_KEY:-}" ] && export TAVILY_API_KEY

echo "[farm:$FARM_ID] starting LLM API on :$LLM_API_PORT  →  llama.cpp=$HUB_LLAMACPP_URL"
(
  cd "$SCRIPT_DIR"
  python run_backend.py
) > "$LOG_DIR/llm_api.log" 2>&1 &
pids+=($!)

echo "[farm:$FARM_ID] waiting for LLM API /health..."
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$LLM_API_PORT/health" >/dev/null 2>&1; then
    echo "[farm:$FARM_ID] LLM API ready"
    break
  fi
  sleep 1
  if [ "$i" = 30 ]; then
    echo "[farm:$FARM_ID] ERROR: LLM API did not come up; see $LOG_DIR/llm_api.log"
    exit 1
  fi
done

# ---- Hoonbot ---------------------------------------------------------------
# Hoonbot needs:
#   - LLM_API_URL        -> localhost:LLM_API_PORT (same machine)
#   - MESSENGER_URL      -> hub Messenger  (REQUIRES the 3-line patch to Bot/Hoonbot/config.py)
#   - HOONBOT_PUBLIC_HOST-> this farm's externally reachable host
#                           (REQUIRES the 1-line patch to Bot/Hoonbot/hoonbot.py)
#   - HOONBOT_BOT_NAME   -> unique per farm so Messenger doesn't double-dispatch
export LLM_API_URL="http://127.0.0.1:${LLM_API_PORT}"
export MESSENGER_URL="$HUB_MESSENGER_URL"
export MESSENGER_PORT="$MESSENGER_PORT"
export HOONBOT_PUBLIC_HOST="$FARM_PUBLIC_HOST"
export HOONBOT_PORT="$HOONBOT_PORT"
export HOONBOT_BOT_NAME="${HOONBOT_BOT_NAME:-Bot-$FARM_ID}"
export USE_CLOUDFLARE="false"

echo "[farm:$FARM_ID] starting Hoonbot on :$HOONBOT_PORT as bot '$HOONBOT_BOT_NAME'"
(
  cd "$SCRIPT_DIR/Bot/Hoonbot"
  # One-time LLM API credential setup (creates data/.llm_key, data/.llm_model)
  if [ ! -f data/.llm_key ] || [ ! -f data/.llm_model ]; then
    echo "[farm:$FARM_ID] Hoonbot setup (first run)..."
    python setup.py || { echo "[farm:$FARM_ID] ERROR: Hoonbot setup failed"; exit 1; }
  fi
  python hoonbot.py
) > "$LOG_DIR/hoonbot.log" 2>&1 &
pids+=($!)

echo "[farm:$FARM_ID] waiting for Hoonbot /health..."
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$HOONBOT_PORT/health" >/dev/null 2>&1; then
    echo "[farm:$FARM_ID] Hoonbot ready"
    break
  fi
  sleep 1
  if [ "$i" = 30 ]; then
    echo "[farm:$FARM_ID] WARN: Hoonbot /health not responding; see $LOG_DIR/hoonbot.log"
  fi
done

cat <<EOF

[farm:$FARM_ID] =========================================================
[farm:$FARM_ID]  LLM API   : http://127.0.0.1:$LLM_API_PORT   (llama.cpp=$HUB_LLAMACPP_URL)
[farm:$FARM_ID]  Hoonbot   : http://$FARM_PUBLIC_HOST:$HOONBOT_PORT  (bot='$HOONBOT_BOT_NAME')
[farm:$FARM_ID]  Messenger : $HUB_MESSENGER_URL (remote)
[farm:$FARM_ID]  Logs      : $LOG_DIR
[farm:$FARM_ID] =========================================================
[farm:$FARM_ID]  Ctrl+C to stop everything on this node.

EOF

wait
