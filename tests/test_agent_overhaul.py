"""
Integration tests for Agent Workflow Overhaul.
Tests all 12 plan items against a live server with GLM-4.7-Flash.

Requires: backend server on :10007, llama.cpp on :5904
"""
import json
import time
import httpx
import asyncio
import sys
from pathlib import Path

BASE = "http://localhost:10007"
LLAMA = "http://localhost:5904"
TIMEOUT = 300.0

passed = 0
failed = 0
results = []


def report(name: str, ok: bool, detail: str = ""):
    global passed, failed
    status = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    else:
        failed += 1
    results.append((name, ok, detail))
    marker = "+" if ok else "X"
    print(f"  [{marker}] {name}")
    if detail:
        for line in detail.split("\n"):
            print(f"      {line}")


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ======================================================================
# Setup: create test user and get token
# ======================================================================

def setup() -> str:
    """Create test user, return auth token."""
    client = httpx.Client(timeout=10)

    # Try signup
    r = client.post(f"{BASE}/api/auth/signup", json={
        "username": "testuser_overhaul",
        "password": "testpass1234",
    })
    if r.status_code == 400 and "already exists" in r.text:
        r = client.post(f"{BASE}/api/auth/login", json={
            "username": "testuser_overhaul",
            "password": "testpass1234",
        })

    if r.status_code != 200:
        print(f"Auth failed: {r.status_code} {r.text}")
        sys.exit(1)

    token = r.json()["access_token"]
    print(f"  Auth token acquired for testuser_overhaul")
    return token


def chat(token: str, message: str, stream: bool = False, session_id: str = None) -> dict:
    """Send a chat request through the API."""
    client = httpx.Client(timeout=TIMEOUT)
    headers = {"Authorization": f"Bearer {token}"}
    data = {
        "messages": json.dumps([{"role": "user", "content": message}]),
        "stream": str(stream).lower(),
    }
    if session_id:
        data["session_id"] = session_id

    r = client.post(f"{BASE}/v1/chat/completions", data=data, headers=headers)
    return r


def chat_stream_events(token: str, message: str, session_id: str = None) -> dict:
    """Send a streaming chat request and collect all events."""
    client = httpx.Client(timeout=TIMEOUT)
    headers = {"Authorization": f"Bearer {token}"}
    data = {
        "messages": json.dumps([{"role": "user", "content": message}]),
        "stream": "true",
    }
    if session_id:
        data["session_id"] = session_id

    text_chunks = []
    tool_events = []
    all_events = []

    with client.stream("POST", f"{BASE}/v1/chat/completions", data=data, headers=headers) as resp:
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload.strip() == "[DONE]":
                break
            try:
                obj = json.loads(payload)
                all_events.append(obj)
                if obj.get("object") == "tool.status":
                    tool_events.append(obj)
                elif obj.get("object") == "chat.completion.chunk":
                    delta = obj.get("choices", [{}])[0].get("delta", {})
                    if delta.get("content"):
                        text_chunks.append(delta["content"])
            except json.JSONDecodeError:
                pass

    return {
        "text": "".join(text_chunks),
        "tool_events": tool_events,
        "all_events": all_events,
        "event_count": len(all_events),
    }


# ======================================================================
# Test 1: Basic non-streaming chat (sanity check)
# ======================================================================

def test_basic_chat(token: str):
    section("Test 1: Basic Non-Streaming Chat")
    start = time.time()
    r = chat(token, "What is 2+2? Answer with just the number.")
    duration = time.time() - start

    ok = r.status_code == 200
    detail = ""
    if ok:
        body = r.json()
        content = body["choices"][0]["message"]["content"]
        has_4 = "4" in content
        detail = f"Response ({duration:.1f}s): {content[:200]}"
        report("Non-streaming chat returns 200", True, detail)
        report("Response contains correct answer", has_4, f"Looking for '4' in response")
        report("Response has session_id", bool(body.get("x_session_id")), body.get("x_session_id", ""))
    else:
        report("Non-streaming chat returns 200", False, f"Got {r.status_code}: {r.text[:300]}")


# ======================================================================
# Test 2: Streaming chat + ToolStatusEvent (plan items 4)
# ======================================================================

def test_streaming_chat(token: str):
    section("Test 2: Streaming Chat")
    start = time.time()
    result = chat_stream_events(token, "Hello! Say hi back in one sentence.")
    duration = time.time() - start

    report("Streaming returns text", len(result["text"]) > 0,
           f"Got {len(result['text'])} chars in {duration:.1f}s: {result['text'][:150]}")
    report("Streaming events received", result["event_count"] > 0,
           f"{result['event_count']} SSE events total")


# ======================================================================
# Test 3: Tool calling — memory tool (plan item 10)
# ======================================================================

def test_memory_tool(token: str):
    section("Test 3: Memory Tool (via agent)")
    start = time.time()
    result = chat_stream_events(
        token,
        "Use the memory tool to store the key 'test_color' with value 'blue'. Then confirm it was stored."
    )
    duration = time.time() - start

    has_tool_events = len(result["tool_events"]) > 0
    has_memory_event = any(e.get("tool_name") == "memory" for e in result["tool_events"])

    report("Agent called memory tool", has_memory_event,
           f"Tool events: {json.dumps(result['tool_events'], indent=2)[:400]}")
    report("ToolStatusEvent streamed (plan item 4)", has_tool_events,
           f"{len(result['tool_events'])} tool status events in {duration:.1f}s")

    if has_tool_events:
        statuses = [e["status"] for e in result["tool_events"]]
        has_started = "started" in statuses
        has_completed = "completed" in statuses or "failed" in statuses
        report("Has 'started' status", has_started, f"Statuses: {statuses}")
        report("Has 'completed'/'failed' status", has_completed, f"Statuses: {statuses}")

    report("Agent produced text response", len(result["text"]) > 0,
           f"Response: {result['text'][:200]}")


# ======================================================================
# Test 4: Tool calling — file_writer + file_reader (plan items 6, 7)
# ======================================================================

def test_file_tools(token: str):
    section("Test 4: File Writer + Reader Tools")
    result = chat_stream_events(
        token,
        "Use file_writer to create a file called 'hello.txt' with content 'Hello from GLM4!'. "
        "Then use file_reader to read it back and tell me what it says."
    )

    tool_names = [e.get("tool_name") for e in result["tool_events"]]
    has_writer = "file_writer" in tool_names
    has_reader = "file_reader" in tool_names

    report("Agent called file_writer", has_writer, f"Tools used: {tool_names}")
    report("Agent called file_reader", has_reader, f"Tools used: {tool_names}")
    report("Response mentions file content", "Hello" in result["text"] or "hello" in result["text"].lower(),
           f"Response: {result['text'][:200]}")


# ======================================================================
# Test 5: Tool calling — shell_exec (plan item 9)
# ======================================================================

def test_shell_tool(token: str):
    section("Test 5: Shell Exec Tool")
    result = chat_stream_events(
        token,
        "Use shell_exec to run the command 'echo hello_from_shell' and tell me the output."
    )

    tool_names = [e.get("tool_name") for e in result["tool_events"]]
    has_shell = "shell_exec" in tool_names

    report("Agent called shell_exec", has_shell, f"Tools used: {tool_names}")
    report("Response contains shell output",
           "hello_from_shell" in result["text"] or "hello" in result["text"].lower(),
           f"Response: {result['text'][:200]}")


# ======================================================================
# Test 6: Tool calling — file_navigator (plan item 8)
# ======================================================================

def test_navigator_tool(token: str):
    section("Test 6: File Navigator Tool")
    result = chat_stream_events(
        token,
        "Use file_navigator with operation 'list' to show me what files are in my workspace."
    )

    tool_names = [e.get("tool_name") for e in result["tool_events"]]
    has_navigator = "file_navigator" in tool_names

    report("Agent called file_navigator", has_navigator, f"Tools used: {tool_names}")
    report("Response has content", len(result["text"]) > 0, f"Response: {result['text'][:200]}")


# ======================================================================
# Test 7: Prompt caching (plan item 3) — structural verification
# ======================================================================

def test_prompt_caching():
    section("Test 7: Prompt Caching (structural)")
    sys.path.insert(0, str(Path(__file__).parent.parent))

    try:
        from backend.agent import _CACHED_SYSTEM_PROMPT, _CACHED_TOOL_SCHEMAS, reload_prompt_cache

        has_prompt = len(_CACHED_SYSTEM_PROMPT) > 50
        report("System prompt cached at module level", has_prompt,
               f"Cached prompt length: {len(_CACHED_SYSTEM_PROMPT)} chars")

        has_schemas = len(_CACHED_TOOL_SCHEMAS) > 0
        schema_names = [s["function"]["name"] for s in _CACHED_TOOL_SCHEMAS]
        report("Tool schemas cached at module level", has_schemas,
               f"Cached schemas: {schema_names}")

        report("All 8 tools in cached schemas", len(_CACHED_TOOL_SCHEMAS) == 8,
               f"Expected 8, got {len(_CACHED_TOOL_SCHEMAS)}: {schema_names}")

        # Verify no session_id in schemas
        for s in _CACHED_TOOL_SCHEMAS:
            props = s["function"]["parameters"].get("properties", {})
            if "session_id" in props:
                report("session_id excluded from schemas", False,
                       f"Found session_id in {s['function']['name']}")
                break
        else:
            report("session_id excluded from cached schemas", True)

        # Verify reload works
        reload_prompt_cache()
        report("reload_prompt_cache() works", True)
    except Exception as e:
        report("Prompt caching structure", False, str(e))


# ======================================================================
# Test 8: Microcompaction (plan item 2) — structural verification
# ======================================================================

def test_microcompaction():
    section("Test 8: Microcompaction (structural)")
    sys.path.insert(0, str(Path(__file__).parent.parent))

    try:
        import config
        report("TOOL_RESULT_BUDGET configured", len(config.TOOL_RESULT_BUDGET) == 8,
               f"Budgets: {config.TOOL_RESULT_BUDGET}")
        report("TOOL_RESULTS_DIR configured", config.TOOL_RESULTS_DIR == Path("data/tool_results"),
               str(config.TOOL_RESULTS_DIR))

        from backend.agent import AgentLoop
        agent = AgentLoop(session_id="test_microcompact", username="test")
        has_truncate = hasattr(agent, '_truncate_tool_result')
        has_compress = hasattr(agent, '_compress_old_iterations')
        has_save = hasattr(agent, '_save_tool_result_to_disk')

        report("_truncate_tool_result method exists", has_truncate)
        report("_compress_old_iterations method exists", has_compress)
        report("_save_tool_result_to_disk method exists", has_save)

        # Test truncation
        long_content = "x" * 10000
        truncated = agent._truncate_tool_result("websearch", long_content)
        report("Truncation works (websearch budget=2000)",
               len(truncated) < 10000 and "truncated" in truncated,
               f"Input: 10000 chars → Output: {len(truncated)} chars")

    except Exception as e:
        report("Microcompaction structure", False, str(e))


# ======================================================================
# Test 9: Max iterations (plan item 5)
# ======================================================================

def test_max_iterations():
    section("Test 9: AGENT_MAX_ITERATIONS = 8")
    import config
    report("AGENT_MAX_ITERATIONS is 8", config.AGENT_MAX_ITERATIONS == 8,
           f"Value: {config.AGENT_MAX_ITERATIONS}")


# ======================================================================
# Test 10: Parallel execution structure (plan item 1)
# ======================================================================

def test_parallel_execution():
    section("Test 10: Parallel Execution (structural)")
    sys.path.insert(0, str(Path(__file__).parent.parent))

    try:
        from backend.agent import AgentLoop
        agent = AgentLoop(session_id="test_parallel", username="test")
        has_parallel = hasattr(agent, '_execute_tools_parallel')
        report("_execute_tools_parallel method exists", has_parallel)

        import inspect
        source = inspect.getsource(agent._execute_tools_parallel)
        uses_gather = "asyncio.gather" in source
        report("Uses asyncio.gather", uses_gather, source.strip()[:200])

    except Exception as e:
        report("Parallel execution", False, str(e))


# ======================================================================
# Test 11: Tool schemas in tools_config.py (plan item 11)
# ======================================================================

def test_tool_schemas():
    section("Test 11: Tool Schemas")
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from tools_config import TOOL_SCHEMAS
    expected = ["websearch", "python_coder", "rag", "file_reader",
                "file_writer", "file_navigator", "shell_exec", "memory"]

    for tool_name in expected:
        has_schema = tool_name in TOOL_SCHEMAS
        report(f"Schema exists: {tool_name}", has_schema)


# ======================================================================
# Test 12: System prompt (plan item 12)
# ======================================================================

def test_system_prompt():
    section("Test 12: System Prompt (ACI)")
    prompt_path = Path(__file__).parent.parent / "prompts" / "system.txt"
    content = prompt_path.read_text(encoding="utf-8")

    report("System prompt file exists", len(content) > 100, f"{len(content)} chars")
    report("Has tool selection table", "file_reader" in content and "file_writer" in content)
    report("Has all 8 tool names", all(t in content for t in
           ["websearch", "python_coder", "rag", "file_reader",
            "file_writer", "file_navigator", "shell_exec", "memory"]))
    report("Has behavior section", "## Behavior" in content or "## behavior" in content.lower())
    report("Has response guidelines", "Response" in content and "Guidelines" in content)


# ======================================================================
# Test 13: ToolStatusEvent dataclass (plan item 4)
# ======================================================================

def test_tool_status_event():
    section("Test 13: ToolStatusEvent Type")
    from backend.core.llm_backend import ToolStatusEvent, StreamEvent

    evt = ToolStatusEvent(tool_name="test", tool_call_id="c1", status="started", duration=0.0)
    report("ToolStatusEvent is a StreamEvent", isinstance(evt, StreamEvent))
    report("Has tool_name field", evt.tool_name == "test")
    report("Has status field", evt.status == "started")
    report("Has duration field", evt.duration == 0.0)

    from backend.models.schemas import ToolStatusChunk
    chunk = ToolStatusChunk(tool_name="test", tool_call_id="c1", status="completed", duration=1.5)
    report("ToolStatusChunk serializable", chunk.model_dump_json() is not None,
           chunk.model_dump_json()[:200])


# ======================================================================
# Run all tests
# ======================================================================

def main():
    print("=" * 60)
    print("  Agent Workflow Overhaul - Integration Tests")
    print(f"  Backend: {BASE}  |  LLM: {LLAMA}")
    print("=" * 60)

    token = setup()

    # Structural tests (fast, no LLM calls)
    test_prompt_caching()
    test_microcompaction()
    test_max_iterations()
    test_parallel_execution()
    test_tool_schemas()
    test_system_prompt()
    test_tool_status_event()

    # Live LLM tests (slow, require inference)
    test_basic_chat(token)
    test_streaming_chat(token)
    test_memory_tool(token)
    test_file_tools(token)
    test_shell_tool(token)
    test_navigator_tool(token)

    # Summary
    print(f"\n{'='*60}")
    print(f"  RESULTS: {passed} passed, {failed} failed, {passed+failed} total")
    print(f"{'='*60}")

    if failed > 0:
        print("\nFailed tests:")
        for name, ok, detail in results:
            if not ok:
                print(f"  X {name}")
                if detail:
                    print(f"    {detail[:200]}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
