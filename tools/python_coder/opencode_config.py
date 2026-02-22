"""
OpenCode Configuration Generator
Generates opencode config.json based on config.py settings (llama.cpp only)
"""
import json
import sys
from pathlib import Path

import config


def get_opencode_config_path() -> Path:
    return Path.home() / ".config" / "opencode" / "config.json"


def generate_opencode_config() -> Path:
    config_path = get_opencode_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    llamacpp_base = config.LLAMACPP_HOST.rstrip("/")
    if not llamacpp_base.endswith("/v1"):
        llamacpp_base = f"{llamacpp_base}/v1"

    opencode_config = {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "llama.cpp": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "llama.cpp",
                "options": {
                    "baseURL": llamacpp_base
                },
                "models": {
                    config.LLAMACPP_MODEL: {
                        "name": config.LLAMACPP_MODEL
                    }
                },
            }
        },
    }

    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(opencode_config, f, indent=2)

    print(f"[OPENCODE] Config generated: {config_path}")
    return config_path


def ensure_opencode_config() -> Path:
    return generate_opencode_config()
