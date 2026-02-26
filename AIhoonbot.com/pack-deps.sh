#!/bin/bash
# =============================================================
#  Run this on a Linux machine WITH internet (e.g. Google Colab)
#  to download all dependencies into deps.tar.gz.
#
#  Usage: bash pack-deps.sh
#  Output: deps.tar.gz
# =============================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$SCRIPT_DIR/deps-bundle"

echo "=============================="
echo "  Packing dependencies"
echo "=============================="
echo

rm -rf "$OUT"
mkdir -p "$OUT/pip-packages"

# ---- Record versions for compatibility check on target ----
echo "node=$(node --version)" > "$OUT/versions.txt"
echo "npm=$(npm --version)" >> "$OUT/versions.txt"
echo "python=$(python3 --version 2>&1 | awk '{print $2}')" >> "$OUT/versions.txt"
cat "$OUT/versions.txt"
echo

# ---- Python packages ----
echo "[1/4] Downloading Python packages..."
pip3 download \
    -r "$SCRIPT_DIR/Hoonbot/requirements.txt" \
    -r "$SCRIPT_DIR/ClaudeCodeWrapper/requirements.txt" \
    -d "$OUT/pip-packages"
echo "[OK] Python packages downloaded: $(ls "$OUT/pip-packages" | wc -l) files"
echo

# ---- npm packages ----
echo "[2/4] Installing npm packages..."
cd "$SCRIPT_DIR/Messenger"
npm install
echo "[OK] npm install done."
echo

echo "[3/4] Bundling node_modules..."
cp -a "$SCRIPT_DIR/Messenger/node_modules" "$OUT/node_modules"
echo "[OK] node_modules copied."
echo

# ---- node-gyp headers (for offline native module rebuild) ----
echo "[4/4] Caching node-gyp headers..."
npx node-gyp install 2>/dev/null || true
GYPCACHE=""
if [ -d "$HOME/.cache/node-gyp" ]; then
    GYPCACHE="$HOME/.cache/node-gyp"
elif [ -d "$HOME/.node-gyp" ]; then
    GYPCACHE="$HOME/.node-gyp"
fi
if [ -n "$GYPCACHE" ]; then
    cp -r "$GYPCACHE" "$OUT/node-gyp-cache"
    echo "[OK] node-gyp headers cached."
else
    echo "[WARN] node-gyp headers not found. npm rebuild may need internet."
fi
echo

# ---- Create archive (tar preserves symlinks) ----
echo "Creating deps.tar.gz..."
cd "$SCRIPT_DIR"
tar czf deps.tar.gz deps-bundle/
rm -rf "$OUT"
echo
SIZE=$(du -h deps.tar.gz | cut -f1)
echo "=============================="
echo "  Done! Created: deps.tar.gz ($SIZE)"
echo
echo "  Transfer to target machine, then run:"
echo "    bash setup-linux.sh"
echo "=============================="
