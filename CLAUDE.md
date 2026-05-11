# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Shape

Three independent services live side-by-side in this repo, plus a shared cluster control plane:

- **`llm-api/`** (port 10007, Python/FastAPI) — OpenAI-compatible API wrapping a separately-run `llama.cpp` server, with an agentic loop, JWT auth, RAG, and tool calling.
- **`hoonbot/`** (port 10001, Python/FastAPI) — Bridges Messenger ↔ LLM API; handles webhooks, debouncing, persistent memory, heartbeat loop, and (on master) cluster delegation.
- **`messenger/`** (port 10006, Node/Express + React/Vite) — Real-time chat UI with Socket.IO, file uploads, and embedded `claude` / `opencode` terminals over WebSocket. Master-only.
- **`cluster_config.py`** at the repo root — single source of truth for node role, name, IPs, ports, prompt/heartbeat/skill profiles, and cluster token. Each app's local `config.py` imports it via `_load_cluster_config()` and exposes only what that app needs.

`llama.cpp` is **not** in this repo. It must be running before `llm-api` starts (default `http://127.0.0.1:5905`, optional backup at `:10000`).

## Common Commands

### Whole-stack (cluster)

```powershell
.\start-master.ps1 -Build        # install deps, then start messenger + llm-api + hoonbot in background
.\start-slave.ps1  -Build        # slaves run only llm-api + hoonbot (no messenger)
```
Bash equivalents: `./start-master.sh --build`, `./start-slave.sh --build`.
On Linux, `--build` now means "run install-master.sh / install-slave.sh first, then launch".
`Start-Master.cmd` / `Start-Slave.cmd` are double-click wrappers.

`install-master.{sh,ps1}` and `install-slave.{sh,ps1}` are install-only (no launch).
On Linux, `OFFLINE_DEPS_DIR` is the airgap contract for staged Messenger runtime assets. Supported Messenger bundle paths are `messenger/node_modules`, `messenger/server/dist`, `messenger/client/dist-web`, and a Linux Node runtime under `node/` or `node-v*-linux-*`. In airgapped mode the scripts skip Python package installation entirely and assume the target server's Python environment is already provisioned. If `OFFLINE_DEPS_DIR` is unset, the scripts auto-detect nearby bundle directories such as `./llm_api_fast_airgap`, `./offline_deps`, `../llm_api_fast_airgap`, or `$HOME/llm_api_fast_airgap`.

### Per-service (run individually)

```powershell
cd llm-api    ; .\start.ps1 -Build      # llama.cpp must already be running
cd messenger  ; .\start.ps1 -Build      # builds web client (npm run build:web) then starts
cd hoonbot    ; .\start.ps1 -Build      # depends on messenger + llm-api being up
```

For Linux Messenger production, `./start.sh --prod` now runs the prebuilt server bundle directly (`server/dist/server.cjs`) instead of `npm run start`.

### Validation (no repo-wide test suite)

```powershell
python -m py_compile <file.py>                  # syntax check Python edits
cd messenger ; npm.cmd run typecheck            # TS check (server + client)
cd messenger ; npm.cmd run build:web            # rebuild served bundle after UI/shared-type changes
cd hoonbot   ; python scripts\test_llm.py       # verify LLM API connectivity from hoonbot
cd llm-api   ; python scripts\clear_data.py     # wipe logs/scratch/sessions
cd llm-api   ; python scripts\clear_rag_data.py --all   # required when switching embedding models
```

`messenger/config.py --export powershell` (or `bash`) prints the env-var exports the start scripts use; `--ensure-dirs` creates runtime dirs.

## Cluster Architecture

The cluster is a master + N slaves over plain HTTP on the LAN. Roles are picked by `CLUSTER_ROLE` env var (set by the start scripts).

- **Master** runs all three services. Slaves run only `llm-api` + `hoonbot` (in worker mode).
- The master `llm-api` exposes a control plane under `/api/cluster/*` (register, heartbeat, claim/complete tasks). Backed by `llm-api/backend/core/cluster_store.py`.
- Slave `hoonbot` polls the master via `hoonbot/core/cluster_client.py` and `cluster_worker.py` to claim delegated tasks.
- Master `hoonbot` parses Messenger directives `@<node-name> task`, `@tag:<tag> task`, `@role:<role> task`, `@all-slaves task` and submits them to `/api/cluster/tasks`. Reserved directives: `bot`, `clear`, `compact`, plus the bot's own name.
- `cluster_config.validate_advertised_url()` enforces a hard rule: inter-node URLs must be `http://<ip>:<port>`. Loopback, `localhost`, DNS names, and Cloudflare/`trycloudflare.com`/`aihoonbot.com` hostnames are rejected for advertised URLs. `MASTER_LLM_API_URL`, `MESSENGER_URL`, `HOONBOT_WEBHOOK_URL`, and `ADVERTISED_LLM_API_URL` are validated on master start.
- Each node has `NODE_NAME`, `NODE_CAPABILITIES`, and `NODE_TAGS`. `NODE_NAME` doubles as the routing handle, log name, and Messenger mention name — keep it unique per machine.
- Prompt/heartbeat/skill profiles resolve from `cluster_config` to `hoonbot/prompts/<profile>/PROMPT.md`, `.../HEARTBEAT.md`, and `hoonbot/profiles/<profile>/skills/`. Defaults are `master` and `slave`. Hoonbot falls back to top-level `prompts/PROMPT.md` / `HEARTBEAT.md` / `skills/` if a profile file is absent.

## Per-Service Architecture Notes

**llm-api** — single `while` loop in `backend/agent/`, no sub-agents or chains. Tool calls run via `asyncio.gather`. The system prompt is cached at module import and `cache_prompt=True` is passed to llama.cpp. Sessions are slot-pinned (`id_slot = hash(session_id) % LLAMACPP_SLOTS`) for stable KV-cache hits. Microcompaction compresses old iterations and spills oversize tool results to `data/tool_results/`. Workers > 1 share no state — use `SERVER_WORKERS = 1` during development. Default admin: `admin` / `administrator`.

**hoonbot** — FastAPI webhook receiver. `handlers/webhook.py` validates → `mark_read` → debounces (`DEBOUNCE_SECONDS=1.5`) → calls LLM API. Memory lives at `hoonbot/data/memory.md` and is injected into the system prompt with an absolute path so the LLM can use file_reader/file_writer tools — **don't move `data/` after startup without restarting**. Heartbeat first tick is delayed one full interval (never immediate). Bot API key is persisted at `hoonbot/data/.apikey`; deleting forces re-registration with Messenger.

**messenger** — `sql.js` runs the SQLite DB **in memory**, auto-saved to `data/messenger.db` every 5s — unclean shutdown can lose up to 5s. No TLS built-in; expects LAN/VPN. Terminal WS endpoints (`/claude`, `/opencode`) gate access via `SECRET_TOKEN` (default `leesihun` — change in prod). The Electron portable build is Windows-only by default (`--linux` for AppImage).

## Configuration Conventions

- Each app's `config.py` is the **single runtime configuration surface** for that app. Edit it directly. Do NOT introduce hidden `.env` runtime requirements.
- Cluster-wide values (role, name, IPs, ports, profiles, token) live in `/cluster_config.py`. App-local `config.py` files import it via `_load_cluster_config()` and surface what they need with `getattr(_CLUSTER, ..., default)`.
- Legitimate runtime env overrides are limited and explicit: e.g. `LLM_API_URL` for hoonbot, `LLAMACPP_HOST` for llm-api, the `MESSENGER_*_DIR` paths for messenger. Don't add new env-var knobs casually.
- Never commit: `data/` (any service's runtime dir), `*.gguf`, `models/`, `llamacpp/`, `offline_models/`, `.env*`, `.apikey`, `.llm_key`, `.llm_model`, `node_modules/`, `dist*/`.

## Style (from AGENTS.md)

- 4-space indent for Python, 2-space for TS/TSX.
- `snake_case` for Python; `camelCase` vars/funcs and `PascalCase` components for TS/React.
- Commits: small, scoped subjects like `messenger: rebuild web attachment flow`.
- PRs should list verification commands run, mention any port/config changes, and include screenshots for visible Messenger UI changes.
