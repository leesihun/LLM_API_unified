@echo off
setlocal
cd /d "%~dp0"
REM One-click: first run sets up a Python venv, then launches llm-api + hoonbot.
REM Later runs start instantly.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-and-start-slave.ps1" %*
pause
