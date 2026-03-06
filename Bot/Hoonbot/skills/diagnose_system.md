# Diagnose System

Run a full system health check on this Linux machine. Execute the following checks using `shell_exec` and report results in a clean summary.

## 1. CPU

```bash
lscpu | grep -E 'Model name|^CPU\(s\)|Thread|Core|MHz' && echo "---" && top -bn1 | grep '%Cpu' | head -1
```

## 2. RAM

```bash
free -h --si | grep -E 'Mem|Swap'
```

## 3. GPU Utilization & VRAM

```bash
nvidia-smi --query-gpu=name,utilization.gpu,memory.total,memory.used,memory.free,temperature.gpu,power.draw --format=csv,noheader,nounits
```

If `nvidia-smi` is not found, fall back to:

```bash
lspci | grep -i vga
```

## 4. Disk Status (All Mounts)

```bash
df -h --type=ext4 --type=xfs --type=btrfs --type=zfs --type=ntfs --type=vfat 2>/dev/null || df -h --exclude-type=tmpfs --exclude-type=devtmpfs --exclude-type=squashfs --exclude-type=overlay
```

## 5. System Uptime & Load

```bash
uptime
```

## 6. Top Processes by Memory

```bash
ps aux --sort=-%mem | head -11
```

## Output Format

Present results as a single organized summary:

```
=== System Diagnostics ===

CPU: <name>, <cores>C/<threads>T, <load>% load
RAM: <used>/<total> (<pct>%)
Swap: <used>/<total>
GPU: <name>, <util>% util, VRAM <used>/<total> MB, <temp>°C
Disks:
  /dev/sda1 on /       — <used>/<total> (<pct>%)
  /dev/sdb1 on /data   — <used>/<total> (<pct>%)
  ...
Uptime: <days>d <hours>h, load avg: <1m> <5m> <15m>

Top Memory Consumers:
  1. <process> — <ram> MB (<pct>%)
  2. ...
```

Flag any warnings:
- CPU load > 95%
- RAM usage > 70%
- GPU temp > 80°C or VRAM usage > 95%
- Any disk > 80% full
- Swap usage > 50%
