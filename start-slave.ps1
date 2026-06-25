param(
    [switch]$Build,
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
& $Python -c "import cluster_config; print('starting slave:', cluster_config.NODE_NAME, 'master=', cluster_config.CLUSTER_MASTER_API_URL)"

Push-Location "llm-api"
& ".\start.ps1" -Build:$Build -Background
Pop-Location

Push-Location "hoonbot"
& ".\start.ps1" -Build:$Build -Background
Pop-Location

Write-Host "[ok] Slave node startup requested."
