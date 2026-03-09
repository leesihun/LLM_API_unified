"""
Entry point for the streaming proxy agent.
Run from project root: python proxy_agent/run.py
"""
import sys
from pathlib import Path

# Ensure project root is on sys.path so `proxy_agent` package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn
from proxy_agent.config import PROXY_HOST, PROXY_PORT

if __name__ == "__main__":
    uvicorn.run("proxy_agent.main:app", host=PROXY_HOST, port=PROXY_PORT)
