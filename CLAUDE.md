# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an **LLM API server** providing OpenAI-compatible endpoints backed by **llama.cpp** with native tool calling. A single agent loop orchestrates everything — the LLM decides when to call tools via structured JSON, never regex.

**Core invariants**:
- **One server** on port 10007 (chat, auth, sessions, tools, RAG management)
- **One agent loop** (`backend/agent.py`) — replaced the old 5-agent hierarchy
- **Native tool calling** via llama.cpp's `tools` parameter (requires `--jinja` flag on llama.cpp)
- **In-process tool execution** — zero HTTP hops between agent and tools

## Development Commands

```bash
python run_backend.py        # Start API server (port 10007, uvicorn)
python run_frontend.py       # Start static frontend (port 3000, opens browser)
python stop_inference.py     # Create data/STOP → halts all running agent loops
python stop_inference.py clear   # Remove data/STOP → resume inference
python stop_inference.py status  # Show current stop signal status
```

**Dependencies**: `pip install -r requirements.txt`

**Utility scripts**:
```bash
python create_user_direct.py                # Interactive: create a single user directly in DB (no server needed)
python create_users.py                      # Batch create users via API (requires server running)
python clear_data.py                        # Clear sessions, scratch, and prompts.log (NOT uploads)
python clear_rag_data.py --all              # Clear RAG indices, documents, metadata (all users)
python clear_rag_data.py --user admin       # Clear RAG data for specific user
python clear_rag_data.py --all --uploads    # Also delete uploaded source files (destructive!)
```

**No test suite** — there are no automated tests or test frameworks configured.

## Configuration (`config.py`)

All settings live in `config.py`. Key settings to know:

| Setting | Default | Notes |
|---------|---------|-------|
| `LLAMACPP_HOST` | `http://localhost:5905` | llama.cpp server URL |
| `LLAMACPP_MODEL` | `"default"` | Model name sent in requests |
| `AGENT_MAX_ITERATIONS` | `50` | Max tool-calling loop iterations |
| `AGENT_SYSTEM_PROMPT` | `"system.txt"` | Prompt file in `prompts/` |
| `PYTHON_EXECUTOR_MODE` | `"opencode"` | `"native"` or `"opencode"` |
| `OPENCODE_MODEL` | `"llama.cpp/MiniMax"` | `"provider/model"` format |
| `TAVILY_API_KEY` | *(set this)* | Required for web search |
| `MAX_CONVERSATION_HISTORY` | `50` | Defined but NOT enforced in code — conversations grow unbounded |
| `SESSION_CLEANUP_DAYS` | `7` | Sessions auto-deleted after N days |
| `MEMO_DIR` | `data/memory` | Per-user persistent memo storage |
| `MEMO_MAX_ENTRIES` | `100` | Max memo entries per user |
| `MEMO_MAX_VALUE_LENGTH` | `1000` | Max chars per memo value |
| `JOBS_DIR` | `data/jobs` | Background job JSON files |
| `JOBS_CLEANUP_DAYS` | `30` | Job files deleted after N days |

**Per-tool overrides** via `TOOL_PARAMETERS` dict (temperature, max_tokens, timeout per tool) and `TOOL_RESULT_BUDGET` dict (char limits for microcompaction).

**RAG configuration** (`RAG_*` settings): embedding model path, chunking strategy (`"semantic"` by default), hybrid search (`RAG_USE_HYBRID_SEARCH=True`), reranking (`RAG_USE_RERANKING=True`), multi-query expansion (`RAG_USE_MULTI_QUERY=True`). These are all enabled by default — see config.py for model paths (`RAG_EMBEDDING_MODEL`, `RAG_RERANKER_MODEL`).

## Architecture

### Agent Loop (`backend/agent.py`)

```
User Input + file_metadata
    ↓
Build system prompt: base system.txt + RAG collections + memo + attached file metadata
    ↓
While iteration < AGENT_MAX_ITERATIONS:
    LLM(system + tool_schemas + messages)
        ├── tool_calls → execute in PARALLEL (asyncio.gather)
        │               → microcompact old iteration results
        │               → loop
        └── text only  → return / stream final response
```

**Prompt caching**: `_CACHED_SYSTEM_PROMPT` and `_CACHED_TOOL_SCHEMAS` are built once at module load for llama.cpp KV cache reuse. Call `reload_prompt_cache()` if schemas change at runtime.

**System prompt construction** (`_build_system_prompt(attached_files)`):
1. Base `system.txt` content (from `prompts/system.txt`)
2. Available RAG collections for current user (loaded via `RAGTool.list_collections()`)
3. Persistent memo entries from `data/memory/{username}.json` (reloaded each request — NOT cached)
4. Attached file metadata (name, size, type + structure: headers/columns/imports/preview depending on file type)

**File types with rich metadata** (from `backend/utils/file_handler.py:extract_file_metadata()`): CSV (headers, sample rows, delimiter detection), JSON (structure type, keys, sample values), Excel (sheet names, column names, sample rows), code files (imports, function/class definitions, preview), text (line/char count, first 10 lines preview).

**Microcompaction**: Tool results exceeding `TOOL_RESULT_BUDGET[tool_name]` are saved to `data/tool_results/{session_id}/{call_id}.json` and replaced with truncated summaries in the message history. `_compress_old_iterations()` additionally reduces previous iterations to one-line summaries, keeping only the current "hot tail" at full fidelity.

**Stop signal**: Each iteration calls `check_stop()` — raises `StopInferenceError` if `data/STOP` exists.

**Key methods**:
- `run(messages, attached_files)` — non-streaming, returns final text
- `run_stream(messages, attached_files)` — yields `TextEvent`, `ToolStatusEvent`, `ToolCallDeltaEvent`
- `_execute_tools_parallel(tool_calls)` — `asyncio.gather` over all tool calls in one turn
- `_dispatch_tool(name, arguments)` — validates RAG collection, injects `session_id`, routes to tool

### LLM Backend (`backend/core/llm_backend.py`)

Fully async `LlamaCppBackend` using `httpx.AsyncClient`. Wrapped by `LLMInterceptor` (in `llm_interceptor.py`) which logs all requests and responses to `data/logs/prompts.log`. The interceptor accepts extra `session_id` and `agent_type` kwargs for logging only — these are not forwarded to the backend.

**Response types**: `LLMResponse`, `TextEvent`, `ToolCallDeltaEvent`, `ToolStatusEvent`, `ToolCall`, `ToolCallFunction`

**Wire format** (request → llama.cpp):
```json
{"model": "...", "messages": [...], "temperature": 0.7, "stream": false,
 "tools": [{"type": "function", "function": {"name": "...", "parameters": {...}}}]}
```

**Wire format** (response with tool call):
```json
{"choices": [{"message": {"tool_calls": [{"function": {"name": "websearch", "arguments": "{\"query\": \"...\"}"}}]}, "finish_reason": "tool"}]}
```

**Tool result** sent back: `{"role": "tool", "name": "websearch", "content": "{...}", "tool_call_id": "call_0"}`

Streaming accumulates tool call deltas across SSE chunks, yields `TextEvent` in real-time, then emits a single `ToolCallDeltaEvent` after stream ends.

### Tool System

Tools run **in-process** (no HTTP between agent and tools):

| Tool | Implementation | Interface |
|------|----------------|-----------|
| **websearch** | `tools/web_search/tool.py` | `WebSearchTool().search(query, max_results)` |
| **python_coder** | `tools/python_coder/` | `PythonCoderTool(session_id).execute(instruction, timeout)` |
| **rag** | `tools/rag/` | `RAGTool(username).retrieve(collection_name, query, max_results)` |
| **file_reader** | `tools/file_ops/reader.py` | `FileReaderTool(username, session_id).read(path, offset, limit)` |
| **file_writer** | `tools/file_ops/writer.py` | `FileWriterTool(session_id).write(path, content, mode)` |
| **file_navigator** | `tools/file_ops/navigator.py` | `FileNavigatorTool(username, session_id).navigate(operation, path, pattern)` |
| **shell_exec** | `tools/shell/tool.py` | `ShellExecTool(session_id).execute(command, timeout, working_directory)` |
| **process_monitor** | `tools/process_monitor/tool.py` | `ProcessMonitorTool(session_id).execute(operation, **kwargs)` — start/status/read_output/kill/list |
| **memo** | `tools/memo/tool.py` | `MemoTool(username).execute(operation, key, value)` |

Tool schemas in `tools_config.py`. `session_id` is stripped from all schemas before sending to LLM (injected by `_dispatch_tool()` at call time).

**python_coder factory** (`tools/python_coder/__init__.py`): `PythonCoderTool(session_id)` uses `__new__` to return either `NativePythonExecutor` (subprocess) or `OpenCodeExecutor` (remote OpenCode server on port 37254) based on `PYTHON_EXECUTOR_MODE`.

**RAG tool auto-selection** (`tools/rag/__init__.py`): `EnhancedRAGTool` is used when any of `RAG_USE_HYBRID_SEARCH`, `RAG_USE_RERANKING`, or `RAG_CHUNKING_STRATEGY != "fixed"` — all true by default. RAG data is per-user: `data/rag_documents/{username}/`, `data/rag_indices/{username}/`, `data/rag_metadata/{username}/`.

**NativePythonExecutor** (`native_tool.py`): Generates code via LLM call to llama.cpp, then runs it in a subprocess. **OpenCodeExecutor** (`opencode_tool.py`): Two-stage — OpenCode generates code and saves to file, then Python subprocess runs it. Maintains a class-level `_session_map` linking LLM session IDs to OpenCode session IDs.

**WebSearchTool**: Uses Tavily API. Logs tool executions directly to `prompts.log` in addition to stdout.

### API Routes

| File | Endpoints |
|------|-----------|
| `app.py` | `GET /` (service status), `GET /health`, `GET /api/health`, `/docs` (Swagger), `/redoc` |
| `auth.py` | `POST /api/auth/signup`, `POST /api/auth/login` |
| `chat.py` | `POST /v1/chat/completions` (OpenAI-compatible, streaming + file uploads) |
| `sessions.py` | `GET /api/chat/sessions[?q=]`, `PATCH /api/chat/sessions/{id}`, `GET /api/chat/history/{id}` |
| `models.py` | `GET /v1/models` |
| `admin.py` | `POST /api/admin/model` (admin only), `GET/POST/DELETE /api/admin/stop-inference` |
| `tools.py` | `/api/tools/*` (direct tool access + RAG collection management) |
| `jobs.py` | `POST /api/jobs`, `GET /api/jobs`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/stream`, `DELETE /api/jobs/{id}` |

**Note**: `rag_upload_async.py` exists (`POST /api/rag/upload/stream` with SSE progress) but is **not registered** in `app.py` — currently dead code.

`/v1/chat/completions` accepts form data (not JSON) so files can be uploaded alongside messages. `session_id` is optional — auto-creates a new session if absent. New sessions get an auto-title from the first user message (truncated to 60 chars, no LLM call).

**Background jobs** (`/api/jobs`): Fire-and-forget agent runs. `POST` returns `202` with a `job_id` immediately. The agent runs as an `asyncio.Task`, streaming output to `data/jobs/{job_id}.json` via `FileLock`. Clients poll `GET /api/jobs/{id}` or subscribe to SSE at `/api/jobs/{id}/stream`. Cancel via `DELETE`. Job state: `pending → running → completed | failed | cancelled`.

### Startup Behavior (`app.py` → `startup_event`)

1. Clears any lingering `data/STOP` signal
2. Cleans up old session files (older than `SESSION_CLEANUP_DAYS`)
3. Cleans up old job files (older than `JOBS_CLEANUP_DAYS`)
4. Checks llama.cpp backend availability
5. Starts OpenCode server if `PYTHON_EXECUTOR_MODE == "opencode"`

### Database & Storage

- **SQLite** (`data/app.db`): users, sessions metadata (includes `title TEXT` column, migration applied on startup)
- **Conversations**: JSON in `data/sessions/{session_id}.json` (FileLock for concurrent access)
- **Uploads**: `data/uploads/{username}/` (persistent)
- **Scratch**: `data/scratch/{session_id}/` (per-session workspace, also gets uploaded files)
- **RAG**: `data/rag_documents/`, `data/rag_indices/`, `data/rag_metadata/`
- **Tool Results**: `data/tool_results/{session_id}/` (microcompaction overflow)
- **Memo**: `data/memory/{username}.json` — flat dict `{key: {value, updated_at}}` for cross-session memory
- **Jobs**: `data/jobs/{job_id}.json` — background job state + streamed output chunks (FileLock)
- **Logs**: `data/logs/prompts.log` (all LLM interactions via LLMInterceptor + direct tool execution logs from websearch/python_coder)

## Adding New Tools

1. Create `tools/{name}/tool.py` — return `{"success": bool, ...}`
2. Add schema to `TOOL_SCHEMAS` in `tools_config.py`
3. Add dispatch case in `_dispatch_tool()` in `backend/agent.py`
4. Add to `config.AVAILABLE_TOOLS`
5. Add char budget to `config.TOOL_RESULT_BUDGET`
6. Add per-tool params to `config.TOOL_PARAMETERS`
7. Call `reload_prompt_cache()` if the agent is already running

## Common Gotchas

1. **llama.cpp needs `--jinja`** — native tool calling requires jinja template support
2. **Password byte limit** — bcrypt truncates at 72 BYTES, not characters; `hash_password()` in `backend/utils/auth.py` raises `ValueError` if exceeded
3. **Session IDs must be unique** — used for workspace isolation in python_coder, file tools, and process_monitor
4. **RAG collection validation** — `_dispatch_tool()` rejects unknown collection names before calling the tool; LLM must use a name from the injected collections list
5. **tool_call id may be absent** — llama.cpp may omit `id`; backend generates `call_0`, `call_1`, etc. if missing
6. **RAG score semantics** — FAISS `IndexFlatIP` returns cosine similarity (0–1, higher = better)
7. **`data/` is gitignored** — entire runtime data directory excluded from version control
8. **SSL cert** — `LlamaCppBackend` looks for `C:/DigitalCity.crt` and uses it if present
9. **process_monitor uses handles, not PIDs** — `process_monitor.start` returns a `handle` string (e.g. `proc_1`); pass it to `status`/`read_output`/`kill`. The `ProcessRegistry` singleton tracks live processes by handle within a session.
10. **Memo NOT prompt-cached** — `MemoTool.load_for_prompt()` is called fresh each request so writes take effect immediately in the same session (unlike the static `_CACHED_SYSTEM_PROMPT`)
11. **`rag_upload_async.py` is dead code** — the router exists but is never registered in `app.py`; to activate it, add `from backend.api.routes import rag_upload_async` and `app.include_router(rag_upload_async.router)` in `app.py`
12. **`create_users.py` requires the server** — it hits HTTP endpoints, unlike `create_user_direct.py` which writes to the DB directly
13. **`system.txt` has duplicate sections** — `process_monitor` and `memo` tool descriptions each appear twice in `prompts/system.txt`
14. **file_reader has a 50KB cap** — `MAX_READ_BYTES = 50 * 1024` in `tools/file_ops/reader.py`; shell_exec also caps at 50KB per stream (`MAX_OUTPUT_SIZE`)
15. **file_reader offset is 1-based** — the actual code treats offset as 1-based (line 1 = first line), but `tools_config.py` schema incorrectly says "0-indexed"
16. **file_writer resolves relative paths from cwd, NOT scratch** — unlike `file_reader` which checks scratch first, then uploads, then cwd
17. **process_monitor is in-memory only** — the `ProcessRegistry` singleton tracks processes in a dict; if the server restarts, all handles are lost
18. **OpenCode server auto-restarts once** — `OpenCodeServerManager.ensure_running()` will attempt one restart if the server dies; subsequent failures require manual intervention
19. **RAG collections are per-user** — each user has isolated document dirs, FAISS indices, and metadata under `data/rag_*/{username}/`

## Default Credentials

- **Admin**: `admin` / `administrator` (change in production via `config.py`)
