# Huni Self-Hosted AI Stack

Three independent, self-contained services plus an optional master/slave cluster
control plane. App folders keep their own config adapter, while cluster-wide
role, node name, IP URLs, prompt profile, heartbeat profile, and skill profile
are controlled from `cluster_config.py`.
Hoonbot prompt and heartbeat profile files live under `hoonbot/prompts/`.
LLM API runtime prompt templates live under `llm-api/prompts/`.

## Services

| Folder | Port | Description |
|---|---:|---|
| `llm-api/` | 10007 | OpenAI-compatible LLM API wrapping llama.cpp, agent loop, auth, RAG, and tools |
| `hoonbot/` | 10001 | Python bot bridging Messenger, LLM API, cluster delegation, and persistent memory |
| `messenger/` | 10006 | Node.js real-time team chat with React UI, Socket.IO, files, and terminals |

## Quick Start

```bash
# Linux master: --build now runs install-master.sh first, then starts services
./start-master.sh --build

# Linux slave: --build now runs install-slave.sh first, then starts services
./start-slave.sh --build
```

```powershell
.\start-master.ps1 -Build
```

Single-click Windows wrappers are available at `Start-Master.cmd` and
`Start-Slave.cmd`.

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
./install-master.sh
./start-master.sh

./install-slave.sh
./start-slave.sh
```

Expected offline bundle layout:

- `messenger/node_modules/` or `node_modules/`
- `messenger/server/dist/server.cjs` or `server/dist/server.cjs`
- `messenger/client/dist-web/index.html` or `client/dist-web/index.html`
- `node/` with an unpacked Linux Node runtime, or a `node-v*-linux-*.tar.xz` / `.tar.gz` archive

Linux scripts skip Python package installation entirely and assume the target
server's Python environment is already provisioned.

Manual service startup still works:

```bash
# 1. LLM API (start llama.cpp first; see llm-api/README.md)
cd llm-api && ./start.sh --build

# 2. Messenger
cd messenger && ./start.sh --build --prod

# 3. Hoonbot
cd hoonbot && ./start.sh --build
```

Windows uses the same shape:

```powershell
cd llm-api; .\start.ps1 -Build
cd ..\messenger; .\start.ps1 -Build
cd ..\hoonbot; .\start.ps1 -Build
```

## Cluster Notes

- Use one `NODE_NAME` per machine; this is the routing name, log name, and
  Messenger mention name.
- Master runs Messenger, master Hoonbot, and master LLM API.
- Slaves run Hoonbot in worker mode plus their local LLM API/model runtime.
- Inter-node URLs should be IP-style, for example `http://192.168.0.10:10007`.
  Loopback URLs are only for same-machine service calls.
- Master cluster APIs live under `/api/cluster/*` on the master LLM API.
- Messenger can delegate with `@node-name task`, `@tag:name task`,
  `@role:name task`, or `@all-slaves task`.

## Dependencies

- `llm-api` requires a running llama.cpp server, default `http://127.0.0.1:5905`.
- `hoonbot` requires LLM API credentials created by `hoonbot/scripts/setup_credentials.py`.
- `messenger` is master-only in v1; slaves do not run Messenger.
