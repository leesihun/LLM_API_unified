#!/usr/bin/env python3
"""
Diagnostic: check vLLM tool-call streaming behaviour.

Connects to vLLM directly (bypassing llm-api) and sends a prompt that forces
at least one tool call. Reports:

  - Whether delta.tool_calls arrive mid-stream or only at [DONE]
  - The chunk number at which each tool's arguments become valid JSON
  - Whether raw tool markup leaks into delta.content
  - Total stream latency

Usage:
    python scripts/check_tool_streaming.py [--host http://127.0.0.1:10000]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx

# Allow running from the llm-api directory or repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config


TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Return the current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"}
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "Return the current UTC time.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

MESSAGES = [
    {
        "role": "user",
        "content": (
            "What is the weather in Seoul AND what is the current UTC time? "
            "Use both tools."
        ),
    }
]


def _try_parse(s: str) -> bool:
    try:
        json.loads(s)
        return True
    except json.JSONDecodeError:
        return False


def run(host: str, model: str | None) -> None:
    if model is None:
        r = httpx.get(f"{host}/v1/models", timeout=5)
        r.raise_for_status()
        model = r.json()["data"][0]["id"]
        print(f"Using model: {model}\n")

    payload = {
        "model": model,
        "messages": MESSAGES,
        "tools": TOOL_SCHEMA,
        "parallel_tool_calls": True,
        "temperature": 0.0,
        "stream": True,
    }

    # Per-index accumulators
    pending: dict[int, dict] = {}
    completed_at: dict[int, int] = {}   # index -> chunk number where JSON completed
    content_chunks: list[str] = []
    chunk_num = 0
    tool_delta_chunks: list[int] = []   # chunk numbers where tool_calls appeared

    print("Streaming…\n")
    t0 = time.monotonic()

    with httpx.Client(timeout=60) as client:
        with client.stream("POST", f"{host}/v1/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            for raw in resp.iter_lines():
                if not raw.startswith("data: "):
                    continue
                data_str = raw[6:].strip()
                if data_str == "[DONE]":
                    break
                chunk_num += 1
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                choices = chunk.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})

                if delta.get("content"):
                    content_chunks.append(delta["content"])

                if "tool_calls" in delta:
                    tool_delta_chunks.append(chunk_num)
                    for tc in delta["tool_calls"]:
                        idx = tc.get("index", 0)
                        if idx not in pending:
                            pending[idx] = {"id": tc.get("id", ""), "name": "", "args": ""}
                        e = pending[idx]
                        fn = tc.get("function", {})
                        if fn.get("name"):
                            e["name"] += fn["name"]
                        if fn.get("arguments"):
                            e["args"] += fn["arguments"]

                        if idx not in completed_at and _try_parse(e["args"]):
                            completed_at[idx] = chunk_num
                            print(
                                f"  [chunk {chunk_num:>4}] index={idx}  {e['name']}  "
                                f"JSON complete → {e['args'][:80]}"
                            )

    elapsed = time.monotonic() - t0

    print(f"\n{'='*60}")
    print(f"Total chunks : {chunk_num}")
    print(f"Stream time  : {elapsed:.2f}s")
    print(f"Tool deltas  : {len(tool_delta_chunks)} chunks "
          f"(first={tool_delta_chunks[0] if tool_delta_chunks else 'none'}, "
          f"last={tool_delta_chunks[-1] if tool_delta_chunks else 'none'})")

    if content_chunks:
        sample = "".join(content_chunks)[:200].replace("\n", "\\n")
        print(f"Content leak : YES — {len(content_chunks)} text chunks — {sample!r}")
    else:
        print("Content leak : none (good)")

    print(f"\nTool results ({len(pending)} tools):")
    for idx in sorted(pending):
        e = pending[idx]
        done_chunk = completed_at.get(idx, chunk_num)  # fallback = stream end
        pct = done_chunk / chunk_num * 100 if chunk_num else 0
        early = done_chunk < chunk_num
        print(
            f"  index={idx}  {e['name']!r:20s}  "
            f"JSON done at chunk {done_chunk}/{chunk_num} ({pct:.0f}%)  "
            f"{'← early dispatch possible' if early else '← only at [DONE]'}"
        )

    if not pending:
        print("  (no tool calls received)")
        print("\n⚠ Model did not call any tools — prompt may need adjustment,")
        print("   or the model does not support native tool calling at this vLLM config.")
    print("="*60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose vLLM tool-call streaming")
    parser.add_argument("--host", default=config.VLLM_HOST.rstrip("/"),
                        help="vLLM base URL (default: from config.VLLM_HOST)")
    parser.add_argument("--model", default=None, help="Model ID (default: first from /v1/models)")
    args = parser.parse_args()
    run(args.host, args.model)


if __name__ == "__main__":
    main()
