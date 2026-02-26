#!/usr/bin/env python3
"""
Hoonbot Setup Script

Automatically obtains LLM_API_KEY from LLM_API_fast and sets up environment variables.
"""
import sys
import json
import subprocess
import os

# Fix Windows encoding issues
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import httpx


def get_llm_api_token(llm_url: str, username: str = "admin", password: str = "administrator") -> str | None:
    """Get access token from LLM_API_fast."""
    print(f"\n[Setup] Connecting to LLM_API_fast at {llm_url}")

    try:
        response = httpx.post(
            f"{llm_url}/api/auth/login",
            json={"username": username, "password": password},
            timeout=10.0
        )
        response.raise_for_status()
        result = response.json()
        token = result.get("access_token")
        if token:
            print(f"[OK] Successfully obtained access token")
            return token
        else:
            print(f"[ERROR] Login response missing 'access_token'")
            return None
    except httpx.ConnectError:
        print(f"[ERROR] Cannot connect to LLM_API_fast")
        print(f"        Make sure it's running on {llm_url}")
        return None
    except httpx.HTTPStatusError as e:
        print(f"[ERROR] Login failed: {e.response.status_code}")
        if e.response.status_code == 401:
            print(f"        Invalid credentials (default: admin/administrator)")
        else:
            print(f"        {e.response.text}")
        return None
    except Exception as e:
        print(f"[ERROR] {e}")
        return None


def get_available_models(llm_url: str, token: str) -> list | None:
    """Get list of available models."""
    try:
        response = httpx.get(
            f"{llm_url}/v1/models",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0
        )
        response.raise_for_status()
        result = response.json()
        models = result.get("data", [])
        if models:
            return [m.get("id") for m in models]
        return None
    except Exception as e:
        print(f"[Warning] Could not fetch model list: {e}")
        return None


def set_env_var(name: str, value: str) -> bool:
    """Set environment variable for current session and suggest persistence."""
    try:
        os.environ[name] = value
        print(f"[OK] Set {name}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to set {name}: {e}")
        return False


def save_llm_credentials(llm_key: str, llm_model: str) -> bool:
    """Save LLM credentials to data/.llm_key and data/.llm_model files."""
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)

    try:
        # Save API key
        key_file = os.path.join(data_dir, ".llm_key")
        with open(key_file, "w") as f:
            f.write(llm_key)
        print(f"[OK] Saved LLM_API_KEY to data/.llm_key")

        # Save model name
        model_file = os.path.join(data_dir, ".llm_model")
        with open(model_file, "w") as f:
            f.write(llm_model)
        print(f"[OK] Saved LLM_MODEL to data/.llm_model")

        return True
    except Exception as e:
        print(f"[ERROR] Failed to save credentials: {e}")
        return False


def main():
    print("\n" + "="*60)
    print("  Hoonbot Setup")
    print("="*60)

    # LLM_API_fast URL
    llm_url = os.environ.get("LLM_API_URL", "http://localhost:10007").rstrip("/")
    print(f"\nLLM_API_fast URL: {llm_url}")

    # Get token
    print("\nAttempting to login to LLM_API_fast...")
    token = get_llm_api_token(llm_url)

    if not token:
        print("\n[Setup] Could not obtain LLM_API_KEY automatically.")
        print("        You'll need to set it manually:")
        print("        export LLM_API_KEY='your_token_here'")
        return 1

    # Get available models
    print("\nFetching available models...")
    models = get_available_models(llm_url, token)

    llm_model = None
    if models:
        print(f"\nAvailable models:")
        for i, model in enumerate(models, 1):
            print(f"  {i}. {model}")

        # Pick first model by default
        llm_model = models[0]
        print(f"\nSelected: {llm_model}")
    else:
        print("\n[Warning] Could not fetch model list")
        print("          Enter model name manually after setup")
        llm_model = "default"

    # Save credentials to files
    print("\nSaving credentials...")
    save_llm_credentials(token, llm_model)

    print("\n" + "="*60)
    print("  Setup Complete!")
    print("="*60)
    print("\nCredentials saved to:")
    print("  data/.llm_key    (API token)")
    print("  data/.llm_model  (Model name)")
    print("\nYou can now start Hoonbot:")
    print("  python hoonbot.py")
    print("\nNo environment variables needed!")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
