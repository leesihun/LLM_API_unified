#
# One-click master bootstrap + launch.
#
# First run does the one-time setup automatically:
#   1. Create a Python virtualenv (.venv) and install llm-api + hoonbot deps.
#   2. Build the Messenger bundle (server.cjs + web UI) once if missing.
# Then launches all three services from prebuilt artifacts (no npm at runtime).
#
# Subsequent runs skip setup and start instantly. Pass -Rebuild to redo setup.
#
param(
    [switch]$Rebuild,           # force venv reinstall + Messenger rebuild
    [string]$NodeName = ""      # optional; overrides NAME in cluster_config.py
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if ($NodeName) { $env:NODE_NAME = $NodeName }

# ---------------------------------------------------------------------------
# 1. Python virtualenv (.venv) + dependencies
# ---------------------------------------------------------------------------
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

# All downstream start scripts honor $env:PYTHON first.
$env:PYTHON = $VenvPython

# ---------------------------------------------------------------------------
# 2. Messenger bundle (server.cjs + web UI) — build once if missing
# ---------------------------------------------------------------------------
$Bundle = Join-Path $Root "messenger\server\dist\server.cjs"
$WebIndex = Join-Path $Root "messenger\client\dist-web\index.html"

if ($Rebuild -or -not (Test-Path $Bundle) -or -not (Test-Path $WebIndex)) {
    $Npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $Npm) { $Npm = Get-Command npm -ErrorAction SilentlyContinue }
    if (-not $Npm) {
        throw "Messenger bundle is missing and npm was not found.`nInstall Node.js (includes npm) once to build it: https://nodejs.org/  — after that, runs never need npm again."
    }
    Write-Host "[setup] Building Messenger bundle (one-time)..."
    Push-Location "messenger"
    try {
        if ($Rebuild -or -not (Test-Path "node_modules")) {
            Write-Host "[setup] npm install..."
            & $Npm.Source install
        }
        Write-Host "[setup] Building web client..."
        & $Npm.Source run build:web
        Write-Host "[setup] Bundling server (esbuild)..."
        & $Npm.Source run build --workspace=server
    } finally {
        Pop-Location
    }
    Write-Host "[ok] Messenger bundle built."
} else {
    Write-Host "[ok] Messenger bundle present (use -Rebuild to refresh)."
}

# ---------------------------------------------------------------------------
# 3. Launch all services from prebuilt artifacts (no -Build => no npm/pip)
# ---------------------------------------------------------------------------
Write-Host "[run] Launching master services..."
& "$Root\start-master.ps1"

Write-Host ""
Write-Host "[ok] One-click master startup complete."
