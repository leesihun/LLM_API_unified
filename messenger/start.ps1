param(
    [switch]$Build,
    [switch]$Background,
    [switch]$Prod
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

function Find-Npm {
    $npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($npmCmd) { return $npmCmd.Source }
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if ($npm) { return $npm.Source }
    throw "npm was not found. Install Node/npm first."
}

$Python = Find-Python
$Npm = Find-Npm

& $Python config.py --ensure-dirs --export powershell | Invoke-Expression
$Port = & $Python config.py --get PORT
$LogFile = & $Python config.py --get MESSENGER_LOG_FILE

Write-Host "=================================================="
Write-Host "  Huni Messenger"
Write-Host "=================================================="

if ($Build -or -not (Test-Path "node_modules")) {
    Write-Host "[build] Installing npm dependencies..."
    & $Npm install
}

if ($Build -or -not (Test-Path "client\dist-web\index.html")) {
    Write-Host "[build] Building web client..."
    & $Npm run build:web
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogFile) | Out-Null

if ($Prod) {
    $NpmArgs = @("run", "start", "--workspace=server")
} else {
    $NpmArgs = @("run", "dev:server")
}

if ($Background) {
    Write-Host "[run] Starting in background. Logs: $LogFile"
    $ErrFile = "$LogFile.err"
    $proc = Start-Process -FilePath $Npm -ArgumentList $NpmArgs -WorkingDirectory $ScriptDir -WindowStyle Hidden -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile -PassThru
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
    & $Npm @NpmArgs
}
