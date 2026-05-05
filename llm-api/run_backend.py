#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM API Server Launcher
Single server: chat, auth, tools — all on one port.
"""

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# PyTorch CUDA allocator tuning — MUST be set before any `import torch`.
# expandable_segments lets the allocator grow a single contiguous segment
# instead of reserving many disjoint fixed-size blocks.  This alone drops
# steady-state reserved memory by 30-60% and keeps it bounded, eliminating
# the "nvidia-smi keeps climbing" symptom caused by allocator fragmentation.
# Requires PyTorch 2.1+.  No latency cost.
# ---------------------------------------------------------------------------
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

import config


def main():
    import uvicorn
    effective_workers = config.SERVER_WORKERS

    # Windows launches can fail when uvicorn tries to fan out workers via
    # multiprocessing. Keep the normal config value, but run single-worker
    # locally so the standard startup path still works.
    if sys.platform == "win32" and effective_workers > 1:
        print("[Startup] Windows detected; forcing SERVER_WORKERS=1 for compatibility.")
        effective_workers = 1

    print("=" * 70)
    print("LLM API Server")
    print("=" * 70)
    print(f"  Host:    {config.SERVER_HOST}")
    print(f"  Port:    {config.SERVER_PORT}")
    print(f"  Workers: {effective_workers}")
    print(f"  Backend: llama.cpp @ {config.LLAMACPP_HOST}")
    print("=" * 70)
    print()

    app_import = "backend.api.app:app"
    if effective_workers > 1:
        uvicorn.run(
            app_import,
            host=config.SERVER_HOST,
            port=config.SERVER_PORT,
            workers=effective_workers,
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
