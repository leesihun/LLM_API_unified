#!/bin/bash
# Messenger: Server - Ubuntu Setup Script
# 이 스크립트는 이미 빌드된 서버를 Ubuntu에 배포합니다.
# Node.js/npm 설치 불필요 - 단일 실행 파일

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="/opt/huni-messenger"
SERVICE_NAME="huni-messenger"

echo "=========================================="
echo "  Messenger: Server 설치"
echo "=========================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "⚠  root 권한이 필요합니다. sudo로 다시 실행해주세요."
  echo "   sudo bash setup.sh"
  exit 1
fi

# Create install directory
echo "[1/4] 설치 디렉토리 생성..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/data"
mkdir -p "$INSTALL_DIR/uploads"

# Copy server binary
echo "[2/4] 서버 파일 복사..."
if [ -f "$SCRIPT_DIR/server/dist/huni-server" ]; then
  cp "$SCRIPT_DIR/server/dist/huni-server" "$INSTALL_DIR/huni-server"
  chmod +x "$INSTALL_DIR/huni-server"

  # better-sqlite3 native module needs to be next to the binary
  if [ -d "$SCRIPT_DIR/server/node_modules/better-sqlite3" ]; then
    cp -r "$SCRIPT_DIR/server/node_modules/better-sqlite3" "$INSTALL_DIR/"
  fi
elif [ -f "$SCRIPT_DIR/server/dist/server.cjs" ]; then
  echo "⚠  독립 실행 파일을 찾을 수 없습니다. 번들 스크립트 모드로 설치합니다."
  echo "   Node.js가 서버에 설치되어 있어야 합니다."
  cp "$SCRIPT_DIR/server/dist/server.cjs" "$INSTALL_DIR/server.cjs"
  if [ -d "$SCRIPT_DIR/server/node_modules" ]; then
    cp -r "$SCRIPT_DIR/server/node_modules" "$INSTALL_DIR/"
  fi
else
  echo "❌ 서버 빌드 파일이 없습니다. 먼저 빌드해주세요:"
  echo "   cd server && npm run build"
  exit 1
fi

# Create start script
echo "[3/4] 시작 스크립트 생성..."
cat > "$INSTALL_DIR/start.sh" << 'STARTEOF'
#!/bin/bash
cd "$(dirname "$0")"
export PORT=${PORT:-3000}

if [ -f "./huni-server" ]; then
  echo "🚀 Messenger: Server 시작 (port: $PORT)"
  ./huni-server
elif [ -f "./server.cjs" ]; then
  echo "🚀 Messenger: Server 시작 (Node.js 모드, port: $PORT)"
  node ./server.cjs
else
  echo "❌ 서버 실행 파일을 찾을 수 없습니다."
  exit 1
fi
STARTEOF
chmod +x "$INSTALL_DIR/start.sh"

# Create systemd service
echo "[4/4] systemd 서비스 등록..."
cat > "/etc/systemd/system/${SERVICE_NAME}.service" << SERVICEEOF
[Unit]
Description=Messenger: Server
After=network.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/start.sh
Restart=always
RestartSec=5
Environment=PORT=3000

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl start "$SERVICE_NAME"

echo ""
echo "=========================================="
echo "  ✅ 설치 완료!"
echo "=========================================="
echo ""
echo "  서버 상태: systemctl status $SERVICE_NAME"
echo "  서버 시작: systemctl start $SERVICE_NAME"
echo "  서버 중지: systemctl stop $SERVICE_NAME"
echo "  로그 보기: journalctl -u $SERVICE_NAME -f"
echo ""
echo "  서버 주소: http://$(hostname -I | awk '{print $1}'):3000"
echo ""
echo "  데이터 경로: $INSTALL_DIR/data/"
echo "  업로드 경로: $INSTALL_DIR/uploads/"
echo ""
