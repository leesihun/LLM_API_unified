param(
    [string]$NodeName = ""   # optional; overrides NAME in cluster_config.py
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$env:CLUSTER_ROLE = "slave"
if ($NodeName) { $env:NODE_NAME = $NodeName }

function Find-Python {
    if ($env:PYTHON) { return $env:PYTHON }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    throw "Python >= 3.10 was not found."
}

$Python = Find-Python

function Install-PythonRequirements($RequirementsPath) {
    if ($env:OFFLINE_DEPS_DIR) {
        $Wheelhouse = Join-Path $env:OFFLINE_DEPS_DIR "wheels"
        if (-not (Test-Path $Wheelhouse)) { $Wheelhouse = $env:OFFLINE_DEPS_DIR }
        & $Python -m pip install --no-index --find-links $Wheelhouse -r $RequirementsPath
    } else {
        & $Python -m pip install -r $RequirementsPath
    }
}

& $Python -c "import cluster_config; print('cluster config:', cluster_config.NODE_ROLE, cluster_config.NODE_NAME, 'master=', cluster_config.CLUSTER_MASTER_API_URL)"

Write-Host "[install] LLM API dependencies"
Install-PythonRequirements "llm-api\deps\requirements.txt"

Write-Host "[install] Hoonbot dependencies"
Install-PythonRequirements "hoonbot\deps\requirements.txt"

Write-Host "[ok] Slave node installed."
