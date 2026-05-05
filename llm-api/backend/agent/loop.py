"""AgentLoop: the main single-while-loop agent that composes all the mixins."""
import asyncio
import hashlib
from typing import List, Dict, Any, Optional, AsyncIterator

import config
from backend.core.llm_backend import (
    StreamEvent, TextEvent,
    ToolCallDeltaEvent, ToolCall, ToolStatusEvent, llm_backend,
)
from backend.utils.stop_signal import check_stop
from tools.schemas import TOOL_METADATA

from backend.agent.logging_helpers import LoggingMixin
from backend.agent.prompt_assembly import PromptMixin
from backend.agent.tool_dispatch import DispatchMixin
from backend.agent.result_formatting import FormattingMixin
from backend.agent.compaction import CompactionMixin


class AgentLoop(LoggingMixin, CompactionMixin, DispatchMixin, FormattingMixin, PromptMixin):
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
        self._filtered_tool_schemas: Optional[List[Dict[str, Any]]] = None
        self._compressed_up_to: int = 0  # tracks how far old-iteration compression has processed
        # Cache log verbosity once (avoids getattr + .lower() on every log call)
        self._log_level: str = str(getattr(config, "AGENT_LOG_VERBOSITY", "summary")).lower()
        # Session-scoped todo list (injected into dynamic context each iteration)
        self._session_todos: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Sampling parameters forwarded to llama.cpp
    # ------------------------------------------------------------------

    def _slot_id(self) -> int:
        digest = hashlib.sha256(self.session_id.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") % config.LLAMACPP_SLOTS

    def _sampling_kwargs(self, final_response: bool = False) -> Dict[str, Any]:
        """Return sampling + slot-pinning params to forward to the LLM backend."""
        kwargs: Dict[str, Any] = {
            "top_p": config.DEFAULT_TOP_P,
            "top_k": config.DEFAULT_TOP_K,
            "min_p": config.DEFAULT_MIN_P,
            "repeat_penalty": config.DEFAULT_REPEAT_PENALTY,
        }
        if final_response:
            kwargs["max_tokens"] = config.DEFAULT_MAX_TOKENS
        else:
            kwargs["max_tokens"] = config.AGENT_TOOL_LOOP_MAX_TOKENS
        # Pin session to a stable llama.cpp KV cache slot for consistent cache hits
        if config.LLAMACPP_SLOTS > 0 and self.session_id:
            kwargs["id_slot"] = self._slot_id()
        return kwargs

    # ------------------------------------------------------------------
    # Non-streaming run — thin accumulator over run_stream().
    # The entire loop is streaming under the hood; this method just
    # collects text events into a final string for callers that don't
    # need incremental output.
    # ------------------------------------------------------------------

    async def run(
        self,
        messages: List[Dict[str, Any]],
        attached_files: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        parts: list[str] = []
        async for event in self.run_stream(messages, attached_files):
            if isinstance(event, TextEvent):
                parts.append(event.content)
        return "".join(parts)

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

            # Collect all tool calls and start executing them as soon as their
            # args are complete (is_partial=True events arrive mid-stream).
            all_tool_calls: list[ToolCall] = []
            # (tc, asyncio.Task) pairs — tasks may already be running by stream end
            pending_tasks: list[tuple[ToolCall, asyncio.Task]] = []
            # Accumulate any text the model streams alongside tool calls so the
            # assistant turn we record back into msgs preserves it. Without this,
            # the model sees content=None next iteration and may emit empty replies.
            streamed_text_parts: list[str] = []
            log_start = len(self.tool_calls_log)

            # Compressed view is rebuilt per attempt inside the wrapper. msgs
            # is the source-of-truth list; auto-compact mutates it on overflow.
            async for event in self._stream_with_autocompact(
                msgs, self.model, self.temperature,
                iteration=iteration,
                tools=tool_schemas,
                session_id=self.session_id,
                agent_type="agent:stream",
                **self._sampling_kwargs(final_response=True),
            ):
                if isinstance(event, TextEvent):
                    streamed_text_parts.append(event.content)
                    yield event
                elif isinstance(event, ToolCallDeltaEvent):
                    for tc in event.tool_calls:
                        all_tool_calls.append(tc)
                        # Start execution immediately — don't wait for the full stream
                        task = asyncio.create_task(
                            self.execute_tool(tc.function.name, tc.function.arguments, tc.id)
                        )
                        pending_tasks.append((tc, task))
                        _meta = TOOL_METADATA.get(tc.function.name, {})
                        yield ToolStatusEvent(
                            tool_name=tc.function.name,
                            tool_call_id=tc.id,
                            status="started",
                            activity=_meta.get("activity", ""),
                            user_name=_meta.get("user_name", ""),
                        )

            if not all_tool_calls:
                # Empty stream after tool results: model produced no text and no
                # tool calls. Some chat templates emit an end-of-turn token right
                # after a tool result, leaving the user with nothing. Retry once
                # with tools disabled to force a final text answer.
                if not streamed_text_parts and iteration > 0:
                    self._log("[AGENT] Empty LLM response after tool result — retrying without tools")
                    async for event in self._stream_with_autocompact(
                        msgs, self.model, self.temperature,
                        iteration=iteration,
                        session_id=self.session_id,
                        agent_type="agent:stream:empty-retry",
                        **self._sampling_kwargs(final_response=True),
                    ):
                        if isinstance(event, TextEvent):
                            yield event
                self._log_agent_complete("LLM returned final text response (stream)", iteration + 1)
                return

            # Log what the LLM requested
            self._log_tool_calls_requested(all_tool_calls, iteration)

            # Append assistant message (must contain ALL tool calls before results)
            msgs.append(self._build_assistant_tool_msg(
                all_tool_calls,
                content="".join(streamed_text_parts).strip() or None,
            ))

            # Gather results — many tasks may already be done since they started mid-stream
            results = await asyncio.gather(*[t for _, t in pending_tasks])

            new_entries = self.tool_calls_log[log_start:]
            duration_by_call_id = {
                e.get("tool_call_id"): e.get("duration", 0)
                for e in new_entries
            }
            durations = [duration_by_call_id.get(tc.id, 0) for tc in all_tool_calls]
            self._log_execution_summary(all_tool_calls, results, durations, iteration)

            # Emit "completed"/"failed" events and append results
            for tc, result in zip(all_tool_calls, results):
                duration = duration_by_call_id.get(tc.id, 0)
                status = "completed" if result.get("success", True) else "failed"
                _meta = TOOL_METADATA.get(tc.function.name, {})
                yield ToolStatusEvent(
                    tool_name=tc.function.name,
                    tool_call_id=tc.id,
                    status=status,
                    duration=round(duration, 2),
                    activity=_meta.get("activity", ""),
                    user_name=_meta.get("user_name", ""),
                )
                msgs.append(self._build_tool_result_msg(tc, result))

            # If any tool requested clarification, relay the question to the user
            # and pause the loop. The user's next message resumes with full context.
            clarifications = [
                (tc, r) for tc, r in zip(all_tool_calls, results)
                if r.get("needs_clarification")
            ]
            if clarifications:
                if len(clarifications) == 1:
                    tc, r = clarifications[0]
                    question = r.get("question") or r.get("error") or "Need more information to proceed."
                    relay = question
                else:
                    lines = ["I need some clarification before I can continue:\n"]
                    for i, (tc, r) in enumerate(clarifications, 1):
                        q = r.get("question") or r.get("error") or "?"
                        lines.append(f"{i}. **{tc.function.name}**: {q}")
                    relay = "\n".join(lines)
                self._log(f"  [CLARIFICATION] Pausing — relaying question to user: {relay[:300]}")
                self._log_agent_complete("Tool requested clarification from user", iteration + 1)
                yield TextEvent(content=relay)
                return

        # Max iterations — final answer without tools
        print(f"[AGENT-STREAM] Max iterations ({self.max_iterations}) reached, requesting final answer")
        self._log_agent_complete(f"Max iterations ({self.max_iterations}) reached (stream)", self.max_iterations)
        async for event in self._stream_with_autocompact(
            msgs, self.model, self.temperature,
            iteration=self.max_iterations,
            use_compressed_view=False,
            session_id=self.session_id,
            agent_type="agent:stream:final",
            **self._sampling_kwargs(final_response=True),
        ):
            if isinstance(event, TextEvent):
                yield event
