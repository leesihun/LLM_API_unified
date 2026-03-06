#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM API Server Launcher
Single server: chat, auth, tools — all on one port.
"""

import sys
from pathlib import Path

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

import config


def main():
    import uvicorn

    print("=" * 70)
    print("LLM API Server")
    print("=" * 70)
    print(f"  Host:    {config.SERVER_HOST}")
    print(f"  Port:    {config.SERVER_PORT}")
    print(f"  Workers: {config.SERVER_WORKERS}")
    print(f"  Backend: llama.cpp @ {config.LLAMACPP_HOST}")
    print("=" * 70)
    print()

    app_import = "backend.api.app:app"
    if config.SERVER_WORKERS > 1:
        uvicorn.run(
            app_import,
            host=config.SERVER_HOST,
            port=config.SERVER_PORT,
            workers=config.SERVER_WORKERS,
            timeout_keep_alive=3600,
            timeout_graceful_shutdown=300,
            log_level=config.LOG_LEVEL.lower(),
        )
    else:
        from backend.api.app import app
        uvicorn.run(
            app,
            host=config.SERVER_HOST,
            port=config.SERVER_PORT,
            timeout_keep_alive=3600,
            timeout_graceful_shutdown=300,
            log_level=config.LOG_LEVEL.lower(),
        )


if __name__ == "__main__":
    main()
