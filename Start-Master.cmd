@echo off
setlocal
cd /d "%~dp0"
REM One-click: first run sets up a Python venv + builds the Messenger bundle,
REM then launches all three services. Later runs start instantly (no npm).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-and-start-master.ps1" %*
pause
