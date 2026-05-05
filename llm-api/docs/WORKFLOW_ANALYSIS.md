# LLM API Fast — Complete Workflow Analysis

> Generated: 2026-04-17  
> Scope: Every mode, every tool, every option, every log path — plus efficiency proposals.

---

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [Entry Points & Workflow Modes](#2-entry-points--workflow-modes)
3. [Agent Loop — Deep Dive](#3-agent-loop--deep-dive)
4. [LLM Backend & Interceptor](#4-llm-backend--interceptor)
5. [Tool Reference](#5-tool-reference)
6. [RAG Pipeline](#6-rag-pipeline)
7. [API Endpoints Reference](#7-api-endpoints-reference)
8. [Bot / Hoonbot System](#8-bot--hoonbot-system)
9. [Storage Layout](#9-storage-layout)
10. [Logging & Observability](#10-logging--observability)
11. [Configuration Quick-Reference](#11-configuration-quick-reference)
12. [Efficiency Analysis & Proposed Improvements](#12-efficiency-analysis--proposed-improvements)

---

## 1. System Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│                          LLM_API_fast (port 10007)                         │
│                                                                            │
│  ┌──────────────┐   ┌─────────────┐   ┌─────────────────────────────────┐ │
│  │   FastAPI     │   │  AgentLoop  │   │          Tools (in-process)     │ │
│  │  (app.py)     │──▶│ (agent.py)  │──▶│  websearch  │ python_coder      │ │
│  │               │   │             │   │  code_exec  │ rag               │ │
│  │  /v1/chat/…   │   │  run()      │   │  file_ops   │ shell_exec        │ │
│  │  /api/jobs    │   │  run_stream()│  │  process_monitor │ memo         │ │
│  │  /api/tools   │   │             │   └─────────────────────────────────┘ │
│  └──────────────┘   └─────┬───────┘                                        │
│                            │                                               │
│                    ┌───────▼──────┐                                        │
│                    │ LLMInterceptor│  (wraps LlamaCppBackend)              │
│                    │  + logger     │──▶  llama.cpp (port 5905)             │
│                    └──────────────┘                                        │
│                                                                            │
│  Storage:  SQLite · JSONL sessions · FAISS indices · job files             │
└────────────────────────────────────────────────────────────────────────────┘
          ▲                                          ▲
          │ HTTP                                     │ HTTP / SSE
┌─────────┴───────┐                       ┌─────────┴──────────┐
│  Browser/Client │                       │  Hoonbot (port 3939)│
│  (frontend)     │                       │  ↕ Messenger        │
└─────────────────┘                       └────────────────────┘
```

**Core invariants:**
- One port (10007), one `AgentLoop`, native llama.cpp tool calling (`--jinja` required)
- All tools execute in-process — zero HTTP hops agent → tool
- KV cache reuse via `cache_prompt=true` + `id_slot` pinning per session
- Byte-stable `_CACHED_SYSTEM_PROMPT` and `_CACHED_TOOL_SCHEMAS` built at module load

---

## 2. Entry Points & Workflow Modes

### 2.1 Synchronous Chat (`POST /v1/chat/completions`, `stream=false`)

```
Client ──POST──▶ chat.py ──▶ AgentLoop.run() ──▶ returns str
                 ↓ (background tasks)
                 conversation_store.append_messages()
                 db.increment_session_message_count()
```

- Response: Full `ChatCompletionResponse` JSON (OpenAI-compatible)
- Session: auto-created if `session_id` absent; title set from first 60 chars of first user message
- File uploads: multipart form; images → base64 data URL in message content; others → metadata extraction
- Blocking: client waits for entire agent loop to finish

### 2.2 Streaming Chat (`POST /v1/chat/completions`, `stream=true`)

```
Client ──POST──▶ chat.py ──▶ AgentLoop.run_stream() ──SSE──▶ client
                 yields:
                   • text/event-stream: ChatCompletionChunk (OpenAI format)
                   • event: tool_status {tool_name, status, duration}
                   • data: [DONE]
```

- Real-time text deltas as `choices[0].delta.content`
- Tool status events are custom named events (`event: tool_status`) — ignored by standard OpenAI clients
- Final chunk carries `x_session_id` field
- Tools start executing as soon as their tool-call delta arrives (before stream ends)

### 2.3 Background Jobs (`POST /api/jobs`)

```
Client ──POST──▶ jobs.py ──202──▶ Client (immediate)
                 ↓ asyncio.Task
                 AgentLoop.run_stream()
                   TextEvent ──▶ job_store.append_chunk()
                   ToolStatusEvent ──▶ job_store.append_tool_event()
                 ──completed/failed──▶ job_store.update_status()
```

- Non-blocking: client gets `job_id` immediately
- Poll: `GET /api/jobs/{id}` (full output + tool events)
- Stream: `GET /api/jobs/{id}/stream` (SSE, polls every 0.2 s)
- Cancel: `DELETE /api/jobs/{id}` → `asyncio.Task.cancel()`
- State machine: `pending → running → completed | failed | cancelled`

### 2.4 Non-Streaming Agent Loop Detail

```
run(messages, attached_files):
  1. _refresh_available_rag_collections()   ← 60s TTL module-level cache
  2. Build system prompt (byte-stable _CACHED_SYSTEM_PROMPT)
  3. Build dynamic context: RAG collections + memo + file metadata
     ─ Total cap: AGENT_DYNAMIC_CONTEXT_MAX_CHARS (6000)
     ─ Memo cap: AGENT_MEMO_MAX_CHARS (2000)
  4. _enforce_history_limit(MAX_CONVERSATION_HISTORY = 50)
  5. Loop up to AGENT_MAX_ITERATIONS (60):
     a. check_stop()  ← raises StopInferenceError if data/STOP exists
     b. Log iteration start
     c. _iteration_boundaries.append(len(msgs))
     d. llm.chat(messages, tools=tool_schemas, id_slot=hash(session)%slots)
     e. If no tool_calls → log "final text response" → return content
     f. Log tool calls requested
     g. Append assistant message
     h. _execute_tools_parallel()  ← asyncio.gather(all tools)
     i. Log execution summary
     j. Append tool result messages
     k. _compress_old_iterations()
  6. If max_iterations hit → llm.chat(tools=None, final_response=True) → return
```

### 2.5 Streaming Agent Loop Detail

Key difference from non-streaming:
- Tools are launched with `asyncio.create_task()` **as each ToolCallDeltaEvent arrives** (mid-stream)
- Text events yielded immediately to client
- After stream finishes, `asyncio.gather(*pending_tasks)` collects already-in-progress results
- Tool status events (`ToolStatusEvent`) yielded after each tool completes

### 2.6 Hoonbot Webhook Message Flow

```
Messenger ──POST /webhook──▶ hoonbot:3939
  ↓
_schedule_debounced(room_id, content)
  ↓ (debounce window: 1.5s, combined if rapid messages)
process_message(room_id, content, sender_name)
  ↓
[New session] build_llm_context() + PROMPT.md + memory.md
[Existing]    inject session_id from room_sessions.json
  ↓
POST /v1/chat/completions (streaming or sync)
  ↓ streaming:
    tool_status "started" → send_message_returning_id()
    tool_status "completed/failed" → edit_message()
    text delta → accumulate
  ↓
send_message(room_id, full_reply)
delete_message(all tool status msgs)
stop_typing(room_id)
```

### 2.7 Hoonbot Heartbeat

```
run_heartbeat_loop():
  while True:
    sleep(HEARTBEAT_INTERVAL_SECONDS = 3600)
    if not _within_active_hours(): skip
    if cooldown active: skip
    read HEARTBEAT.md checklist
    POST /v1/chat/completions with checklist + timestamp
    send reply to MESSENGER_HOME_ROOM_ID
```

- Active hours window: `HEARTBEAT_ACTIVE_START` – `HEARTBEAT_ACTIVE_END` (HH:MM)
- LLM connection cooldown: 600s after `httpx.ConnectError`
- Runs independently of message processing

---

## 3. Agent Loop — Deep Dive

### 3.1 Sampling Parameters

Every LLM call sends (when set in config):

| Parameter | Config Key | Default | Notes |
|-----------|-----------|---------|-------|
| `temperature` | `DEFAULT_TEMPERATURE` | 0.7 | Overridable per request |
| `top_p` | `DEFAULT_TOP_P` | 0.9 | |
| `top_k` | `DEFAULT_TOP_K` | 40 | |
| `min_p` | `DEFAULT_MIN_P` | 0.05 | llama.cpp's most effective sampler |
| `repeat_penalty` | `DEFAULT_REPEAT_PENALTY` | 1.1 | |
| `max_tokens` | `AGENT_TOOL_LOOP_MAX_TOKENS` | 4096 | Tool-loop calls |
| `max_tokens` | `DEFAULT_MAX_TOKENS` | 128000 | Final response calls |
| `id_slot` | `hash(session_id) % LLAMACPP_SLOTS` | — | KV cache slot pinning |
| `cache_prompt` | `LLAMACPP_CACHE_PROMPT` | True | Prefix reuse |

### 3.2 Microcompaction Strategy

Two-layer compression for long conversations:

**Layer 1 — `_truncate_tool_result()` (immediate)**
- Per-tool char budgets from `TOOL_RESULT_BUDGET`
- If result > budget: truncate + save full result to `data/tool_results/{session_id}/{call_id}.json`

**Layer 2 — `_compress_old_iterations()` (deferred)**
- Applied to all iterations before the current one
- Tool results > 120 chars → `[tool_name: {40-char summary}...]`
- Assistant tool-call args > 80 chars → `[called: tool1, tool2]` with empty args `{}`
- Tracks progress via `_compressed_up_to` (never recompresses the same range)

**Layer 3 — `_enforce_history_limit()` (per request)**
- If non-system messages > `MAX_CONVERSATION_HISTORY` (50):
  - Drop oldest messages
  - Insert compaction notice: `[Compacted N earlier messages: 3 user, 2 tool, ...]`
  - Compress "cold" tail (beyond limit//2): tool results > 80 chars compressed to 40 chars

### 3.3 Tool Result Budgets

| Tool | Budget (chars) |
|------|---------------|
| websearch | 2,000 |
| code_exec | 5,000 |
| python_coder | 5,000 |
| rag | 3,000 |
| file_reader | 4,000 |
| file_writer | 500 |
| file_navigator | 2,000 |
| shell_exec | 3,000 |
| process_monitor | 3,000 |
| memo | 1,000 |
| default | 3,000 |

### 3.4 Logging Verbosity

Controlled by `AGENT_LOG_VERBOSITY` (default `"summary"`):

| Level | `_summary_logging_enabled()` | `_debug_logging_enabled()` |
|-------|------------------------------|---------------------------|
| `"off"` | False | False |
| `"summary"` | **True** | False |
| `"debug"` | **True** | **True** |

Debug mode adds:
- Full tool arguments (up to 500 chars vs 280 in summary)
- Full tool result JSON (up to 1500 chars)

Log path: `AGENT_LOG_PATH` → `data/logs/prompts.log` (same file as LLM interceptor)

### 3.5 Stop Signal

Each iteration calls `check_stop()`:
- Reads `data/STOP` file existence
- If exists: raises `StopInferenceError` (breaks out of the loop cleanly)
- Cleared on server startup via `clear_stop()`
- API: `POST /api/admin/stop-inference` / `DELETE /api/admin/stop-inference`

---

## 4. LLM Backend & Interceptor

### 4.1 LlamaCppBackend

**Connection pool:**
```python
httpx.AsyncClient(
    verify=ssl_cert_if_exists("C:/DigitalCity.crt"),
    timeout=STREAM_TIMEOUT,          # 864000s
    limits=Limits(
        max_connections=LLAMACPP_CONNECTION_POOL_SIZE,        # 20
        max_keepalive_connections=LLAMACPP_CONNECTION_POOL_SIZE // 2  # 10
    )
)
```

**Wire format → llama.cpp:**
```json
{
  "model": "default",
  "messages": [...],
  "temperature": 0.7,
  "stream": false,
  "tools": [...],
  "parallel_tool_calls": true,
  "cache_prompt": true,
  "id_slot": 3,
  "top_p": 0.9, "top_k": 40, "min_p": 0.05,
  "repeat_penalty": 1.1,
  "max_tokens": 4096
}
```

**Streaming delta accumulation:**
- `pending_tool_calls[idx]` accumulates `name` + `arguments_str` across chunks
- When a new tool call index arrives mid-stream: yields previous as `ToolCallDeltaEvent(is_partial=True)`
- At stream end: yields remaining as `ToolCallDeltaEvent(is_partial=False)`
- Text deltas: yielded immediately as `TextEvent` chunks

### 4.2 LLMInterceptor Logging

Every LLM call logs two entries to `prompts.log`:

**Request entry:**
```
================================================================================
[REQUEST] model=default  backend=LlamaCppBackend  temp=0.7
  agent=agent  session=abc123  streaming=No
  messages=3 (1 system, 1 user, 1 tool)  tools=10
  est_input_tokens=1234
================================================================================
  response=[WAITING FOR RESPONSE...]
```

**Response entry (updated):**
```
================================================================================
[RESPONSE] model=default  backend=LlamaCppBackend  temp=0.7
  agent=agent  session=abc123  streaming=No
  duration=2.34s
  est_tokens: input=1234  output=456  total=1690
  speed=195 tok/s
  status=SUCCESS
================================================================================
  response=The answer is...
```

Token estimation: `len(str(content)) // 4` (rough, character-based)

---

## 5. Tool Reference

### 5.1 code_exec
**Purpose:** LLM writes complete Python code → single subprocess run. No generation round-trip.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `code` | string | required | Complete Python code to execute |
| `timeout` | int | 300 | Execution timeout (seconds) |

- Workspace: `data/scratch/{session_id}/`
- Shared workspace with `python_coder` (files visible to both)
- Output cap: `PYTHON_EXECUTOR_MAX_OUTPUT_SIZE` (10 MB)
- Script named by first `def`/`class` name in code, else `exec_{HHmmss}.py`
- Returns: `{success, execution_mode:"code_exec", stdout, stderr, returncode, execution_time, files, workspace}`
- **When to use:** LLM already has the exact code; fastest path (no LLM codegen call)

### 5.2 websearch
**Purpose:** Web search via Tavily API.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | Search query |
| `max_results` | int | 5 | Number of results (max from `WEBSEARCH_MAX_RESULTS`) |

- Config: `TAVILY_SEARCH_DEPTH = "advanced"`, `TAVILY_API_KEY`
- Domain filtering: `TAVILY_INCLUDE_DOMAINS`, `TAVILY_EXCLUDE_DOMAINS`
- Returns raw Tavily results: `{success, results:[{title,url,score,content}], query, execution_time, num_results}`

### 5.3 python_coder
**Purpose:** Natural language instruction → LLM generates code → subprocess executes. Two-stage pipeline.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `instruction` | string | required | Natural language description of task |
| `timeout` | int | 864000 | Total timeout (generation + execution) |

**Mode selection** (`PYTHON_EXECUTOR_MODE`):

**`"opencode"` (default):**
- Stage 1: OpenCode generates Python (HTTP server or subprocess fallback)
- Stage 2: `subprocess.run([sys.executable, script.py])`
- Session isolation: fresh OpenCode session per call, stale sessions cleaned up
- HTTP server port: 37254; auto-restart once on failure
- Script detection: newly created .py → mentioned in output → most recently modified .py

**`"native"`:**
- Stage 1: Async LLM call to llama.cpp (httpx direct, separate from main backend)
- Stage 2: `subprocess.run([sys.executable, script.py])`
- Workspace context injected: lists existing .py files + their contents
- Temperature: 0.5 (from `TOOL_PARAMETERS["python_coder"]`)

- Output cap: 3000 chars (OpenCode) / `PYTHON_EXECUTOR_MAX_OUTPUT_SIZE` (native)
- Returns: `{success, execution_mode, stdout, stderr, returncode, script_path, execution_time, files, workspace}`

### 5.4 rag
**Purpose:** Semantic search over uploaded document collections.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `collection_name` | string | required | Must match an existing collection for the user |
| `query` | string | required | Search query |
| `max_results` | int | 10 | Max chunks to return |

- Collection validated by `_dispatch_tool()` before calling tool (returns error if unknown)
- Available collections listed in dynamic context (injected into system prompt)
- Returns: `{success, documents:[{document,chunk,score,chunk_index}], execution_time}`

**Enhanced mode** (active when `RAG_USE_HYBRID_SEARCH=True` OR `RAG_USE_RERANKING=True` OR `RAG_CHUNKING_STRATEGY != "fixed"`):
- Stage 1: Dense FAISS retrieval (cosine similarity, IndexFlatIP)
- Stage 2: Hybrid BM25 fusion via RRF (alpha=0.5)
- Stage 3: Context window expansion (RAG_CONTEXT_WINDOW=1, adjacent chunks)
- Stage 4: Cross-encoder reranking (mmarco-mMiniLMv2-L12-H384-v1)
- Returns: `{..., rerank_score, pipeline:{hybrid_search, reranking, chunking_strategy}}`

### 5.5 file_reader
**Purpose:** Read text files with optional offset/limit.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | string | required | File path (relative or absolute) |
| `offset` | int | 1 | First line to read (1-based) |
| `limit` | int | — | Max lines to return |

**Path resolution order:**
1. Absolute path → used directly
2. Relative → `data/scratch/{session_id}/` (session workspace)
3. Relative → `data/uploads/{username}/`
4. Relative → current working directory

- Hard cap: 50 KB (`MAX_READ_BYTES = 50 * 1024`)
- Supported: 26+ text/code/config extensions
- Returns: `{success, content, path, size, total_lines, lines_returned, truncated}`
- **Bug in schema:** `tools/schemas.py` says offset is "0-indexed" but code treats it as 1-based

### 5.6 file_writer
**Purpose:** Write or append content to files.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | string | required | File path |
| `content` | string | required | Content to write |
| `mode` | string | `"write"` | `"write"` (overwrite) or `"append"` |

**Path resolution:** Relative paths from `data/scratch/{session_id}/` (NOT from uploads, NOT from cwd — different from file_reader)
- Auto-creates parent directories
- Returns: `{success, path, bytes_written, mode}`

### 5.7 file_navigator
**Purpose:** List, search, or tree directory structure.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation` | string | required | `"list"`, `"search"`, or `"tree"` |
| `path` | string | — | Directory to operate on |
| `pattern` | string | — | Glob pattern for search (e.g., `**/*.py`) |

**Path resolution:** No path → session scratch workspace; relative → from session workspace

- `list`: files + dirs with name, path, size, modified, is_dir
- `search`: glob pattern matching, recursive supported
- `tree`: full depth tree with relative paths

### 5.8 shell_exec
**Purpose:** Run shell commands asynchronously.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `command` | string | required | Shell command |
| `timeout` | int | 300 | Timeout in seconds |
| `working_directory` | string | — | Working directory (optional) |

- Async subprocess via `asyncio.create_subprocess_shell`
- **Does NOT kill process on timeout** — returns `{still_running: True, pid: N}` with kill instructions
- Output cap: 50 KB per stream (stdout/stderr separately)
- Returns: `{success, stdout, stderr, exit_code, duration, command, pid}`
- Timeout returns: `{success: False, still_running: True, pid, note: "kill with..."}`

### 5.9 process_monitor
**Purpose:** Launch and monitor long-running background processes.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation` | string | required | `start`, `status`, `read_output`, `kill`, `list` |
| `command` | string | — | Required for `start` |
| `handle` | string | — | Required for `status`/`read_output`/`kill` (e.g., `proc_1`) |
| `working_directory` | string | — | For `start` |
| `offset` | int | 0 | For `read_output`: line offset for pagination |
| `max_lines` | int | — | For `read_output`: limit lines returned |
| `stream` | bool | — | For `read_output`: tail mode |

- Ring buffer: 5000 lines per stream (stdout + stderr separately)
- Drain threads: 2 daemon threads per process
- Per-session limit: 20 processes (`PROCESS_MONITOR_MAX_PER_SESSION`)
- Handle format: `proc_1`, `proc_2`, ... (auto-incremented per session)
- **In-memory only**: `ProcessRegistry` singleton lost on server restart
- Kill: SIGTERM → 5s wait → SIGKILL

### 5.10 memo
**Purpose:** Persistent key-value memory across sessions.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation` | string | required | `write`, `read`, `list`, `delete` |
| `key` | string | — | Required for write/read/delete |
| `value` | string | — | Required for write |

- Storage: `data/memory/{username}.json`
- Limits: `MEMO_MAX_ENTRIES = 100`, `MEMO_MAX_VALUE_LENGTH = 1000`
- **Auto-injected** into every agent system prompt via `MemoTool.load_for_prompt()` (NOT cached — read fresh each request)
- Returns: `{success, key, written/value/entries/deleted}`

---

## 6. RAG Pipeline

### 6.1 Document Upload Flow

```
upload_document(collection_name, file_path/content):
  1. Read file (PDF/CSV/Excel/DOCX/JSON/text)
  2. Chunk text:
     - "fixed": overlap-based split (chunk_size=512, overlap=50)
     - "semantic": AdvancedChunker (natural boundary detection)
  3. Embed chunks: SentenceTransformer (bge-m3, GPU)
     - Batch size: RAG_EMBEDDING_BATCH_SIZE (16)
     - Normalize embeddings for cosine similarity
  4. Add to FAISS IndexFlatIP
  5. Update metadata JSON (chunk_lookup, doc references)
  6. If hybrid search: rebuild BM25 index (full corpus retokenize)
  7. Save index to disk
```

Large docs (> threshold): `MemoryEfficientUploader` stores chunks on disk (`_chunks/chunks_{ts}.json`)

PDF uploads: `OptimizedRAGUploader` — parallel page extraction via ProcessPoolExecutor (5-10x faster)

### 6.2 Retrieval Pipeline

```
retrieve(collection_name, query, max_results):
  1. Load FAISS index (mtime-based process-level cache)
  2. Embed query (with RAG_QUERY_PREFIX prefix)
  3. Dense search: index.search(query_emb, k=max_results)
  4. [If hybrid] Sparse BM25 search on tokenized corpus
             → RRF fusion: score = 1/(k + rank_dense) + alpha*(1/(k + rank_sparse))
  5. Expand context window: include adjacent chunks (RAG_CONTEXT_WINDOW=1)
  6. Filter by RAG_MIN_SCORE_THRESHOLD (0.5)
  7. [If reranking] CrossEncoder.predict(query, chunk) → rerank top RAG_RERANKING_TOP_K (20)
  8. Return sorted results with scores
```

### 6.3 Per-User Isolation

```
data/
  rag_documents/{username}/{collection_name}/     ← source files
  rag_indices/{username}/{collection_name}.index  ← FAISS binary
  rag_metadata/{username}/{collection_name}.json  ← chunk lookup + doc refs
```

---

## 7. API Endpoints Reference

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | — | Service status (version, backend, host) |
| GET | `/health`, `/api/health` | — | Full health (llama.cpp, OpenCode, disk, config) |
| POST | `/api/auth/signup` | — | Create user |
| POST | `/api/auth/login` | — | Login → JWT (7 days) |
| POST | `/v1/chat/completions` | JWT | Chat (stream or sync, file upload) |
| GET | `/v1/models` | — | List available models |
| GET | `/api/chat/sessions` | JWT (optional) | List sessions (supports `?q=search`) |
| PATCH | `/api/chat/sessions/{id}` | JWT | Rename session (max 120 chars) |
| GET | `/api/chat/history/{id}` | JWT | Full conversation history |
| POST | `/api/jobs` | JWT | Submit background job → 202 |
| GET | `/api/jobs` | JWT | List user jobs |
| GET | `/api/jobs/{id}` | JWT | Job status + full output |
| GET | `/api/jobs/{id}/stream` | JWT | SSE stream of job output |
| DELETE | `/api/jobs/{id}` | JWT | Cancel job |
| GET | `/api/tools/list` | — | List tool schemas |
| POST | `/api/tools/websearch` | — | Direct websearch |
| POST | `/api/tools/python_coder` | — | Direct python_coder |
| GET | `/api/tools/python_coder/files/{session_id}` | — | List workspace files |
| GET | `/api/tools/python_coder/files/{session_id}/{filename}` | — | Read workspace file |
| POST | `/api/tools/rag/collections` | — | Create RAG collection |
| GET | `/api/tools/rag/collections` | JWT | List RAG collections |
| DELETE | `/api/tools/rag/collections/{name}` | JWT | Delete collection |
| POST | `/api/tools/rag/upload` | — | Upload document to collection |
| GET | `/api/tools/rag/collections/{name}/documents` | JWT | List documents |
| DELETE | `/api/tools/rag/collections/{name}/documents/{id}` | JWT | Delete document |
| POST | `/api/tools/rag/query` | — | Direct RAG query + LLM synthesis |
| GET | `/api/admin/stop-inference` | — | Check stop signal |
| POST | `/api/admin/stop-inference` | Admin | Activate stop signal |
| DELETE | `/api/admin/stop-inference` | Admin | Clear stop signal |
| POST | `/api/admin/model` | Admin | Change default model (runtime only) |

**Note:** `POST /api/rag/upload/stream` (SSE progress) exists in `rag_upload_async.py` but is **never registered** — dead code.

---

## 8. Bot / Hoonbot System

### 8.1 Architecture

```
Messenger (port 3000) ◄──► Hoonbot (port 3939) ◄──► LLM API (port 10007)
```

Hoonbot is a standalone FastAPI app that:
- Registers as a bot user with Messenger via REST API
- Receives webhook events (`new_message`, `message_edited`, `message_deleted`)
- Routes messages to LLM API with session continuity
- Posts LLM replies back to Messenger rooms
- Runs proactive heartbeat tasks from `HEARTBEAT.md`

### 8.2 Session Continuity

- Sessions stored in `Bot/Hoonbot/data/room_sessions.json`
- Format: `{room_id: {session_id, created_at}}`
- Auto-expire: `SESSION_MAX_AGE_DAYS` (7 days)
- On 404 from LLM API: clear session + retry once with fresh context
- Message count tracked per room; at `MEMORY_FLUSH_THRESHOLD` (30), injects memory-save hint

### 8.3 Context Injection (New Sessions)

Every new session receives:
```
[PROMPT.md content]

---

## Session Variables
- messenger_url: http://localhost:3000
- messenger_api_key: <key>
- bot_user_id: <id>
- bot_name: Hoonbot
- home_room_id: <id>
- data_dir: /absolute/path/to/data/
- memory_file: /absolute/path/to/memory.md
- skills_dir: /absolute/path/to/skills/

## Current Memory
[memory.md content]
```

### 8.4 Debouncing

Rapid messages in same room are combined:
- Window: `DEBOUNCE_SECONDS = 1.5`
- Accumulated: `content1 + "\n" + content2`
- Files merged across messages
- On new message: cancel previous debounce task + `stop_typing()` + restart timer

### 8.5 Message Splitting

Long replies split respecting boundaries (priority order):
1. Paragraph break (`\n\n`)
2. Line break (`\n`)
3. Word boundary (` `)
4. Character boundary (hard cut)

Max per chunk: `MAX_MESSAGE_LENGTH = 2000`

---

## 9. Storage Layout

```
data/
├── app.db                         SQLite: users, sessions metadata
├── sessions/
│   ├── {id}.jsonl                 Append-only full conversation log
│   ├── {id}.recent.json           Bounded hot cache (last MAX_CONV_HISTORY msgs)
│   └── {id}.lock                  FileLock (10s timeout)
├── uploads/{username}/            Persistent uploaded files
├── scratch/{session_id}/          Session workspace (python_coder, code_exec)
├── tool_results/{session_id}/     Microcompaction overflow
│   └── {call_id}.json
├── jobs/
│   ├── {id}.json                  Job metadata + status
│   ├── {id}.output.txt            Append-only text output
│   ├── {id}.events.jsonl          Tool events (tool, status, duration, at)
│   └── {id}.lock
├── rag_documents/{username}/{collection}/  Source files
├── rag_indices/{username}/         FAISS binary indices
├── rag_metadata/{username}/        Chunk lookup + doc references
├── memory/{username}.json          Memo key-value store
├── logs/
│   └── prompts.log                 All LLM interactions + agent events
│                                   (FIFO rotated at 100k lines, keeps newest 80%)
├── STOP                            Stop signal file (created by admin API)
└── vector_db/                      (legacy, unused)

Bot/Hoonbot/data/
├── .apikey                         Messenger bot API key
├── .llm_key                        LLM JWT token
├── .llm_model                      Model name
├── memory.md                       Markdown memory file for bot
└── room_sessions.json              Per-room session mapping
```

**Cleanup schedule** (set at server startup):

| Data | Config Key | Default |
|------|-----------|---------|
| Sessions | `SESSION_CLEANUP_DAYS` | **0 (DISABLED!)** |
| Scratch dirs | `SCRATCH_CLEANUP_DAYS` | 14 days |
| Tool results | `TOOL_RESULTS_CLEANUP_DAYS` | 14 days |
| Job files | `JOBS_CLEANUP_DAYS` | 30 days |
| Log rotation | `LOG_ROTATION_DAYS` | 14 days |

---

## 10. Logging & Observability

### 10.1 Log File: `data/logs/prompts.log`

Single unified log for all LLM activity. Three sources write to it:

| Source | What's logged |
|--------|--------------|
| `LLMInterceptor` | Every LLM request + response (timing, tokens, tools) |
| `AgentLoop` | Iteration boundaries, tool calls, results, summaries, completion |
| `WebSearchTool` | Search queries + result previews |
| `OpenCodeExecutor` | Code generation stage + execution stage |

**Rotation:** `append_capped_prompts_log()` — checked every 100 appends; if > 100k lines, keeps newest 80% (atomically via temp file + `os.replace()`).

### 10.2 Agent Log Events

```
─── AGENT ITERATION 1 (session: abc, user: admin, 2026-04-17 12:00:00) ───
[TOOL CALL REQUESTED] iteration=1
  [1] websearch (call_0) args={"query": "hello world"}
─── TOOL RESULT: websearch (call_0) ───
  Status: SUCCESS  duration=1.23s
─── EXECUTION SUMMARY (iteration 1) ───
  Succeeded: 1  Failed: 0  Wall time: 1.23s
  websearch: SUCCESS
─── AGENT COMPLETE: final text response (2 iterations, 1 tool calls) ───
```

### 10.3 Console Output

Separate from file logging; always printed:
- LLM call banner: model, backend, temperature, agent type, message/tool counts
- Response time, tool call preview, or response text preview
- Agent iteration and tool execution banners

### 10.4 OpenCode Logging

Verbosity: `OPENCODE_LOG_VERBOSITY = "summary"` (summary/debug)
- Summary: stage transitions (CODE GENERATION, EXECUTION) + final result
- Debug: full streaming output line by line

---

## 11. Configuration Quick-Reference

### Server & Network

| Key | Default | Notes |
|-----|---------|-------|
| `SERVER_PORT` | 10007 | Main API port |
| `LLAMACPP_HOST` | `http://localhost:5905` | llama.cpp server |
| `LLAMACPP_SLOTS` | 4 | Must match `--parallel` on llama.cpp |
| `LLAMACPP_CONNECTION_POOL_SIZE` | 20 | Keep-alive pool |
| `STREAM_TIMEOUT` | 864000 | 10 days (effectively unlimited) |
| `CORS_ORIGINS` | `["*"]` | Open CORS — restrict in production |

### Inference

| Key | Default | Notes |
|-----|---------|-------|
| `DEFAULT_TEMPERATURE` | 0.7 | |
| `DEFAULT_MIN_P` | 0.05 | llama.cpp's most effective sampler |
| `AGENT_MAX_ITERATIONS` | 60 | Max tool-calling loop depth |
| `AGENT_TOOL_LOOP_MAX_TOKENS` | 4096 | Tokens during tool loop |
| `DEFAULT_MAX_TOKENS` | 128000 | Final response tokens |
| `MAX_CONVERSATION_HISTORY` | 50 | Non-system messages kept |

### Python Executor

| Key | Default | Notes |
|-----|---------|-------|
| `PYTHON_EXECUTOR_MODE` | `"opencode"` | `"native"` or `"opencode"` |
| `OPENCODE_SERVER_PORT` | 37254 | OpenCode HTTP server |
| `OPENCODE_MODEL` | `"llama.cpp/MiniMax"` | `"provider/model"` |

### RAG

| Key | Default | Notes |
|-----|---------|-------|
| `RAG_EMBEDDING_MODEL` | `bge-m3` | SentenceTransformer |
| `RAG_EMBEDDING_DEVICE` | `cuda` | |
| `RAG_CHUNKING_STRATEGY` | `"semantic"` | `"fixed"` or `"semantic"` |
| `RAG_USE_HYBRID_SEARCH` | True | BM25 + FAISS fusion |
| `RAG_USE_RERANKING` | True | Cross-encoder reranking |
| `RAG_MIN_SCORE_THRESHOLD` | 0.5 | Filter threshold |
| `RAG_RERANKING_TOP_K` | 20 | Candidates before reranking |

### Security (Change in production!)

| Key | Default | Warning |
|-----|---------|---------|
| `JWT_SECRET_KEY` | `"tvly-dev-..."` | **INSECURE hardcoded value** |
| `DEFAULT_ADMIN_PASSWORD` | `"administrator"` | **Change immediately** |
| `TAVILY_API_KEY` | `"your-secret-key..."` | Set real key |

---

## 12. Efficiency Analysis & Proposed Improvements

### CRITICAL — Fix These First

---

#### C1. Session Scratch Never Cleaned Up
**Problem:** `SESSION_CLEANUP_DAYS = 0` **disables** session cleanup. Every conversation creates a `data/scratch/{session_id}/` directory that is never deleted. Over time this fills disk.

**Fix:**
```python
# config.py
SESSION_CLEANUP_DAYS = 7   # or 14
```
This one-line change activates the already-written `_cleanup_old_sessions()` startup routine.

---

#### C2. `AGENT_LOG_ASYNC = False` Blocks the Event Loop
**Problem:** Sync log writes run on the asyncio event loop thread, adding I/O latency to every iteration boundary, tool call, and result. With `AGENT_LOG_ASYNC=False`, the entire agent waits for disk I/O during each log.

**Fix:**
```python
# config.py
AGENT_LOG_ASYNC = True
```

---

#### C3. JWT Secret is Hardcoded
**Problem:** `JWT_SECRET_KEY = "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"` is committed to source. Anyone with repo access can forge tokens.

**Fix:**
```python
# config.py
import secrets
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY") or secrets.token_hex(32)
```
Or load from a `.env` file excluded from git.

---

#### C4. `AGENT_TOOL_LOOP_MAX_TOKENS = 4096` Too Low
**Problem:** The tool loop uses only 4096 max tokens. If the LLM needs to generate a long `file_writer` call (writing a large file), or produce a complex multi-tool plan, 4096 tokens truncates the response mid-call, causing malformed tool JSON.

**Fix:**
```python
# config.py
AGENT_TOOL_LOOP_MAX_TOKENS = 16384   # or 32768 depending on model context
```

---

### HIGH IMPACT — Address Next

---

#### H1. `shell_exec` Orphans Processes on Timeout
**Problem:** When `shell_exec` times out, the subprocess keeps running as an orphan. The LLM is told to kill it manually, but often doesn't (it moves on). Repeated timeouts accumulate zombie processes.

**Fix in `tools/shell/tool.py`:** Add optional kill-on-timeout config:
```python
# After asyncio.TimeoutError
if config.SHELL_EXEC_KILL_ON_TIMEOUT:
    proc.kill()
    await proc.wait()
    return {"success": False, "killed": True, "stdout": ..., "stderr": ...}
```
Default `SHELL_EXEC_KILL_ON_TIMEOUT = False` for backward compatibility.

---

#### H2. Job SSE Polling Creates Lock Contention
**Problem:** `GET /api/jobs/{id}/stream` polls job store every 0.2 seconds. Each poll acquires a `FileLock`. For multiple concurrent streaming clients on the same job, this creates unnecessary lock contention.

**Fix:** Use `asyncio.Event` for signaling:
```python
# In job_store.py
_job_events: dict[str, asyncio.Event] = {}

def signal_job_update(job_id: str):
    if job_id in _job_events:
        _job_events[job_id].set()
        _job_events[job_id].clear()
```
Streaming route waits on event instead of sleeping 0.2s. Reduces unnecessary disk reads by ~80% under normal conditions.

---

#### H3. RAG BM25 Full Rebuild on Every Upload
**Problem:** `_rebuild_bm25_index()` retokenizes the **entire** corpus on every document upload. For a collection with 10,000 chunks and a new 50-chunk document, 10,000 chunks are re-tokenized needlessly.

**Fix:** Incremental BM25 update — append new tokenized chunks to existing corpus before rebuilding index, or use an append-friendly BM25 implementation.

---

#### H4. `tools/schemas.py` Schema Bug: `file_reader` offset is 1-based but documented as 0-indexed
**Problem:** LLMs reading the schema think offset=0 is the first line, but the code treats offset=1 as the first line. This causes off-by-one confusion.

**Fix in `tools/schemas.py`:**
```python
"offset": {
    "type": "integer",
    "description": "Line number to start reading from (1-based; 1 = first line, default 1)",
    "default": 1
}
```

---

#### H5. Dynamic Context Rebuilt From Scratch Every Request
**Problem:** `_build_dynamic_context()` always loads RAG collections (60s TTL cache, OK) and memo (no cache, disk read every request). For high-frequency requests, this is extra disk I/O per request.

**Fix:** Add a short TTL (5–10 second) memo cache keyed by `(username, mtime)`:
```python
_memo_cache: dict[str, tuple[float, str]] = {}  # username → (mtime, content)

def _load_memo_cached(username):
    memo_path = config.MEMO_DIR / f"{username}.json"
    try:
        mtime = memo_path.stat().st_mtime
        if username in _memo_cache and _memo_cache[username][0] == mtime:
            return _memo_cache[username][1]
        content = MemoTool.load_for_prompt(username)
        _memo_cache[username] = (mtime, content)
        return content
    except FileNotFoundError:
        return ""
```
This preserves the "live update" guarantee (mtime-based) while avoiding redundant reads within the same second.

---

### MEDIUM IMPACT

---

#### M1. `process_monitor` Handles Lost on Server Restart
Processes launched via `process_monitor` are tracked in an in-memory singleton. A server restart loses all handles, orphaning real OS processes.

**Fix:** Persist the process registry to `data/process_registry.json` on each `start` operation. On startup, attempt to re-attach to any live PIDs. Stale entries (dead PIDs) are cleaned up silently.

---

#### M2. Dead Code: `rag_upload_async.py` Never Registered
The SSE-progress RAG upload route (`POST /api/rag/upload/stream`) is implemented but never added to `app.py`. It provides real-time upload progress — a useful feature currently inaccessible.

**Fix:** Either:
- **Activate it:** Add to `app.py`:
  ```python
  from backend.api.routes import rag_upload_async
  app.include_router(rag_upload_async.router)
  ```
- **Delete it:** Remove `backend/api/routes/rag_upload_async.py` if SSE upload isn't needed.

---

#### M3. Hoonbot Memory Is Unstructured Markdown
The Hoonbot memory file (`memory.md`) is a free-form markdown file the LLM reads and edits. This is fragile — the LLM may rewrite the entire file in unexpected formats.

**Fix:** Use the `memo` tool's structured JSON format (`data/memory/{username}.json`) instead. Hoonbot's LLM API user (`admin`) already has a memo namespace. The memo tool provides atomically-safe read/write/delete operations and is already injected into the system prompt automatically.

---

#### M4. `tool_calls_log` Grows Unbounded Per Session
`AgentLoop.tool_calls_log` accumulates all tool calls for the session's lifetime and is never cleared. For long sessions with hundreds of iterations, this list grows large in memory.

**Fix:** Cap at last N entries (e.g., 200), or clear on each `run()` call since it's only used for the final completion log.

---

#### M5. Hoonbot Tool Status Message Cleanup Is Sequential
After streaming, Hoonbot deletes tool status messages one at a time sequentially:
```python
for msg_id in tool_status_msgs.values():
    await messenger.delete_message(msg_id)
```

**Fix:** Delete concurrently:
```python
await asyncio.gather(*[messenger.delete_message(mid) for mid in tool_status_msgs.values()])
```

---

#### M6. LLM Token Estimation Is Too Rough for Useful Metrics
The interceptor estimates tokens as `len(str(content)) // 4`. This is off by 2-3x for Korean/CJK text (each character ≈ 1-2 tokens, not 0.25).

**Fix:** Use `tiktoken` with an OpenAI-compatible tokenizer, or multiply by a language-aware factor. Even a rough `len(content.encode("utf-8")) // 4` would be more accurate for multi-byte text.

---

### LOWER PRIORITY

---

#### L1. `CORS_ORIGINS = ["*"]` in Production
Open CORS allows any origin to make authenticated requests. Restrict to your actual frontend origin(s).

#### L2. No Rate Limiting on `/v1/chat/completions`
A single user can fire unlimited concurrent requests. Consider `slowapi` or a per-user token bucket middleware.

#### L3. `KV Cache Slot Collision`
With `LLAMACPP_SLOTS = 4` and many sessions, `hash(session_id) % 4` creates hot spots. Sessions sharing a slot evict each other's KV cache. Consider increasing `LLAMACPP_SLOTS` to 8–16 if your GPU VRAM allows.

#### L4. `AGENT_OLD_TOOL_RESULT_SUMMARY_MAX_CHARS = 40` Is Extremely Aggressive
Compressing old tool results to 40 characters discards most of the content. Consider 80–120 chars to preserve more context for long multi-step tasks.

#### L5. `OpenCode` Config Regenerated Every Startup
`ensure_opencode_config()` rewrites `~/.config/opencode/config.json` on every server start even if the content hasn't changed. Add a content hash check before writing.

#### L6. `code_exec` vs `python_coder` Distinction May Confuse LLM
Both tools execute Python and share workspace. The system prompt table helps, but the distinction (code_exec = LLM writes code directly; python_coder = natural language → LLM generates code) is subtle. Consider renaming or consolidating, or adding stronger guidance in tool descriptions.

---

### Summary Table

| Priority | Issue | Fix Effort | Impact |
|----------|-------|-----------|--------|
| 🔴 Critical | Session scratch never cleaned (`SESSION_CLEANUP_DAYS=0`) | 1 line | Disk space |
| 🔴 Critical | Log writes block event loop (`AGENT_LOG_ASYNC=False`) | 1 line | Latency |
| 🔴 Critical | JWT secret hardcoded | 3 lines | Security |
| 🔴 Critical | Tool loop max tokens too low (4096) | 1 line | Correctness |
| 🟠 High | Shell process orphans on timeout | ~10 lines | Stability |
| 🟠 High | Job SSE polling creates lock contention | ~30 lines | Scalability |
| 🟠 High | BM25 full corpus rebuild per upload | Medium | RAG performance |
| 🟠 High | `file_reader` offset schema bug (says 0-based, is 1-based) | 1 line | LLM accuracy |
| 🟠 High | Memo disk read every request | ~15 lines | Throughput |
| 🟡 Medium | `process_monitor` handles lost on restart | ~40 lines | Reliability |
| 🟡 Medium | Dead code `rag_upload_async.py` | 2 lines to activate | UX |
| 🟡 Medium | Hoonbot uses unstructured `memory.md` | Config change | Reliability |
| 🟡 Medium | `tool_calls_log` unbounded growth | 2 lines | Memory |
| 🟡 Medium | Tool status deletion sequential | 1 line | Responsiveness |
| 🟡 Medium | Token estimation inaccurate for Korean | ~5 lines | Observability |
| 🔵 Low | Open CORS `["*"]` | 1 line | Security |
| 🔵 Low | No rate limiting | ~20 lines | Security |
| 🔵 Low | KV slot collision at 4 slots | 1 line | Cache hit rate |
| 🔵 Low | Old tool result summary too short (40 chars) | 1 line | Context quality |
| 🔵 Low | OpenCode config always overwritten | ~5 lines | Startup speed |
| 🔵 Low | code_exec/python_coder naming confusion | Schema edit | LLM accuracy |
