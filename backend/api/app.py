"""
Main FastAPI application — single server for chat, auth, tools, and sessions.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import json
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import config
from backend.api.routes import auth, models, admin, chat, sessions, tools, jobs

_START_TIME = time.time()

app = FastAPI(
    title="LLM API",
    description="OpenAI-compatible LLM API with native tool calling via llama.cpp",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _cleanup_old_sessions():
    """Delete session JSON files older than SESSION_CLEANUP_DAYS."""
    sessions_dir = Path("data/sessions")
    if not sessions_dir.exists():
        return
    cutoff = datetime.now() - timedelta(days=config.SESSION_CLEANUP_DAYS)
    removed = 0
    for f in sessions_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            updated = datetime.fromisoformat(data.get("updated_at", ""))
            if updated < cutoff:
                f.unlink()
                removed += 1
        except Exception:
            pass
    if removed:
        print(f"[Startup] Cleaned up {removed} old session file(s)")


def _cleanup_old_jobs():
    """Delete job JSON files older than JOBS_CLEANUP_DAYS."""
    jobs_dir = config.JOBS_DIR
    if not jobs_dir.exists():
        return
    cutoff = datetime.now() - timedelta(days=config.JOBS_CLEANUP_DAYS)
    removed = 0
    for f in jobs_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(data.get("created_at", ""))
            if created < cutoff:
                f.unlink()
                lock = f.with_suffix(".lock")
                if lock.exists():
                    lock.unlink()
                removed += 1
        except Exception:
            pass
    if removed:
        print(f"[Startup] Cleaned up {removed} old job file(s)")


@app.on_event("startup")
async def startup_event():
    from backend.utils.stop_signal import clear_stop
    clear_stop()

    _cleanup_old_sessions()
    _cleanup_old_jobs()

    from backend.core.llm_backend import llm_backend
    available = await llm_backend.is_available()
    if available:
        print(f"[Startup] llama.cpp backend available at {config.LLAMACPP_HOST}")
    else:
        print(f"[Startup] WARNING: llama.cpp backend NOT available at {config.LLAMACPP_HOST}")

    if config.PYTHON_EXECUTOR_MODE == "opencode":
        from tools.python_coder.opencode_server import start_opencode_server
        start_opencode_server()


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "LLM API",
        "version": "2.0.0",
        "backend": {
            "type": "llamacpp",
            "host": config.LLAMACPP_HOST,
        },
    }


async def _get_health_data() -> dict:
    from backend.core.llm_backend import llm_backend
    llamacpp_ok = await llm_backend.is_available()
    disk = shutil.disk_usage(".")
    opencode_enabled = config.PYTHON_EXECUTOR_MODE == "opencode"
    return {
        "status": "ok" if llamacpp_ok else "degraded",
        "uptime_s": round(time.time() - _START_TIME),
        "llamacpp": {
            "available": llamacpp_ok,
            "host": config.LLAMACPP_HOST,
        },
        "opencode": {
            "enabled": opencode_enabled,
            "host": f"{config.OPENCODE_SERVER_HOST}:{config.OPENCODE_SERVER_PORT}" if opencode_enabled else None,
        },
        "disk": {
            "free_gb": round(disk.free / 1e9, 1),
            "used_gb": round(disk.used / 1e9, 1),
            "total_gb": round(disk.total / 1e9, 1),
        },
        "config": {
            "agent_max_iterations": config.AGENT_MAX_ITERATIONS,
            "available_tools": config.AVAILABLE_TOOLS,
            "python_executor_mode": config.PYTHON_EXECUTOR_MODE,
        },
    }


@app.get("/health")
async def health():
    return await _get_health_data()


@app.get("/api/health")
async def api_health():
    return await _get_health_data()


# Routes
app.include_router(auth.router)      # /api/auth/*
app.include_router(models.router)    # /v1/models
app.include_router(admin.router)     # /api/admin/*
app.include_router(chat.router)      # /v1/chat/completions
app.include_router(sessions.router)  # /api/chat/sessions, /api/chat/history
app.include_router(tools.router)     # /api/tools/*
app.include_router(jobs.router)      # /api/jobs/*


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"error": {"message": str(exc), "type": "internal_error"}},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.SERVER_HOST, port=config.SERVER_PORT, log_level=config.LOG_LEVEL.lower())
