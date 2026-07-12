# Shared cluster-node launcher (Windows). Called by start-master.ps1 /
# start-slave.ps1 — keep using those entry points; don't run this directly.
param(
    [Parameter(Mandatory)][ValidateSet("master", "slave")][string]$Role,
    [switch]$Build,
    [string]$NodeName = ""   # optional; overrides NAME in cluster_config.py
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$env:CLUSTER_ROLE = $Role
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
if ($Role -eq "master") {
    & $Python -c "import cluster_config; cluster_config.require_valid_advertised_urls(); print('starting master:', cluster_config.NODE_NAME, cluster_config.MASTER_LLM_API_URL)"
} else {
    & $Python -c "import cluster_config; print('starting slave:', cluster_config.NODE_NAME, 'master=', cluster_config.CLUSTER_MASTER_API_URL)"
}

if ($Role -eq "master") {
    Push-Location "messenger"
    & ".\start.ps1" -Build:$Build -Background -Prod
    Pop-Location
}

Push-Location "llm-api"
& ".\start.ps1" -Build:$Build -Background
Pop-Location

Push-Location "hoonbot"
& ".\start.ps1" -Build:$Build -Background
Pop-Location

Write-Host "[ok] $Role node startup requested."
