#!/usr/bin/env bash
# Build an airgap deployment bundle for the LLM_API_fast cluster.
#
# Run this on WSL Ubuntu (or any glibc-based Linux host with internet). It
# produces dist/llm_api_fast_airgap.tar.gz with the layout the offline
# install/start scripts auto-detect:
#
#     llm_api_fast_airgap/
#     ├── node/node-vX.Y.Z-linux-<arch>.tar.xz   (auto-extracted on target)
#     └── messenger/
#         ├── node_modules/                       (Linux-built; includes compiled node-pty)
#         ├── server/dist/server.cjs              (+ sql-wasm.wasm + public/)
#         └── client/dist-web/index.html          (+ assets)
#
# Usage:
#     bash scripts/build-airgap-bundle.sh [--clean] [--skip-node]
#                                         [--node-version=20.18.0] [--arch=x64|arm64]

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

NODE_VERSION="20.18.0"
ARCH="x64"
CLEAN=0
SKIP_NODE=0

for arg in "$@"; do
  case "$arg" in
    --clean)              CLEAN=1 ;;
    --skip-node)          SKIP_NODE=1 ;;
    --node-version=*)     NODE_VERSION="${arg#*=}" ;;
    --arch=*)             ARCH="${arg#*=}" ;;
    -h|--help)
      sed -n '2,18p' "$0"; exit 0 ;;
    *)
      echo "[ERROR] Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

die() { echo "[ERROR] $*" >&2; exit 1; }
log() { echo "[build] $*"; }

# --- Sanity checks --------------------------------------------------------- #

[[ "$(uname -s)" == "Linux" ]] \
  || die "Must run on Linux (use WSL Ubuntu on Windows). Detected: $(uname -s)"

command -v node >/dev/null  || die "node not found on PATH"
command -v npm  >/dev/null  || die "npm not found on PATH"
command -v tar  >/dev/null  || die "tar not found on PATH"
command -v curl >/dev/null  || die "curl not found on PATH"
command -v sha256sum >/dev/null || die "sha256sum not found on PATH"

NODE_MAJOR="$(node --version | sed -E 's/^v([0-9]+).*/\1/')"
[[ "$NODE_MAJOR" -ge 18 ]] || die "Node >= 18 required for build (have $(node --version))"

[[ -f messenger/package.json ]]      || die "Run from repo root; messenger/package.json missing"
[[ -f messenger/package-lock.json ]] || die "messenger/package-lock.json missing — needed for reproducible 'npm ci'"

# --- Paths ----------------------------------------------------------------- #

BUNDLE_DIR="$ROOT_DIR/dist/llm_api_fast_airgap"
BUNDLE_TGZ="$ROOT_DIR/dist/llm_api_fast_airgap.tar.gz"
NODE_TARBALL="node-v${NODE_VERSION}-linux-${ARCH}.tar.xz"
NODE_URL="https://nodejs.org/dist/v${NODE_VERSION}/${NODE_TARBALL}"

# --- Step 1: clean (opt-in) ------------------------------------------------ #

if [[ "$CLEAN" -eq 1 ]]; then
  log "Cleaning messenger build outputs"
  rm -rf messenger/node_modules
  rm -rf messenger/server/dist
  rm -rf messenger/client/dist-web
  rm -rf "$BUNDLE_DIR" "$BUNDLE_TGZ"
fi

mkdir -p "$BUNDLE_DIR/node" "$BUNDLE_DIR/messenger"

# --- Step 2: download Linux Node tarball ----------------------------------- #

if [[ "$SKIP_NODE" -eq 1 ]]; then
  log "Skipping Node tarball download (--skip-node)"
else
  if [[ -f "$BUNDLE_DIR/node/$NODE_TARBALL" ]]; then
    log "Node tarball already present: $NODE_TARBALL"
  else
    log "Downloading $NODE_URL"
    curl -fSL --retry 3 -o "$BUNDLE_DIR/node/$NODE_TARBALL" "$NODE_URL"
  fi
fi

# --- Step 3: install Messenger deps (Linux-native) ------------------------- #

log "Installing messenger deps via 'npm ci' (this rebuilds native modules for Linux)"
(
  cd messenger
  # Reset offline-only env that scripts/install-node.sh sets — we need real registry access here.
  unset npm_config_offline npm_config_registry npm_config_audit npm_config_fund npm_config_update_notifier
  npm ci --no-audit --no-fund
)

# --- Step 4: build web bundle ---------------------------------------------- #

log "Building messenger web bundle (vite)"
(
  cd messenger
  npm run build:web --workspace=client
)

# --- Step 5: build server bundle ------------------------------------------- #

log "Building messenger server bundle (esbuild)"
(
  cd messenger
  npm run build --workspace=server
)

# --- Step 6: assemble bundle ----------------------------------------------- #

log "Assembling bundle at $BUNDLE_DIR"
rm -rf "$BUNDLE_DIR/messenger/node_modules" \
       "$BUNDLE_DIR/messenger/server" \
       "$BUNDLE_DIR/messenger/client"

mkdir -p "$BUNDLE_DIR/messenger/server" "$BUNDLE_DIR/messenger/client"

cp -a messenger/node_modules     "$BUNDLE_DIR/messenger/node_modules"
cp -a messenger/server/dist      "$BUNDLE_DIR/messenger/server/dist"
cp -a messenger/client/dist-web  "$BUNDLE_DIR/messenger/client/dist-web"

# --- Step 7: sanity-check the assembled bundle ----------------------------- #

require() { [[ -e "$1" ]] || die "Bundle missing: $1"; }
require "$BUNDLE_DIR/messenger/node_modules"
require "$BUNDLE_DIR/messenger/server/dist/server.cjs"
require "$BUNDLE_DIR/messenger/client/dist-web/index.html"

PTY_NODE="$BUNDLE_DIR/messenger/node_modules/node-pty/build/Release/pty.node"
if [[ -f "$PTY_NODE" ]]; then
  if command -v file >/dev/null; then
    PTY_TYPE="$(file -b "$PTY_NODE")"
    case "$PTY_TYPE" in
      *ELF*) log "node-pty binary OK: $PTY_TYPE" ;;
      *)     die "node-pty is not an ELF binary — built on the wrong OS? ($PTY_TYPE)" ;;
    esac
  else
    log "[warn] 'file' not installed — skipping ELF check on node-pty"
  fi
else
  log "[warn] node-pty native binary not found at expected path; messenger terminal features may be disabled"
fi

# --- Step 8: tar it up ----------------------------------------------------- #

log "Creating tarball $BUNDLE_TGZ (this may take a few minutes)"
tar -C "$ROOT_DIR/dist" -czf "$BUNDLE_TGZ" llm_api_fast_airgap

SIZE_BYTES="$(stat -c '%s' "$BUNDLE_TGZ")"
SIZE_MIB="$(awk "BEGIN { printf \"%.1f\", $SIZE_BYTES / 1048576 }")"
SHA256="$(sha256sum "$BUNDLE_TGZ" | awk '{print $1}')"
FILE_COUNT="$(tar -tzf "$BUNDLE_TGZ" | wc -l)"

cat <<EOF

[build] DONE
  bundle:     $BUNDLE_TGZ
  size:       ${SIZE_MIB} MiB (${SIZE_BYTES} bytes)
  entries:    ${FILE_COUNT}
  sha256:     ${SHA256}

Ship to the airgapped server, e.g.:
  scp $BUNDLE_TGZ user@target:~/
  ssh user@target 'tar -xzf llm_api_fast_airgap.tar.gz'
  ssh user@target 'cd /path/to/LLM_API_fast && ./start-master.sh --build'
EOF
