"""
Latency benchmark harness for agentic flow.

Runs representative chat scenarios and reports:
- wall time
- estimated iteration count (from prompts.log)
- estimated tool call count (from prompts.log)
- mean LLM turn duration for the session (from prompts.log STATS blocks)
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


DEFAULT_BASE_URL = "http://127.0.0.1:10007"
LOG_PATH = Path("data/logs/prompts.log")


def load_log_lines() -> List[str]:
    if not LOG_PATH.exists():
        return []
    return LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()


def run_chat(base_url: str, prompt: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    payload = {
        "messages": json.dumps([{"role": "user", "content": prompt}], ensure_ascii=False),
        "stream": "false",
    }
    if session_id:
        payload["session_id"] = session_id

    start = time.perf_counter()
    response = requests.post(url, data=payload, timeout=600)
    elapsed = time.perf_counter() - start
    response.raise_for_status()
    body = response.json()
    new_session_id = body.get("x_session_id", session_id)
    assistant_text = ""
    choices = body.get("choices", [])
    if choices:
        assistant_text = choices[0].get("message", {}).get("content", "") or ""

    return {
        "elapsed_s": round(elapsed, 2),
        "session_id": new_session_id,
        "assistant_text": assistant_text,
    }


def parse_session_metrics(lines: List[str], session_id: str) -> Dict[str, Any]:
    iterations = 0
    tool_calls = 0
    llm_durations: List[float] = []

    # Parse tool-call blocks and iteration logs written by AgentLoop.
    for idx, line in enumerate(lines):
        if ">>> AGENT ITERATION" in line or ">>> AGENT STREAM ITERATION" in line:
            # Look for nearby session line.
            window = lines[idx: idx + 8]
            if any(session_id in w for w in window):
                iterations += 1

        if ">>> LLM REQUESTED TOOL CALLS" in line:
            window = lines[idx: idx + 12]
            if any(session_id in w for w in window):
                for w in window:
                    if "Tool Count:" in w:
                        try:
                            tool_calls += int(w.split("Tool Count:")[1].strip())
                        except Exception:
                            pass
                        break

    # Parse interceptor STATS blocks.
    current_session: Optional[str] = None
    in_stats = False
    current_duration: Optional[float] = None
    current_agent: Optional[str] = None
    for line in lines:
        stripped = line.strip()
        if stripped == "STATS:":
            in_stats = True
            current_session = None
            current_duration = None
            current_agent = None
            continue

        if in_stats and stripped.startswith("Session:"):
            current_session = stripped.split("Session:", 1)[1].strip()
        elif in_stats and stripped.startswith("Agent:"):
            current_agent = stripped.split("Agent:", 1)[1].strip()
        elif in_stats and stripped.startswith("Duration:"):
            raw = stripped.split("Duration:", 1)[1].strip().rstrip("s")
            try:
                current_duration = float(raw)
            except ValueError:
                current_duration = None
        elif in_stats and stripped.startswith("Status:"):
            if current_session == session_id and current_duration is not None:
                if current_agent and current_agent.startswith("agent"):
                    llm_durations.append(current_duration)
            in_stats = False

    mean_llm_duration = round(sum(llm_durations) / len(llm_durations), 2) if llm_durations else None
    return {
        "iterations_estimate": iterations,
        "tool_calls_estimate": tool_calls,
        "llm_turn_count": len(llm_durations),
        "llm_turn_mean_s": mean_llm_duration,
    }


def benchmark_case(base_url: str, name: str, prompt: str) -> Dict[str, Any]:
    before_lines = load_log_lines()
    chat_result = run_chat(base_url=base_url, prompt=prompt)
    # Allow async log writers to flush.
    time.sleep(0.5)
    after_lines = load_log_lines()
    new_lines = after_lines[len(before_lines):]
    metrics = parse_session_metrics(new_lines, chat_result["session_id"])
    return {
        "name": name,
        "session_id": chat_result["session_id"],
        "wall_time_s": chat_result["elapsed_s"],
        **metrics,
        "response_chars": len(chat_result["assistant_text"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run latency benchmark scenarios.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base URL")
    parser.add_argument("--include-heavy", action="store_true", help="Include heavy visualization scenario")
    args = parser.parse_args()

    scenarios = [
        (
            "simple_file_read",
            "Read the file C:/Users/Lee/Desktop/Huni/LLM_API_fast/config.py and tell me only the value of AGENT_MAX_ITERATIONS.",
        ),
        (
            "python_coder_analysis",
            "Use python_coder to create and run a short python script that computes mean and standard deviation of [1,2,3,4,5], then print the results.",
        ),
    ]
    if args.include_heavy:
        scenarios.append(
            (
                "python_coder_visualization",
                "Use python_coder to create and run a script that generates a simple matplotlib line chart from x=[1,2,3,4], y=[1,4,9,16], save it as bench_plot.png, and print the saved path.",
            )
        )

    results: List[Dict[str, Any]] = []
    for name, prompt in scenarios:
        print(f"\n[Benchmark] Running scenario: {name}")
        result = benchmark_case(args.base_url, name, prompt)
        results.append(result)
        print(json.dumps(result, indent=2))

    output_path = Path("use_cases/latency_benchmark_results.json")
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved benchmark results: {output_path}")


if __name__ == "__main__":
    main()
