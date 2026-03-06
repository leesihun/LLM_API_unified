#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Load Settings ---
SETTINGS="$SCRIPT_DIR/settings.txt"
if [ -f "$SETTINGS" ]; then
    source "$SETTINGS"
else
    # Fallback defaults if settings.txt is missing
    USE_CLOUDFLARE=true
fi

pkill -f "ClaudeCodeWrapper" 2>/dev/null
pkill -f "Messenger" 2>/dev/null
pkill -f "npm run dev:server" 2>/dev/null
pkill -f "tsx watch src/index.ts" 2>/dev/null
pkill -f "python3 hoonbot.py" 2>/dev/null
pkill -f "python hoonbot.py" 2>/dev/null
pkill -f "run_backend.py" 2>/dev/null
pkill -f "tools_server.py" 2>/dev/null

if [ "$USE_CLOUDFLARE" = "true" ]; then
    pkill -f "cloudflared" 2>/dev/null
    echo "ClaudeCodeWrapper, Messenger, Hoonbot, LLM API, and cloudflared have been closed."
else
    echo "ClaudeCodeWrapper, Messenger, Hoonbot, and LLM API have been closed."
fi
