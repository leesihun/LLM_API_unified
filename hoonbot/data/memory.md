# Hoonbot Memory

This file stores persistent information about the user, projects, preferences, and important facts.

Last updated: 2026-05-08 15:58 KST

## User

- Name: SiHun Lee
- Language: English (default)
- **Preference: Call as "User" - never use valid name**

## ⚠️ Critical Behavior Rules

1. **ALWAYS fetch fresh/live data when reporting system status.** Never rely on cached or previously reported values. Always run diagnostic commands directly.
2. **WHEN DEALING WITH FILES AND FOLDERS, CHECK ITS PATH CAREFULLY.** Don't assume. Check its name. If not sure, ask the user!!!
3. **Update memory every system check (heartbeat).** After every heartbeat, overwrite all stale sections in this file with fresh live data. The memory must always reflect the current state.
4. **When training crashes, restart it IMMEDIATELY.** Do not wait for user input. Check logs, find last epoch, and relaunch.
5. **Keep llama-server alive.** It takes ~30 min to load models. Only kill it if GPU memory is needed for training AND no training is active. If GPU memory is needed for training, do NOT kill llama-server. Ask the user for instructions instead.
6. **ALWAYS save to memory.** Hoonbot memory file is the only thing that lives through everything. Always save something even remotely important to memory
7. **ALWAYS update memory**
8. **CHECK THE LOG FILE** After you run something always.... wait 5 seconds and then check the log file to confirm everything is running as intended.
9. **Don't care about warnings** Proactively proceed. Just notify the user
10. **Give user a detailed explanation** Tell user in detail, what I did, why it did, how it did in all steps. Be verbose

## System Health (2026-05-08 15:22 KST)

### GPU Status

| GPU | Name | Status | Memory Used | Memory Free | Util | Temp |
|------|------|--------|-------------|-------------|------|------|
| 0 | NVIDIA T400 4GB | Idle | 10 MiB | 3706 MiB | 0% | 31°C |
| 1 | NVIDIA H200 NVL | Active | 86006 MiB (~84 GiB) | 57151 MiB (~56 GiB) | 48% | 47°C |
| 2 | NVIDIA H200 NVL | Active | 84140 MiB (~82 GiB) | 59017 MiB (~58 GiB) | 0% | 48°C |

**Notes:**

- GPU 0 is idle (T400, only 4GB — not suitable for training)
- GPU 1 running vae2 training, GPU 2 running vae4 training
- Both H200s at 47-48°C — normal operating temperature
- ⚠️ Root filesystem (`/`) at 66% (550G/879G) — monitor closely

### RAM

- Total: ~503 GB, Used: ~48 GB, Available: ~450 GB

### Disk

- /: 879G total, 550G used (66%), 285G available ⚠️
- /boot/efi: 599M total, 6.1M used (2%)
- /scratch0: 7.0T total, 2.0T used (28%), 5.1T available
- /scratch1: 7.0T total, 901G used (13%), 6.2T available
- /scratch2: 7.0T total, 1.6T used (22%), 5.5T available
- /scratch3: 7.0T total, 50G used (1%), 7.0T available

### llama-server

- Running on pts/22, PID 534894
- Model: MiniMax-M2-UD-Q4_K_XL, port 5905
- Memory: ~6.6 GiB, CPU ~26%, uptime ~711 hours (since May 4)

## MeshGraphNets-V VAE Latent Dim Sweep

**Project path:** `/scratch1/MeshGraphNets-V`

**Config dir:** `/scratch1/MeshGraphNets-V/_b8_all_warpage_input`

**Main script:** `MeshGraphNets_main.py`

**Output logs:** `/scratch1/MeshGraphNets-V/outputs/b8_all/train_vae{N}.log`

**Model saves:** `/scratch1/MeshGraphNets-V/model_zoo/vae{N}/`

**Training epochs:** 500 per model (~4.2 hours each at ~30s/epoch)

### Sweep configs (16 files total)

| Latent Dim | Train Config | Infer Config | GPU |
|---|---|---|---|
| 2 | `config_train_vae2.txt` | `config_infer_vae2.txt` | 1 |
| 4 | `config_train_vae4.txt` | `config_infer_vae4.txt` | 2 |
| 8 | `config_train_vae8.txt` | `config_infer_vae8.txt` | 0 |
| 16 | `config_train_vae16.txt` | `config_infer_vae16.txt` | 1 |
| 32 | `config_train_vae32.txt` | `config_infer_vae32.txt` | 0 |
| 64 | `config_train_vae64.txt` | `config_infer_vae64.txt` | 1 |
| 128 | `config_train_vae128.txt` | `config_infer_vae128.txt` | 0 |
| 256 | `config_train_vae256.txt` | `config_infer_vae256.txt` | 1 |

### Sweep Execution Plan (2 at a time, sequential pairs)

**Launch commands (run from /scratch1/MeshGraphNets-V):**

```text
nohup python MeshGraphNets_main.py --config ./_b8_all_warpage_input/config_train_vae{N}.txt > outputs/b8_all/train_vae{N}.log 2>&1 &
```

(GPU is specified inside each config file via `gpu_ids`. No `--gpu` flag — script only accepts `--config`.)

| Pair | Train | Infer | GPUs | Status |
|---|---|---|---|---|
| 1 | vae2, vae4 | vae2, vae4 | 1, 2 | **RUNNING** (vae2 PID 2126583, vae4 PID 2127153 — both restarted 15:58 KST) |
| 2 | vae8, vae16 | vae8, vae16 | 0, 1 | pending |
| 3 | vae32, vae64 | vae32, vae64 | 0, 1 | pending |
| 4 | vae128, vae256 | vae128, vae256 | 0, 1 | pending |

### Pair 1 Live Status (as of 15:22 KST)

- **vae2** (GPU 1): Epoch 497/500 (~12h 27min elapsed) — TrainOpt recon=8.35e-03, mmd=1.01e-01, total=1.94e-02 | ValidQ recon=1.52e-02, mmd=9.98e-02, total=2.52e-02 | ValidPrior@8 recon=1.73e-01, gap=1.57e-01
- **vae4** (GPU 2): Epoch 490/500 (~12h 22min elapsed) — TrainOpt recon=5.42e-03, mmd=1.41e-01, total=1.97e-02 | ValidQ recon=1.02e-02, mmd=1.39e-01, total=2.41e-02 | ValidPrior@8 recon=1.66e-01, gap=1.56e-01

**Note:** Both trainings restarted from scratch after crash detection at epochs 498/500 and 491/500.

**Note:** Startup takes ~10+ minutes per job (serial z-score normalization, coarsening).

**Note:** pin_memory=True causes "Pin memory thread exited unexpectedly" crashes — configs use pin_memory=False.

**Bug fixed:** Script only accepts `--config` and `--gpu` args, not positional args. GPU must be set in config file.

## Reminders

- None currently set this should be the admin memory. add this
