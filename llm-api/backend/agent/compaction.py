"""CompactionMixin: microcompaction, history limits, and auto-compact on context overflow."""
import asyncio
import json
from typing import List, Dict, Any, AsyncIterator

import config
from backend.core.llm_backend import StreamEvent, TextEvent, ToolStatusEvent


class CompactionMixin:
    """Compresses old tool results and auto-compacts on llama.cpp context overflow."""

    def _compress_old_iterations(self, msgs: List[Dict[str, Any]], current_iteration: int) -> List[Dict[str, Any]]:
        """
        Return a copy of msgs with old-iteration tool results and assistant
        tool-call messages compressed to short summaries. The original msgs list
        is NEVER mutated so the llama.cpp KV-cache prefix stays byte-stable
        across iterations.

        Only messages before the warm-window boundary are compressed; the hot
        tail (recent `warm` iterations) is passed through unchanged.
        """
        warm = config.AGENT_COMPACTION_WARM_WINDOW
        if current_iteration == 0 or len(self._iteration_boundaries) <= warm:
            return msgs

        old_boundary = self._iteration_boundaries[-(warm + 1)]
        summary_cap = config.AGENT_OLD_TOOL_RESULT_SUMMARY_MAX_CHARS
        tool_result_min = 120
        assistant_min = 80

        compressed_count = 0
        result: List[Dict[str, Any]] = []

        for i, msg in enumerate(msgs):
            if i >= old_boundary:
                result.append(msg)
                continue

            role = msg.get("role")

            if role == "tool":
                content = msg.get("content", "")
                if len(content) > tool_result_min:
                    tool_name = msg.get("name", "tool")
                    summary = content[:summary_cap].replace('\n', ' ')
                    msg = {**msg, "content": f"[{tool_name}: {summary}...]"}
                    compressed_count += 1

            elif role == "assistant" and msg.get("tool_calls"):
                tc_list = msg["tool_calls"]
                raw_size = sum(
                    len(tc.get("function", {}).get("arguments", ""))
                    for tc in tc_list
                )
                if raw_size > assistant_min:
                    names = ", ".join(
                        tc.get("function", {}).get("name", "?") for tc in tc_list
                    )
                    msg = {
                        **msg,
                        "content": f"[called: {names}]",
                        "tool_calls": [
                            {
                                "id": tc.get("id", f"call_{j}"),
                                "type": "function",
                                "function": {
                                    "name": tc.get("function", {}).get("name", ""),
                                    "arguments": "{}",
                                },
                            }
                            for j, tc in enumerate(tc_list)
                        ],
                    }
                    compressed_count += 1

            result.append(msg)

        if compressed_count:
            self._log(f"  [MICROCOMPACT] Compressed {compressed_count} old message(s) "
                      f"from iterations before {current_iteration + 1}")

        return result

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

        # Additionally compress old messages in the kept portion
        # (compress everything except the last limit//2 messages)
        compress_boundary = len(msgs) - limit // 2
        masked = 0
        for i in range(system_end, compress_boundary):
            msg = msgs[i]
            role = msg.get("role")

            if role == "tool":
                content = msg.get("content", "")
                if len(content) > 80:
                    tool_name = msg.get("name", "tool")
                    summary = content[:40].replace("\n", " ")
                    msg["content"] = f"[{tool_name}: {summary}...]"
                    masked += 1

            elif role == "assistant" and msg.get("tool_calls"):
                tc_list = msg["tool_calls"]
                raw_size = sum(
                    len(tc.get("function", {}).get("arguments", ""))
                    for tc in tc_list
                )
                if raw_size > 60:
                    names = ", ".join(
                        tc.get("function", {}).get("name", "?") for tc in tc_list
                    )
                    msg["content"] = f"[called: {names}]"
                    msg["tool_calls"] = [
                        {
                            "id": tc.get("id", f"call_{j}"),
                            "type": "function",
                            "function": {"name": tc.get("function", {}).get("name", ""), "arguments": "{}"},
                        }
                        for j, tc in enumerate(tc_list)
                    ]
                    masked += 1

        if masked:
            print(f"[AGENT] Compressed {masked} old message(s)")

    @staticmethod
    def _is_context_overflow_error(exc: BaseException) -> bool:
        """True if exc is an llama.cpp HTTP error caused by context-window overflow."""
        import httpx
        if not isinstance(exc, httpx.HTTPStatusError):
            return False
        msg = str(exc).lower()
        needles = (
            "context", "exceed", "too large", "too long",
            "n_ctx", "slot unavailable", "input is too large",
        )
        return any(n in msg for n in needles)

    async def _summarize_and_compact_msgs(self, msgs: List[Dict[str, Any]]) -> bool:
        """Summarize the older half of msgs into one system message. Mutates msgs in place.
        Returns True if compaction happened, False if there isn't enough to compact."""
        system_end = 0
        for i, m in enumerate(msgs):
            if m.get("role") == "system":
                system_end = i + 1
            else:
                break

        keep_recent = max(0, getattr(config, "AGENT_AUTOCOMPACT_KEEP_RECENT", 4))
        middle_start = system_end
        middle_end = max(system_end, len(msgs) - keep_recent)
        middle_count = middle_end - middle_start
        if middle_count < 4:
            return False

        half = middle_count // 2
        to_compact = msgs[middle_start:middle_start + half]

        per_msg_cap = max(200, getattr(config, "AGENT_AUTOCOMPACT_PER_MSG_CHARS", 1500))
        summary_max_tokens = max(100, getattr(config, "AGENT_AUTOCOMPACT_SUMMARY_MAX_TOKENS", 1500))

        lines = []
        for i, m in enumerate(to_compact):
            role = m.get("role", "unknown")
            content = m.get("content")
            if content is None:
                content = ""
            elif not isinstance(content, str):
                try:
                    content = json.dumps(content, ensure_ascii=False, default=str)
                except Exception:
                    content = str(content)
            if len(content) > per_msg_cap:
                content = content[:per_msg_cap] + f"...[+{len(content) - per_msg_cap} chars]"
            tc_summary = ""
            if m.get("tool_calls"):
                names = ", ".join(
                    tc.get("function", {}).get("name", "?") for tc in m["tool_calls"]
                )
                tc_summary = f" [tool_calls: {names}]"
            name_label = f" ({m['name']})" if m.get("name") else ""
            lines.append(f"[{i}] {role.upper()}{name_label}{tc_summary}\n{content}")
        convo_text = "\n\n".join(lines)

        summary_prompt = (
            "Summarize the following conversation segment for use as compressed "
            "context. Preserve: file paths, decisions made, tool names and key "
            "results, user intent, and any open questions. Output a brief factual "
            "summary with no preamble or meta-commentary.\n\n"
            f"--- BEGIN CONVERSATION ---\n{convo_text}\n--- END CONVERSATION ---"
        )

        total_chars = sum(len(str(m.get("content") or "")) for m in to_compact)
        self._log(f"  [AUTOCOMPACT] Summarizing {len(to_compact)} messages ({total_chars} chars)")

        summary_text = ""
        try:
            resp = await self.llm.chat(
                messages=[{"role": "user", "content": summary_prompt}],
                model=self.model,
                temperature=0.0,
                session_id=self.session_id,
                agent_type="agent:autocompact",
                max_tokens=summary_max_tokens,
            )
            summary_text = (resp.content or "").strip()
        except Exception as e:
            self._log(f"  [AUTOCOMPACT] Summarizer call failed ({e}); dropping without summary")

        if summary_text:
            notice = f"[Earlier conversation summary]\n{summary_text}"
        else:
            notice = (f"[Earlier conversation auto-compacted: dropped {len(to_compact)} "
                      f"older messages without summary]")

        msgs[middle_start:middle_start + half] = [{"role": "system", "content": notice}]
        self._log(f"  [AUTOCOMPACT] Replaced {len(to_compact)} msgs with 1 system summary "
                  f"({len(notice)} chars). Total msgs now: {len(msgs)}")
        return True

    async def _stream_with_autocompact(
        self,
        msgs: List[Dict[str, Any]],
        model: str,
        temperature: float,
        *,
        iteration: int,
        use_compressed_view: bool = True,
        **chat_kwargs,
    ) -> AsyncIterator[StreamEvent]:
        """Wraps self.llm.chat_stream with reactive auto-compaction.

        On a llama.cpp context-overflow error, summarizes the older half of msgs
        (mutating in place) and retries from scratch. Safe because llama.cpp
        rejects context overflow BEFORE streaming any tokens — we re-raise
        immediately if any events were yielded prior to the error.
        """
        enabled = getattr(config, "AGENT_AUTOCOMPACT_ENABLED", True)
        max_retries = max(0, getattr(config, "AGENT_AUTOCOMPACT_MAX_RETRIES", 2))
        attempt = 0
        while True:
            events_yielded = False
            view = self._compress_old_iterations(msgs, iteration) if use_compressed_view else msgs
            try:
                async for event in self.llm.chat_stream(view, model, temperature, **chat_kwargs):
                    events_yielded = True
                    yield event
                return
            except Exception as e:
                if not enabled or events_yielded or attempt >= max_retries:
                    raise
                if not self._is_context_overflow_error(e):
                    raise
                attempt += 1
                self._log(f"  [AUTOCOMPACT] Context-overflow error caught "
                          f"(attempt {attempt}/{max_retries}): {str(e)[:200]}")
                compacted = await self._summarize_and_compact_msgs(msgs)
                if not compacted:
                    self._log("  [AUTOCOMPACT] Nothing left to compact; propagating error")
                    raise
                if attempt == 1:
                    yield ToolStatusEvent(
                        tool_name="autocompact",
                        tool_call_id="autocompact",
                        status="started",
                        activity="Auto-compacting context",
                        user_name="System",
                    )
