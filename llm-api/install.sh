#!/usr/bin/env bash
# =============================================================
#  LLM API — Installer
#  Run once after cloning or moving to a new machine.
#  Usage: ./install.sh [--with-llamacpp]
# =============================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=================================================="
echo "  LLM API — Installing dependencies"
echo "=================================================="
echo

# --- Python version check ---
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] python3 not found. Install Python >= 3.10 first."
    exit 1
fi
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [[ "$PY_MAJOR" -lt 3 || ("$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 10) ]]; then
    echo "[ERROR] Python >= 3.10 required. Found: $PY_VER"
    exit 1
fi
echo "[OK] Python $PY_VER"

# --- pip install ---
echo "[1/3] Installing Python dependencies..."
pip install -r "$SCRIPT_DIR/deps/requirements.txt"
echo "[OK] Python dependencies installed."
echo

# --- Create data skeleton ---
echo "[2/3] Creating data directories..."
mkdir -p "$SCRIPT_DIR/data/logs" \
         "$SCRIPT_DIR/data/sessions" \
         "$SCRIPT_DIR/data/uploads" \
         "$SCRIPT_DIR/data/scratch" \
         "$SCRIPT_DIR/data/rag_documents" \
         "$SCRIPT_DIR/data/rag_indices" \
         "$SCRIPT_DIR/data/rag_metadata" \
         "$SCRIPT_DIR/data/tool_results" \
         "$SCRIPT_DIR/data/memory" \
         "$SCRIPT_DIR/data/jobs"
echo "[OK] Data directories ready."
echo

# --- Optional: llama.cpp install ---
echo "[3/3] llama.cpp setup..."
if [[ "${1:-}" == "--with-llamacpp" ]] && [[ -f "$SCRIPT_DIR/deps/install-llamacpp.sh" ]]; then
    echo "  Running deps/install-llamacpp.sh..."
    bash "$SCRIPT_DIR/deps/install-llamacpp.sh"
else
    echo "  Skipped (pass --with-llamacpp to install, or start your own llama-server separately)."
fi
echo

echo "=================================================="
echo "  Installation complete!"
echo "  Edit llm-api/config.py to point at your llama.cpp"
echo "  server and model, then run: ./start.sh"
echo "=================================================="
