#!/bin/bash
# =============================================================
#  AIhoonbot.com — One-click Linux Setup
#
#  Prerequisites: python3, pip3, node, npm
#  Usage:
#    1. Place deps.tar.gz in this directory (from pack-deps.sh)
#    2. bash setup-linux.sh
#    3. bash start-all.sh
# =============================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================"
echo "  AIhoonbot.com — Linux Setup"
echo "============================================"
echo
# ===========================================================
#  1. Check required tools
# ===========================================================
echo "[1/6] Checking required tools..."
MISSING=()
for cmd in python3 pip3 node npm; do
    if ! command -v "$cmd" &>/dev/null; then
        MISSING+=("$cmd")
    fi
done
if [ ${#MISSING[@]} -ne 0 ]; then
    echo
    echo "[ERROR] Missing: ${MISSING[*]}"
    echo
    echo "  Install on Ubuntu/Debian:"
    echo "    sudo apt update"
    echo "    sudo apt install -y python3 python3-pip"
    echo "    curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo bash -"
    echo "    sudo apt install -y nodejs"
    echo
    exit 1
fi
echo "  python3 : $(python3 --version 2>&1)"
echo "  node    : $(node --version)"
echo "  npm     : $(npm --version)"
echo "  pip3    : $(pip3 --version | awk '{print $2}')"
echo "[OK]"
echo

# ===========================================================
#  2. Check / install build tools (needed for node-pty)
# ===========================================================
echo "[2/6] Checking build tools (make, g++)..."
NEED_BUILD=false
for cmd in make g++; do
    if ! command -v "$cmd" &>/dev/null; then
        NEED_BUILD=true
        break
    fi
done
if [ "$NEED_BUILD" = true ]; then
    echo "  Installing build-essential..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y build-essential python3-dev
    elif command -v yum &>/dev/null; then
        sudo yum install -y gcc-c++ make python3-devel
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y gcc-c++ make python3-devel
    else
        echo "[ERROR] Cannot auto-install build tools."
        echo "        Manually install: make, g++, python3-dev"
        exit 1
    fi
fi
echo "[OK] Build tools available."
echo

# ===========================================================
#  3. Install dependencies
# ===========================================================
echo "[3/6] Installing dependencies..."
if [ -f "$SCRIPT_DIR/deps.tar.gz" ]; then
    bash "$SCRIPT_DIR/install-deps-offline.sh"
else
    echo "  deps.tar.gz not found — installing from internet..."
    echo

    echo "  Installing Python packages..."
    pip3 install \
        -r "$SCRIPT_DIR/Hoonbot/requirements.txt" \
        -r "$SCRIPT_DIR/ClaudeCodeWrapper/requirements.txt"
    echo "  [OK] Python packages installed."
    echo

    echo "  Installing npm packages..."
    cd "$SCRIPT_DIR/Messenger"
    npm install
    cd "$SCRIPT_DIR"
    echo "  [OK] npm packages installed."
    echo
fi
echo

# ===========================================================
#  4. Build Messenger web client
# ===========================================================
echo "[4/6] Building Messenger web client..."
cd "$SCRIPT_DIR/Messenger"
npm run build:web
cd "$SCRIPT_DIR"
echo "[OK] Web client built."
echo

# ===========================================================
#  5. Configure ClaudeCodeWrapper
# ===========================================================
echo "[5/6] Configuring ClaudeCodeWrapper..."
source "$SCRIPT_DIR/settings.txt"
ENV_FILE="$SCRIPT_DIR/ClaudeCodeWrapper/.env"

mkdir -p "$WORKSPACE_DIR" 2>/dev/null || true

cat > "$ENV_FILE" << EOF
SECRET_TOKEN=changeme
HOST=0.0.0.0
PORT=8000
CLAUDE_CMD=claude
CURSOR_CMD=agent
WORKSPACE_DIR=$WORKSPACE_DIR
MIN_TASK_GAP_SECONDS=0
TASK_TIMEOUT_SECONDS=1800
TUNNEL_ENABLED=false
CLOUDFLARED_CMD=cloudflared
EOF
echo "  [OK] Created $ENV_FILE (WORKSPACE_DIR=$WORKSPACE_DIR)"
echo "       Change WORKSPACE_DIR in settings.txt, then re-run setup."
echo

# ===========================================================
#  6. Final setup
# ===========================================================
echo "[6/6] Final setup..."
mkdir -p "$SCRIPT_DIR/logs"
chmod +x "$SCRIPT_DIR/start-all.sh" 2>/dev/null || true
chmod +x "$SCRIPT_DIR/pack-deps.sh" 2>/dev/null || true
chmod +x "$SCRIPT_DIR/install-deps-offline.sh" 2>/dev/null || true
echo "[OK]"
echo

# ===========================================================
#  Done
# ===========================================================
echo "============================================"
echo "  Setup complete!"
echo
echo "  To start all services:"
echo "    cd $SCRIPT_DIR"
echo "    bash start-all.sh"
echo
echo "  Config files:"
echo "    settings.txt             — ports, cloudflare, LLM"
echo "    ClaudeCodeWrapper/.env   — workspace, tokens"
echo "============================================"
