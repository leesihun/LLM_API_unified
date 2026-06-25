#
# One-click slave bootstrap + launch.
#
# First run creates a Python virtualenv (.venv) and installs llm-api + hoonbot
# deps. Then launches llm-api + hoonbot (slaves do not run Messenger).
# Subsequent runs start instantly. Pass -Rebuild to redo setup.
#
param(
    [switch]$Rebuild,           # force venv reinstall
    [string]$NodeName = ""      # optional; overrides NAME in cluster_config.py
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if ($NodeName) { $env:NODE_NAME = $NodeName }

function Find-SystemPython {
    if ($env:SYSTEM_PYTHON) { return $env:SYSTEM_PYTHON }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    throw "Python >= 3.10 was not found. Install it from https://www.python.org/downloads/ (check 'Add to PATH')."
}

$VenvDir = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$Marker = Join-Path $VenvDir ".installed"

if (-not (Test-Path $VenvPython)) {
    $SysPython = Find-SystemPython
    Write-Host "[setup] Creating virtual environment (.venv)..."
    & $SysPython -m venv $VenvDir
}

if ($Rebuild -or -not (Test-Path $Marker)) {
    Write-Host "[setup] Installing Python dependencies (one-time; this can take a while)..."
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r "llm-api\deps\requirements.txt"
    & $VenvPython -m pip install -r "hoonbot\deps\requirements.txt"
    "installed $(Get-Date -Format o)" | Out-File -FilePath $Marker -Encoding ascii
    Write-Host "[ok] Python dependencies installed."
} else {
    Write-Host "[ok] Python venv already provisioned (use -Rebuild to refresh)."
}

$env:PYTHON = $VenvPython

Write-Host "[run] Launching slave services..."
& "$Root\start-slave.ps1"

Write-Host ""
Write-Host "[ok] One-click slave startup complete."
