# LLM API Fast

A FastAPI-based LLM API server providing OpenAI-compatible endpoints backed by **llama.cpp** with native tool calling. Ships with a companion **Hoonbot** messenger bot and a **Messenger** chat platform UI.

## Recent Changes

- Unified logging now writes LLM requests/responses, agent iterations, and direct tool execution summaries to `data/logs/prompts.log` with file locking and a `PROMPTS_LOG_MAX_LINES` cap.
- Startup now clears stale sessions, jobs, scratch workspaces, tool-result overflow, and rotates old logs automatically.
- Health endpoints now report llama.cpp availability, OpenCode status, disk usage, uptime, and active tool configuration at `GET /health` and `GET /api/health`.
- `python_coder` in OpenCode mode now keeps per-session OpenCode sessions, relocates stray generated scripts into the workspace, and attempts recovery execution when generation only partially succeeds.
- Added `use_cases/latency_benchmark.py` for quick end-to-end latency checks using `prompts.log` telemetry.
- Hoonbot now auto-probes candidate LLM API URLs, can resolve the home room by name, catches up on missed messages at startup, and subscribes to `message_edited` / `message_deleted` webhooks.

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

**Tests**: no automated test suite is currently configured in this repository.

### Architecture

**Single agent loop** (`backend/agent.py`) — the LLM decides when to call tools via structured JSON. No regex parsing, no HTTP hops between agent and tools.

```
User Input + file_metadata
    ↓
Build system prompt: system.txt + RAG collections + memo + attached file metadata
    ↓
While iteration < AGENT_MAX_ITERATIONS:
    LLM(system + tool_schemas + messages)
        ├── tool_calls → execute in PARALLEL (asyncio.gather)
        │             → microcompact oversized results + compress older iterations
        │             → loop
        └── text only → stream / return final response
```

**Prompt caching**: `_CACHED_SYSTEM_PROMPT` and `_CACHED_TOOL_SCHEMAS` are built once at module load for llama.cpp KV cache reuse. Call `reload_prompt_cache()` if schemas change at runtime.

**Attached file metadata**: CSV/Excel/JSON/code/text uploads get structured metadata injected into the prompt, such as headers, sample rows, top-level keys, imports, function/class definitions, and short previews.

**Microcompaction**: oversized tool results are saved under `data/tool_results/{session_id}/...` and replaced with compact summaries so long agent runs stay within the conversation budget.

### API Endpoints

| Route | Description |
|-------|-------------|
| `GET /` | Service metadata |
| `GET /health` | Health summary: llama.cpp, OpenCode, disk, uptime, config |
| `GET /api/health` | Same health payload under `/api/*` |
| `GET /docs`, `GET /redoc` | Interactive API docs |
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
| `POST /api/jobs` | Submit background agent run |
| `GET /api/jobs` | List current user's background jobs |
| `GET /api/jobs/{id}` | Job status + accumulated output |
| `GET /api/jobs/{id}/stream` | SSE stream of background job output |
| `DELETE /api/jobs/{id}` | Cancel a running job |

**`/v1/chat/completions` accepts form data** (not JSON) so files can be attached. Key parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `messages` | JSON string | Array of `{role, content}` objects |
| `session_id` | string | Optional; auto-creates session if absent |
| `stream` | bool | SSE streaming; tool status events included |
| `temperature` | float | Sampling temperature |
| files | multipart | Optional file attachments |

**Streaming payloads** (SSE, when `stream=true`):
- `{"object":"chat.completion.chunk", ...}` — OpenAI-style delta chunks for assistant text
- `{"object":"tool.status", ...}` — tool lifecycle visibility (`started`, `completed`, `failed`)
- The final `chat.completion.chunk` includes `finish_reason="stop"` and `x_session_id`, then the stream sends `[DONE]`

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
| `LLAMACPP_MODEL` | `"default"` | Model name sent to llama.cpp |
| `LLAMACPP_CACHE_PROMPT` | `True` | Reuse KV cache for stable prompt prefixes |
| `LLAMACPP_CONNECTION_POOL_SIZE` | `20` | Persistent HTTP connection pool size |
| `LLAMACPP_SLOTS` | `4` | Slot pinning for session KV cache reuse |
| `AGENT_MAX_ITERATIONS` | `60` | Max tool-calling loop iterations |
| `AGENT_TOOL_LOOP_MAX_TOKENS` | `4096` | Token cap for intermediary tool-selection turns |
| `PYTHON_EXECUTOR_MODE` | `"opencode"` | `"native"` or `"opencode"` |
| `OPENCODE_MODEL` | `"llama.cpp/MiniMax"` | Model used by OpenCode |
| `AGENT_LOG_VERBOSITY` | `"summary"` | `off`, `summary`, or `debug` |
| `PROMPTS_LOG_MAX_LINES` | `100000` | Hard cap for `data/logs/prompts.log` |
| `TAVILY_API_KEY` | *(set this)* | Required for web search |
| `DEFAULT_MIN_P` | `0.05` | min_p sampler |
| `DEFAULT_REPEAT_PENALTY` | `1.1` | Repetition penalty |
| `MAX_CONVERSATION_HISTORY` | `50` | Old messages dropped + tool results compressed |
| `SESSION_CLEANUP_DAYS` | `14` | Old session cleanup window |
| `SCRATCH_CLEANUP_DAYS` | `14` | Scratch workspace cleanup window |
| `TOOL_RESULTS_CLEANUP_DAYS` | `14` | Tool result retention window |
| `LOG_ROTATION_DAYS` | `14` | Rotate stale logs on startup |
| `JOBS_CLEANUP_DAYS` | `30` | Background job retention |
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

Fire-and-forget agent runs via `POST /api/jobs` — returns `202` with a `job_id` immediately. Job states: `pending → running → completed | failed | cancelled`. Use:

- `GET /api/jobs` to list your jobs
- `GET /api/jobs/{id}` to read status, output, and tool events
- `GET /api/jobs/{id}/stream` to stream output via SSE
- `DELETE /api/jobs/{id}` to cancel a pending or running job

### Health, Startup, and Retention

On startup the API server clears `data/STOP`, removes stale sessions, jobs, scratch directories, and tool-result overflow, rotates old logs, checks llama.cpp availability, and auto-starts the OpenCode server when `PYTHON_EXECUTOR_MODE == "opencode"`.

`GET /health` and `GET /api/health` expose uptime, llama.cpp reachability, OpenCode status, disk usage, `AGENT_MAX_ITERATIONS`, enabled tools, and the active Python executor mode.

### Logging & Observability

- `data/logs/prompts.log` is the canonical combined log for LLM requests/responses, agent iteration summaries, and direct tool execution logs.
- Log writes go through a file-locked append helper so multi-worker writes stay consistent.
- `PROMPTS_LOG_MAX_LINES` keeps the log bounded by dropping the oldest lines first.
- `use_cases/latency_benchmark.py` runs representative scenarios and estimates iteration counts, tool-call counts, and mean LLM turn latency from `prompts.log`.

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
python clear_data.py                  # Clear sessions, scratch, prompts.log (not uploads)
python clear_rag_data.py --all        # Clear all RAG data
python clear_rag_data.py --user admin # Clear RAG for specific user
python clear_rag_data.py --all --uploads # Also delete uploaded RAG source files
python use_cases/latency_benchmark.py # Run representative API latency scenarios
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
└── logs/prompts.log           # Combined LLM + agent + tool execution log
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

`setup.py` connects to LLM API at `http://localhost:10007`, logs in with default credentials, and saves `data/.llm_key` and `data/.llm_model`. No environment variables needed after that. At runtime, Hoonbot probes its candidate LLM API URLs and switches to the first healthy `/health` endpoint.

### Message Flow

```
User → Messenger (port 10006) → POST /webhook → Hoonbot (port 3939)
    → debounce → POST /v1/chat/completions → LLM API (port 10007)
    → agent loop with tools → SSE stream or JSON
    → Messenger REST API → User
```

Hoonbot never calls tools directly — the LLM API agent handles everything.

### Key Behavior

- **LLM API autodiscovery**: On startup, probes candidate LLM API URLs in priority order and uses the first healthy `/health` endpoint
- **Debounce**: Rapid messages within `HOONBOT_DEBOUNCE_SECONDS` (default 1.5s) are combined before sending to LLM
- **Room targeting**: In non-home rooms, Hoonbot only responds when mentioned; `HOONBOT_HOME_ROOM_NAME` can resolve the heartbeat room dynamically at startup
- **Catch-up**: On startup, scans recent room history and replies to the most recent unanswered human text message
- **Streaming**: When `HOONBOT_STREAMING=true`, tool status events show as temporary messages (auto-deleted after reply)
- **Sessions**: Per-room LLM sessions tracked in `data/room_sessions.json`; auto-expire after `SESSION_MAX_AGE_DAYS`; reset on 404
- **Heartbeat**: Background loop runs `HEARTBEAT.md` checklist through LLM agent every `HEARTBEAT_INTERVAL_SECONDS` and posts to home room
- **Memory**: `data/memory.md` is injected into every first-session prompt; LLM reads/writes it via file_reader/file_writer tools
- **Webhooks**: Subscribes to `new_message`, `message_edited`, and `message_deleted`

### Configuration

All settings in `settings.txt` at the repo root (parsed by `Hoonbot/config.py` — works on Windows without sourcing).

| Setting | Default | Purpose |
|---------|---------|---------|
| `HOONBOT_PORT` | 3939 | Bot server port |
| `HOONBOT_BOT_NAME` | Hoonbot | Display name in Messenger |
| `HOONBOT_HOME_ROOM_ID` | 1 | Numeric room that receives heartbeat output |
| `HOONBOT_HOME_ROOM_NAME` | `""` | Optional room name to resolve at startup |
| `HOONBOT_STREAMING` | true | Stream LLM responses |
| `HOONBOT_DEBOUNCE_SECONDS` | 1.5 | Message combination window |
| `HOONBOT_LLM_TIMEOUT` | 300 | LLM request timeout (seconds) |
| `HOONBOT_SESSION_MAX_AGE_DAYS` | 7 | Auto-expire room sessions |
| `HOONBOT_CATCHUP_LIMIT` | 20 | Messages scanned per room during startup catch-up |
| `HOONBOT_HEARTBEAT_INTERVAL` | 3600 | Seconds between heartbeat ticks |
| `HOONBOT_HEARTBEAT_LLM_COOLDOWN_SECONDS` | 600 | Minimum gap between heartbeat LLM calls |
| `HOONBOT_HEARTBEAT_ACTIVE_START/END` | 00:00/23:59 | Active hours window |
| `HOONBOT_STARTUP_RETRIES` | 6 | Retry attempts for startup HTTP operations |
| `HOONBOT_STARTUP_RETRY_DELAY` | 1.0 | Base delay for startup retries |
| `LLM_API_URL` | `""` | Optional explicit LLM API override |
| `USE_CLOUDFLARE` | false | Prefer Cloudflare URLs for Messenger + LLM API |
| `HOONBOT_WEBHOOK_SECRET` | `""` | Optional secret for incoming external webhooks |

Credentials stored at runtime:
- `data/.llm_key` — LLM API JWT token
- `data/.llm_model` — Model name
- `data/.apikey` — Messenger bot API key (created on first startup)

### Hoonbot File Structure

```
Bot/Hoonbot/
├── hoonbot.py              # Entry point: auto-detect LLM API, register bot, catch up, start heartbeat
├── config.py               # Reads settings.txt + env vars
├── setup.py                # One-time credential setup
├── PROMPT.md               # LLM system prompt (identity, memory, behavior)
├── HEARTBEAT.md            # Proactive task checklist (user-editable)
├── handlers/
│   ├── webhook.py          # All message processing: debounce, session, streaming
│   └── health.py           # Health check endpoint
├── core/
│   ├── context.py          # Shared prompt + memory + session-variable injection
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
        if not line or not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload == "[DONE]":
            break

        chunk = json.loads(payload)
        if chunk.get("object") == "tool.status":
            print(f"\n[tool:{chunk['tool_name']}] {chunk['status']}")
            continue

        delta = chunk["choices"][0]["delta"].get("content", "")
        if delta:
            print(delta, end="", flush=True)

# With file upload
with open("data.csv", "rb") as f:
    r = httpx.post(f"{BASE}/v1/chat/completions",
        data={"messages": json.dumps([{"role": "user", "content": "Analyze this"}])},
        files=[("files", ("data.csv", f, "text/csv"))],
        headers=headers, timeout=300.0)
```
