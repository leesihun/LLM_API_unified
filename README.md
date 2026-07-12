# Huni Self-Hosted AI Stack

Three self-contained services plus an optional master/slave cluster, all
configured from **one file at the repo root: [`cluster_config.py`](cluster_config.py)**.

## Services

| Folder | Port | Description |
|---|---:|---|
| `llm-api/` | 10002 | OpenAI-compatible LLM API wrapping vLLM, agent loop, auth, RAG, and tools |
| `hoonbot/` | 10001 | Python bot bridging Messenger, LLM API, cluster delegation, and persistent memory |
| `messenger/` | 10006 | Node.js real-time team chat with React UI, Socket.IO, files, and terminals |

## Configure everything in one file

Open [`cluster_config.py`](cluster_config.py) and edit the **`EDIT HERE`** block at
the top. That single block controls every machine and all three services — you do
not need to touch the per-app `config.py` files for normal setup:

| Setting | What it does |
|---|---|
| `ROLE` | `"master"` (runs all 3 services) or `"slave"` (runs llm-api + hoonbot) |
| `NAME` | Unique node name — routing handle, log name, `@mention`. `""` = auto |
| `THIS_NODE_IP` / `MASTER_NODE_IP` | LAN IPs. On a slave, point `MASTER_NODE_IP` at the master |
| `VLLM_SERVER_URL` | **Where llm-api loads the model server from** (your vLLM) |
| `MESSENGER_PORT` / `HOONBOT_PORT` / `LLM_API_PORT` | Service ports |
| `CLUSTER_SECRET` | Shared token every node must match — change for real deployments |
| `LLM_API_ADMIN_USERNAME` / `_PASSWORD` | llm-api admin login |
| `TAVILY_API_KEY` | Web-search tool key |
| `RAG_EMBEDDING_MODEL` / `RAG_RERANKER_MODEL` / `RAG_EMBEDDING_DEVICE` | RAG model paths + device |
| `BOT_NAME` / `BOT_HOME_ROOM_NAME` / `HEARTBEAT_*` | Hoonbot identity and heartbeat |
| `MESSENGER_TERMINAL_TOKEN` | Gates the embedded `/claude` and `/opencode` terminals |

Any value can also be overridden by an environment variable of the same name.
For a single machine, the defaults work as-is — just point `VLLM_SERVER_URL`
at your running vLLM server.

## Quick Start

1. Start your `vLLM` server (not included — see [llm-api/README.md](llm-api/README.md)).
2. Edit the `EDIT HERE` block in [`cluster_config.py`](cluster_config.py).
3. Run the launcher for this machine's role:

```powershell
# Windows — just double-click Start-Master.cmd (master) or Start-Slave.cmd (slave).
```

On Windows the `.cmd` launchers are **one-click**. The first run does the
one-time setup automatically — creates a Python virtualenv (`.venv`), installs
the Python deps, and builds the Messenger bundle once — then starts every
service. **Later runs start instantly with no npm, no Vite, and no build step.**
Pass `-Rebuild` to redo the one-time setup after dependency changes:

```powershell
.\setup-and-start-master.ps1            # same as double-clicking Start-Master.cmd
.\setup-and-start-master.ps1 -Rebuild   # refresh venv + rebuild Messenger bundle
```

```bash
# Linux — --build installs deps first, then launches
./start-master.sh --build
./start-slave.sh  --build
```

The first run needs Python (always) and, on the machine that hosts Messenger,
Node/npm **once** to build the bundle. After that the host only runs prebuilt
artifacts. Everything else comes from `cluster_config.py`.

### Windows desktop Messenger app (end users)

End users don't need any of the above. Build a portable app once and hand out
the single `.exe` — it needs **no Python, Node, or npm** on the user's PC:

```powershell
cd messenger ; npm.cmd run build:portable   # -> client/dist-portable/Messenger.exe
```

The app is a **thin client**: it just opens the master node's Messenger UI
(`http://<master-ip>:10006`). The default address is baked in from
`cluster_config.MESSENGER_URL`; on first launch (or anytime via **Ctrl+,**) the
user can point it at a different server. Double-click and chat.

For airgapped Linux nodes, use the install step explicitly. The scripts now
auto-detect an offline bundle if it is placed in one of these nearby paths:

- `./llm_api_fast_airgap`
- `./offline_deps`
- `./.offline_deps`
- `./airgap`
- `../llm_api_fast_airgap`
- `../offline_deps`
- `$HOME/llm_api_fast_airgap`

You can still override with `OFFLINE_DEPS_DIR` if needed.

Linux scripts refuse online npm fallback. If the offline bundle is missing,
they fail immediately instead of reaching `registry.npmjs.org`.

```bash
./start-master.sh --build   # first run: stage offline deps, then launch
./start-master.sh           # later runs

./start-slave.sh --build
./start-slave.sh
```

Expected offline bundle layout:

- `messenger/node_modules/` or `node_modules/`
- `messenger/server/dist/server.cjs` or `server/dist/server.cjs`
- `messenger/client/dist-web/index.html` or `client/dist-web/index.html`
- `node/` with an unpacked Linux Node runtime, or a `node-v*-linux-*.tar.xz` / `.tar.gz` archive

Linux scripts skip Python package installation entirely and assume the target
server's Python environment is already provisioned.

### Building the airgap bundle on Windows (via WSL)

The bundle must be assembled on Linux because `messenger/node-pty` is a native
module — Windows binaries will not load on the airgapped target. From a WSL
Ubuntu shell with internet access, run:

```bash
cd /mnt/c/Users/<you>/Desktop/Huni/LLM_API_fast    # or wherever the repo lives
bash scripts/build-airgap-bundle.sh
```

This produces `dist/llm_api_fast_airgap.tar.gz` containing the messenger
runtime, a Linux Node tarball, and prebuilt server/web bundles. Copy it to the
airgapped server and extract it next to the repo (or in `$HOME`):

```bash
scp dist/llm_api_fast_airgap.tar.gz target:~/
ssh target 'tar -xzf llm_api_fast_airgap.tar.gz'
ssh target 'cd /path/to/LLM_API_fast && ./start-master.sh --build'
```

Flags: `--clean` wipes caches before building; `--skip-node` omits the Node
runtime tarball if the server already has one; `--node-version=X.Y.Z` and
`--arch=x64|arm64` override the defaults (Node 20.18.0 / x64).

Manual service startup still works:

```bash
# 1. LLM API (start vLLM first; see llm-api/README.md)
cd llm-api && ./start.sh --build

# 2. Messenger
cd messenger && ./start.sh --build --prod

# 3. Hoonbot
cd hoonbot && ./start.sh --build
```

Windows uses the same shape (`-Build` is one-time; without it, Messenger runs
the prebuilt `server/dist/server.cjs` directly — no npm, no Vite, no tsx):

```powershell
cd llm-api; .\start.ps1 -Build
cd ..\messenger; .\start.ps1 -Build   # first time only; later: .\start.ps1
cd ..\hoonbot; .\start.ps1 -Build
```

`messenger\start.ps1 -Dev` runs the TypeScript dev server (tsx watch) for
development instead of the prebuilt bundle.

## Cluster Notes

- Use one `NODE_NAME` per machine; this is the routing name, log name, and
  Messenger mention name.
- Master runs Messenger, master Hoonbot, and master LLM API.
- Slaves run Hoonbot in worker mode plus their local LLM API/model runtime.
- Inter-node URLs should be IP-style, for example `http://192.168.0.10:10002`.
  Loopback URLs are only for same-machine service calls.
- Master cluster APIs live under `/api/cluster/*` on the master LLM API.
- Messenger can delegate with `@node-name task`, `@tag:name task`,
  `@role:name task`, or `@all-slaves task`.

## Dependencies

- `llm-api` requires a running vLLM server, default `http://127.0.0.1:10000`.
- `hoonbot` requires LLM API credentials created by `hoonbot/scripts/setup_credentials.py`.
- `messenger` is master-only in v1; slaves do not run Messenger.
