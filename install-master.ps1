param(
    [string]$NodeName = ""   # optional; overrides NAME in cluster_config.py
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$env:CLUSTER_ROLE = "master"
if ($NodeName) { $env:NODE_NAME = $NodeName }

function Find-Python {
    if ($env:PYTHON) { return $env:PYTHON }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    throw "Python >= 3.10 was not found."
}

function Find-Npm {
    $npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($npmCmd) { return $npmCmd.Source }
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if ($npm) { return $npm.Source }
    throw "npm was not found."
}

$Python = Find-Python
$Npm = Find-Npm

function Install-PythonRequirements($RequirementsPath) {
    if ($env:OFFLINE_DEPS_DIR) {
        $Wheelhouse = Join-Path $env:OFFLINE_DEPS_DIR "wheels"
        if (-not (Test-Path $Wheelhouse)) { $Wheelhouse = $env:OFFLINE_DEPS_DIR }
        & $Python -m pip install --no-index --find-links $Wheelhouse -r $RequirementsPath
    } else {
        & $Python -m pip install -r $RequirementsPath
    }
}

function Install-MessengerNodeModules {
    $OfflineNodeModules = $null
    if ($env:MESSENGER_NODE_MODULES_DIR -and (Test-Path $env:MESSENGER_NODE_MODULES_DIR)) {
        $OfflineNodeModules = $env:MESSENGER_NODE_MODULES_DIR
    } elseif ($env:OFFLINE_DEPS_DIR) {
        $Candidate = Join-Path $env:OFFLINE_DEPS_DIR "node_modules"
        if (Test-Path $Candidate) { $OfflineNodeModules = $Candidate }
    }

    Push-Location "messenger"
    if ($OfflineNodeModules -and -not (Test-Path "node_modules")) {
        Copy-Item -Recurse -Force $OfflineNodeModules "node_modules"
    } else {
        & $Npm install
    }
    & $Npm run build:web
    Pop-Location
}

& $Python -c "import cluster_config; cluster_config.require_valid_advertised_urls(); print('cluster config ok:', cluster_config.NODE_ROLE, cluster_config.NODE_NAME)"

Write-Host "[install] LLM API dependencies"
Install-PythonRequirements "llm-api\deps\requirements.txt"

Write-Host "[install] Hoonbot dependencies"
Install-PythonRequirements "hoonbot\deps\requirements.txt"

Write-Host "[install] Messenger dependencies"
Install-MessengerNodeModules

Write-Host "[ok] Master node installed."
