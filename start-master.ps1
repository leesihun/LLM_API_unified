param(
    [switch]$Build,
    [string]$NodeName = "master"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$env:CLUSTER_ROLE = "master"
$env:NODE_NAME = $NodeName

function Find-Python {
    if ($env:PYTHON) { return $env:PYTHON }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    throw "Python >= 3.10 was not found."
}

$Python = Find-Python
& $Python -c "import cluster_config; cluster_config.require_valid_advertised_urls(); print('starting master:', cluster_config.NODE_NAME, cluster_config.MASTER_LLM_API_URL)"

Push-Location "messenger"
& ".\start.ps1" -Build:$Build -Background -Prod
Pop-Location

Push-Location "llm-api"
& ".\start.ps1" -Build:$Build -Background
Pop-Location

Push-Location "hoonbot"
& ".\start.ps1" -Build:$Build -Background
Pop-Location

Write-Host "[ok] Master node '$NodeName' startup requested."
