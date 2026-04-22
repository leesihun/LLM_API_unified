# CLAUDE.md — LLM API Fast

This document is for Claude Code. It describes the codebase architecture, key files, conventions, and important gotchas to be aware of when making changes.

---

## What This Is

A self-hosted, OpenAI-compatible LLM API server that wraps **llama.cpp** with a full agentic loop, JWT auth, RAG, and 10 built-in tools. Single-server model: one FastAPI process talks to one llama.cpp process (or a farm of them via `start-farm.sh`/`start-hub.sh`).

---

## Directory Layout

```
LLM_API_fast/
├── config.py               # ALL settings live here — edit this, not env vars
├── tools_config.py         # Tool schemas in OpenAI function-calling format
├── run_backend.py          # Entry point: launches uvicorn
├── run_frontend.py         # Simple HTTP server for frontend/static/
├── backend/
│   ├── agent.py            # ★ Core agentic loop (read this first)
│   ├── api/
│   │   ├── app.py          # FastAPI app, startup cleanup, route registration
│   │   └── routes/         # auth, chat, sessions, tools, jobs, models, admin, rag_upload_async
│   ├── core/
│   │   ├── llm_backend.py  # Async httpx client → llama.cpp; stream event types
│   │   ├── llm_interceptor.py  # Wraps backend; logs all LLM calls to prompts.log
│   │   ├── database.py     # SQLite: users, sessions, conversation_store
│   │   └── job_store.py    # Long-running background job lifecycle
│   ├── models/schemas.py   # Pydantic schemas for all request/response types
│   └── utils/
│       ├── auth.py         # JWT creation/verification, password hashing
│       ├── file_handler.py # Upload processing, image resize, metadata extraction
│       ├── prompts_log_append.py  # Append to prompts.log with line-cap rotation
│       ├── flush_logging.py       # Log banner printed once per process
│       ├── stop_signal.py         # data/STOP file → graceful inference halt
│       └── subprocess_stream.py   # Stream subprocess stdout for code_exec/python_coder
├── tools/
│   ├── web_search/tool.py  # Tavily API
│   ├── code_exec/tool.py   # Direct Python execution (subprocess, in-session sandbox)
│   ├── python_coder/       # Instruction → LLM generates code → execute
│   │   ├── base.py         # Abstract base
│   │   ├── native_tool.py  # Uses llm_backend directly
│   │   ├── opencode_tool.py   # Uses OpenCode CLI sidecar
│   │   ├── opencode_server.py # Manages the OpenCode sidecar process
│   │   └── opencode_config.py # Writes ~/.config/opencode/config.json
│   ├── rag/
│   │   ├── tool.py         # BaseRAGTool — FAISS index, embeddings, retrieve/upload
│   │   ├── enhanced_tool.py  # EnhancedRAGTool — wraps BaseRAGTool + extra features
│   │   ├── hybrid_retrieval.py  # BM25 + dense, optional cross-encoder reranking
│   │   ├── advanced_chunking.py # Semantic chunking with sentence-transformers
│   │   ├── optimized_uploader.py   # Parallel ProcessPoolExecutor uploader
│   │   └── memory_efficient_uploader.py  # Single-worker uploader for low-VRAM
│   ├── file_ops/           # reader.py, writer.py, navigator.py
│   ├── shell/tool.py       # asyncio subprocess shell execution
│   ├── memo/tool.py        # Persistent JSON key-value memory per user
│   └── process_monitor/tool.py  # Start/status/kill background processes
├── prompts/
│   └── system.txt          # System prompt loaded at startup (cached module-level)
├── data/                   # Runtime data (gitignored)
│   ├── app.db              # SQLite database
│   ├── logs/prompts.log    # Combined LLM + agent + tool call log
│   ├── sessions/           # Per-session conversation JSONL files
│   ├── uploads/            # User-uploaded files
│   ├── scratch/            # Code execution working dirs (per session)
│   ├── rag_documents/      # Uploaded RAG source files (per user/collection)
│   ├── rag_indices/        # FAISS index files
│   ├── rag_metadata/       # Collection metadata JSON
│   ├── tool_results/       # Oversize tool result overflow (per session)
│   ├── memory/             # Memo tool storage (per user JSON)
│   └── jobs/               # Background job state JSON files
├── proxy_agent/            # Optional HTTP proxy → upstream LLM API
├── docs/                   # API docs, feature guides, RAG guides
├── start-farm.sh           # GPU farm node launcher
├── start-hub.sh            # Central hub launcher (llama.cpp + Messenger)
├── install-llamacpp.sh     # Offline installer for airgapped Linux
└── gather-llamacpp.sh      # Bundle creator (run on internet machine first)
```

---

## Key Architectural Decisions

### Agent Loop (`backend/agent.py`)

- **Single `while` loop** — no sub-agents, no chains. The loop runs until LLM returns plain text or `AGENT_MAX_ITERATIONS` is hit.
- **Parallel tool execution** — `asyncio.gather` runs all tool calls in one iteration concurrently. Tools start executing mid-stream as soon as their arguments arrive (before the full LLM response is received).
- **Prompt caching** — system prompt is loaded once at module import and never changes. `cache_prompt=True` tells llama.cpp to reuse KV cache for the shared prefix. Dynamic context (RAG collections, memo, attached files) goes in a separate `system` message so the static prefix stays byte-identical.
- **Microcompaction** — old iteration tool results and assistant messages are compressed to short summaries. Oversize results are saved to `data/tool_results/{session_id}/` and replaced with truncated versions in-context.
- **Session slot pinning** — `id_slot = hash(session_id) % LLAMACPP_SLOTS` pins each session to a stable llama.cpp KV slot for consistent cache hits.

### LLM Backend (`backend/core/llm_backend.py`)

- Always streams — there is no non-streaming code path.
- Emits three event types: `TextEvent`, `ToolCallDeltaEvent`, `ToolStatusEvent`.
- `ToolCallDeltaEvent(is_partial=True)` fires as soon as one tool call's args are complete mid-stream, so the agent can start executing it immediately.
- Wrapped by `LLMInterceptor` which logs every call to `prompts.log`.

### RAG (`tools/rag/`)

- **Singleton embedding model** — `get_global_embedding_model()` in `tool.py` loads SentenceTransformer once per worker process. Never create a second instance anywhere else (doubles VRAM).
- **Hybrid search** — BM25 (sparse) + FAISS cosine (dense), then optional CrossEncoder reranking. Controlled by `RAG_USE_HYBRID_SEARCH` and `RAG_USE_RERANKING` in `config.py`.
- **`RAGTool` in `__init__.py`** resolves to `EnhancedRAGTool` when available; falls back to `BaseRAGTool`.

### Configuration (`config.py`)

Everything is in one file. There are no `.env` files (only `JWT_SECRET_KEY` is read from environment). To change a setting, edit `config.py` directly. Key settings to know:
- `LLAMACPP_HOST` — URL of the llama.cpp server
- `AVAILABLE_TOOLS` — list controls which tools are loaded and exposed to the LLM
- `PYTHON_EXECUTOR_MODE` — `"native"` (uses `llm_backend`) or `"opencode"` (uses OpenCode CLI sidecar)
- `RAG_EMBEDDING_MODEL` — path to a local SentenceTransformer model directory
- `AGENT_LOG_VERBOSITY` — `"off"` | `"summary"` | `"debug"`
- `TAVILY_API_KEY` — required for websearch tool

---

## Running the Server

```bash
# Install dependencies
pip install -r requirements.txt

# Start llama.cpp separately (example)
llama-server --model /path/to/model.gguf --port 5905 --parallel 4

# Start the API
python run_backend.py
# → listens on http://0.0.0.0:10007
```

Default admin credentials: `admin` / `administrator` (change in `config.py`).

---

## Common Development Commands

```bash
# Clear dev data (logs, scratch, sessions)
python clear_data.py

# Clear RAG indices (needed when switching embedding models)
python clear_rag_data.py --all

# Create users via API (server must be running)
python create_users.py

# Create users directly in the DB (no server needed)
python create_user_direct.py

# Halt inference without killing the server
python stop_inference.py stop    # creates data/STOP
python stop_inference.py clear   # removes data/STOP
python stop_inference.py status
```

---

## Adding a New Tool

1. Create `tools/my_tool/tool.py` with a class that has an `execute()` method returning `{"success": bool, ...}`.
2. Add `__init__.py` that exports the class.
3. Add the schema to `tools_config.py` → `TOOL_SCHEMAS` dict.
4. Add the tool name to `AVAILABLE_TOOLS` in `config.py`.
5. Add a dispatch branch in `backend/agent.py` → `_dispatch_tool()`.
6. Optionally add tool parameters to `TOOL_PARAMETERS` and `TOOL_RESULT_BUDGET` in `config.py`.

---

## Important Gotchas

- **`config.py` runs directory creation at import time** — importing config always creates `data/` subdirs. Safe, but be aware on fresh checkouts.
- **`prompts.log` is one file for everything** — LLM calls, agent iterations, and tool results all go there. It's capped at `PROMPTS_LOG_MAX_LINES` lines; older lines are dropped.
- **RAG indices are embedding-model-specific** — switching `RAG_EMBEDDING_MODEL` (e.g., bge-base-en 768-dim → bge-m3 1024-dim) requires `python clear_rag_data.py --all` or FAISS will throw dimension mismatch errors.
- **`PYTHON_EXECUTOR_MODE="opencode"` requires the OpenCode CLI** (`opencode` binary on PATH). If it's missing, the server starts but `python_coder` tool calls will fail.
- **Workers > 1 means multiple processes share no state** — session pinning (`id_slot`) and the RAG embedding singleton are per-process. Use `workers=1` for development; for production, llama.cpp's own parallel slots handle concurrency.
- **`data/STOP` file halts inference** — `check_stop()` raises `StopIteration` inside the agent loop. This is for graceful user-initiated pauses, not server restarts.
- **JWT secret key** — `config.py` has a hardcoded dev default. Set `JWT_SECRET_KEY` environment variable in production.
- **SSL cert** — if `C:/DigitalCity.crt` exists, it's used for HTTPS to llama.cpp. This is a Samsung internal cert; remove the check in `llm_backend.py:_resolve_ssl()` if not needed.

---

## API Quick Reference

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/` | GET | No | Status |
| `/health` | GET | No | Health + llama.cpp availability |
| `/api/auth/login` | POST | No | Returns JWT |
| `/api/auth/signup` | POST | No | Create account |
| `/v1/models` | GET | Optional | List available models |
| `/v1/chat/completions` | POST | Optional | OpenAI-compatible chat (stream or sync) |
| `/api/chat/sessions` | GET | Yes | List user sessions |
| `/api/chat/history/{session_id}` | GET | Yes | Session message history |
| `/api/tools/rag/collections` | GET | Yes | List RAG collections |
| `/api/rag/upload/stream` | POST | Yes | Upload docs to RAG (SSE progress) |
| `/api/jobs` | POST | Yes | Submit background job |
| `/api/jobs/{job_id}` | GET | Yes | Job status |
| `/api/admin/stop` | POST | Admin | Halt inference |

Full docs at `/docs` (Swagger UI) when server is running.
