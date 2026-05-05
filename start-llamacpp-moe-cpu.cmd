@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

rem Runs llama.cpp server for llm-api on port 5905.
rem Prefers a user-level Downloads llama.cpp install to keep the repo clean.
rem Default model is the MoE GGUF found in the user's Downloads folder.
rem Override any setting before running, for example:
rem   set MODEL_PATH=C:\path\to\model.gguf
rem   set MMPROJ_PATH=C:\path\to\mmproj.gguf
rem   set LLAMA_SERVER=C:\path\to\llama-server.exe
rem   set MODEL_ALIAS=default
rem   set CPU_MOE_ARGS=--n-cpu-moe 16

if not defined LLAMA_CPP_DIR (
    if exist "%USERPROFILE%\Downloads\llama.cpp-b9028-cuda124" (
        set "LLAMA_CPP_DIR=%USERPROFILE%\Downloads\llama.cpp-b9028-cuda124"
    ) else if exist "%USERPROFILE%\Downloads\llama.cpp" (
        set "LLAMA_CPP_DIR=%USERPROFILE%\Downloads\llama.cpp"
    ) else if exist "%SCRIPT_DIR%\llama.cpp-b9028-cuda124" (
        rem Legacy repo-local fallback during migration.
        set "LLAMA_CPP_DIR=%SCRIPT_DIR%\llama.cpp-b9028-cuda124"
    ) else if exist "%SCRIPT_DIR%\llama.cpp" (
        rem Legacy repo-local fallback during migration.
        set "LLAMA_CPP_DIR=%SCRIPT_DIR%\llama.cpp"
    ) else (
        set "LLAMA_CPP_DIR=%USERPROFILE%\Downloads\llama.cpp"
    )
)
if not defined MODEL_PATH (
    if exist "%USERPROFILE%\Downloads\Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf" (
        set "MODEL_PATH=%USERPROFILE%\Downloads\Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf"
    ) else if exist "%USERPROFILE%\Downloads\gemma-4-E4B-it-UD-Q5_K_XL.gguf" (
        set "MODEL_PATH=%USERPROFILE%\Downloads\gemma-4-E4B-it-UD-Q5_K_XL.gguf"
    )
)
if not defined MMPROJ_PATH (
    if /I not "%MODEL_PATH:Qwen3.6-35B-A3B=%"=="%MODEL_PATH%" (
        if exist "%USERPROFILE%\Downloads\mmproj-Qwen3.6-35B-A3B-F16.gguf" (
            set "MMPROJ_PATH=%USERPROFILE%\Downloads\mmproj-Qwen3.6-35B-A3B-F16.gguf"
        )
    ) else if /I not "%MODEL_PATH:gemma-4-E4B-it=%"=="%MODEL_PATH%" (
        if exist "%USERPROFILE%\Downloads\mmproj-gemma-4-E4B-it-Q8_0.gguf" (
            set "MMPROJ_PATH=%USERPROFILE%\Downloads\mmproj-gemma-4-E4B-it-Q8_0.gguf"
        )
    )
)
if not defined HOST set "HOST=0.0.0.0"
if not defined PORT set "PORT=5905"
if not defined CTX_SIZE set "CTX_SIZE=65536"
if not defined PARALLEL set "PARALLEL=2"
if not defined GPU_LAYERS set "GPU_LAYERS=auto"
if not defined BATCH_SIZE set "BATCH_SIZE=2048"
if not defined UBATCH_SIZE set "UBATCH_SIZE=512"
if not defined MODEL_ALIAS set "MODEL_ALIAS=default"
if not defined CPU_MOE_ARGS set "CPU_MOE_ARGS=--cpu-moe"
if not defined SERVER_CWD set "SERVER_CWD=%LLAMA_CPP_DIR%"

set "SERVER_EXE="

if defined LLAMA_SERVER (
    if exist "%LLAMA_SERVER%" set "SERVER_EXE=%LLAMA_SERVER%"
)

if not defined SERVER_EXE (
    for %%P in (
        "%LLAMA_CPP_DIR%\build\bin\Release\llama-server.exe"
        "%LLAMA_CPP_DIR%\build\bin\llama-server.exe"
        "%LLAMA_CPP_DIR%\build\bin\Debug\llama-server.exe"
        "%LLAMA_CPP_DIR%\bin\llama-server.exe"
        "%LLAMA_CPP_DIR%\llama-server.exe"
    ) do (
        if exist "%%~P" (
            set "SERVER_EXE=%%~P"
            goto :found_server
        )
    )
)

if not defined SERVER_EXE (
    for /f "delims=" %%P in ('where llama-server.exe 2^>nul') do (
        set "SERVER_EXE=%%P"
        goto :found_server
    )
)

:found_server
if not defined SERVER_EXE (
    echo [ERROR] llama-server.exe was not found.
    echo Checked LLAMA_SERVER, PATH, and common build paths under:
    echo   %LLAMA_CPP_DIR%
    echo.
    echo Build llama.cpp first, for example:
    echo   cd /d "%LLAMA_CPP_DIR%"
    echo   cmake -B build
    echo   cmake --build build --config Release -j
    exit /b 1
)

if not exist "%MODEL_PATH%" (
    echo [ERROR] Model file not found:
    echo   %MODEL_PATH%
    exit /b 1
)
if defined MMPROJ_PATH (
    if not exist "%MMPROJ_PATH%" (
        echo [ERROR] Multimodal projector file not found:
        echo   %MMPROJ_PATH%
        exit /b 1
    )
)

echo [INFO] llama-server: %SERVER_EXE%
echo [INFO] model:        %MODEL_PATH%
if defined MMPROJ_PATH (
    echo [INFO] mmproj:       %MMPROJ_PATH%
) else (
    echo [INFO] mmproj:       disabled
)
echo [INFO] alias:        %MODEL_ALIAS%
echo [INFO] listen:       http://%HOST%:%PORT%
echo [INFO] cwd:          %SERVER_CWD%
echo [INFO] MoE CPU args: %CPU_MOE_ARGS%
echo.

pushd "%SERVER_CWD%" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Could not enter llama.cpp directory:
    echo   %SERVER_CWD%
    exit /b 1
)

if defined MMPROJ_PATH (
    "%SERVER_EXE%" ^
      --model "%MODEL_PATH%" ^
      --mmproj "%MMPROJ_PATH%" ^
      --alias "%MODEL_ALIAS%" ^
      --host "%HOST%" ^
      --port "%PORT%" ^
      --ctx-size "%CTX_SIZE%" ^
      --parallel "%PARALLEL%" ^
      --n-gpu-layers "%GPU_LAYERS%" ^
      %CPU_MOE_ARGS% ^
      --batch-size "%BATCH_SIZE%" ^
      --ubatch-size "%UBATCH_SIZE%" ^
      %*
) else (
    "%SERVER_EXE%" ^
      --model "%MODEL_PATH%" ^
      --alias "%MODEL_ALIAS%" ^
      --host "%HOST%" ^
      --port "%PORT%" ^
      --ctx-size "%CTX_SIZE%" ^
      --parallel "%PARALLEL%" ^
      --n-gpu-layers "%GPU_LAYERS%" ^
      %CPU_MOE_ARGS% ^
      --batch-size "%BATCH_SIZE%" ^
      --ubatch-size "%UBATCH_SIZE%" ^
      %*
)

set "EXITCODE=%ERRORLEVEL%"
popd >nul
exit /b %EXITCODE%
