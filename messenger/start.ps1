param(
    [switch]$Build,        # rebuild deps + web client + server bundle (developer step)
    [switch]$Background,
    [switch]$Prod,         # accepted for compatibility; prebuilt run is now the default
    [switch]$Dev           # run the TypeScript dev server (tsx watch) instead of the bundle
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
    throw "Python was not found. Messenger config is config.py, so Python is required."
}

function Find-Node {
    # Prefer a bundled runtime (airgap-style) at the repo root: ..\node\node.exe
    $bundled = Join-Path (Split-Path -Parent $ScriptDir) "node\node.exe"
    if (Test-Path $bundled) { return $bundled }
    $node = Get-Command node -ErrorAction SilentlyContinue
    if ($node) { return $node.Source }
    return $null
}

function Find-Npm {
    $npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($npmCmd) { return $npmCmd.Source }
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if ($npm) { return $npm.Source }
    throw "npm was not found. Install Node/npm first (only needed for -Build)."
}

$Python = Find-Python

& $Python config.py --ensure-dirs --export powershell | Invoke-Expression
$Port = & $Python config.py --get PORT
$LogFile = & $Python config.py --get MESSENGER_LOG_FILE

Write-Host "=================================================="
Write-Host "  Huni Messenger"
Write-Host "=================================================="

$ServerBundle = Join-Path $ScriptDir "server\dist\server.cjs"
$WebIndex = Join-Path $ScriptDir "client\dist-web\index.html"

# ---- Build (developer step): only on explicit -Build ----
if ($Build) {
    $Npm = Find-Npm
    if (-not (Test-Path "node_modules")) {
        Write-Host "[build] Installing npm dependencies..."
        & $Npm install
    }
    Write-Host "[build] Building web client..."
    & $Npm run build:web
    Write-Host "[build] Bundling server (esbuild)..."
    & $Npm run build --workspace=server
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogFile) | Out-Null

# ---- Dev mode: run TypeScript directly via tsx watch ----
if ($Dev) {
    $Npm = Find-Npm
    if (-not (Test-Path "node_modules")) { & $Npm install }
    Write-Host "[run] Dev server (tsx watch) on http://127.0.0.1:$Port"
    if ($Background) {
        $ErrFile = "$LogFile.err"
        $proc = Start-Process -FilePath $Npm -ArgumentList @("run", "dev:server") -WorkingDirectory $ScriptDir -WindowStyle Hidden -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile -PassThru
        Write-Host "[ok] Dev PID $($proc.Id)"
    } else {
        & $Npm run dev:server
    }
    return
}

# ---- Default + -Prod: run the prebuilt bundle. No npm, no Vite, no tsx. ----
if (-not (Test-Path $ServerBundle)) {
    throw "Server bundle not found: server\dist\server.cjs`nRun '.\start.ps1 -Build' once to build it (needs Node/npm)."
}
if (-not (Test-Path $WebIndex)) {
    Write-Host "[warn] client\dist-web not found — the web UI will not be served. Run -Build to build it."
}

$Node = Find-Node
if (-not $Node) {
    throw "Node runtime not found. Install Node, or place a bundled runtime at ..\node\node.exe."
}

Write-Host "[run] Prebuilt server: $Node server\dist\server.cjs"

if ($Background) {
    Write-Host "[run] Starting in background. Logs: $LogFile"
    $ErrFile = "$LogFile.err"
    $proc = Start-Process -FilePath $Node -ArgumentList @("server\dist\server.cjs") -WorkingDirectory $ScriptDir -WindowStyle Hidden -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile -PassThru
    for ($i = 0; $i -lt 20; $i++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2 | Out-Null
            Write-Host "[ok] PID $($proc.Id) ready at http://127.0.0.1:$Port"
            exit 0
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    Write-Host "[warn] Started PID $($proc.Id), but health check did not pass yet."
} else {
    Write-Host "[run] Starting foreground on http://127.0.0.1:$Port"
    & $Node "server\dist\server.cjs"
}
