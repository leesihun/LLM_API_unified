# Skill: Diagnose System

Run a strict host health check and return one concise report.

## Trigger

diagnose system, health check, server status, resource usage

## Required Inputs

- none (no Messenger API calls needed)

## Tool

- `shell_exec`

## Commands (Run In Order)

1. CPU: `lscpu`
2. Load: `uptime`
3. RAM/Swap: `free -h --si`
4. Disk: `df -h`
5. Top memory processes: `ps aux --sort=-%mem | head -11`
6. GPU (strict): `nvidia-smi --query-gpu=name,utilization.gpu,memory.total,memory.used,memory.free,temperature.gpu,power.draw --format=csv,noheader,nounits`

## Hard Rules

- If any command fails, report failure and stop.
- No fallback commands.
- Include warning flags:
  - CPU load > 95%
  - RAM > 70%
  - Swap > 50%
  - Any disk > 80%
  - GPU temp > 80C or VRAM > 95%

## Response Format

`System Diagnostics: CPU=<...>; RAM=<...>; Swap=<...>; GPU=<...>; Disks=<...>; Uptime=<...>; TopMem=<...>; Warnings=<list|none>.`
