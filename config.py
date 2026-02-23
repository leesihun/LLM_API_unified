"""
LLM API Configuration
All settings are configurable here.
Single server, llama.cpp backend, native tool calling.
"""
from pathlib import Path
from typing import Literal

# ============================================================================
# Server Settings
# ============================================================================
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 10007
SERVER_WORKERS = 4
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
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TOP_P = 0.9
DEFAULT_TOP_K = 40
DEFAULT_MAX_TOKENS = 128000

# ============================================================================
# Agent Settings
# ============================================================================
AGENT_MAX_ITERATIONS = 8
AGENT_SYSTEM_PROMPT = "system.txt"

# ============================================================================
# Database Settings
# ============================================================================
DATABASE_PATH = "data/app.db"

# ============================================================================
# Authentication Settings
# ============================================================================
JWT_SECRET_KEY = "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"
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

# ============================================================================
# Prompts Settings
# ============================================================================
PROMPTS_DIR = Path("prompts")

# ============================================================================
# Logging Settings
# ============================================================================
LOG_DIR = Path("data/logs")
PROMPTS_LOG_PATH = LOG_DIR / "prompts.log"

# ============================================================================
# Stop Signal Settings
# ============================================================================
STOP_FILE = Path("data/STOP")

# ============================================================================
# Tools Settings
# ============================================================================
AVAILABLE_TOOLS = [
    "websearch",
    "python_coder",
    "rag",
    "file_reader",
    "file_writer",
    "file_navigator",
    "shell_exec",
    "memory",
]

TOOL_PARAMETERS = {
    "websearch": {
        "temperature": 0.7,
        "max_tokens": 30000,
        "timeout": 864000,
    },
    "python_coder": {
        "temperature": 1.0,
        "max_tokens": 128000,
        "timeout": 864000,
    },
    "rag": {
        "temperature": 0.2,
        "max_tokens": 30000,
        "timeout": 864000,
    },
}

DEFAULT_TOOL_TIMEOUT = 864000

# ============================================================================
# Microcompaction: Tool Result Budgets (chars)
# ============================================================================
TOOL_RESULT_BUDGET = {
    "websearch": 2000,
    "python_coder": 5000,
    "rag": 3000,
    "file_reader": 4000,
    "file_writer": 500,
    "file_navigator": 2000,
    "shell_exec": 3000,
    "memory": 500,
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
PYTHON_EXECUTOR_MODE: Literal["native", "opencode"] = "opencode"

PYTHON_EXECUTOR_TIMEOUT = 864000
PYTHON_EXECUTOR_MAX_OUTPUT_SIZE = 1024 * 1024 * 10
PYTHON_WORKSPACE_DIR = SCRATCH_DIR
PYTHON_CODER_TIMEOUT = 864000

OPENCODE_PATH: str = "opencode"
OPENCODE_SERVER_PORT: int = 37254
OPENCODE_SERVER_HOST: str = "127.0.0.1"
OPENCODE_TIMEOUT: int = 864000

PYTHON_CODER_SMART_EDIT = True

# ============================================================================
# RAG Tool Settings
# ============================================================================
RAG_DOCUMENTS_DIR = Path("data/rag_documents")
RAG_INDEX_DIR = Path("data/rag_indices")
RAG_METADATA_DIR = Path("data/rag_metadata")

RAG_EMBEDDING_MODEL = "/scratch0/LLM_models/offline_models/bge-m3"
RAG_EMBEDDING_DEVICE = "cpu"
RAG_EMBEDDING_BATCH_SIZE = 16

RAG_INDEX_TYPE = "Flat"
RAG_SIMILARITY_METRIC = "cosine"

RAG_CHUNK_SIZE = 512
RAG_CHUNK_OVERLAP = 50
RAG_CHUNKING_STRATEGY = "semantic"
RAG_MAX_RESULTS = 100
RAG_MIN_SCORE_THRESHOLD = 0.5
RAG_CONTEXT_WINDOW = 1

RAG_USE_HYBRID_SEARCH = True
RAG_HYBRID_ALPHA = 0.5

RAG_USE_RERANKING = True
RAG_RERANKER_MODEL = "/scratch0/LLM_models/offline_models/mmarco-mMiniLMv2-L12-H384-v1"
RAG_RERANKING_TOP_K = 500

RAG_QUERY_PREFIX = ""
RAG_USE_MULTI_QUERY = True
RAG_MULTI_QUERY_COUNT = 6
RAG_QUERY_EXPANSION = False

RAG_DEFAULT_COLLECTION = "default"
RAG_SUPPORTED_FORMATS = [".txt", ".pdf", ".docx", ".xlsx", ".xls", ".md", ".json", ".csv"]

# ============================================================================
# Session Settings
# ============================================================================
MAX_CONVERSATION_HISTORY = 50
SESSION_CLEANUP_DAYS = 7

# ============================================================================
# Streaming Settings
# ============================================================================
STREAM_CHUNK_SIZE = 1
STREAM_TIMEOUT = 864000

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
