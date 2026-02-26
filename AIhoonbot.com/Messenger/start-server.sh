#!/bin/bash
# Messenger: Server - 수동 시작 스크립트
cd "$(dirname "$0")"

if [ -f "./server/dist/huni-server" ]; then
  echo "🚀 Messenger: Server 시작..."
  cd server/dist
  PORT=${PORT:-3000} ./huni-server
elif [ -f "./server/dist/server.cjs" ]; then
  echo "🚀 Messenger: Server 시작 (Node.js 모드)..."
  cd server/dist
  PORT=${PORT:-3000} node server.cjs
else
  echo "❌ 서버 빌드 파일이 없습니다."
  echo "   먼저 빌드하세요: cd server && npm run build"
  exit 1
fi
