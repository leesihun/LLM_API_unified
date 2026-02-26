@echo off
chcp 65001 >nul 2>&1
title AIhoonbot.com - Launcher

echo ==========================================
echo   AIhoonbot.com - Starting All Services
echo ==========================================
echo.

set CLOUDFLARED=C:\Users\Lee\AppData\Local\Microsoft\WinGet\Packages\Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe\cloudflared.exe

:: --- Verify prerequisites ---

where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js is not installed or not in PATH.
    pause
    exit /b 1
)

if not exist "%CLOUDFLARED%" (
    echo [ERROR] cloudflared not found. Run tunnel-setup.ps1 first.
    pause
    exit /b 1
)

if not exist "%USERPROFILE%\.cloudflared\config.yml" (
    echo [ERROR] Tunnel config not found. Run tunnel-setup.ps1 first.
    pause
    exit /b 1
)

:: --- Build Messenger web client if needed ---

if not exist "%~dp0Messenger\client\dist-web\index.html" (
    echo [0/2] Building Messenger web client...
    cd /d "%~dp0Messenger"
    call npm run build:web
    if %errorlevel% neq 0 (
        echo [ERROR] Messenger web client build failed.
        pause
        exit /b 1
    )
    echo [OK] Web client built.
    echo.
)

:: --- Start services ---

echo [1/2] Starting Messenger (port 3000)...
start "Messenger" cmd /k "cd /d "%~dp0Messenger" && npm run dev:server"

:: Wait for services to start before tunnel connects
echo.
echo Waiting for services to start...
timeout /t 4 /nobreak >nul

echo [2/2] Starting Cloudflare Tunnel...
start "Cloudflare Tunnel" cmd /k ""%CLOUDFLARED%" tunnel run aihoonbot"

echo.
echo ==========================================
echo   All services launched!
echo.
echo   Messenger:    https://aihoonbot.com
echo   Claude Code:  https://aihoonbot.com/claude
echo   OpenCode:     https://aihoonbot.com/opencode
echo.
echo   Local access (all via Messenger on port 3000):
echo     Messenger:    http://localhost:3000
echo     Claude Code:  http://localhost:3000/claude
echo     OpenCode:     http://localhost:3000/opencode
echo ==========================================
echo.
echo You can close this window.
timeout /t 10
