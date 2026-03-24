# LLM API Fast

A FastAPI-based LLM API server providing OpenAI-compatible endpoints backed by **llama.cpp** with native tool calling. Ships with a companion **Hoonbot** messenger bot and a **Messenger** chat platform UI.

## System Overview

```
┌──────────────────────────────┐      POST /v1/chat/completions
│  Messenger (TypeScript)      │ ◄──────────────────────────────────────────┐
│  Chat UI  •  port 10006      │                                            │
└──────────┬───────────────────┘                                            │
           │ POST /webhook                                                   │
           ▼                                                                 │
┌──────────────────────────────┐      Messenger REST API                    │
│  Hoonbot (Python/FastAPI)    │ ──────────────────────────────►            │
│  Bot server  •  port 3939    │                                            │
└──────────────────────────────┘                                            │
                                                                            │
┌──────────────────────────────────────────────────────────────────────┐   │
│  LLM API Fast (Python/FastAPI)  •  port 10007                        │◄──┘
│                                                                      │
│  Agent Loop ─► llama.cpp (port 5905)                                 │
│                                                                      │
│  In-process tools: websearch · python_coder · rag · file_reader      │
│                    file_writer · file_navigator · shell_exec         │
│                    process_monitor · memo                            │
└──────────────────────────────────────────────────────────────────────┘
```

Three independent components — start only what you need:

| Component | Port | Language | Purpose |
|-----------|------|----------|---------|
| **LLM API Fast** | 10007 | Python | Core LLM server with tool calling |
| **Messenger** | 10006 | TypeScript/Node | Chat platform (UI + WebSocket server) |
| **Hoonbot** | 3939 | Python | AI bot that bridges Messenger ↔ LLM API |

---

## LLM API Fast

### Quick Start

```bash
pip install -r requirements.txt
python run_backend.py        # Start API server (port 10007)
python run_frontend.py       # Start static frontend (port 3000, opens browser)
```

**Prerequisites**: llama.cpp server running on port 5905 with `--jinja` flag (required for native tool calling).

### Architecture

**Single agent loop** (`backend/agent.py`) — the LLM decides when to call tools via structured JSON. No regex parsing, no HTTP hops between agent and tools.

```
User Input
    ↓
Build system prompt: system.txt + RAG collections + memo + attached file metadata
    ↓
While iteration < AGENT_MAX_ITERATIONS:
    LLM(system + tool_schemas + messages)
        ├── tool_calls → execute in PARALLEL (asyncio.gather) → loop
        └── text only  → stream / return final response
```

**Prompt caching**: `_CACHED_SYSTEM_PROMPT` and `_CACHED_TOOL_SCHEMAS` are built once at module load for llama.cpp KV cache reuse. Call `reload_prompt_cache()` if schemas change at runtime.

### API Endpoints

| Route | Description |
|-------|-------------|
| `POST /v1/chat/completions` | OpenAI-compatible chat (multipart form, supports file uploads) |
| `GET /v1/models` | Available models |
| `POST /api/auth/signup` | Create account |
| `POST /api/auth/login` | Login → JWT |
| `GET /api/chat/sessions` | List sessions (supports `?q=` search) |
| `PATCH /api/chat/sessions/{id}` | Rename session |
| `GET /api/chat/history/{id}` | Conversation history |
| `GET/POST/DELETE /api/admin/stop-inference` | Stop signal management |
| `POST /api/admin/model` | Change default model (admin only) |
| `GET /api/tools/*` | Direct tool access + RAG collection management |
| `POST /api/jobs` | Fire-and-forget background agent run |
| `GET /api/jobs/{id}/stream` | SSE stream of background job output |

**`/v1/chat/completions` accepts form data** (not JSON) so files can be attached. Key parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `messages` | JSON string | Array of `{role, content}` objects |
| `session_id` | string | Optional; auto-creates session if absent |
| `stream` | bool | SSE streaming; tool status events included |
| `temperature` | float | Sampling temperature |
| files | multipart | Optional file attachments |

**Streaming events** (SSE, when `stream=true`):
- `text` — partial text token
- `tool_status.started` / `tool_status.completed` — tool execution lifecycle
- `tool_call_delta` — accumulated after stream ends

### Tools

All tools run **in-process** — zero HTTP hops:

| Tool | Description |
|------|-------------|
| `websearch` | Web search via Tavily API |
| `python_coder` | Code generation + execution (native subprocess or OpenCode remote) |
| `rag` | FAISS document retrieval with optional hybrid BM25, reranking, multi-query |
| `file_reader` | Read files from scratch workspace, uploads, or CWD (50 KB cap) |
| `file_writer` | Write files (resolves relative paths from CWD) |
| `file_navigator` | List/search/stat files |
| `shell_exec` | Run shell commands (50 KB output cap) |
| `process_monitor` | Start/monitor/kill long-running processes by handle |
| `memo` | Per-user persistent key-value memory across sessions |

### Configuration (`config.py`)

Key settings:

| Setting | Default | Notes |
|---------|---------|-------|
| `LLAMACPP_HOST` | `http://localhost:5905` | llama.cpp server URL |
| `AGENT_MAX_ITERATIONS` | `200` | Max tool-calling loop iterations |
| `PYTHON_EXECUTOR_MODE` | `"opencode"` | `"native"` or `"opencode"` |
| `TAVILY_API_KEY` | *(set this)* | Required for web search |
| `DEFAULT_MIN_P` | `0.05` | min_p sampler |
| `DEFAULT_REPEAT_PENALTY` | `1.1` | Repetition penalty |
| `MAX_CONVERSATION_HISTORY` | `50` | Old messages dropped + tool results compressed |
| `RAG_USE_HYBRID_SEARCH` | `True` | BM25 + FAISS hybrid search |
| `RAG_USE_RERANKING` | `True` | Cross-encoder reranking |
| `RAG_CHUNKING_STRATEGY` | `"semantic"` | Chunking strategy |
| `MEMO_DIR` | `data/memory` | Per-user persistent memo storage |

**Per-tool overrides** via `TOOL_PARAMETERS` (temperature, max_tokens, timeout per tool) and `TOOL_RESULT_BUDGET` (char limits for microcompaction).

### RAG Pipeline

Per-user FAISS indices at `data/rag_indices/{username}/`. Auto-selects `EnhancedRAGTool` when hybrid search, reranking, or semantic chunking are enabled (all on by default).

Supported upload formats: `.txt`, `.pdf`, `.docx`, `.xlsx`, `.xls`, `.md`, `.json`, `.csv`

RAG configuration:

| Setting | Default | Description |
|---------|---------|-------------|
| `RAG_EMBEDDING_MODEL` | — | Path/name of embedding model (e.g. `BAAI/bge-m3`) |
| `RAG_EMBEDDING_DEVICE` | `"cuda"` | `"cuda"` or `"cpu"` |
| `RAG_CHUNK_SIZE` | `512` | Characters per chunk |
| `RAG_INDEX_TYPE` | `"Flat"` | FAISS index type: `"Flat"`, `"IVF"`, `"HNSW"` |
| `RAG_MIN_SCORE_THRESHOLD` | `0.5` | Minimum similarity score (0–1) |
| `RAG_MULTI_QUERY_COUNT` | `6` | Query variants for recall expansion |

### Background Jobs

Fire-and-forget agent runs via `POST /api/jobs` — returns `202` with a `job_id` immediately. Job states: `pending → running → completed | failed | cancelled`. Poll `GET /api/jobs/{id}` or stream output via SSE at `/api/jobs/{id}/stream`.

### Recommended llama.cpp Launch Flags

```bash
llama-server \
  --model MODEL.gguf \
  --flash-attn auto \
  --cache-type-k q8_0 \
  --cache-type-v q8_0 \
  --cont-batching \
  --parallel 4 \              # Must match config.LLAMACPP_SLOTS (default 4)
  --ctx-size 8192 \
  --jinja \                   # REQUIRED for native tool calling
  --threads $(nproc) \
  --slot-prompt-similarity 0.5
```

Speculative decoding (1.3–3× speedup with a draft model):
```bash
  --model-draft SMALL_MODEL.gguf \
  --draft-max 8 --draft-min 4 --draft-p-min 0.9
```

### Utility Scripts

```bash
python stop_inference.py              # Create data/STOP → halts all agent loops
python stop_inference.py clear        # Remove data/STOP → resume
python stop_inference.py status       # Show current stop status
python create_user_direct.py          # Create user directly in DB (no server needed)
python create_users.py                # Batch create users via API (server must be running)
python clear_data.py                  # Clear sessions, scratch, prompts.log
python clear_rag_data.py --all        # Clear all RAG data
python clear_rag_data.py --user admin # Clear RAG for specific user
```

### Adding New Tools

1. Create `tools/{name}/tool.py` — return `{"success": bool, ...}`
2. Add schema to `TOOL_SCHEMAS` in `tools_config.py`
3. Add dispatch case in `_dispatch_tool()` in `backend/agent.py`
4. Add to `config.AVAILABLE_TOOLS`
5. Add char budget to `config.TOOL_RESULT_BUDGET`
6. Add per-tool params to `config.TOOL_PARAMETERS`
7. Call `reload_prompt_cache()` if the agent is already running

### Storage Layout

```
data/                          # Entire directory is gitignored
├── app.db                     # SQLite (users, sessions metadata)
├── sessions/{id}.json         # Conversation history (FileLock)
├── uploads/{username}/        # Persistent user uploads
├── scratch/{session_id}/      # Per-session workspace
├── rag_documents/{username}/  # Uploaded RAG source files
├── rag_indices/{username}/    # FAISS indices
├── rag_metadata/{username}/   # RAG chunk metadata
├── memory/{username}.json     # Memo key-value store
├── jobs/{job_id}.json         # Background job state + output (FileLock)
├── tool_results/{session_id}/ # Microcompacted tool output overflow
└── logs/prompts.log           # All LLM interactions + tool executions
```

### Default Credentials

| Username | Password | Role |
|----------|----------|------|
| `admin` | `administrator` | admin |

### Known Gotchas

1. **`--jinja` required** — native tool calling won't work without it
2. **bcrypt 72-byte limit** — `hash_password()` raises `ValueError` if password exceeds 72 bytes (not chars)
3. **file_reader offset is 1-based** — schema says 0-indexed but code treats offset as 1-based
4. **file_writer resolves from CWD** — unlike file_reader (checks scratch first), file_writer resolves relative paths from `os.getcwd()`
5. **process_monitor handles, not PIDs** — `start` returns a handle string (e.g. `proc_1`); handles are in-memory only, lost on server restart
6. **Memo NOT prompt-cached** — `MemoTool.load_for_prompt()` called fresh each request so writes take effect immediately
7. **`rag_upload_async.py` is dead code** — router exists but not registered in `app.py`
8. **`--parallel` must match `LLAMACPP_SLOTS`** — default 4; mismatch breaks session pinning for KV cache reuse

---

## Hoonbot

Personal AI bot that bridges **Messenger** (chat UI) with **LLM API Fast** (agent backend).

### Quick Start

```bash
cd Bot/Hoonbot
pip install -r requirements.txt
python setup.py           # One-time: authenticates with LLM API, saves credentials
python hoonbot.py         # Start bot on port 3939
```

Or use the repo-level scripts:
```bash
./start-all.sh            # Linux: start all services (reads settings.txt)
start-all.bat             # Windows: start Messenger + Cloudflare only
```

`setup.py` connects to LLM API at `http://localhost:10007`, logs in with default credentials, and saves `data/.llm_key` and `data/.llm_model`. No environment variables needed after that.

### Message Flow

```
User → Messenger (port 10006) → POST /webhook → Hoonbot (port 3939)
    → debounce → POST /v1/chat/completions → LLM API (port 10007)
    → agent loop with tools → SSE stream or JSON
    → Messenger REST API → User
```

Hoonbot never calls tools directly — the LLM API agent handles everything.

### Key Behavior

- **Debounce**: Rapid messages within `HOONBOT_DEBOUNCE_SECONDS` (default 1.5s) are combined before sending to LLM
- **Streaming**: When `HOONBOT_STREAMING=true`, tool status events show as temporary messages (auto-deleted after reply)
- **Sessions**: Per-room LLM sessions tracked in `data/room_sessions.json`; auto-expire after `SESSION_MAX_AGE_DAYS`; reset on 404
- **Heartbeat**: Background loop runs `HEARTBEAT.md` checklist through LLM agent every `HEARTBEAT_INTERVAL_SECONDS` and posts to home room
- **Memory**: `data/memory.md` is injected into every first-session prompt; LLM reads/writes it via file_reader/file_writer tools

### Configuration

All settings in `settings.txt` at the repo root (parsed by `Hoonbot/config.py` — works on Windows without sourcing).

| Setting | Default | Purpose |
|---------|---------|---------|
| `HOONBOT_PORT` | 3939 | Bot server port |
| `HOONBOT_BOT_NAME` | Bot | Display name in Messenger |
| `HOONBOT_HOME_ROOM_ID` | 1 | Room that receives heartbeat output |
| `HOONBOT_STREAMING` | true | Stream LLM responses |
| `HOONBOT_DEBOUNCE_SECONDS` | 1.5 | Message combination window |
| `HOONBOT_LLM_TIMEOUT` | 300 | LLM request timeout (seconds) |
| `HOONBOT_SESSION_MAX_AGE_DAYS` | 7 | Auto-expire room sessions |
| `HOONBOT_HEARTBEAT_INTERVAL` | 3600 | Seconds between heartbeat ticks |
| `HOONBOT_HEARTBEAT_ACTIVE_START/END` | 00:00/23:59 | Active hours window |

Credentials stored at runtime:
- `data/.llm_key` — LLM API JWT token
- `data/.llm_model` — Model name
- `data/.apikey` — Messenger bot API key (created on first startup)

### Hoonbot File Structure

```
Bot/Hoonbot/
├── hoonbot.py              # Entry point: register bot, subscribe webhooks, start heartbeat
├── config.py               # Reads settings.txt + env vars
├── setup.py                # One-time credential setup
├── PROMPT.md               # LLM system prompt (identity, memory, behavior)
├── HEARTBEAT.md            # Proactive task checklist (user-editable)
├── handlers/
│   ├── webhook.py          # All message processing: debounce, session, streaming
│   └── health.py           # Health check endpoint
├── core/
│   ├── messenger.py        # Messenger REST API client (async httpx, connection pool)
│   ├── heartbeat.py        # Background heartbeat loop
│   └── retry.py            # Exponential backoff decorator
├── skills/                 # Markdown skill definitions for complex operations
│   ├── send_attachments.md
│   ├── download_attachment.md
│   ├── search_messages.md
│   └── ...
└── data/
    ├── memory.md           # Persistent LLM memory (Markdown, auto-injected)
    ├── room_sessions.json  # Room → session_id + created_at
    ├── .llm_key            # LLM API token
    ├── .llm_model          # Model name
    └── .apikey             # Messenger bot API key
```

### Messenger API Coverage

`core/messenger.py` wraps the Messenger REST API (all calls authenticated with `x-api-key` header):

- **Messages**: send, send-returning-id, edit, delete, mark-read, search, split long messages automatically
- **Typing**: start/stop indicators
- **Files**: send-file (multipart), send-base64 (data URL)
- **Rooms**: create, get, get-messages, resolve by name
- **Bot**: register, get-info, register-webhook
- **Pins**: pin, unpin, get
- **Web watchers**: create, list, delete — polls URLs, posts to room on content change

### Skills

Skill definitions in `Bot/Hoonbot/skills/` are Markdown files with step-by-step procedures for multi-step operations. The LLM uses these as reference when executing complex tasks (e.g. `send_attachments.md` describes the exact multipart upload procedure, auth flow, and room resolution logic).

### External Webhooks

External services can trigger Hoonbot:
```http
POST http://localhost:3939/webhook/incoming/<source>
X-Webhook-Secret: optional_secret
Content-Type: application/json

{"message": "Something happened"}
```

### Utilities

```bash
python reset.py --memory         # Clear memory.md
python reset.py --list-memory    # View current memory
python reset.py --all            # Reset everything
python test_llm.py               # Verify LLM API connectivity and credentials
```

---

## Messenger

TypeScript/Node.js real-time chat platform serving as the UI for Hoonbot interactions.

```bash
cd Bot/Messenger
npm install
npm run dev:server    # Server only (hot-reload)
npm run dev           # Server + Vite client
npm run typecheck     # Type-check without emit
npm run build:web     # Web-only build
npm run build         # Electron build (Windows)
```

- Default port: **10006**
- In-memory SQLite (`sql.js`) — auto-saved to disk every 5 seconds
- WebSocket for real-time message delivery
- REST API documented in `Messenger/docs/API.md`
- Canonical TypeScript types in `Messenger/shared/types.ts`

> **Note**: Unclean shutdown can lose up to 5 seconds of messages (in-memory DB).

---

## Python Client Example

```python
import httpx, json

BASE = "http://localhost:10007"

# Login
token = httpx.post(f"{BASE}/api/auth/login",
    json={"username": "admin", "password": "administrator"}).json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# Chat (non-streaming)
r = httpx.post(f"{BASE}/v1/chat/completions", data={
    "messages": json.dumps([{"role": "user", "content": "What is 2+2?"}]),
}, headers=headers, timeout=300.0)
print(r.json()["choices"][0]["message"]["content"])
session_id = r.json()["x_session_id"]

# Continue conversation
r = httpx.post(f"{BASE}/v1/chat/completions", data={
    "messages": json.dumps([{"role": "user", "content": "Multiply that by 10"}]),
    "session_id": session_id,
}, headers=headers, timeout=300.0)

# Streaming
with httpx.stream("POST", f"{BASE}/v1/chat/completions", data={
    "messages": json.dumps([{"role": "user", "content": "Write a haiku"}]),
    "stream": "true",
}, headers=headers, timeout=300.0) as resp:
    for line in resp.iter_lines():
        if line.startswith("data: ") and line != "data: [DONE]":
            chunk = json.loads(line[6:])
            print(chunk["choices"][0]["delta"].get("content", ""), end="", flush=True)

# With file upload
with open("data.csv", "rb") as f:
    r = httpx.post(f"{BASE}/v1/chat/completions",
        data={"messages": json.dumps([{"role": "user", "content": "Analyze this"}])},
        files=[("files", ("data.csv", f, "text/csv"))],
        headers=headers, timeout=300.0)
```
