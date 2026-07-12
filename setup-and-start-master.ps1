param(
    [switch]$Rebuild,           # force venv reinstall + Messenger rebuild
    [string]$NodeName = ""      # optional; overrides NAME in cluster_config.py
)
& (Join-Path $PSScriptRoot "scripts\setup-node.ps1") -Role master -Rebuild:$Rebuild -NodeName $NodeName
