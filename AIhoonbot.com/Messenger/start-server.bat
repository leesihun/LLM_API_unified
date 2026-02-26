@echo off
chcp 65001 >nul 2>&1
title Huni Messenger - Server

set "ROOT=%~dp0"
cd /d "%ROOT%"

where node >nul 2>&1
if %errorlevel% neq 0 (
    echo Node.js가 설치되어 있지 않습니다.
    echo https://nodejs.org 에서 설치해주세요.
    pause
    exit /b 1
)

if not exist "node_modules" (
    echo 의존성을 설치합니다...
    call npm install
    if %errorlevel% neq 0 (
        echo npm install 실패.
        pause
        exit /b 1
    )
)

if not exist "server\node_modules" (
    echo 서버 의존성을 설치합니다...
    call npm install --workspace=server
    if %errorlevel% neq 0 (
        echo 서버 의존성 설치 실패.
        pause
        exit /b 1
    )
)

echo ==========================================
echo   Huni Messenger Server 시작
echo   http://localhost:3000
echo ==========================================
echo.
echo   종료하려면 Ctrl+C 를 누르세요.
echo.

call npm run dev:server

pause
