"""AgentLoop: the main single-while-loop agent that composes all the mixins."""
import asyncio
import hashlib
import json as _json
from collections import deque
from pathlib import Path
from typing import List, Dict, Any, Optional, AsyncIterator, Deque, Tuple

import config
from backend.core.llm_backend import (
    StreamEvent, TextEvent, ReasoningEvent,
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
    - Parallel read-only tool execution
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
        workspace_dir: Optional[str] = None,
    ):
        self.model = model or config.LLAMACPP_MODEL
        self.temperature = self._resolve_temperature(temperature)
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

        # Per-session workspace dir. None preserves legacy behaviour (relative
        # paths resolve against scratch/uploads/CWD). When set, file_reader,
        # file_navigator, file_editor, file_writer, apply_patch,
        # and shell_exec all treat it as the project root.
        self.workspace_dir: Optional[Path] = self._validate_workspace(workspace_dir)

        # ----- Reflection / anti-spiral state -----
        # (tool_name, sha1(args_canonical_json)[:16]) tuples in arrival order.
        self._tool_call_history: Deque[Tuple[str, str]] = deque(maxlen=64)
        # Iteration index where the last repeat-call reminder was injected.
        self._last_repeat_reminder_iter: int = -10**6
        # Per-iteration tool-success ledger (1 = all-failed, 0 = at least one success).
        self._iteration_failures: Deque[int] = deque(maxlen=8)
        # Carry-forward goal extracted from autocompact summary (active goal line).
        self._carried_active_goal: Optional[str] = None
        # Iterations at which milestone goal reminders have been emitted (so we
        # don't double-inject when the loop reattempts after autocompact).
        self._emitted_goal_reminder_iters: set = set()
        # True after we inject the first-iteration plan nudge so it doesn't fire
        # repeatedly across autocompact retries.
        self._plan_nudge_emitted: bool = False

        # New files created by file_writer/apply_patch during this run that
        # weren't flagged persist=True. Swept at end of run_stream so the agent
        # doesn't litter the workspace with temp scripts/scratch files.
        self._tracked_new_files: set[str] = set()

        # AGENTS.md / CLAUDE.md files already injected this session. The
        # tool_dispatch walk-up uses this set to inject each subtree
        # instruction file at most once. Resolved paths as strings.
        self._agents_md_seen: set[str] = set()

    # ------------------------------------------------------------------
    # Sampling parameters forwarded to llama.cpp
    # ------------------------------------------------------------------

    def _slot_id(self) -> int:
        digest = hashlib.sha256(self.session_id.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") % config.LLAMACPP_SLOTS

    def _resolve_temperature(self, requested: Optional[float]) -> float:
        """Pick the temperature for this session.

        Caller-supplied value wins. Otherwise look up MODEL_TEMPERATURE_OVERRIDES
        for a substring match on the model name (e.g. 'minimax' -> 1.0 per
        MiniMax M2 official recommendation). Falls back to DEFAULT_TEMPERATURE.
        """
        if requested is not None:
            return requested
        overrides = getattr(config, "MODEL_TEMPERATURE_OVERRIDES", None) or {}
        if overrides:
            model_lower = (self.model or "").lower()
            for needle, temp in overrides.items():
                if needle and needle.lower() in model_lower:
                    return float(temp)
        return config.DEFAULT_TEMPERATURE

    # ------------------------------------------------------------------
    # Workspace validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_workspace(raw: Optional[str]) -> Optional[Path]:
        """Resolve and validate a workspace path supplied by the caller.

        Returns None for unset / invalid values rather than raising — an
        unknown workspace should degrade to legacy behaviour, not break the
        chat request. Validation errors are printed for the operator.
        """
        if not raw:
            default = getattr(config, "AGENT_DEFAULT_WORKSPACE", None)
            raw = default if default else None
        if not raw:
            return None
        try:
            p = Path(raw).expanduser().resolve()
        except Exception as e:
            print(f"[AGENT] Ignoring invalid workspace path '{raw}': {e}")
            return None
        if not p.exists() or not p.is_dir():
            print(f"[AGENT] Ignoring workspace '{p}' - directory does not exist")
            return None
        # Refuse to point the agent at its own install root by default — the
        # agent editing itself is almost always unintentional.
        try:
            api_root = config.APP_DIR.resolve()
            if p == api_root:
                print(f"[AGENT] Refusing workspace == llm-api install dir ({p})")
                return None
        except Exception:
            pass
        return p

    # ------------------------------------------------------------------
    # Reflection helpers (anti-spiral)
    # ------------------------------------------------------------------

    @staticmethod
    def _tool_signature(name: str, arguments: Any) -> Tuple[str, str]:
        """Return (tool_name, short_arg_hash) — used for repeat-call detection."""
        try:
            if isinstance(arguments, str):
                canon = arguments
            else:
                canon = _json.dumps(arguments, sort_keys=True, default=str, ensure_ascii=False)
        except Exception:
            canon = repr(arguments)
        h = hashlib.sha1(canon.encode("utf-8", errors="replace")).hexdigest()[:16]
        return name, h

    def _record_iteration_outcome(self, results: List[Dict[str, Any]]) -> None:
        """Append 1 to the failure ledger if every result in this iteration failed."""
        if not results:
            return
        any_success = any(bool(r.get("success", True)) for r in results)
        self._iteration_failures.append(0 if any_success else 1)

    def _detect_repeat_call(self, current_iteration: int) -> Optional[str]:
        """Return a reminder string when the most recent tool signature has
        appeared >= threshold times within the recent window. Otherwise None.

        Honors a cooldown so the same reminder isn't injected every iteration.
        """
        threshold = max(2, getattr(config, "AGENT_STUCK_REPEAT_THRESHOLD", 3))
        window = max(threshold, getattr(config, "AGENT_STUCK_REPEAT_WINDOW", 6))
        cooldown = max(0, getattr(config, "AGENT_STUCK_COOLDOWN_ITERATIONS", 4))
        if current_iteration - self._last_repeat_reminder_iter < cooldown:
            return None
        if len(self._tool_call_history) < threshold:
            return None
        recent = list(self._tool_call_history)[-window:]
        if not recent:
            return None
        latest_sig = recent[-1]
        count = sum(1 for sig in recent if sig == latest_sig)
        if count < threshold:
            return None
        self._last_repeat_reminder_iter = current_iteration
        tool_name = latest_sig[0]
        return (
            f"<system-reminder>The `{tool_name}` call has run {count} times with "
            f"similar arguments in the last {window} tool rounds and isn't "
            f"producing new information. Stop repeating it. Choose one: "
            f"(a) try a fundamentally different approach, (b) ask the user "
            f"for clarification, or (c) report what you've found and what's "
            f"blocking you.</system-reminder>"
        )

    def _detect_consecutive_failures(self) -> Optional[str]:
        """Return a reflection reminder when the last N iterations all failed."""
        threshold = max(2, getattr(config, "AGENT_CONSECUTIVE_FAILURE_THRESHOLD", 2))
        recent = list(self._iteration_failures)[-threshold:]
        if len(recent) < threshold or not all(recent):
            return None
        return (
            f"<system-reminder>The last {threshold} tool rounds all failed. "
            f"Step back: re-read the user's latest request, identify the "
            f"assumption that's wrong, and decide whether to (a) investigate "
            f"the failure (read the error), (b) try a different tool or path, "
            f"or (c) ask the user. Do not retry the same call.</system-reminder>"
        )

    def _milestone_goal_reminder(self, current_iteration: int,
                                 latest_user_text: Optional[str]) -> Optional[str]:
        """At configured milestones, re-inject the user's latest request to
        combat lost-in-the-middle on long iteration tails."""
        milestones = tuple(getattr(config, "AGENT_GOAL_REMINDER_ITERATIONS", ()))
        if not milestones or not latest_user_text:
            return None
        if current_iteration not in milestones:
            return None
        if current_iteration in self._emitted_goal_reminder_iters:
            return None
        self._emitted_goal_reminder_iters.add(current_iteration)
        cap = max(200, getattr(config, "AGENT_TAIL_GOAL_MAX_CHARS", 1500))
        text = latest_user_text.strip()
        if len(text) > cap:
            text = text[:cap] + "...[truncated]"
        return (
            f"<system-reminder>User's request (reminder at iteration "
            f"{current_iteration + 1}/{self.max_iterations}): {text}"
            f"</system-reminder>"
        )

    def _plan_nudge(self, current_iteration: int,
                    latest_user_text: Optional[str]) -> Optional[str]:
        """On the first iteration of a session, prompt a brief plan before any
        tool calls. Fires unconditionally — even trivial-looking requests
        benefit from a one-line plan, and the cost (one short reminder) is
        negligible compared to the tool-spam it prevents."""
        if self._plan_nudge_emitted or current_iteration != 0 or not latest_user_text:
            return None
        self._plan_nudge_emitted = True
        return (
            "<system-reminder>Before any tool calls, state a brief plan "
            "(1–5 bullets, scaled to the task). Read provided docs/files "
            "if you haven't. Avoid exploratory grep/search loops — converge "
            "fast on the specific files the task touches.</system-reminder>"
        )

    # ------------------------------------------------------------------
    # Static helpers for view overlays
    # ------------------------------------------------------------------

    @staticmethod
    def _find_last_user_message(msgs: List[Dict[str, Any]]) -> Optional[Tuple[int, str]]:
        """Return (index, text) of the last role=user message, or None.

        Strips list-content (multimodal) blocks to plain text.
        """
        for i in range(len(msgs) - 1, -1, -1):
            m = msgs[i]
            if m.get("role") != "user":
                continue
            content = m.get("content")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(part.get("text", ""))
                text = " ".join(parts)
            else:
                text = str(content) if content is not None else ""
            return i, text
        return None

    @staticmethod
    def _has_prior_assistant_turn(msgs: List[Dict[str, Any]], user_idx: int) -> bool:
        """True if there's any role=assistant message at index < user_idx."""
        for i in range(user_idx):
            if msgs[i].get("role") == "assistant":
                return True
        return False

    # ------------------------------------------------------------------
    # View overlay hook called by CompactionMixin._compress_old_iterations
    # ------------------------------------------------------------------

    def _apply_loop_overlays(
        self,
        view: List[Dict[str, Any]],
        msgs: List[Dict[str, Any]],
        current_iteration: int,
    ) -> None:
        """Insert view-only `<system-reminder>` blocks for:

        - D1: turn-boundary marker before a new user message that follows
          prior assistant turns,
        - B5: plan-first nudge on iteration 0 for long/multi-step requests,
        - B4: milestone goal re-injection at configured iterations,
        - B2: repeat-call detection reminder,
        - B3: consecutive-failure reflection reminder,
        - D3: carried "Active goal" from autocompact,
        - C1: tail-pinned user-goal echo.

        Mutates *view* in place. Never touches *msgs*.
        """
        last_user = self._find_last_user_message(view)
        latest_user_text = last_user[1] if last_user else None
        # Capture pre-overlay view length so the tail-goal min-turns gate uses
        # the real conversation size, not the size after we inserted markers.
        view_len_pre_overlay = len(view)

        # ---- D1: turn-boundary marker ----
        if getattr(config, "AGENT_TURN_BOUNDARY_MARKER_ENABLED", True) and last_user is not None:
            user_idx, _ = last_user
            if self._has_prior_assistant_turn(view, user_idx):
                view.insert(user_idx, {
                    "role": "system",
                    "content": (
                        "<system-reminder>New user request boundary. Earlier "
                        "turns in this session are completed work — treat them "
                        "as background context, not as ongoing constraints, "
                        "unless the user explicitly references them. The "
                        "user's *next* message (immediately after this "
                        "reminder) is the active request.</system-reminder>"
                    ),
                })

        # ---- Tail-injected reminders (appended to view) ----
        tail_blocks: List[str] = []

        # B5: plan nudge (iteration 0 only)
        plan = self._plan_nudge(current_iteration, latest_user_text)
        if plan:
            tail_blocks.append(plan)

        # B4: milestone goal re-injection
        milestone = self._milestone_goal_reminder(current_iteration, latest_user_text)
        if milestone:
            tail_blocks.append(milestone)

        # B2: repeat-call detection
        repeat = self._detect_repeat_call(current_iteration)
        if repeat:
            tail_blocks.append(repeat)

        # B3: consecutive-failure reflection
        failure = self._detect_consecutive_failures()
        if failure:
            tail_blocks.append(failure)

        # D3: carried active goal from autocompact summary
        if self._carried_active_goal:
            cap = max(200, getattr(config, "AGENT_TAIL_GOAL_MAX_CHARS", 1500))
            goal_text = self._carried_active_goal.strip()
            if len(goal_text) > cap:
                goal_text = goal_text[:cap] + "...[truncated]"
            tail_blocks.append(
                f"<system-reminder>Active goal carried forward from earlier "
                f"summary: {goal_text}</system-reminder>"
            )

        # C1: tail-pinned latest user goal (always last, wins recency)
        if (
            getattr(config, "AGENT_TAIL_GOAL_REMINDER_ENABLED", True)
            and latest_user_text
            and view_len_pre_overlay >= getattr(config, "AGENT_TAIL_GOAL_MIN_TURNS", 4)
        ):
            cap = max(200, getattr(config, "AGENT_TAIL_GOAL_MAX_CHARS", 1500))
            text = latest_user_text.strip()
            if len(text) > cap:
                text = text[:cap] + "...[truncated]"
            tail_blocks.append(
                f"<system-reminder>The user's latest request, repeated for "
                f"fidelity (highest priority after system instructions): "
                f"{text}</system-reminder>"
            )

        for block in tail_blocks:
            view.append({"role": "system", "content": block})

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

    def _can_start_tool_immediately(self, tool_name: str, deferred_seen: bool) -> bool:
        """Only start read-only concurrency-safe tools during model streaming."""
        if deferred_seen:
            return False
        meta = TOOL_METADATA.get(tool_name, {})
        return bool(meta.get("is_read_only") and meta.get("is_concurrency_safe"))

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

    def _cleanup_temp_files(self) -> None:
        """Delete files created during this run that weren't flagged persist=True.

        Called from run_stream's finally block — runs even on stop/exception.
        Empty parent dirs are NOT cleaned (would surprise the user if they
        wrote into an existing project dir).
        """
        if not self._tracked_new_files:
            return
        for path in list(self._tracked_new_files):
            try:
                p = Path(path)
                if p.is_file():
                    p.unlink()
                    print(f"[AGENT] Removed temp file: {p}")
            except Exception as exc:
                print(f"[AGENT] Failed to remove temp file {path}: {exc}")
        self._tracked_new_files.clear()

    async def run_stream(
        self,
        messages: List[Dict[str, Any]],
        attached_files: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[StreamEvent]:
        """Run the agent loop and yield events. Wraps _run_stream_body so we
        can sweep non-persisted temp files in a single finally block, even on
        early return / exception / generator close."""
        try:
            async for event in self._run_stream_body(messages, attached_files):
                yield event
        finally:
            self._cleanup_temp_files()

    async def _run_stream_body(
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

            # Collect all tool calls. Read-only safe tools may start during
            # streaming; mutating/stateful tools run serially after.
            all_tool_calls: list[ToolCall] = []
            # (tc, task_or_none) pairs; None means deferred serial execution.
            pending_tasks: list[tuple[ToolCall, Optional[asyncio.Task]]] = []
            deferred_seen = False
            # Accumulate any text the model streams alongside tool calls so the
            # assistant turn we record back into msgs preserves it. Without this,
            # the model sees content=None next iteration and may emit empty replies.
            streamed_text_parts: list[str] = []
            # Reasoning/thinking deltas (separate field on reasoning models).
            # Preserved in history but NOT yielded to the caller, so the user
            # never sees raw chain-of-thought.
            streamed_reasoning_parts: list[str] = []
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
                elif isinstance(event, ReasoningEvent):
                    streamed_reasoning_parts.append(event.content)
                    # Internal-only: NOT yielded to the caller (chat.py / hoonbot).
                elif isinstance(event, ToolCallDeltaEvent):
                    for tc in event.tool_calls:
                        all_tool_calls.append(tc)
                        task = None
                        if self._can_start_tool_immediately(tc.function.name, deferred_seen):
                            task = asyncio.create_task(
                                self.execute_tool(tc.function.name, tc.function.arguments, tc.id)
                            )
                        else:
                            deferred_seen = True
                        pending_tasks.append((tc, task))
                        _meta = TOOL_METADATA.get(tc.function.name, {})
                        if task is not None:
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

            # Append assistant message (must contain ALL tool calls before results).
            # Reasoning content (if emitted by the model) is preserved inline as
            # `<think>...</think>` so the model can build on its own chain of
            # thought on the next iteration. MiniMax M2 in particular degrades
            # severely when prior reasoning is stripped from history.
            text_body = "".join(streamed_text_parts).strip()
            reasoning_body = "".join(streamed_reasoning_parts).strip()
            if reasoning_body:
                if text_body:
                    combined_content = f"<think>\n{reasoning_body}\n</think>\n\n{text_body}"
                else:
                    combined_content = f"<think>\n{reasoning_body}\n</think>"
            else:
                combined_content = text_body
            msgs.append(self._build_assistant_tool_msg(
                all_tool_calls,
                content=combined_content or None,
            ))

            # Record tool-call signatures for repeat detection BEFORE awaiting
            # results — we want every issued call counted even if a later one
            # in the same iteration fails.
            for tc in all_tool_calls:
                self._tool_call_history.append(
                    self._tool_signature(tc.function.name, tc.function.arguments)
                )

            # Resolve results in model order.
            results = []
            for tc, task in pending_tasks:
                _meta = TOOL_METADATA.get(tc.function.name, {})
                if task is None:
                    yield ToolStatusEvent(
                        tool_name=tc.function.name,
                        tool_call_id=tc.id,
                        status="started",
                        activity=_meta.get("activity", ""),
                        user_name=_meta.get("user_name", ""),
                    )
                    result = await self.execute_tool(tc.function.name, tc.function.arguments, tc.id)
                else:
                    result = await task
                results.append(result)

            # Record iteration outcome (all-failed vs at-least-one-success)
            # for the consecutive-failure detector.
            self._record_iteration_outcome(results)

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
