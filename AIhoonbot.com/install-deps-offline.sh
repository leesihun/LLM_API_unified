#!/bin/bash
# =============================================================
#  Install dependencies from deps.tar.gz (no internet needed).
#  Called automatically by setup-linux.sh — don't run directly.
# =============================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE="$SCRIPT_DIR/deps-bundle"
MESSENGER_DIR="$SCRIPT_DIR/Messenger"
MESSENGER_PKG="$MESSENGER_DIR/package.json"
MESSENGER_CLIENT_PKG="$MESSENGER_DIR/client/package.json"

if [ ! -f "$SCRIPT_DIR/deps.tar.gz" ]; then
    echo "[ERROR] deps.tar.gz not found in $SCRIPT_DIR"
    echo "        Create it first with: bash pack-deps.sh"
    exit 1
fi

if [ ! -f "$MESSENGER_PKG" ]; then
    echo "[ERROR] Missing file: $MESSENGER_PKG"
    echo "        Linux target directory is incomplete."
    echo "        Re-copy project files, including Messenger/package.json."
    exit 1
fi

if [ ! -f "$MESSENGER_CLIENT_PKG" ]; then
    echo "[ERROR] Missing file: $MESSENGER_CLIENT_PKG"
    echo "        Linux target directory is incomplete."
    echo "        Re-copy project files, including Messenger/client/package.json."
    exit 1
fi
echo "=============================="
echo "  Installing offline deps"
echo "=============================="
echo

# ---- Extract ----
echo "[1/4] Extracting deps.tar.gz..."
tar xzf "$SCRIPT_DIR/deps.tar.gz" -C "$SCRIPT_DIR"
echo "[OK] Extracted."
echo

# ---- Version check ----
if [ -f "$BUNDLE/versions.txt" ]; then
    echo "Packed with:"
    cat "$BUNDLE/versions.txt"
    echo
    PACK_NODE=$(grep '^node=' "$BUNDLE/versions.txt" | cut -d= -f2 | cut -d. -f1 | tr -d 'v')
    LOCAL_NODE=$(node --version | cut -d. -f1 | tr -d 'v')
    if [ "$PACK_NODE" != "$LOCAL_NODE" ]; then
        echo "[WARN] Node.js major version mismatch!"
        echo "       Packed: v$PACK_NODE.x  /  Local: v$LOCAL_NODE.x"
        echo "       Native modules (node-pty) may not work."
        echo "       Recommend installing Node.js v$PACK_NODE LTS."
        echo
    fi
fi

# ---- Python ----
echo "[2/4] Installing Python packages..."
pip3 install \
    --no-index \
    --find-links="$BUNDLE/pip-packages" \
    -r "$SCRIPT_DIR/Hoonbot/requirements.txt" \
    -r "$SCRIPT_DIR/ClaudeCodeWrapper/requirements.txt"
echo "[OK] Python packages installed."
echo

# ---- npm: copy node_modules ----
echo "[3/4] Installing npm packages..."
rm -rf "$SCRIPT_DIR/Messenger/node_modules"
cp -a "$BUNDLE/node_modules" "$MESSENGER_DIR/node_modules"
echo "[OK] node_modules installed."
echo

# ---- npm: rebuild native modules for this machine ----
echo "[4/4] Rebuilding native modules..."
if [ -d "$BUNDLE/node-gyp-cache" ]; then
    mkdir -p "$HOME/.cache"
    cp -rn "$BUNDLE/node-gyp-cache" "$HOME/.cache/node-gyp" 2>/dev/null || true
fi
cd "$MESSENGER_DIR"
npm rebuild 2>&1 || echo "[WARN] npm rebuild had issues (may be OK if Node versions match)."
echo

# ---- Cleanup ----
rm -rf "$BUNDLE"

echo "=============================="
echo "  Offline install complete!"
echo "=============================="
