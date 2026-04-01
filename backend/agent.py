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
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, AsyncIterator
from uuid import uuid4

import config
from backend.core.llm_backend import (
    LLMResponse, StreamEvent, TextEvent,
    ToolCallDeltaEvent, ToolCall, ToolStatusEvent, llm_backend,
)
from backend.utils.stop_signal import check_stop
from backend.utils.flush_logging import print_agent_log_banner_once
from backend.utils.prompts_log_append import append_capped_prompts_log


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

# Module-level RAG collections cache: {username: {"collections": [...], "expires_at": float}}
_rag_collections_cache: Dict[str, Dict[str, Any]] = {}
_RAG_CACHE_TTL: float = 60.0


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
        self._tool_cache: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Sampling parameters forwarded to llama.cpp
    # ------------------------------------------------------------------

    def _sampling_kwargs(self, final_response: bool = False) -> Dict[str, Any]:
        """Return sampling + slot-pinning params to forward to the LLM backend."""
        kwargs: Dict[str, Any] = {}
        if hasattr(config, 'DEFAULT_TOP_P'):
            kwargs["top_p"] = config.DEFAULT_TOP_P
        if hasattr(config, 'DEFAULT_TOP_K'):
            kwargs["top_k"] = config.DEFAULT_TOP_K
        if hasattr(config, 'DEFAULT_MIN_P'):
            kwargs["min_p"] = config.DEFAULT_MIN_P
        if final_response:
            if hasattr(config, 'DEFAULT_MAX_TOKENS'):
                kwargs["max_tokens"] = config.DEFAULT_MAX_TOKENS
        elif hasattr(config, 'AGENT_TOOL_LOOP_MAX_TOKENS'):
            kwargs["max_tokens"] = config.AGENT_TOOL_LOOP_MAX_TOKENS
        elif hasattr(config, 'DEFAULT_MAX_TOKENS'):
            kwargs["max_tokens"] = config.DEFAULT_MAX_TOKENS
        if hasattr(config, 'DEFAULT_REPEAT_PENALTY'):
            kwargs["repeat_penalty"] = config.DEFAULT_REPEAT_PENALTY
        # Pin session to a stable llama.cpp KV cache slot for consistent cache hits
        num_slots = getattr(config, 'LLAMACPP_SLOTS', 0)
        if num_slots > 0 and self.session_id:
            kwargs["id_slot"] = hash(self.session_id) % num_slots
        return kwargs

    # ------------------------------------------------------------------
    # Prompts.log logging (agent-level events)
    # ------------------------------------------------------------------

    def _log_verbosity(self) -> str:
        return str(getattr(config, "AGENT_LOG_VERBOSITY", "summary")).lower()

    def _summary_logging_enabled(self) -> bool:
        return self._log_verbosity() in {"summary", "debug"}

    def _debug_logging_enabled(self) -> bool:
        return self._log_verbosity() == "debug"

    def _write_log_sync(self, message: str):
        path = Path(getattr(config, "AGENT_LOG_PATH", config.PROMPTS_LOG_PATH))
        print_agent_log_banner_once(path)
        append_capped_prompts_log(
            message if message.endswith("\n") else message + "\n",
            path=path,
        )

    def _log(self, message: str):
        """Append a line to prompts.log."""
        if not self._summary_logging_enabled():
            return
        try:
            if getattr(config, "AGENT_LOG_ASYNC", True):
                try:
                    loop = asyncio.get_running_loop()
                    loop.run_in_executor(None, self._write_log_sync, message)
                    return
                except RuntimeError:
                    pass
            self._write_log_sync(message)
        except Exception as e:
            print(f"[AGENT-LOG] Failed to write to prompts.log: {e}")

    def _log_block(self, lines: List[str]):
        """Write multiple lines to prompts.log as a single block."""
        self._log('\n'.join(lines))

    def _log_iteration_start(self, iteration: int, streaming: bool = False):
        tag = "STREAM " if streaming else ""
        self._log_block([
            "",
            "~" * 80,
            f">>> AGENT {tag}ITERATION {iteration + 1}/{self.max_iterations}",
            "~" * 80,
            f"  Session:     {self.session_id or 'N/A'}",
            f"  Username:    {self.username or 'N/A'}",
            f"  Timestamp:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "~" * 80,
            "",
        ])

    def _log_tool_calls_requested(self, tool_calls: List[ToolCall], iteration: int):
        if not self._summary_logging_enabled():
            return
        lines = [
            "",
            "-" * 80,
            f">>> LLM REQUESTED TOOL CALLS (Iteration {iteration + 1})",
            "-" * 80,
            f"  Tool Count:  {len(tool_calls)}",
            f"  Timestamp:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
        for i, tc in enumerate(tool_calls, 1):
            lines.append(f"  [{i}] {tc.function.name} (id: {tc.id})")
            arg_cap = 500 if self._debug_logging_enabled() else 280
            for k, v in tc.function.arguments.items():
                sv = str(v)
                if len(sv) > arg_cap:
                    sv = sv[:arg_cap] + f"... [{len(sv)} chars total]"
                lines.append(f"      {k}: {sv}")
            lines.append("")
        lines.append("-" * 80)
        lines.append("")
        self._log_block(lines)

    def _log_tool_result(self, tool_name: str, tool_call_id: str,
                         result: Dict[str, Any], duration: float):
        if not self._summary_logging_enabled():
            return
        success = result.get("success", True)
        lines = [
            "",
            "." * 80,
            f"<<< TOOL RESULT: {tool_name} [{tool_call_id or 'N/A'}]",
            "." * 80,
            f"  Status:      {'SUCCESS' if success else 'FAILED'}",
            f"  Duration:    {duration:.2f}s",
        ]
        if not success and result.get("error"):
            lines.append(f"  Error:       {str(result['error'])[:500]}")
        if self._debug_logging_enabled():
            result_str = json.dumps(result, ensure_ascii=False, default=str)
            if len(result_str) > 1500:
                lines.append(f"  Result:      {result_str[:1500]}")
                lines.append(f"               ... [{len(result_str)} chars total]")
            else:
                lines.append(f"  Result:      {result_str}")
        else:
            lines.append(f"  Executed:    {result.get('executed', 'N/A')}")
            lines.append(f"  Return Code: {result.get('returncode', 'N/A')}")
            preview_cap = 450
            for key in ("stdout", "stderr", "output", "message"):
                chunk = result.get(key)
                if chunk is None:
                    continue
                s = str(chunk).strip()
                if not s:
                    continue
                label = key.upper()
                if len(s) > preview_cap:
                    s = s[:preview_cap] + f"... [{len(str(chunk))} chars total]"
                lines.append(f"  {label}:       {s}")
        lines.append("." * 80)
        lines.append("")
        self._log_block(lines)

    def _log_execution_summary(self, tool_calls: List[ToolCall],
                               results: List[Dict[str, Any]],
                               durations: List[float], iteration: int):
        succeeded = sum(1 for r in results if r.get("success", True))
        failed = len(results) - succeeded
        wall_time = max(durations) if durations else 0
        lines = [
            "",
            "-" * 80,
            f">>> TOOL EXECUTION SUMMARY (Iteration {iteration + 1})",
            "-" * 80,
            f"  Tools Run:   {len(results)}",
            f"  Succeeded:   {succeeded}",
            f"  Failed:      {failed}",
            f"  Wall Time:   {wall_time:.2f}s (parallel execution)",
            "",
        ]
        for i, (tc, res, dur) in enumerate(zip(tool_calls, results, durations), 1):
            status = "SUCCESS" if res.get("success", True) else "FAILED"
            lines.append(f"  [{i}] {tc.function.name:<20s} -- {status} ({dur:.2f}s)")
        lines.extend(["", "-" * 80, ""])
        self._log_block(lines)

    def _log_agent_complete(self, reason: str, iterations_used: int):
        self._log_block([
            "",
            "~" * 80,
            ">>> AGENT COMPLETE",
            "~" * 80,
            f"  Reason:      {reason}",
            f"  Iterations:  {iterations_used}",
            f"  Tool Calls:  {len(self.tool_calls_log)}",
            f"  Session:     {self.session_id or 'N/A'}",
            f"  Username:    {self.username or 'N/A'}",
            f"  Timestamp:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "~" * 80,
            "",
        ])

    # ------------------------------------------------------------------
    # System prompt (cached, with per-request file attachments appended)
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Return the STATIC system prompt (byte-stable for KV cache reuse)."""
        return _CACHED_SYSTEM_PROMPT

    def _build_dynamic_context(self, attached_files: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
        """Return per-request dynamic context (RAG, memo, files). Separate from
        system prompt so the static prefix stays byte-identical for cache_prompt."""
        parts = []
        rag_ctx = self._format_rag_collections_context()
        if rag_ctx:
            parts.append(rag_ctx)
        if self.username and "memo" in self.enabled_tools:
            from tools.memo.tool import MemoTool
            memo_ctx = MemoTool.load_for_prompt(self.username)
            if memo_ctx:
                memo_cap = getattr(config, "AGENT_MEMO_MAX_CHARS", 2000)
                if len(memo_ctx) > memo_cap:
                    memo_ctx = memo_ctx[:memo_cap] + "\n...[memo context truncated]"
                parts.append(memo_ctx)
        if attached_files:
            parts.append(self._format_attached_files(attached_files))
        if not parts:
            return None
        dynamic_ctx = "\n".join(parts)
        dynamic_cap = getattr(config, "AGENT_DYNAMIC_CONTEXT_MAX_CHARS", 6000)
        if len(dynamic_ctx) > dynamic_cap:
            dynamic_ctx = dynamic_ctx[:dynamic_cap] + "\n...[dynamic context truncated]"
        return dynamic_ctx

    def _refresh_available_rag_collections(self):
        """Load available RAG collections for the current user (60s module-level TTL cache)."""
        self._available_rag_collections = []

        if "rag" not in self.enabled_tools or not self.username:
            return

        # Check module-level cache first
        cached = _rag_collections_cache.get(self.username)
        if cached and time.time() < cached["expires_at"]:
            self._available_rag_collections = cached["collections"]
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
            _rag_collections_cache[self.username] = {
                "collections": names,
                "expires_at": time.time() + _RAG_CACHE_TTL,
            }
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
                preview_cap = getattr(config, "AGENT_FILE_PREVIEW_MAX_CHARS", 120)
                lines.append(f"   Preview: {str(f['preview'])[:preview_cap]}...")
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

    async def execute_tool(self, name: str, arguments: Dict[str, Any],
                           tool_call_id: str = None) -> Dict[str, Any]:
        start = time.time()
        print(f"\n{'='*70}")
        print(f"[TOOL] Executing: {name}")
        print(f"{'='*70}")
        for k, v in arguments.items():
            sv = str(v)
            print(f"  {k}: {sv[:150]}{'...' if len(sv) > 150 else ''}")

        try:
            result = await self._dispatch_tool(name, arguments)
            duration = time.time() - start
            print(f"[TOOL] {name} completed in {duration:.2f}s — success={result.get('success', '?')}")
            self.tool_calls_log.append({
                "name": name, "input": arguments,
                "tool_call_id": tool_call_id,
                "success": result.get("success", True), "duration": duration,
            })
            self._log_tool_result(name, tool_call_id, result, duration)
            return result
        except Exception as e:
            duration = time.time() - start
            print(f"[TOOL] {name} FAILED in {duration:.2f}s — {e}")
            err_result = {"success": False, "error": str(e)}
            self.tool_calls_log.append({
                "name": name, "input": arguments,
                "tool_call_id": tool_call_id,
                "success": False, "error": str(e), "duration": duration,
            })
            self._log_tool_result(name, tool_call_id, err_result, duration)
            return err_result

    async def _execute_tools_parallel(self, tool_calls: List[ToolCall]) -> List[Dict[str, Any]]:
        """Execute multiple tool calls concurrently."""
        tasks = [
            self.execute_tool(tc.function.name, tc.function.arguments, tool_call_id=tc.id)
            for tc in tool_calls
        ]
        return await asyncio.gather(*tasks)

    async def _dispatch_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        cache = self._tool_cache

        if name == "websearch":
            if "websearch" not in cache:
                from tools.web_search import WebSearchTool
                cache["websearch"] = WebSearchTool()
            return await asyncio.to_thread(
                cache["websearch"].search,
                query=arguments["query"],
                max_results=arguments.get("max_results"),
            )

        elif name == "python_coder":
            if "python_coder" not in cache:
                from tools.python_coder import PythonCoderTool
                cache["python_coder"] = PythonCoderTool(session_id=self.session_id)
            return await cache["python_coder"].execute(
                instruction=arguments["instruction"],
                timeout=arguments.get("timeout"),
            )

        elif name == "rag":
            if "rag" not in cache:
                from tools.rag import RAGTool
                cache["rag"] = RAGTool(username=self.username)
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

            return await asyncio.to_thread(
                cache["rag"].retrieve,
                collection_name=requested_collection,
                query=arguments["query"],
                max_results=arguments.get("max_results"),
            )

        elif name == "file_reader":
            if "file_reader" not in cache:
                from tools.file_ops import FileReaderTool
                cache["file_reader"] = FileReaderTool(username=self.username, session_id=self.session_id)
            return await asyncio.to_thread(
                cache["file_reader"].read,
                path=arguments["path"],
                offset=arguments.get("offset"),
                limit=arguments.get("limit"),
            )

        elif name == "file_writer":
            if "file_writer" not in cache:
                from tools.file_ops import FileWriterTool
                cache["file_writer"] = FileWriterTool(session_id=self.session_id)
            return await asyncio.to_thread(
                cache["file_writer"].write,
                path=arguments["path"],
                content=arguments["content"],
                mode=arguments.get("mode", "write"),
            )

        elif name == "file_navigator":
            if "file_navigator" not in cache:
                from tools.file_ops import FileNavigatorTool
                cache["file_navigator"] = FileNavigatorTool(username=self.username, session_id=self.session_id)
            return await asyncio.to_thread(
                cache["file_navigator"].navigate,
                operation=arguments["operation"],
                path=arguments.get("path"),
                pattern=arguments.get("pattern"),
            )

        elif name == "shell_exec":
            if "shell_exec" not in cache:
                from tools.shell import ShellExecTool
                cache["shell_exec"] = ShellExecTool(session_id=self.session_id)
            return await cache["shell_exec"].execute(
                command=arguments["command"],
                timeout=arguments.get("timeout", 300),
                working_directory=arguments.get("working_directory"),
            )

        elif name == "memo":
            if "memo" not in cache:
                from tools.memo import MemoTool
                cache["memo"] = MemoTool(username=self.username)
            return await asyncio.to_thread(
                cache["memo"].execute,
                operation=arguments["operation"],
                key=arguments.get("key"),
                value=arguments.get("value"),
            )

        elif name == "process_monitor":
            if "process_monitor" not in cache:
                from tools.process_monitor import ProcessMonitorTool
                cache["process_monitor"] = ProcessMonitorTool(session_id=self.session_id)
            return await asyncio.to_thread(
                cache["process_monitor"].execute,
                operation=arguments["operation"],
                command=arguments.get("command"),
                handle=arguments.get("handle"),
                working_directory=arguments.get("working_directory"),
                offset=arguments.get("offset"),
                max_lines=arguments.get("max_lines"),
                stream=arguments.get("stream"),
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

        self._log(f"  [MICROCOMPACT] {tool_name} result truncated: {len(content)} -> {budget} chars")

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

        compressed_count = 0
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
            summary_cap = getattr(config, "AGENT_OLD_TOOL_RESULT_SUMMARY_MAX_CHARS", 80)
            summary = content[:summary_cap].replace('\n', ' ')
            msg["content"] = f"[{tool_name} result — {summary}...]"
            compressed_count += 1
        if compressed_count:
            self._log(f"  [MICROCOMPACT] Compressed {compressed_count} old tool result(s) "
                      f"from iterations before {current_iteration + 1}")

    # ------------------------------------------------------------------
    # History limit enforcement
    # ------------------------------------------------------------------

    def _enforce_history_limit(self, msgs: List[Dict[str, Any]]):
        """Enforce MAX_CONVERSATION_HISTORY by dropping old messages.

        When the conversation exceeds the limit:
        1. Keep system messages at the front (indices 0, 1, ...)
        2. Drop oldest non-system messages, replacing with a compaction notice
        3. Compress tool results in remaining old messages

        Operates in-place on *msgs*.
        """
        limit = config.MAX_CONVERSATION_HISTORY
        if len(msgs) <= limit:
            return

        # Find where system messages end
        system_end = 0
        for i, msg in enumerate(msgs):
            if msg.get("role") == "system":
                system_end = i + 1
            else:
                break

        non_system = msgs[system_end:]
        excess = len(non_system) - limit

        if excess > 0:
            dropped = non_system[:excess]
            kept = non_system[excess:]
            # Build compaction notice
            dropped_roles = {}
            for m in dropped:
                r = m.get("role", "unknown")
                dropped_roles[r] = dropped_roles.get(r, 0) + 1
            summary_parts = [f"{v} {k}" for k, v in dropped_roles.items()]
            notice = f"[Compacted {len(dropped)} earlier messages: {', '.join(summary_parts)}]"
            # Rebuild msgs in-place
            msgs[system_end:] = [{"role": "system", "content": notice}] + kept
            print(f"[AGENT] History compacted: dropped {len(dropped)} old messages "
                  f"({len(msgs)} remaining, limit {limit})")

        # Additionally compress old tool results in the kept portion
        # (compress everything except the last limit//2 messages)
        compress_boundary = len(msgs) - limit // 2
        masked = 0
        for i in range(system_end, compress_boundary):
            msg = msgs[i]
            if msg.get("role") != "tool":
                continue
            content = msg.get("content", "")
            if len(content) <= 120:
                continue
            tool_name = msg.get("name", "tool")
            summary = content[:50].replace("\n", " ")
            msg["content"] = f"[{tool_name}: {summary}...]"
            masked += 1
        if masked:
            print(f"[AGENT] Compressed {masked} old tool result(s)")

    # ------------------------------------------------------------------
    # Non-streaming run
    # ------------------------------------------------------------------

    async def run(
        self,
        messages: List[Dict[str, Any]],
        attached_files: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        self._refresh_available_rag_collections()
        # Static system prompt first (byte-stable → KV cache hit)
        system_prompt = self._build_system_prompt()
        msgs: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        # Dynamic context in a separate message (changes per request, doesn't break prefix cache)
        dynamic_ctx = self._build_dynamic_context(attached_files)
        if dynamic_ctx:
            msgs.append({"role": "system", "content": dynamic_ctx})
        msgs.extend(messages)
        self._enforce_history_limit(msgs)
        tool_schemas = self._get_tool_schemas()

        for iteration in range(self.max_iterations):
            check_stop()
            print(f"\n[AGENT] Iteration {iteration + 1}/{self.max_iterations}")
            self._log_iteration_start(iteration)

            # Track iteration boundaries for microcompaction
            self._iteration_boundaries.append(len(msgs))

            response: LLMResponse = await self.llm.chat(
                msgs, self.model, self.temperature,
                tools=tool_schemas,
                session_id=self.session_id,
                agent_type="agent",
                **self._sampling_kwargs(final_response=False),
            )

            if not response.tool_calls:
                self._log_agent_complete("LLM returned final text response", iteration + 1)
                return response.content or ""

            # Log what the LLM wants to call
            self._log_tool_calls_requested(response.tool_calls, iteration)

            # Append assistant message with tool_calls
            msgs.append(self._build_assistant_tool_msg(response.tool_calls))

            # Execute all tools in parallel (individual results logged in execute_tool)
            log_start = len(self.tool_calls_log)
            results = await self._execute_tools_parallel(response.tool_calls)
            new_entries = self.tool_calls_log[log_start:]
            duration_by_call_id = {
                e.get("tool_call_id"): e.get("duration", 0)
                for e in new_entries
            }
            durations = [duration_by_call_id.get(tc.id, 0) for tc in response.tool_calls]
            self._log_execution_summary(response.tool_calls, results, durations, iteration)

            for tc, result in zip(response.tool_calls, results):
                msgs.append(self._build_tool_result_msg(tc, result))

            # Compress old iteration tool results (hot tail: keep current full)
            self._compress_old_iterations(msgs, iteration)

        # Max iterations reached — final answer without tools
        print(f"[AGENT] Max iterations ({self.max_iterations}) reached, requesting final answer")
        self._log_agent_complete(f"Max iterations ({self.max_iterations}) reached", self.max_iterations)
        final_response: LLMResponse = await self.llm.chat(
            msgs, self.model, self.temperature,
            session_id=self.session_id,
            agent_type="agent:final",
            **self._sampling_kwargs(final_response=True),
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
        system_prompt = self._build_system_prompt()
        msgs: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        dynamic_ctx = self._build_dynamic_context(attached_files)
        if dynamic_ctx:
            msgs.append({"role": "system", "content": dynamic_ctx})
        msgs.extend(messages)
        self._enforce_history_limit(msgs)
        tool_schemas = self._get_tool_schemas()

        for iteration in range(self.max_iterations):
            check_stop()
            print(f"\n[AGENT-STREAM] Iteration {iteration + 1}/{self.max_iterations}")
            self._log_iteration_start(iteration, streaming=True)

            self._iteration_boundaries.append(len(msgs))

            collected_tool_event: Optional[ToolCallDeltaEvent] = None

            async for event in self.llm.chat_stream(
                msgs, self.model, self.temperature,
                tools=tool_schemas,
                session_id=self.session_id,
                agent_type="agent:stream",
                **self._sampling_kwargs(final_response=False),
            ):
                if isinstance(event, TextEvent):
                    yield event
                elif isinstance(event, ToolCallDeltaEvent):
                    collected_tool_event = event

            if not collected_tool_event:
                self._log_agent_complete("LLM returned final text response (stream)", iteration + 1)
                return

            # Log what the LLM wants to call
            self._log_tool_calls_requested(collected_tool_event.tool_calls, iteration)

            # Tool calls detected — emit status events and execute in parallel
            msgs.append(self._build_assistant_tool_msg(collected_tool_event.tool_calls))

            # Emit "started" events for all tools
            for tc in collected_tool_event.tool_calls:
                yield ToolStatusEvent(
                    tool_name=tc.function.name,
                    tool_call_id=tc.id,
                    status="started",
                )

            # Execute all tools in parallel (individual results logged in execute_tool)
            log_start = len(self.tool_calls_log)
            start_time = time.time()
            results = await self._execute_tools_parallel(collected_tool_event.tool_calls)
            new_entries = self.tool_calls_log[log_start:]
            duration_by_call_id = {
                e.get("tool_call_id"): e.get("duration", 0)
                for e in new_entries
            }
            durations = [duration_by_call_id.get(tc.id, 0) for tc in collected_tool_event.tool_calls]
            self._log_execution_summary(collected_tool_event.tool_calls, results, durations, iteration)

            # Emit "completed"/"failed" events and append results
            for tc, result in zip(collected_tool_event.tool_calls, results):
                duration = duration_by_call_id.get(tc.id)
                if duration is None:
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
        self._log_agent_complete(f"Max iterations ({self.max_iterations}) reached (stream)", self.max_iterations)
        async for event in self.llm.chat_stream(
            msgs, self.model, self.temperature,
            session_id=self.session_id,
            agent_type="agent:stream:final",
            **self._sampling_kwargs(final_response=True),
        ):
            if isinstance(event, TextEvent):
                yield event
