"""
Messenger runtime configuration.

This is the single editable runtime config file for Messenger. The Node server
reads it at startup, and the launch scripts export the same values before
running npm commands. Runtime environment variables can override these defaults.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shlex
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
SERVER_DIR = APP_DIR / "server"
CLIENT_DIR = APP_DIR / "client"


def _load_cluster_config():
    path = APP_DIR.parent / "cluster_config.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("_messenger_cluster_config", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CLUSTER = _load_cluster_config()

PORT = int(os.environ.get("PORT", str(getattr(_CLUSTER, "MESSENGER_PORT", 10006))))

def _path_setting(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    path = Path(raw) if raw else default
    if not path.is_absolute():
        path = APP_DIR / path
    return path.resolve()


MESSENGER_DATA_DIR = _path_setting("MESSENGER_DATA_DIR", SERVER_DIR / "data")
MESSENGER_UPLOADS_DIR = _path_setting("MESSENGER_UPLOADS_DIR", SERVER_DIR / "uploads")
MESSENGER_CHUNKS_DIR = _path_setting("MESSENGER_CHUNKS_DIR", SERVER_DIR / "chunks")
MESSENGER_STORAGE_DIR = _path_setting("MESSENGER_STORAGE_DIR", SERVER_DIR / "storage")
MESSENGER_PUBLIC_DIR = _path_setting("MESSENGER_PUBLIC_DIR", SERVER_DIR / "public")
MESSENGER_WEB_DIR = _path_setting("MESSENGER_WEB_DIR", CLIENT_DIR / "dist-web")

SECRET_TOKEN = os.environ.get("SECRET_TOKEN", "leesihun")
WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", str(APP_DIR.parent))
CLAUDE_CMD = os.environ.get("CLAUDE_CMD", "claude")
OPENCODE_CMD = os.environ.get("OPENCODE_CMD", "opencode")
MESSENGER_EMBEDDED = os.environ.get("MESSENGER_EMBEDDED", "")
VITE_BACKEND_URL = os.environ.get("VITE_BACKEND_URL", getattr(_CLUSTER, "MESSENGER_URL", f"http://127.0.0.1:{PORT}"))

MESSENGER_LOG_FILE = _path_setting("MESSENGER_LOG_FILE", MESSENGER_DATA_DIR / "messenger.log")


def as_env() -> dict[str, str]:
    return {
        "PORT": str(PORT),
        "MESSENGER_DATA_DIR": str(MESSENGER_DATA_DIR),
        "MESSENGER_UPLOADS_DIR": str(MESSENGER_UPLOADS_DIR),
        "MESSENGER_CHUNKS_DIR": str(MESSENGER_CHUNKS_DIR),
        "MESSENGER_STORAGE_DIR": str(MESSENGER_STORAGE_DIR),
        "MESSENGER_PUBLIC_DIR": str(MESSENGER_PUBLIC_DIR),
        "MESSENGER_WEB_DIR": str(MESSENGER_WEB_DIR),
        "SECRET_TOKEN": SECRET_TOKEN,
        "WORKSPACE_DIR": WORKSPACE_DIR,
        "CLAUDE_CMD": CLAUDE_CMD,
        "OPENCODE_CMD": OPENCODE_CMD,
        "MESSENGER_EMBEDDED": MESSENGER_EMBEDDED,
        "VITE_BACKEND_URL": VITE_BACKEND_URL,
        "MESSENGER_LOG_FILE": str(MESSENGER_LOG_FILE),
    }


def ensure_dirs() -> None:
    for path in (
        MESSENGER_DATA_DIR,
        MESSENGER_UPLOADS_DIR,
        MESSENGER_CHUNKS_DIR,
        MESSENGER_STORAGE_DIR,
        MESSENGER_PUBLIC_DIR,
        MESSENGER_WEB_DIR.parent,
        MESSENGER_LOG_FILE.parent,
    ):
        path.mkdir(parents=True, exist_ok=True)


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def main() -> int:
    parser = argparse.ArgumentParser(description="Print Messenger runtime config.")
    parser.add_argument("--json", action="store_true", help="Print config as JSON.")
    parser.add_argument("--get", metavar="KEY", help="Print one config value.")
    parser.add_argument("--export", choices=("bash", "powershell"), help="Print shell export commands.")
    parser.add_argument("--ensure-dirs", action="store_true", help="Create configured runtime directories.")
    args = parser.parse_args()

    if args.ensure_dirs:
        ensure_dirs()

    env = as_env()
    if args.get:
        print(env.get(args.get, ""))
    elif args.export == "bash":
        for key, value in env.items():
            print(f"export {key}={shlex.quote(value)}")
    elif args.export == "powershell":
        for key, value in env.items():
            print(f"$env:{key} = {_powershell_quote(value)}")
    else:
        print(json.dumps(env, indent=2 if not args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
