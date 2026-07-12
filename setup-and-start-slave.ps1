param(
    [switch]$Rebuild,           # force venv reinstall
    [string]$NodeName = ""      # optional; overrides NAME in cluster_config.py
)
& (Join-Path $PSScriptRoot "scripts\setup-node.ps1") -Role slave -Rebuild:$Rebuild -NodeName $NodeName
