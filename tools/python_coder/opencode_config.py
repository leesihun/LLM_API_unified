"""
OpenCode Configuration Generator
Generates opencode config.json based on config.py settings.

Only writes a custom provider entry for llama.cpp when OPENCODE_MODEL
uses it. Built-in providers (opencode, minimax, anthropic, etc.) need
no config — OpenCode discovers them automatically.
"""
import json
from pathlib import Path

import config


def get_opencode_config_path() -> Path:
    return Path.home() / ".config" / "opencode" / "config.json"


def generate_opencode_config() -> Path:
    config_path = get_opencode_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    provider_id = config.OPENCODE_MODEL.split("/", 1)[0]

    opencode_config: dict = {
        "$schema": "https://opencode.ai/config.json",
        "model": config.OPENCODE_MODEL,
    }

    # llama.cpp is a custom provider — register it so OpenCode knows the baseURL
    if provider_id == "llama.cpp":
        llamacpp_base = config.LLAMACPP_HOST.rstrip("/")
        if not llamacpp_base.endswith("/v1"):
            llamacpp_base = f"{llamacpp_base}/v1"
        model_id = config.OPENCODE_MODEL.split("/", 1)[1]
        opencode_config["provider"] = {
            "llama.cpp": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "llama.cpp",
                "options": {"baseURL": llamacpp_base},
                "models": {model_id: {"name": model_id}},
            }
        }

    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(opencode_config, f, indent=2)

    print(f"[OPENCODE] Config generated: {config_path} (model: {config.OPENCODE_MODEL})")
    return config_path


def ensure_opencode_config() -> Path:
    return generate_opencode_config()
