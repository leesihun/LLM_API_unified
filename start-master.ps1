param(
    [switch]$Build,
    [string]$NodeName = ""   # optional; overrides NAME in cluster_config.py
)
& (Join-Path $PSScriptRoot "scripts\start-node.ps1") -Role master -Build:$Build -NodeName $NodeName
