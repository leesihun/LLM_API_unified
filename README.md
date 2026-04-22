# LLM API Fast

A self-hosted, OpenAI-compatible LLM API server built on **llama.cpp** with a full agentic loop, JWT authentication, RAG, and 10 built-in tools. Drop-in replacement for the OpenAI `/v1/chat/completions` endpoint.

---

## Features

- **OpenAI-compatible API** — works with any client that speaks the OpenAI chat format
- **Streaming** — real-time token streaming + tool status events over SSE
- **Agentic loop** — automatic multi-step tool use until the LLM produces a final answer
- **Parallel tool execution** — multiple tool calls in one iteration run concurrently
- **Prompt caching** — llama.cpp KV cache reuse for fast repeated requests
- **JWT authentication** — per-user sessions and conversation history
- **RAG** — FAISS vector search with hybrid BM25 + dense retrieval and cross-encoder reranking
- **10 built-in tools**: web search, code execution, Python coder, RAG, file reader/writer/navigator, shell, memo, process monitor
- **Background jobs** — long-running agent tasks with SSE progress streaming
- **Microcompaction** — compresses old context to stay within token limits automatically

---

## Requirements

- Python 3.10+
- [llama.cpp](https://github.com/ggerganov/llama.cpp) server (`llama-server`) running separately
- CUDA GPU recommended for RAG embeddings (CPU works but is slow)
- [Tavily API key](https://tavily.com/) for the web search tool (optional)

---

## Installation

```bash
git clone <repo>
cd LLM_API_fast

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

# PyTorch with CUDA (for RAG GPU embeddings) — pick your CUDA version:
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

---

## Quick Start

### 1. Start llama.cpp

```bash
llama-server \
  --model /path/to/model.gguf \
  --port 5905 \
  --parallel 4 \
  --ctx-size 32768 \
  --jinja \
  --cont-batching
```

### 2. Configure

Edit [`config.py`](config.py) — all settings are in one place:

```python
LLAMACPP_HOST = "http://localhost:5905"   # llama.cpp URL
TAVILY_API_KEY = "tvly-..."               # web search (set or remove from AVAILABLE_TOOLS)
RAG_EMBEDDING_MODEL = "/path/to/bge-m3"  # local embedding model
RAG_EMBEDDING_DEVICE = "cuda"            # "cuda" or "cpu"
```

Set `JWT_SECRET_KEY` as an environment variable in production:
```bash
export JWT_SECRET_KEY="your-long-random-secret"
```

### 3. Start the server

```bash
python run_backend.py
# → http://0.0.0.0:10007
# → Swagger docs: http://localhost:10007/docs
```

Default admin: `admin` / `administrator`

---

## Configuration Reference

Key settings in [`config.py`](config.py):

| Setting | Default | Description |
|---|---|---|
| `SERVER_PORT` | `10007` | API listen port |
| `LLAMACPP_HOST` | `http://localhost:5905` | llama.cpp server URL |
| `LLAMACPP_SLOTS` | `4` | Parallel KV cache slots |
| `AVAILABLE_TOOLS` | (all 10) | Remove tools you don't want |
| `PYTHON_EXECUTOR_MODE` | `"opencode"` | `"native"` or `"opencode"` |
| `RAG_EMBEDDING_MODEL` | `/scratch0/.../bge-m3` | Path to SentenceTransformer model |
| `RAG_USE_HYBRID_SEARCH` | `True` | BM25 + dense retrieval |
| `RAG_USE_RERANKING` | `True` | Cross-encoder reranking |
| `AGENT_MAX_ITERATIONS` | `60` | Max tool-call loops per request |
| `AGENT_LOG_VERBOSITY` | `"summary"` | `"off"` / `"summary"` / `"debug"` |
| `MAX_CONVERSATION_HISTORY` | `50` | Messages kept per session |
| `TAVILY_API_KEY` | *(change this)* | Required for websearch tool |

---

## API Usage

### Chat (OpenAI-compatible)

```bash
# Non-streaming
curl http://localhost:10007/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "default",
    "messages": [{"role": "user", "content": "What is the capital of France?"}]
  }'

# Streaming
curl http://localhost:10007/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "default",
    "stream": true,
    "messages": [{"role": "user", "content": "Search the web for latest AI news"}]
  }'
```

### Authentication

```bash
# Login
TOKEN=$(curl -s -X POST http://localhost:10007/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"administrator"}' | jq -r .access_token)

# Use token
curl http://localhost:10007/api/chat/sessions \
  -H "Authorization: Bearer $TOKEN"
```

### RAG Upload

```bash
# Upload a document to a collection
curl -X POST http://localhost:10007/api/rag/upload/stream \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@report.pdf" \
  -F "collection_name=my-docs"
```

---

## Built-in Tools

| Tool | Description |
|---|---|
| `websearch` | Web search via Tavily API |
| `code_exec` | Execute Python code directly (no second LLM call) |
| `python_coder` | Instruction → LLM generates code → executes it |
| `rag` | Semantic search over user-uploaded document collections |
| `file_reader` | Read files with optional offset/limit |
| `file_writer` | Write or append to files |
| `file_navigator` | List directories, glob search, directory tree |
| `shell_exec` | Run shell commands with timeout |
| `memo` | Persistent key-value memory per user (survives sessions) |
| `process_monitor` | Start, stream, and kill long-running background processes |

---

## Deployment: Farm + Hub

For multi-GPU setups, use the hub+farm architecture:

**Hub** (runs llama.cpp + Messenger chat platform):
```bash
LLAMACPP_MODEL_PATH=/models/llm.gguf bash start-hub.sh
```

**Farm nodes** (each runs the LLM API, points to the hub's llama.cpp):
```bash
HUB_HOST=10.0.0.5 FARM_ID=gpu01 FARM_PUBLIC_HOST=10.0.0.10 bash start-farm.sh
```

For airgapped Linux servers, use `gather-llamacpp.sh` on an internet-connected machine to create an offline bundle, then `install-llamacpp.sh` to install it.

---

## Development Utilities

```bash
# Clear logs, scratch, and session data
python clear_data.py

# Clear RAG indices (required when changing embedding models)
python clear_rag_data.py --all
python clear_rag_data.py --user admin

# Create test users
python create_users.py           # via API (server must be running)
python create_user_direct.py     # directly in DB

# Stop/resume inference without restarting the server
python stop_inference.py stop
python stop_inference.py clear
python stop_inference.py status
```

---

## Data Directory

All runtime data is stored under `data/` (not committed to git):

```
data/
├── app.db              # SQLite: users, sessions
├── logs/prompts.log    # Full LLM + agent + tool call log
├── sessions/           # Conversation history (JSONL per session)
├── uploads/            # User file uploads
├── scratch/            # Code execution sandboxes
├── rag_documents/      # RAG source files
├── rag_indices/        # FAISS index files
├── rag_metadata/       # Collection metadata
├── memory/             # Memo tool (per-user JSON)
└── jobs/               # Background job state
```

---

## License

Internal use. See repository owner for licensing terms.
