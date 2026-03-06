@echo off
echo ==============================================
echo   AIhoonbot.com - Pack Dependencies
echo ==============================================
echo.

REM Check if WSL is available
wsl --status >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] WSL is not available.
    echo.
    echo Use Google Colab instead:
    echo   1. Upload colab-pack-deps\ folder to Google Drive
    echo   2. Open pack-deps.ipynb in Colab
    echo   3. Run all cells
    echo   4. Download deps.tar.gz
    echo.
    pause
    exit /b 1
)

REM Check if any distro is installed
wsl -l -q >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] No WSL distribution installed.
    echo.
    echo Use Google Colab instead:
    echo   1. Upload colab-pack-deps\ folder to Google Drive
    echo   2. Open pack-deps.ipynb in Colab
    echo   3. Run all cells
    echo   4. Download deps.tar.gz
    echo.
    pause
    exit /b 1
)

echo Running pack-deps.sh via WSL...
echo.
wsl bash -c "cd '%~dp0' && bash pack-deps.sh"
echo.
if %ERRORLEVEL% EQU 0 (
    echo [OK] deps.tar.gz created.
    echo     Copy it to the Linux server and run: bash setup-linux.sh
) else (
    echo [ERROR] pack-deps.sh failed.
)
echo.
pause
