"""
Unified Agent Loop: single while-loop with native tool calling.

Modern agentic workflow following:
- Anthropic "Building Effective Agents": single loop, parallelization, ACI
- Claude Code architecture: microcompaction, prompt caching, tool status events
- OpenAI agent guide: streaming observability, tool orchestration
"""
import asyncio
import json
import time
from typing import List, Dict, Any, Optional, AsyncIterator
from uuid import uuid4

import config
from backend.core.llm_backend import (
    LLMResponse, StreamEvent, TextEvent,
    ToolCallDeltaEvent, ToolCall, ToolStatusEvent, llm_backend,
)
from backend.utils.stop_signal import check_stop


# ======================================================================
# Module-level prompt & schema caching (for llama.cpp KV cache reuse)
# ======================================================================

def _load_system_prompt() -> str:
    prompt_path = config.PROMPTS_DIR / config.AGENT_SYSTEM_PROMPT
    if prompt_path.exists():
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    return "You are a helpful assistant with access to tools."


def _build_tool_schemas() -> List[Dict[str, Any]]:
    """Build tool schemas once at module load. Frozen order for cache stability."""
    from tools_config import TOOL_SCHEMAS
    schemas = []
    for tool_name in config.AVAILABLE_TOOLS:
        schema = TOOL_SCHEMAS.get(tool_name)
        if not schema:
            continue
        params = dict(schema["parameters"])
        props = dict(params.get("properties", {}))
        required = list(params.get("required", []))
        props.pop("session_id", None)
        if "session_id" in required:
            required.remove("session_id")
        schemas.append({
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema["description"],
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        })
    return schemas


_CACHED_SYSTEM_PROMPT: str = _load_system_prompt()
_CACHED_TOOL_SCHEMAS: List[Dict[str, Any]] = _build_tool_schemas()


def reload_prompt_cache():
    """Reload cached prompt and schemas (call after config changes)."""
    global _CACHED_SYSTEM_PROMPT, _CACHED_TOOL_SCHEMAS
    _CACHED_SYSTEM_PROMPT = _load_system_prompt()
    _CACHED_TOOL_SCHEMAS = _build_tool_schemas()


class AgentLoop:
    """
    Single agent loop that uses llama.cpp native tool calling.

    The LLM receives tool schemas and returns structured tool_calls.
    The loop executes tools in-process (parallel when possible) and
    feeds results back until the LLM responds with plain text.

    Features:
    - Parallel tool execution (asyncio.gather)
    - Microcompaction (save large results to disk, compress old iterations)
    - Prompt caching (byte-stable prefix for llama.cpp KV reuse)
    - Tool status events (streaming visibility)
    """

    def __init__(
        self,
        model: str = None,
        temperature: float = None,
        session_id: str = None,
        username: str = None,
        tools: Optional[List[str]] = None,
    ):
        self.model = model or config.LLAMACPP_MODEL
        self.temperature = temperature if temperature is not None else config.DEFAULT_TEMPERATURE
        self.session_id = session_id
        self.username = username
        self.llm = llm_backend
        self.max_iterations = config.AGENT_MAX_ITERATIONS
        self.enabled_tools = tools or config.AVAILABLE_TOOLS
        self.tool_calls_log: List[Dict[str, Any]] = []
        self._iteration_boundaries: List[int] = []
        self._available_rag_collections: Optional[List[str]] = None

    # ------------------------------------------------------------------
    # System prompt (cached, with per-request file attachments appended)
    # ------------------------------------------------------------------

    def _build_system_prompt(self, attached_files: Optional[List[Dict[str, Any]]] = None) -> str:
        prompt = _CACHED_SYSTEM_PROMPT
        prompt += self._format_rag_collections_context()
        if attached_files:
            prompt += self._format_attached_files(attached_files)
        return prompt

    def _refresh_available_rag_collections(self):
        """Load available RAG collections for the current user."""
        self._available_rag_collections = []

        if "rag" not in self.enabled_tools or not self.username:
            return

        try:
            from tools.rag import RAGTool
            tool = RAGTool(username=self.username)
            result = tool.list_collections()
            if not result.get("success"):
                return

            collections = result.get("collections", [])
            names = sorted({
                c.get("name")
                for c in collections
                if isinstance(c, dict) and isinstance(c.get("name"), str) and c.get("name")
            })
            self._available_rag_collections = names
        except Exception as e:
            print(f"[RAG] Failed to load available collections for prompt context: {e}")

    def _get_available_rag_collections(self) -> List[str]:
        if self._available_rag_collections is None:
            self._refresh_available_rag_collections()
        return self._available_rag_collections or []

    def _format_rag_collections_context(self) -> str:
        if "rag" not in self.enabled_tools:
            return ""

        available = self._get_available_rag_collections()
        lines = ["\n\n## RAG COLLECTIONS"]
        lines.append("Use only existing collection_name values from this list when calling the rag tool.")
        if available:
            lines.append(f"Available collection_name values: {json.dumps(available, ensure_ascii=False)}")
        else:
            lines.append("Available collection_name values: []")
            lines.append("No collection exists yet. Ask the user to create a collection before using rag.")
        return "\n".join(lines)

    def _format_attached_files(self, attached_files: List[Dict[str, Any]]) -> str:
        if not attached_files:
            return ""
        lines = ["\n\n## ATTACHED FILES"]
        lines.append(f"The user has attached {len(attached_files)} file(s).\n")
        for idx, f in enumerate(attached_files, 1):
            if "error" in f:
                lines.append(f"{idx}. {f['name']} - ERROR: {f['error']}")
                continue
            size_kb = f.get('size', 0) / 1024
            lines.append(f"{idx}. {f['name']} ({f.get('type', '?')}, {size_kb:.1f} KB)")
            if 'headers' in f:
                lines.append(f"   Columns: {', '.join(f['headers'])}")
                lines.append(f"   Rows: {f.get('rows', '?')}")
            if 'structure' in f:
                lines.append(f"   Structure: {f['structure']}")
                if f.get('keys'):
                    lines.append(f"   Keys: {', '.join(f['keys'][:10])}")
            if 'lines' in f:
                lines.append(f"   Lines: {f['lines']}")
                if f.get('definitions'):
                    lines.append(f"   Definitions: {', '.join(f['definitions'][:5])}")
            if 'preview' in f:
                lines.append(f"   Preview: {str(f['preview'])[:200]}...")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Tool schemas (cached at module level, filtered by enabled_tools)
    # ------------------------------------------------------------------

    def _get_tool_schemas(self) -> Optional[List[Dict[str, Any]]]:
        if not self.enabled_tools:
            return None
        schemas = [s for s in _CACHED_TOOL_SCHEMAS
                   if s["function"]["name"] in self.enabled_tools]
        return schemas if schemas else None

    # ------------------------------------------------------------------
    # In-process tool execution (with parallel support)
    # ------------------------------------------------------------------

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        start = time.time()
        print(f"\n{'='*70}")
        print(f"[TOOL] Executing: {name}")
        print(f"{'='*70}")
        for k, v in arguments.items():
            sv = str(v)
            print(f"  {k}: {sv[:150]}{'...' if len(sv) > 150 else ''}")

        try:
            result = self._dispatch_tool(name, arguments)
            duration = time.time() - start
            print(f"[TOOL] {name} completed in {duration:.2f}s — success={result.get('success', '?')}")
            self.tool_calls_log.append({
                "name": name, "input": arguments,
                "success": result.get("success", True), "duration": duration,
            })
            return result
        except Exception as e:
            duration = time.time() - start
            print(f"[TOOL] {name} FAILED in {duration:.2f}s — {e}")
            self.tool_calls_log.append({
                "name": name, "input": arguments,
                "success": False, "error": str(e), "duration": duration,
            })
            return {"success": False, "error": str(e)}

    async def _execute_tools_parallel(self, tool_calls: List[ToolCall]) -> List[Dict[str, Any]]:
        """Execute multiple tool calls concurrently."""
        tasks = [
            self.execute_tool(tc.function.name, tc.function.arguments)
            for tc in tool_calls
        ]
        return await asyncio.gather(*tasks)

    def _dispatch_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if name == "websearch":
            from tools.web_search import WebSearchTool
            tool = WebSearchTool()
            return tool.search(
                query=arguments["query"],
                max_results=arguments.get("max_results"),
            )

        elif name == "python_coder":
            from tools.python_coder import PythonCoderTool
            tool = PythonCoderTool(session_id=self.session_id)
            return tool.execute(
                instruction=arguments["instruction"],
                timeout=arguments.get("timeout"),
            )

        elif name == "rag":
            from tools.rag import RAGTool
            tool = RAGTool(username=self.username)
            available_collections = self._get_available_rag_collections()
            requested_collection = arguments.get("collection_name")

            if not available_collections:
                return {
                    "success": False,
                    "error": "No RAG collections are available for this user. Create a collection first.",
                    "available_collections": [],
                }

            if requested_collection not in available_collections:
                return {
                    "success": False,
                    "error": (
                        f"Invalid collection_name '{requested_collection}'. "
                        "Use one of the available collections."
                    ),
                    "available_collections": available_collections,
                }

            return tool.retrieve(
                collection_name=requested_collection,
                query=arguments["query"],
                max_results=arguments.get("max_results"),
            )

        elif name == "file_reader":
            from tools.file_ops import FileReaderTool
            tool = FileReaderTool(username=self.username, session_id=self.session_id)
            return tool.read(
                path=arguments["path"],
                offset=arguments.get("offset"),
                limit=arguments.get("limit"),
            )

        elif name == "file_writer":
            from tools.file_ops import FileWriterTool
            tool = FileWriterTool(session_id=self.session_id)
            return tool.write(
                path=arguments["path"],
                content=arguments["content"],
                mode=arguments.get("mode", "write"),
            )

        elif name == "file_navigator":
            from tools.file_ops import FileNavigatorTool
            tool = FileNavigatorTool(username=self.username, session_id=self.session_id)
            return tool.navigate(
                operation=arguments["operation"],
                path=arguments.get("path"),
                pattern=arguments.get("pattern"),
            )

        elif name == "shell_exec":
            from tools.shell import ShellExecTool
            tool = ShellExecTool(session_id=self.session_id)
            return tool.execute(
                command=arguments["command"],
                timeout=arguments.get("timeout", 30),
                working_directory=arguments.get("working_directory"),
            )

        elif name == "memory":
            from tools.memory import MemoryTool
            tool = MemoryTool(username=self.username)
            return tool.execute(
                operation=arguments["operation"],
                key=arguments.get("key"),
                value=arguments.get("value"),
            )

        else:
            return {"success": False, "error": f"Unknown tool: {name}"}

    # ------------------------------------------------------------------
    # Message builders
    # ------------------------------------------------------------------

    def _build_assistant_tool_msg(self, tool_calls: List[ToolCall]) -> Dict[str, Any]:
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": json.dumps(tc.function.arguments, ensure_ascii=False),
                    },
                }
                for tc in tool_calls
            ],
        }

    def _build_tool_result_msg(self, tool_call: ToolCall, result: Dict[str, Any]) -> Dict[str, Any]:
        content = json.dumps(result, ensure_ascii=False, default=str)
        content = self._truncate_tool_result(tool_call.function.name, content)
        return {
            "role": "tool",
            "name": tool_call.function.name,
            "content": content,
            "tool_call_id": tool_call.id,
        }

    # ------------------------------------------------------------------
    # Microcompaction
    # ------------------------------------------------------------------

    def _truncate_tool_result(self, tool_name: str, content: str) -> str:
        """Truncate a tool result to its per-tool budget. Save full version to disk if over budget."""
        budget = config.TOOL_RESULT_BUDGET.get(tool_name, config.TOOL_RESULT_DEFAULT_BUDGET)
        if len(content) <= budget:
            return content

        # Save full result to disk for potential re-retrieval
        if self.session_id:
            call_id = str(uuid4())[:8]
            self._save_tool_result_to_disk(call_id, content)

        return content[:budget] + f"\n...[truncated, {len(content)} chars total]"

    def _save_tool_result_to_disk(self, call_id: str, content: str):
        """Persist full tool result to disk."""
        session_dir = config.TOOL_RESULTS_DIR / (self.session_id or "default")
        session_dir.mkdir(parents=True, exist_ok=True)
        path = session_dir / f"{call_id}.json"
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            print(f"[MICROCOMPACT] Failed to save tool result to disk: {e}")

    def _compress_old_iterations(self, msgs: List[Dict[str, Any]], current_iteration: int):
        """
        Compress tool results from previous iterations to one-line summaries.
        Only the current iteration's tool results remain full-size (hot tail).
        """
        if current_iteration == 0 or len(self._iteration_boundaries) < 2:
            return

        # Messages before the current iteration's boundary are "old"
        old_boundary = self._iteration_boundaries[-1]

        for i, msg in enumerate(msgs):
            if i >= old_boundary:
                break
            if msg.get("role") != "tool":
                continue
            content = msg.get("content", "")
            if len(content) <= 200:
                continue
            tool_name = msg.get("name", "tool")
            # Extract a brief summary from the content
            summary = content[:100].replace('\n', ' ')
            msg["content"] = f"[{tool_name} result — {summary}...]"

    # ------------------------------------------------------------------
    # Non-streaming run
    # ------------------------------------------------------------------

    async def run(
        self,
        messages: List[Dict[str, Any]],
        attached_files: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        self._refresh_available_rag_collections()
        system_prompt = self._build_system_prompt(attached_files)
        msgs: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}] + list(messages)
        tool_schemas = self._get_tool_schemas()

        for iteration in range(self.max_iterations):
            check_stop()
            print(f"\n[AGENT] Iteration {iteration + 1}/{self.max_iterations}")

            # Track iteration boundaries for microcompaction
            self._iteration_boundaries.append(len(msgs))

            response: LLMResponse = await self.llm.chat(
                msgs, self.model, self.temperature,
                tools=tool_schemas,
                session_id=self.session_id,
                agent_type="agent",
            )

            if not response.tool_calls:
                return response.content or ""

            # Append assistant message with tool_calls
            msgs.append(self._build_assistant_tool_msg(response.tool_calls))

            # Execute all tools in parallel
            results = await self._execute_tools_parallel(response.tool_calls)
            for tc, result in zip(response.tool_calls, results):
                msgs.append(self._build_tool_result_msg(tc, result))

            # Compress old iteration tool results (hot tail: keep current full)
            self._compress_old_iterations(msgs, iteration)

        # Max iterations reached — final answer without tools
        print(f"[AGENT] Max iterations ({self.max_iterations}) reached, requesting final answer")
        final_response: LLMResponse = await self.llm.chat(
            msgs, self.model, self.temperature,
            session_id=self.session_id,
            agent_type="agent:final",
        )
        return final_response.content or ""

    # ------------------------------------------------------------------
    # Streaming run
    # ------------------------------------------------------------------

    async def run_stream(
        self,
        messages: List[Dict[str, Any]],
        attached_files: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[StreamEvent]:
        self._refresh_available_rag_collections()
        system_prompt = self._build_system_prompt(attached_files)
        msgs: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}] + list(messages)
        tool_schemas = self._get_tool_schemas()

        for iteration in range(self.max_iterations):
            check_stop()
            print(f"\n[AGENT-STREAM] Iteration {iteration + 1}/{self.max_iterations}")

            self._iteration_boundaries.append(len(msgs))

            collected_tool_event: Optional[ToolCallDeltaEvent] = None

            async for event in self.llm.chat_stream(
                msgs, self.model, self.temperature,
                tools=tool_schemas,
                session_id=self.session_id,
                agent_type="agent:stream",
            ):
                if isinstance(event, TextEvent):
                    yield event
                elif isinstance(event, ToolCallDeltaEvent):
                    collected_tool_event = event

            if not collected_tool_event:
                return

            # Tool calls detected — emit status events and execute in parallel
            msgs.append(self._build_assistant_tool_msg(collected_tool_event.tool_calls))

            # Emit "started" events for all tools
            for tc in collected_tool_event.tool_calls:
                yield ToolStatusEvent(
                    tool_name=tc.function.name,
                    tool_call_id=tc.id,
                    status="started",
                )

            # Execute all tools in parallel
            start_time = time.time()
            results = await self._execute_tools_parallel(collected_tool_event.tool_calls)

            # Emit "completed"/"failed" events and append results
            for tc, result in zip(collected_tool_event.tool_calls, results):
                duration = time.time() - start_time
                status = "completed" if result.get("success", True) else "failed"
                yield ToolStatusEvent(
                    tool_name=tc.function.name,
                    tool_call_id=tc.id,
                    status=status,
                    duration=round(duration, 2),
                )
                msgs.append(self._build_tool_result_msg(tc, result))

            # Compress old iterations
            self._compress_old_iterations(msgs, iteration)

        # Max iterations — final answer without tools
        print(f"[AGENT-STREAM] Max iterations ({self.max_iterations}) reached, requesting final answer")
        async for event in self.llm.chat_stream(
            msgs, self.model, self.temperature,
            session_id=self.session_id,
            agent_type="agent:stream:final",
        ):
            if isinstance(event, TextEvent):
                yield event
