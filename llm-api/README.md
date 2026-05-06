# LLM API

A self-hosted, OpenAI-compatible LLM API server that wraps **llama.cpp** with a full agentic loop, JWT auth, RAG, and 10 built-in tools.

## Quick Start

```bash
# 1. Install dependencies
./install.sh

# 2. Edit config (point at your llama.cpp server and model)
nano config.py

# 3. Start llama.cpp separately (example — adjust model path)
llama-server --model /path/to/model.gguf --port 5905 --parallel 4
# Optional backup llama.cpp: use --port 10000

# 4. Start the API
./start.sh
# → http://localhost:10007
# → Swagger UI: http://localhost:10007/docs
```

## Configuration

**All settings live in `config.py`** — edit it directly. Key values:

| Setting | Default | Purpose |
|---|---|---|
| `SERVER_PORT` | `10007` | API listen port |
| `LLAMACPP_HOST` | `http://localhost:5905` | llama.cpp server URL |
| `LLAMACPP_BACKUP_HOST` | `http://localhost:10000` | fallback llama.cpp server URL |
| `AVAILABLE_TOOLS` | (list) | Tools exposed to the LLM |
| `AGENT_MAX_ITERATIONS` | `30` | Max tool-call iterations per request |
| `JWT_SECRET_KEY` | env or hardcoded | Set via `JWT_SECRET_KEY` env var in prod |
| `RAG_EMBEDDING_MODEL` | (path) | Path to SentenceTransformer model dir |
| `AGENT_LOG_VERBOSITY` | `"summary"` | `"off"` / `"summary"` / `"debug"` |

## Directory Layout

```
llm-api/
├── config.py          All settings — edit this, not env vars
├── run_backend.py     Entry point (uvicorn)
├── install.sh         Installer
├── start.sh           Start script
├── deps/
│   └── requirements.txt
├── backend/
│   ├── agent/         Agentic loop (tool dispatch, compaction, streaming)
│   ├── api/           FastAPI app + routes (auth, chat, sessions, jobs, RAG)
│   ├── core/          llm_backend (httpx→llama.cpp), database (SQLite), job store
│   ├── models/        Pydantic schemas
│   └── utils/         Auth (JWT), file handler, logging helpers
├── tools/             10 built-in tools (websearch, RAG, code_exec, shell, ...)
├── prompts/           system.txt + per-tool prompt fragments
├── scripts/           Dev helpers (clear_data.py, create_users.py, etc.)
├── docs/              API docs, RAG guides, feature notes
└── data/              Runtime data (SQLite, uploads, sessions, logs) — gitignored
```

## API (OpenAI-Compatible)

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/` | GET | No | Status |
| `/health` | GET | No | Server + llama.cpp health |
| `/api/auth/login` | POST | No | Returns JWT |
| `/api/auth/signup` | POST | No | Create account |
| `/v1/models` | GET | Optional | List models |
| `/v1/chat/completions` | POST | Optional | Chat + streaming (OpenAI-compatible) |
| `/api/chat/sessions` | GET | Yes | List sessions |
| `/api/tools/rag/collections` | GET | Yes | List RAG collections |
| `/api/rag/upload/stream` | POST | Yes | Upload docs (SSE progress) |
| `/api/jobs` | POST | Yes | Submit background job |
| `/docs` | GET | No | Swagger UI |

Default admin credentials: `admin` / `administrator` (change in `config.py`).

## Dev Commands

```bash
# Clear logs, scratch, sessions
python3 scripts/clear_data.py

# Clear RAG indices (required when switching embedding models)
python3 scripts/clear_rag_data.py --all

# Create users (server must be running)
python3 scripts/create_users.py

# Create users directly in DB (no server needed)
python3 scripts/create_user_direct.py

# Halt inference without killing the server
python3 scripts/stop_inference.py stop    # creates data/STOP
python3 scripts/stop_inference.py clear   # removes data/STOP
```

## Architecture Notes

- **Single `while` loop** in `backend/agent/` — no sub-agents, no chains.
- **Parallel tool execution** — `asyncio.gather` runs all tool calls concurrently.
- **Prompt caching** — system prompt cached at module import; `cache_prompt=True` sent to llama.cpp.
- **Microcompaction** — old iterations are compressed; oversize results spill to `data/tool_results/`.
- **Session slot pinning** — `id_slot = hash(session_id) % LLAMACPP_SLOTS` for stable KV cache hits.
- **Workers > 1** — multiple processes share no state; use `workers=1` for development.
