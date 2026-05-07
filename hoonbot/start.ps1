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
Write-Host "  Hoonbot"
Write-Host "=================================================="

if ($Build) {
    Write-Host "[build] Installing Python dependencies..."
    & $Python -m pip install -r "deps\requirements.txt"
}

$MessengerUrl = & $Python -c "import config; print(config.MESSENGER_URL)"
$LlmApiUrl = & $Python -c "import config; print(config.LLM_API_URL)"
$HoonbotPort = & $Python -c "import config; print(config.HOONBOT_PORT)"
$LogFile = & $Python -c "import config; from pathlib import Path; print(Path(config.DATA_DIR) / 'hoonbot.log')"

if ((-not (Test-Path "data\.llm_key")) -or (-not (Test-Path "data\.llm_model"))) {
    Write-Host "[setup] LLM credentials not found. Running setup..."
    New-Item -ItemType Directory -Force -Path "data" | Out-Null
    & $Python scripts\setup_credentials.py
}

Write-Host "[check] Messenger: $MessengerUrl"
try {
    Invoke-WebRequest -UseBasicParsing -Uri "$MessengerUrl/health" -TimeoutSec 3 | Out-Null
    Write-Host "[ok] Messenger reachable."
} catch {
    Write-Host "[warn] Messenger not reachable. Hoonbot will retry on startup."
}

Write-Host "[check] LLM API: $LlmApiUrl"
try {
    Invoke-WebRequest -UseBasicParsing -Uri "$LlmApiUrl/health" -TimeoutSec 3 | Out-Null
    Write-Host "[ok] LLM API reachable."
} catch {
    Write-Host "[warn] LLM API not reachable."
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogFile) | Out-Null

if ($Background) {
    Write-Host "[run] Starting in background. Logs: $LogFile"
    $ErrFile = "$LogFile.err"
    $proc = Start-Process -FilePath $Python -ArgumentList @("hoonbot.py") -WorkingDirectory $ScriptDir -WindowStyle Hidden -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile -PassThru
    Write-Host "[ok] PID $($proc.Id) listening on http://localhost:$HoonbotPort"
} else {
    Write-Host "[run] Starting foreground on http://localhost:$HoonbotPort"
    & $Python hoonbot.py
}
