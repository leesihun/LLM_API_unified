# LLM API

A FastAPI-based LLM API server providing OpenAI-compatible endpoints with support for multiple LLM backends, a sophisticated agent system with tool calling, and RAG (Retrieval Augmented Generation).

## Features

- **OpenAI-compatible API** — Drop-in replacement for `/v1/chat/completions` and `/v1/models`
- **Multiple LLM backends** — Ollama, llama.cpp, or auto-fallback between them
- **Agent system** — Five agent types: Chat, ReAct, Plan & Execute, Ultrawork, and Auto (smart router)
- **Built-in tools** — Web search (Tavily), Python code execution, and RAG document retrieval
- **RAG pipeline** — FAISS-based retrieval with optional hybrid BM25 search, cross-encoder reranking, semantic chunking, and multi-query expansion
- **File uploads** — Automatic metadata extraction for JSON, CSV, Excel, Python, and PDF files
- **Streaming** — Server-Sent Events (SSE) streaming for real-time responses
- **Authentication** — JWT-based auth with role-based access control
- **Session management** — Persistent conversation history stored as JSON files

## Architecture

The system uses a **dual-server architecture** to prevent deadlock:

```
┌──────────────────────────┐         HTTP calls          ┌──────────────────────────┐
│     Main API Server      │ ──────────────────────────▸ │     Tools API Server     │
│      (port 10007)        │                             │      (port 10006)        │
│                          │                             │                          │
│  • Chat completions      │                             │  • Web search (Tavily)   │
│  • Authentication        │                             │  • Python code execution │
│  • Session management    │                             │  • RAG retrieval         │
│  • Agent orchestration   │                             │                          │
└──────────────────────────┘                             └──────────────────────────┘
```

Agents on the main server make HTTP requests to tools on the tools server. Running both on the same server would cause deadlock when agents call tools during request processing.

### Agent System

All agents inherit from a common base class and are selected via the `agent_type` parameter:

| Agent | Type Key | Description |
|-------|----------|-------------|
| **ChatAgent** | `chat` | Simple conversational agent, no tool calling |
| **ReActAgent** | `react` | Reasoning + Acting loop — thinks, picks a tool, observes results, repeats |
| **PlanExecuteAgent** | `plan_execute` | Creates a multi-step plan, then executes steps sequentially |
| **UltraworkAgent** | `ultrawork` | Iterative refinement via OpenCode for code-heavy tasks |
| **AutoAgent** | `auto` | Analyzes the query and routes to the best agent automatically |

### Tool System

| Tool | Description |
|------|-------------|
| **websearch** | Web search via Tavily API with configurable depth |
| **python_coder** | Python code execution in isolated workspaces (native subprocess or OpenCode mode) |
| **rag** | Document retrieval from FAISS collections with upload, query, and collection management |

## Quick Start

### Prerequisites

- Python 3.10+
- An LLM backend: [Ollama](https://ollama.com/) or a [llama.cpp](https://github.com/ggerganov/llama.cpp) server
- (Optional) [Tavily API key](https://tavily.com/) for web search
- (Optional) CUDA-capable GPU for RAG embeddings

### Installation

```bash
git clone <repository-url>
cd LLM_API
pip install -r requirements.txt
```

### Configuration

All settings are centralized in `config.py`. Key settings to review:

```python
# LLM Backend
LLM_BACKEND = "ollama"          # "ollama", "llamacpp", or "auto"
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "your-model-name"

# Server ports
SERVER_PORT = 10007             # Main API
TOOLS_PORT = 10006              # Tools API

# Authentication (CHANGE IN PRODUCTION)
JWT_SECRET_KEY = "your-secret-key-change-in-production"
DEFAULT_ADMIN_PASSWORD = "administrator"

# Web search
TAVILY_API_KEY = "your-tavily-api-key"

# RAG
RAG_EMBEDDING_MODEL = "path/to/embedding-model"  # e.g. BAAI/bge-m3
RAG_EMBEDDING_DEVICE = "cuda"   # or "cpu"
```

### Starting the Servers

**Start the tools server first**, then the main server:

```bash
# Terminal 1 — Tools API (must start first)
python tools_server.py

# Terminal 2 — Main API
python run_backend.py
```

Both servers run with 4 uvicorn workers by default (configurable via `SERVER_WORKERS` / `TOOLS_SERVER_WORKERS`).

### Default Credentials

| Username | Password | Role |
|----------|----------|------|
| `admin` | `administrator` | admin |

Change these in `config.py` before deploying to production.

## API Reference

### Authentication

**Sign up**
```http
POST /api/auth/signup
Content-Type: application/json

{"username": "myuser", "password": "mypassword"}
```

**Log in**
```http
POST /api/auth/login
Content-Type: application/json

{"username": "myuser", "password": "mypassword"}
```

Both return `{"access_token": "..."}`. Include the token in subsequent requests:
```
Authorization: Bearer <token>
```

### Chat Completions

```http
POST /v1/chat/completions
Authorization: Bearer <token>
Content-Type: multipart/form-data

model=your-model-name
messages=[{"role": "user", "content": "Hello!"}]
agent_type=auto
stream=false
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | string | required | Model name |
| `messages` | JSON string | required | Array of `{role, content}` objects |
| `agent_type` | string | `"auto"` | One of: `auto`, `react`, `plan_execute`, `ultrawork`, `chat` |
| `stream` | bool | `false` | Enable SSE streaming (disables tool calling) |
| `session_id` | string | auto-generated | Session ID for conversation continuity |
| `temperature` | float | `0.7` | Sampling temperature |
| `max_tokens` | int | `128000` | Maximum output tokens |
| files | file(s) | — | Optional file attachments |

**Response** (non-streaming):
```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "..."},
      "finish_reason": "stop"
    }
  ],
  "x_session_id": "..."
}
```

> **Note**: When `stream=true`, the response is an SSE stream and the agent system is bypassed entirely — no tool calling occurs.

### Sessions

```http
GET /api/chat/sessions              # List all sessions
GET /api/chat/history/{session_id}  # Get conversation history
```

### Models

```http
GET /v1/models                      # List available models (OpenAI-compatible)
```

### Admin

```http
POST /api/admin/model               # Change default model (admin only)
```

### Tools (Direct Access)

These endpoints are primarily used by agents internally, but can also be called directly:

```http
GET  /api/tools/list                                          # List available tools
POST /api/tools/websearch                                     # Web search
POST /api/tools/python_coder                                  # Execute Python code
GET  /api/tools/python_coder/files/{session_id}               # List workspace files
GET  /api/tools/python_coder/files/{session_id}/{filename}    # Read workspace file
POST /api/tools/rag/collections                               # Create RAG collection
GET  /api/tools/rag/collections                               # List collections
DELETE /api/tools/rag/collections/{name}                      # Delete collection
POST /api/tools/rag/upload                                    # Upload document
GET  /api/tools/rag/collections/{name}/documents              # List documents
DELETE /api/tools/rag/collections/{name}/documents/{id}       # Delete document
POST /api/tools/rag/query                                     # Query collection
```

## Usage Examples

### Python Client

```python
import httpx
import json

BASE_URL = "http://localhost:10007"

# Login
r = httpx.post(f"{BASE_URL}/api/auth/login", json={
    "username": "admin", "password": "administrator"
}, timeout=10.0)
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# Chat (non-streaming, with agent)
r = httpx.post(f"{BASE_URL}/v1/chat/completions", data={
    "model": "your-model",
    "messages": json.dumps([{"role": "user", "content": "What is the capital of France?"}]),
    "agent_type": "auto"
}, headers=headers, timeout=300.0)
reply = r.json()["choices"][0]["message"]["content"]
session_id = r.json()["x_session_id"]

# Continue conversation
r = httpx.post(f"{BASE_URL}/v1/chat/completions", data={
    "model": "your-model",
    "messages": json.dumps([{"role": "user", "content": "Tell me more about it."}]),
    "session_id": session_id,
    "agent_type": "auto"
}, headers=headers, timeout=300.0)

# Chat with file upload
with open("data.csv", "rb") as f:
    r = httpx.post(f"{BASE_URL}/v1/chat/completions", data={
        "model": "your-model",
        "messages": json.dumps([{"role": "user", "content": "Analyze this CSV file"}]),
        "agent_type": "react"
    }, files=[("files", ("data.csv", f, "text/csv"))],
    headers=headers, timeout=300.0)
```

### Streaming

```python
with httpx.stream("POST", f"{BASE_URL}/v1/chat/completions", data={
    "model": "your-model",
    "messages": json.dumps([{"role": "user", "content": "Write a poem"}]),
    "stream": "true"
}, headers=headers, timeout=300.0) as response:
    for line in response.iter_lines():
        if line.startswith("data: ") and line != "data: [DONE]":
            chunk = json.loads(line[6:])
            content = chunk["choices"][0]["delta"].get("content", "")
            print(content, end="", flush=True)
```

### cURL

```bash
# Login
TOKEN=$(curl -s http://localhost:10007/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"administrator"}' | jq -r .access_token)

# Chat
curl http://localhost:10007/v1/chat/completions \
  -H "Authorization: Bearer $TOKEN" \
  -F "model=your-model" \
  -F 'messages=[{"role":"user","content":"Hello!"}]' \
  -F "agent_type=auto"
```

See `use_cases/API_examples.ipynb` for more comprehensive examples.

## RAG (Retrieval Augmented Generation)

The RAG system supports document upload, indexing, and semantic retrieval.

### Supported Formats

`.txt`, `.pdf`, `.docx`, `.xlsx`, `.xls`, `.md`, `.json`, `.csv`

### Basic vs Enhanced Mode

The system automatically selects `EnhancedRAGTool` when any of these are enabled in `config.py`:

- `RAG_USE_HYBRID_SEARCH = True` — Dense (FAISS) + sparse (BM25) retrieval with Reciprocal Rank Fusion
- `RAG_USE_RERANKING = True` — Two-stage retrieval with cross-encoder reranking
- `RAG_CHUNKING_STRATEGY = "semantic"` — Semantic chunking instead of fixed-size

Otherwise, the basic `BaseRAGTool` with pure FAISS similarity search is used.

### Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `RAG_EMBEDDING_MODEL` | — | Path or name of the embedding model (e.g. `BAAI/bge-m3`) |
| `RAG_EMBEDDING_DEVICE` | `"cuda"` | Device for embeddings (`"cuda"` or `"cpu"`) |
| `RAG_CHUNK_SIZE` | `512` | Characters per chunk |
| `RAG_CHUNK_OVERLAP` | `50` | Overlap between chunks |
| `RAG_CHUNKING_STRATEGY` | `"semantic"` | `"fixed"`, `"semantic"`, `"recursive"`, or `"sentence"` |
| `RAG_INDEX_TYPE` | `"Flat"` | FAISS index type: `"Flat"`, `"IVF"`, or `"HNSW"` |
| `RAG_MIN_SCORE_THRESHOLD` | `0.5` | Minimum similarity score (0.0–1.0) |
| `RAG_USE_HYBRID_SEARCH` | `True` | Enable BM25 + FAISS hybrid search |
| `RAG_USE_RERANKING` | `True` | Enable cross-encoder reranking |
| `RAG_USE_MULTI_QUERY` | `True` | Generate multiple query variants for better recall |
| `RAG_MULTI_QUERY_COUNT` | `6` | Number of query variants |

## Adding New Tools

1. Create the tool implementation in `tools/{tool_name}/tool.py` returning:
   ```python
   {"success": bool, "answer": str, "data": dict, "metadata": dict}
   ```

2. Add the tool schema to `tools_config.py` in the `TOOL_SCHEMAS` dict

3. Add an API endpoint in `backend/api/routes/tools.py`

4. Add parameter parsing in `backend/agents/react_agent.py` → `_convert_string_to_params()`

5. Update `config.py`:
   - Add to `AVAILABLE_TOOLS`
   - Add to `TOOL_MODELS` and `TOOL_PARAMETERS`

## Project Structure

```
LLM_API/
├── backend/
│   ├── agents/                # Agent implementations
│   │   ├── base_agent.py      # Base class (call_tool, load_prompt, history formatting)
│   │   ├── chat_agent.py      # Simple chat (no tools)
│   │   ├── react_agent.py     # ReAct loop agent
│   │   ├── plan_execute_agent.py  # Plan & Execute agent
│   │   ├── ultrawork_agent.py # Iterative OpenCode agent
│   │   └── auto_agent.py      # Smart routing agent
│   ├── api/
│   │   ├── app.py             # FastAPI application factory
│   │   └── routes/            # Endpoint handlers
│   ├── core/
│   │   ├── llm_backend.py     # LLM backend abstraction
│   │   ├── llm_interceptor.py # Request/response logging
│   │   └── database.py        # SQLite operations
│   ├── models/
│   │   └── schemas.py         # Pydantic models
│   └── utils/
│       ├── auth.py            # JWT utilities
│       ├── file_handler.py    # File upload & metadata extraction
│       └── conversation_store.py  # JSON conversation persistence
├── tools/
│   ├── web_search/tool.py     # Tavily web search
│   ├── python_coder/          # Code execution (native / OpenCode)
│   └── rag/                   # FAISS retrieval (basic / enhanced)
├── prompts/
│   ├── agents/                # Agent system prompts
│   └── tools/                 # Tool-specific prompts
├── data/                      # Runtime data (gitignored)
│   ├── app.db                 # SQLite database
│   ├── sessions/              # Conversation JSON files
│   ├── uploads/               # User file uploads
│   ├── scratch/               # Session temp files
│   ├── rag_documents/         # RAG document storage
│   ├── rag_indices/           # FAISS indices
│   ├── rag_metadata/          # RAG metadata
│   └── logs/                  # LLM interaction logs
├── tests/                     # Test scripts
├── use_cases/                 # Demo notebooks and docs
├── config.py                  # Centralized configuration
├── tools_config.py            # Tool schemas for LLM
├── tools_server.py            # Tools server entry point
├── run_backend.py             # Main server entry point
└── requirements.txt           # Python dependencies
```

## Utility Scripts

```bash
python create_users.py          # Batch create users
python create_user_direct.py    # Create a single user directly in DB
python clear_data.py            # Clear sessions, uploads, scratch, logs
python clear_rag_data.py        # Clear RAG indices, documents, metadata
```

## Testing

```bash
# RAG tool tests (no servers needed)
python tests/test_rag.py

# RAG upload performance tests
python tests/test_rag_upload_performance.py
```

Tests use `requests` against `http://localhost:10007` and clean up after themselves.

## Configuration Reference

<details>
<summary>Full configuration table</summary>

| Category | Variable | Default | Description |
|----------|----------|---------|-------------|
| **Server** | `SERVER_HOST` | `"0.0.0.0"` | Bind address |
| | `SERVER_PORT` | `10007` | Main API port |
| | `TOOLS_PORT` | `10006` | Tools API port |
| | `SERVER_WORKERS` | `4` | Main server workers |
| | `TOOLS_SERVER_WORKERS` | `4` | Tools server workers |
| **LLM** | `LLM_BACKEND` | `"llamacpp"` | `"ollama"`, `"llamacpp"`, or `"auto"` |
| | `OLLAMA_HOST` | `"http://localhost:11434"` | Ollama server URL |
| | `OLLAMA_MODEL` | — | Default Ollama model |
| | `LLAMACPP_HOST` | `"http://localhost:5904"` | llama.cpp server URL |
| | `DEFAULT_TEMPERATURE` | `0.7` | Sampling temperature |
| | `DEFAULT_MAX_TOKENS` | `128000` | Max output tokens |
| | `PRELOAD_MODEL_ON_STARTUP` | `False` | Preload model at start |
| **Auth** | `JWT_SECRET_KEY` | — | JWT signing key |
| | `JWT_EXPIRATION_HOURS` | `168` | Token expiry (7 days) |
| | `DEFAULT_ADMIN_USERNAME` | `"admin"` | Default admin user |
| | `DEFAULT_ADMIN_PASSWORD` | `"administrator"` | Default admin password |
| **Agent** | `DEFAULT_AGENT` | `"auto"` | Default agent type |
| | `REACT_MAX_ITERATIONS` | `5` | Max ReAct loop iterations |
| | `PLAN_MAX_STEPS` | `5` | Max planning steps |
| | `ULTRAWORK_MAX_ITERATIONS` | `5` | Max Ultrawork iterations |
| **Tools** | `DEFAULT_TOOL_TIMEOUT` | `864000` | Tool timeout (10 days) |
| | `TAVILY_API_KEY` | — | Tavily web search API key |
| | `TAVILY_SEARCH_DEPTH` | `"advanced"` | `"basic"` or `"advanced"` |
| | `PYTHON_EXECUTOR_MODE` | `"opencode"` | `"native"` or `"opencode"` |
| | `PYTHON_CODER_SMART_EDIT` | `True` | LLM-based code merging |
| **RAG** | `RAG_EMBEDDING_MODEL` | — | Embedding model path |
| | `RAG_EMBEDDING_DEVICE` | `"cuda"` | `"cuda"` or `"cpu"` |
| | `RAG_CHUNK_SIZE` | `512` | Chunk size in characters |
| | `RAG_INDEX_TYPE` | `"Flat"` | `"Flat"`, `"IVF"`, `"HNSW"` |
| | `RAG_USE_HYBRID_SEARCH` | `True` | BM25 + FAISS hybrid |
| | `RAG_USE_RERANKING` | `True` | Cross-encoder reranking |
| | `RAG_MIN_SCORE_THRESHOLD` | `0.5` | Minimum similarity score |
| **Storage** | `MAX_FILE_SIZE_MB` | `100` | Max upload size |
| | `MAX_CONVERSATION_HISTORY` | `50` | Max messages per session |
| | `DATABASE_PATH` | `"data/app.db"` | SQLite database path |

</details>

## Important Notes

- **Start order matters** — Always start the tools server (`tools_server.py`) before the main server (`run_backend.py`)
- **Streaming disables tools** — `stream=true` bypasses the agent system entirely; use non-streaming mode for tool calling
- **File storage** — The entire `data/` directory is gitignored and created at runtime
- **Password limits** — Bcrypt has a 72-byte limit (not 72 characters; emoji and CJK characters use multiple bytes)
- **Conversation history** — Capped at 50 messages per session by default
