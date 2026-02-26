#!/usr/bin/env python3
"""
Quick test to verify LLM_API_fast connection and memory command parsing.
"""
import json
import os
import sys
import asyncio

import httpx

import config

async def test_llm_connection():
    """Test if we can call LLM_API_fast."""
    print(f"Testing LLM_API_fast connection...")
    print(f"  URL: {config.LLM_API_URL}")
    print(f"  Model: {config.LLM_MODEL}")
    print(f"  Has API key: {bool(config.LLM_API_KEY)}")
    print()

    if not config.LLM_API_KEY:
        print("ERROR: LLM_API_KEY not set!")
        print("  Set it with: export LLM_API_KEY='your_token'")
        return False

    if not config.LLM_MODEL:
        print("ERROR: LLM_MODEL not set!")
        print("  Set it with: export LLM_MODEL='your_model'")
        return False

    # Simple test message
    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant. When updating memory, embed: [UPDATE_MEMORY: new memory content]"
        },
        {
            "role": "user",
            "content": "My name is Huni. Remember this. Also respond normally."
        }
    ]

    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"}
    data = {
        "model": config.LLM_MODEL,
        "messages": json.dumps(messages),
        "agent_type": "auto",
    }

    print("Sending test request...")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{config.LLM_API_URL}/v1/chat/completions",
                data=data,
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()

        reply = result["choices"][0]["message"]["content"]
        print(f"SUCCESS! Got response:\n{reply}\n")

        # Check for memory command
        if "[UPDATE_MEMORY:" in reply:
            print("GOOD: Response contains [UPDATE_MEMORY: ...] command")
            import re
            match = re.search(r"\[UPDATE_MEMORY:(.*?)\]", reply, re.DOTALL)
            if match:
                print(f"Extracted memory content: {match.group(1)[:100]}")
        else:
            print("WARNING: Response doesn't contain [UPDATE_MEMORY: ...] command")
            print("  The LLM might not be following the instructions properly.")

        return True

    except httpx.HTTPStatusError as e:
        print(f"HTTP ERROR {e.response.status_code}: {e.response.text}")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(test_llm_connection())
    sys.exit(0 if success else 1)
