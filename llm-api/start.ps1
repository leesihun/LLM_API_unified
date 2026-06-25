param(
    [switch]$Build,
    [switch]$Background
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

function Find-Python {
    if ($env:PYTHON) { return $env:PYTHON }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    throw "Python >= 3.10 was not found."
}

$Python = Find-Python

Write-Host "=================================================="
Write-Host "  LLM API"
Write-Host "=================================================="

if ($Build) {
    Write-Host "[build] Installing Python dependencies..."
    & $Python -m pip install -r "deps\requirements.txt"
}

if (-not (Test-Path "config.py")) {
    throw "config.py not found. Run this from llm-api."
}

$VllmHost = & $Python -c "import config; print(getattr(config, 'VLLM_HOST', 'http://127.0.0.1:10000'))"
$ServerPort = & $Python -c "import config; print(getattr(config, 'SERVER_PORT', 10002))"
$LogFile = & $Python -c "import config; print(config.LOG_DIR / 'llm_api.log')"

Write-Host "[check] vLLM: $VllmHost"
try {
    Invoke-WebRequest -UseBasicParsing -Uri "$VllmHost/health" -TimeoutSec 3 | Out-Null
    Write-Host "[ok] vLLM reachable."
} catch {
    Write-Host "[warn] inference will fail until vLLM is reachable."
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogFile) | Out-Null

if ($Background) {
    Write-Host "[run] Starting in background. Logs: $LogFile"
    $ErrFile = "$LogFile.err"
    $proc = Start-Process -FilePath $Python -ArgumentList @("run_backend.py") -WorkingDirectory $ScriptDir -WindowStyle Hidden -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile -PassThru
    Write-Host "[ok] PID $($proc.Id) listening on http://127.0.0.1:$ServerPort"
} else {
    Write-Host "[run] Starting foreground on http://127.0.0.1:$ServerPort"
    & $Python run_backend.py
}
