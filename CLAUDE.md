# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an **LLM API server** that provides OpenAI-compatible endpoints backed by **llama.cpp** with native tool calling. The system uses a single agent loop architecture where the LLM decides when to call tools using structured JSON (not free-text parsing).

**Key Architecture**: Single server, single agent loop, native tool calling.
- **One server** on port 10007 handles everything: chat, auth, sessions, tools
- **One agent loop** (`backend/agent.py`) replaces the old 5-agent hierarchy
- **Native tool calling** via llama.cpp's `/v1/chat/completions` with `tools` parameter
- **In-process tool execution** — no HTTP calls between agent and tools

## Development Commands

### Starting the Server

```bash
python run_backend.py
```

Single server on port 10007. No separate tools server needed.

**Important**: Your llama.cpp server must be started with `--jinja` flag for native tool calling to work.

### Dependencies

```bash
pip install -r requirements.txt
```

### Testing

```bash
python tests/test_rag.py                    # Direct RAG tool tests (no server needed)
python tests/test_rag_upload_performance.py  # RAG upload performance tests
```

### Utility Scripts

```bash
python create_users.py          # Batch create users
python create_user_direct.py    # Create a single user directly in DB
python clear_data.py            # Clear all data (sessions, uploads, scratch)
python clear_rag_data.py        # Clear RAG indices, documents, metadata
```

### Configuration

All configuration is centralized in `config.py`. Key settings:
- `LLAMACPP_HOST`: llama.cpp server URL (default: `http://localhost:5904`)
- `LLAMACPP_MODEL`: Model name (default: `"default"`)
- `AGENT_MAX_ITERATIONS`: Max tool-calling loop iterations (default: 8)
- `AGENT_SYSTEM_PROMPT`: System prompt file in `prompts/` (default: `"system.txt"`)
- `PYTHON_EXECUTOR_MODE`: `"native"` or `"opencode"` for code execution

## Architecture

### Agent Loop (`backend/agent.py`)

Single `AgentLoop` class with a while-loop following modern agent patterns (Anthropic, Claude Code, OpenAI):

```
User Input → [cached system prompt + cached tool schemas + messages] → LLM
         ↓
    tool_calls in response?
         ├── Yes → execute tool(s) in PARALLEL → microcompact old results → loop back to LLM
         └── No  → return text response
```

The LLM receives tool schemas via the `tools` parameter and returns structured `tool_calls` with `function.name` and `function.arguments` as JSON. No regex parsing, no "Thought/Action/Action Input" format.

**Key features**:
- **Parallel tool execution**: multiple tool calls in one turn run via `asyncio.gather`
- **Microcompaction**: large tool results saved to disk, old iteration results compressed to summaries
- **Prompt caching**: system prompt and tool schemas cached at module load for llama.cpp KV reuse
- **Tool status streaming**: `ToolStatusEvent` emitted during tool execution for client visibility

**Key methods**:
- `run()` — non-streaming, returns final text
- `run_stream()` — streaming, yields `TextEvent`, `ToolStatusEvent`, and `ToolCallDeltaEvent`
- `_execute_tools_parallel()` — runs multiple tools concurrently
- `_compress_old_iterations()` — microcompaction of old tool results

### LLM Backend (`backend/core/llm_backend.py`)

Fully async `LlamaCppBackend` using `httpx.AsyncClient`:
- `chat(messages, model, temperature, tools)` → `LLMResponse` (content + tool_calls)
- `chat_stream(messages, model, temperature, tools)` → `AsyncIterator[StreamEvent]`
- Wrapped by `LLMInterceptor` for logging to `data/logs/prompts.log`

**Response types**: `LLMResponse`, `TextEvent`, `ToolCallDeltaEvent`, `ToolStatusEvent`, `ToolCall`, `ToolCallFunction`

### Tool System

Tools run **in-process** (no HTTP between agent and tools):

| Tool | Implementation | Interface |
|------|---------------|-----------|
| **websearch** | `tools/web_search/tool.py` | `WebSearchTool().search(query, max_results)` |
| **python_coder** | `tools/python_coder/` | `PythonCoderTool(session_id).execute(instruction, timeout)` |
| **rag** | `tools/rag/` | `RAGTool(username).retrieve(collection_name, query, max_results)` |
| **file_reader** | `tools/file_ops/reader.py` | `FileReaderTool(username, session_id).read(path, offset, limit)` |
| **file_writer** | `tools/file_ops/writer.py` | `FileWriterTool(session_id).write(path, content, mode)` |
| **file_navigator** | `tools/file_ops/navigator.py` | `FileNavigatorTool(username, session_id).navigate(operation, path, pattern)` |
| **shell_exec** | `tools/shell/tool.py` | `ShellExecTool(session_id).execute(command, timeout, working_directory)` |

Tool schemas are defined in `tools_config.py`. Schemas are cached at module load time in `agent.py` for llama.cpp KV cache stability, automatically excluding `session_id` (injected by the agent).

**RAG Tool Selection** (`tools/rag/__init__.py`): `EnhancedRAGTool` is auto-selected if `RAG_USE_HYBRID_SEARCH`, `RAG_USE_RERANKING`, or `RAG_CHUNKING_STRATEGY != "fixed"` are set.

### Native Tool Calling Wire Format

**Request** to llama.cpp:
```json
{
  "messages": [...],
  "tools": [{"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}],
  "temperature": 0.7,
  "stream": false
}
```

**Response** with tool call:
```json
{
  "choices": [{"message": {"role": "assistant", "content": null, "tool_calls": [{"function": {"name": "websearch", "arguments": "{\"query\": \"...\"}"}}]}, "finish_reason": "tool"}]
}
```

**Tool result** sent back:
```json
{"role": "tool", "name": "websearch", "content": "{...}", "tool_call_id": "call_0"}
```

### Streaming

Both `stream=true` and `stream=false` go through the `AgentLoop`. Streaming yields `TextEvent` tokens in real-time. `ToolStatusEvent` is emitted when tools start/complete/fail. When tool calls appear in the stream, they're buffered, executed in parallel, and a new streaming LLM call resumes.

### API Routes

| File | Endpoints |
|------|-----------|
| `auth.py` | `/api/auth/signup`, `/api/auth/login`, `/api/auth/me` |
| `chat.py` | `/v1/chat/completions` (OpenAI-compatible, streaming + tools) |
| `sessions.py` | `/api/chat/sessions`, `/api/chat/history` |
| `models.py` | `/v1/models` (OpenAI-compatible) |
| `admin.py` | `/api/admin/*` (user management) |
| `tools.py` | `/api/tools/*` (direct tool access + RAG management) |

### Database & Storage

- **SQLite** (`data/app.db`): users, sessions
- **Conversations**: JSON in `data/sessions/{session_id}.json` (with `FileLock`)
- **Uploads**: `data/uploads/{username}/`
- **Scratch**: `data/scratch/{session_id}/`
- **RAG**: `data/rag_documents/`, `data/rag_indices/`, `data/rag_metadata/`
- **Tool Results**: `data/tool_results/{session_id}/` (microcompaction disk storage)

## Adding New Tools

1. **Create implementation** in `tools/{tool_name}/tool.py` — return `{"success": bool, ...}`
2. **Add schema** to `TOOL_SCHEMAS` in `tools_config.py`
3. **Add dispatch** in `backend/agent.py` `_dispatch_tool()` method
4. **Add to** `config.AVAILABLE_TOOLS`
5. **Add budget** to `config.TOOL_RESULT_BUDGET` (chars limit for microcompaction)
6. **Call** `reload_prompt_cache()` if schemas change at runtime

## File Organization

```
backend/
  agent.py            - Unified agent loop (parallel exec, microcompaction, caching)
  api/routes/         - FastAPI route handlers
  core/               - LLM backend, database, interceptor
  models/             - Pydantic schemas
  utils/              - Auth, file handling, conversation store, stop signal
tools/
  web_search/         - Tavily integration
  python_coder/       - Code execution (native or opencode)
  rag/                - FAISS document retrieval
  file_ops/           - File reader, writer, navigator
  shell/              - Shell command execution
prompts/
  system.txt          - Structured ACI agent prompt (all 7 tools)
  tools/              - Tool-specific prompts (rag_synthesize, rag_query)
data/                 - Runtime data (gitignored)
  tool_results/       - Microcompaction disk storage
```

## Common Gotchas

1. **llama.cpp needs `--jinja`** — native tool calling requires jinja template support
2. **Password byte length != character length** — bcrypt limit is 72 BYTES
3. **Session IDs must be unique** — used for workspace isolation in python_coder
4. **Tool timeouts** — default is 10 days (864000s) for long-running operations
5. **Windows UTF-8** — server sets explicit UTF-8 encoding for console
6. **RAG score semantics** — FAISS `IndexFlatIP` returns cosine similarity (0-1, higher=better)
7. **`data/` is gitignored** — entire data directory excluded from version control
8. **tool_call id may be absent** — llama.cpp may not return `id` on tool_calls; agent generates one if missing

## Default Credentials

- **Admin**: `admin` / `administrator` (change in production via `config.py`)
