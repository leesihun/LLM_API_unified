# Huni — Self-Hosted AI Stack

Three independent, self-contained services. Each has its own config, installer, and start script.

## Services

| Folder | Port | Description |
|---|---|---|
| [`llm-api/`](llm-api/) | 10007 | OpenAI-compatible LLM API wrapping llama.cpp — full agentic loop, JWT auth, RAG, 10 tools |
| [`hoonbot/`](hoonbot/) | 3939 | Python bot bridging Messenger ↔ LLM API with tool access and persistent memory |
| [`messenger/`](messenger/) | 10006 | Node.js real-time team chat (React UI, Socket.IO, file sharing, Claude/OpenCode terminals) |

## Quick Start

```bash
# 1. LLM API (start llama.cpp first — see llm-api/README.md)
cd llm-api && ./install.sh && ./start.sh

# 2. Messenger
cd messenger && ./install.sh && ./start.sh

# 3. Hoonbot (Messenger + LLM API must be running)
cd hoonbot && ./install.sh && ./start.sh
```

## Dependencies

- `llm-api` requires a running **llama.cpp** server (`llama-server --model ... --port 5905`)
- `hoonbot` requires `llm-api` (10007) and `messenger` (10006) to be reachable
- `messenger` is fully standalone

Each folder contains a `README.md` with full configuration details.
