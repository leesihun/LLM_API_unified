#!/usr/bin/env bash
# Stop all running cluster services: messenger, llm-api, hoonbot.
# Sends SIGTERM, waits up to 5 seconds, then SIGKILL on any stragglers.
# Safe to run even when nothing is up — exits 0 with a message.
#
# Usage:
#   ./stop-cluster.sh            # graceful stop (SIGTERM, then SIGKILL after 5s)
#   ./stop-cluster.sh --force    # skip SIGTERM, send SIGKILL immediately

set -u

FORCE=false
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=true ;;
    -h|--help)
      sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "[ERROR] Unknown option: $arg" >&2; exit 1 ;;
  esac
done

# Pattern + human label for each known service entry point.
# Patterns are matched against the FULL command line via pgrep -f.
PATTERNS=(
  'python.*run_backend\.py'           # llm-api
  'python.*hoonbot\.py'               # hoonbot
  'node .*server/dist/server\.cjs'    # messenger (prod, prebuilt)
  'tsx .*server/src/index\.ts'        # messenger (dev server)
  'vite .*vite\.config'               # messenger (dev client)
)
LABELS=(
  'llm-api'
  'hoonbot'
  'messenger (prod)'
  'messenger (dev server)'
  'messenger (dev client)'
)

# Avoid killing this script itself (pgrep -f would match `bash stop-cluster.sh`
# if any pattern accidentally matched — but our patterns are specific enough).
SELF_PID=$$

list_pids() {
  local pattern="$1"
  pgrep -f -- "$pattern" 2>/dev/null | grep -v "^$SELF_PID$" || true
}

any_running=0
for i in "${!PATTERNS[@]}"; do
  pids="$(list_pids "${PATTERNS[$i]}")"
  if [[ -n "$pids" ]]; then
    any_running=1
    sig="TERM"
    $FORCE && sig="KILL"
    # shellcheck disable=SC2086
    echo "[stop] ${LABELS[$i]} (pids: $(echo $pids | tr '\n' ' ')) -> SIG${sig}"
    # shellcheck disable=SC2086
    kill -"$sig" $pids 2>/dev/null || true
  fi
done

if [[ "$any_running" -eq 0 ]]; then
  echo "[stop] No cluster services running."
  exit 0
fi

if $FORCE; then
  echo "[stop] Force-killed all matching processes."
  exit 0
fi

# Wait up to 5 seconds for graceful exit
for _ in 1 2 3 4 5; do
  still=0
  for pattern in "${PATTERNS[@]}"; do
    if [[ -n "$(list_pids "$pattern")" ]]; then
      still=1; break
    fi
  done
  [[ "$still" -eq 0 ]] && break
  sleep 1
done

# Force-kill any stragglers
straggler=0
for i in "${!PATTERNS[@]}"; do
  pids="$(list_pids "${PATTERNS[$i]}")"
  if [[ -n "$pids" ]]; then
    straggler=1
    # shellcheck disable=SC2086
    echo "[stop] ${LABELS[$i]} still alive (pids: $(echo $pids | tr '\n' ' ')) -> SIGKILL"
    # shellcheck disable=SC2086
    kill -KILL $pids 2>/dev/null || true
  fi
done

if [[ "$straggler" -eq 0 ]]; then
  echo "[stop] All cluster services stopped cleanly."
else
  echo "[stop] All cluster services stopped (some required SIGKILL)."
fi
