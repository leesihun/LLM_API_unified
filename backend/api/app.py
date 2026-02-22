"""
Main FastAPI application — single server for chat, auth, tools, and sessions.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import config
from backend.api.routes import auth, models, admin, chat, sessions, tools

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


@app.on_event("startup")
async def startup_event():
    from backend.utils.stop_signal import clear_stop
    clear_stop()

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


@app.get("/health")
async def health():
    from backend.core.llm_backend import llm_backend
    available = await llm_backend.is_available()
    return {
        "status": "healthy",
        "llm_backend": "available" if available else "unavailable",
        "database": "connected",
    }


# Routes
app.include_router(auth.router)      # /api/auth/*
app.include_router(models.router)    # /v1/models
app.include_router(admin.router)     # /api/admin/*
app.include_router(chat.router)      # /v1/chat/completions
app.include_router(sessions.router)  # /api/chat/sessions, /api/chat/history
app.include_router(tools.router)     # /api/tools/*


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"error": {"message": str(exc), "type": "internal_error"}},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.SERVER_HOST, port=config.SERVER_PORT, log_level=config.LOG_LEVEL.lower())
