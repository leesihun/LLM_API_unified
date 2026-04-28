"""
LLM API Configuration
All settings are configurable here.
Single server, llama.cpp backend, native tool calling.
"""
import os
from pathlib import Path
from typing import Literal

# ============================================================================
# Server Settings
# ============================================================================
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 10007
SERVER_WORKERS = 2
LOG_LEVEL = "INFO"

# ============================================================================
# llama.cpp Backend
# ============================================================================
LLAMACPP_HOST = "http://localhost:5905"
LLAMACPP_MODEL = "default"
OPENCODE_MODEL: str = "llama.cpp/MiniMax"  # "provider/model" format (e.g., "llama.cpp/default", "opencode/minimax-m2.5-free")

# ============================================================================
# Model Parameters (Default LLM Inference Settings)
# ============================================================================
DEFAULT_TEMPERATURE = 1.0  # 0.7
DEFAULT_TOP_P = 0.95
DEFAULT_TOP_K = 40
DEFAULT_MIN_P = 0.1
DEFAULT_MAX_TOKENS = 8192
DEFAULT_REPEAT_PENALTY = 1

# ============================================================================
# llama.cpp Performance Tuning
# ============================================================================
# cache_prompt: tell llama.cpp to reuse KV cache for shared prompt prefixes
# (biggest speedup for agent loops where system prompt + tool schemas are identical)
LLAMACPP_CACHE_PROMPT = True
# Connection pool size for persistent HTTP connections to llama.cpp
LLAMACPP_CONNECTION_POOL_SIZE = 20
# Number of parallel slots on llama.cpp server (for id_slot session pinning)
LLAMACPP_SLOTS = 2

# ============================================================================
# Logging Settings (before Agent — agent log target references PROMPTS_LOG_PATH)
# ============================================================================
LOG_DIR = Path("data/logs")
PROMPTS_LOG_PATH = LOG_DIR / "prompts.log"
# Oldest lines are dropped when the file would exceed this (see prompts_log_append).
PROMPTS_LOG_MAX_LINES = 10_000

# ============================================================================
# Agent Settings
# ============================================================================
AGENT_MAX_ITERATIONS = 300
AGENT_TOOL_LOOP_MAX_TOKENS = 4096
AGENT_SYSTEM_PROMPT = "system.txt"
AGENT_DYNAMIC_CONTEXT_MAX_CHARS = 6000
AGENT_MEMO_MAX_CHARS = 2000
AGENT_FILE_PREVIEW_MAX_CHARS = 120
AGENT_OLD_TOOL_RESULT_SUMMARY_MAX_CHARS = 500
AGENT_COMPACTION_WARM_WINDOW = 4  # keep this many previous iterations uncompressed
AGENT_LOG_VERBOSITY: Literal["off", "summary", "debug"] = "summary"
# True = offload log writes to thread pool (non-blocking, recommended for production).
AGENT_LOG_ASYNC = True
# Same file as LLM interceptor + tools: one combined prompts.log (set to another Path to split).
AGENT_LOG_PATH = PROMPTS_LOG_PATH

# ============================================================================
# Database Settings
# ============================================================================
DATABASE_PATH = "data/app.db"

# ============================================================================
# Authentication Settings
# ============================================================================
# Set JWT_SECRET_KEY environment variable in production. The fallback is only for local dev.
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "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")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24 * 7

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "administrator"

# ============================================================================
# File Storage Settings
# ============================================================================
UPLOAD_DIR = Path("data/uploads")
SCRATCH_DIR = Path("data/scratch")
MAX_FILE_SIZE_MB = 100
IMAGE_SUPPORTED_FORMATS = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"]
IMAGE_MAX_SIZE_MB = 20
IMAGE_MAX_DIMENSION = 4096  # resize if either side exceeds this (saves context tokens)

# ============================================================================
# Prompts Settings
# ============================================================================
PROMPTS_DIR = Path("prompts")

# ============================================================================
# Stop Signal Settings
# ============================================================================
STOP_FILE = Path("data/STOP")

# ============================================================================
# Tools Settings
# ============================================================================
AVAILABLE_TOOLS = [
    "websearch",
    "code_exec",       # Direct code execution — no second LLM call (prefer over python_coder)
    "python_coder",    # Instruction-driven — makes a second LLM call to generate code
    "rag",
    "file_reader",
    "file_writer",
    "file_navigator",
    "shell_exec",
    "process_monitor",
    "memo",
]

TOOL_PARAMETERS = {
    "websearch": {
        "temperature": 0.7,
        "max_tokens": 30000,
        "timeout": 864000,
    },
    "code_exec": {
        "temperature": 1.0,
        "max_tokens": 8000,
        "timeout": 864000,
    },
    "python_coder": {
        "temperature": 1.0,
    },
    "rag": {
        "temperature": 0.2,
        "max_tokens": 30000,
        "timeout": 864000,
    },
    "file_reader": {
        "temperature": 0.3,
        "max_tokens": 8000,
        "timeout": 60,
    },
    "file_writer": {
        "temperature": 0.3,
        "max_tokens": 8000,
        "timeout": 60,
    },
    "file_navigator": {
        "temperature": 0.3,
        "max_tokens": 4000,
        "timeout": 30,
    },
    "shell_exec": {
        "temperature": 0.7,
        "max_tokens": 8000,
        "timeout": 864000,
    },
    "process_monitor": {
        "temperature": 0.3,
        "max_tokens": 4000,
        "timeout": 30,
    },
    "memo": {
        "temperature": 0.1,
        "max_tokens": 2000,
        "timeout": 10,
    },
}

DEFAULT_TOOL_TIMEOUT = 864000

# ============================================================================
# Microcompaction: Tool Result Budgets (chars)
# ============================================================================
TOOL_RESULT_BUDGET = {
    "websearch": 2000,
    "code_exec": 8000,
    "python_coder": 8000,
    "rag": 3000,
    "file_reader": 4000,
    "file_writer": 500,
    "file_navigator": 2000,
    "shell_exec": 3000,
    "process_monitor": 3000,
    "memo": 1000,
}
TOOL_RESULT_DEFAULT_BUDGET = 3000
TOOL_RESULTS_DIR = Path("data/tool_results")

# ============================================================================
# Web Search Tool Settings
# ============================================================================
WEBSEARCH_PROVIDER = "tavily"
TAVILY_API_KEY = "your-secret-key-change-in-production"
TAVILY_MAX_RESULTS = 5
TAVILY_SEARCH_DEPTH = "advanced"
TAVILY_INCLUDE_DOMAINS = []
TAVILY_EXCLUDE_DOMAINS = []
WEBSEARCH_MAX_RESULTS = 5

# ============================================================================
# Python Coder Tool Settings
# ============================================================================
PYTHON_EXECUTOR_MODE: Literal["native", "opencode"] = "native"

# Kept for code_exec tool and opencode fallback (subprocess caps):
PYTHON_EXECUTOR_TIMEOUT = 300
PYTHON_EXECUTOR_MAX_OUTPUT_SIZE = 1024 * 1024 * 10
PYTHON_WORKSPACE_DIR = SCRATCH_DIR

# Layered timeouts for native executor:
PYTHON_GENERATION_TIMEOUT = 120      # LLM code-generation call
PYTHON_EXECUTION_TIMEOUT = 300       # per-attempt subprocess / kernel default
PYTHON_EXECUTION_TIMEOUT_MAX = 900   # ceiling when caller passes a bigger value
PYTHON_EXECUTION_IDLE_TIMEOUT = None # disabled — most scripts don't print continuously
PYTHON_TOTAL_TIMEOUT = 600           # wall-clock cap: gen + exec + all retries

PYTHON_EXECUTOR_MAX_RETRIES = 1      # self-debug retries on non-zero exit

OPENCODE_PATH: str = "opencode"
OPENCODE_SERVER_PORT: int = 37254
OPENCODE_SERVER_HOST: str = "127.0.0.1"
OPENCODE_TIMEOUT: int = 864000
OPENCODE_LOG_VERBOSITY: Literal["summary", "debug"] = "summary"

PYTHON_CODER_SMART_EDIT = True

# ============================================================================
# RAG Tool Settings
# ============================================================================
RAG_DOCUMENTS_DIR = Path("data/rag_documents")
RAG_INDEX_DIR = Path("data/rag_indices")
RAG_METADATA_DIR = Path("data/rag_metadata")

RAG_EMBEDDING_MODEL = "/scratch0/LLM_models/offline_models/bge-m3"
RAG_EMBEDDING_DEVICE = "cuda"
RAG_EMBEDDING_BATCH_SIZE = 16

RAG_INDEX_TYPE = "Flat"
RAG_SIMILARITY_METRIC = "cosine"

RAG_CHUNK_SIZE = 512
RAG_CHUNK_OVERLAP = 50
RAG_CHUNKING_STRATEGY = "semantic"
RAG_MAX_RESULTS = 10
RAG_MIN_SCORE_THRESHOLD = 0.5
RAG_CONTEXT_WINDOW = 1

RAG_USE_HYBRID_SEARCH = True
RAG_HYBRID_ALPHA = 0.5

RAG_USE_RERANKING = True
RAG_RERANKER_MODEL = "/scratch0/LLM_models/offline_models/mmarco-mMiniLMv2-L12-H384-v1"
RAG_RERANKING_TOP_K = 20

RAG_QUERY_PREFIX = ""

RAG_DEFAULT_COLLECTION = "default"
RAG_SUPPORTED_FORMATS = [".txt", ".pdf", ".docx", ".xlsx", ".xls", ".md", ".json", ".csv"]

# ============================================================================
# Process Monitor Tool Settings
# ============================================================================
PROCESS_MONITOR_MAX_BUFFER_LINES = 5000
PROCESS_MONITOR_MAX_PER_SESSION = 20

# ============================================================================
# Shell Exec Tool Settings
# ============================================================================
# True = kill the process when shell_exec timeout is reached (prevents orphan processes).
# False = legacy behaviour: return partial output, leave process running.
SHELL_EXEC_KILL_ON_TIMEOUT = True

# ============================================================================
# Memo Tool Settings
# ============================================================================
MEMO_DIR = Path("data/memory")
MEMO_MAX_ENTRIES = 100
MEMO_MAX_VALUE_LENGTH = 1000

# ============================================================================
# Background Jobs Settings
# ============================================================================
JOBS_DIR = Path("data/jobs")
JOBS_CLEANUP_DAYS = 30

# ============================================================================
# Session Settings
# ============================================================================
MAX_CONVERSATION_HISTORY = 50
SESSION_CLEANUP_DAYS = 7

# ============================================================================
# Cleanup Settings (data retention — 2-week rolling window)
# ============================================================================
SCRATCH_CLEANUP_DAYS = 14       # data/scratch/{session_id}/ dirs
TOOL_RESULTS_CLEANUP_DAYS = 14  # data/tool_results/{session_id}/ dirs
LOG_ROTATION_DAYS = 14          # rotate data/logs/prompts.log after N days

# ============================================================================
# LLM File Write Policy
# ============================================================================
LLM_GENERATED_DIR = Path("data/llm_generated")   # dedicated dir for LLM absolute-path writes
LLM_FILE_RETENTION_DAYS = 3                        # auto-delete files older than N days (0 = disabled)
ALLOWED_WRITE_DIRS: list[Path] = []  # empty = allow all absolute paths

# ============================================================================
# Streaming Settings
# ============================================================================
STREAM_CHUNK_SIZE = 1
STREAM_TIMEOUT = 600

# ============================================================================
# CORS Settings
# ============================================================================
CORS_ORIGINS = [
    "http://localhost:10007",
    "http://127.0.0.1:10007",
    "*",
]

# ============================================================================
# Ensure directories exist
# ============================================================================
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
RAG_DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
RAG_INDEX_DIR.mkdir(parents=True, exist_ok=True)
RAG_METADATA_DIR.mkdir(parents=True, exist_ok=True)
TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
MEMO_DIR.mkdir(parents=True, exist_ok=True)
JOBS_DIR.mkdir(parents=True, exist_ok=True)
LLM_GENERATED_DIR.mkdir(parents=True, exist_ok=True)
