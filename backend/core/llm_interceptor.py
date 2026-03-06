"""
LLM Interceptor for logging all LLM interactions.
Wraps LlamaCppBackend and logs requests/responses to prompts.log.
"""
import json
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, AsyncIterator
from pathlib import Path
import uuid

import config


class LLMInterceptor:
    """Wraps the LLM backend, adding logging for every call."""

    def __init__(self, backend, log_path: Path = None):
        self.backend = backend
        self.log_path = log_path or config.PROMPTS_LOG_PATH
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _format_human_readable(self, log_data: Dict) -> str:
        lines = []

        response = log_data.get("response", "")
        is_request = response in ("[WAITING FOR RESPONSE...]", "[STREAMING...]")

        lines.append("")
        lines.append("=" * 80)
        lines.append(">>> REQUEST TO LLM" if is_request else "<<< RESPONSE FROM LLM")
        lines.append("=" * 80)

        if is_request:
            messages = log_data.get("messages", [])
            lines.append("")
            for i, msg in enumerate(messages):
                lines.append(f"Message {i+1}:")
                lines.append(f"  role: {msg.get('role', 'unknown')}")
                content = msg.get('content') or ''
                if content:
                    lines.append(f"  content:")
                    for line in str(content).split('\n'):
                        lines.append(f"    {line}" if line else "")
                if msg.get("tool_calls"):
                    lines.append(f"  tool_calls: {json.dumps(msg['tool_calls'], ensure_ascii=False)[:500]}")
                if msg.get("tool_call_id"):
                    lines.append(f"  tool_call_id: {msg['tool_call_id']}")
                lines.append("")
            if log_data.get("tools_provided"):
                lines.append(f"  [tools: {log_data['tools_provided']} schema(s) provided]")
                lines.append("")
        else:
            response_text = log_data.get("response", log_data.get("partial_response", ""))
            lines.append("")
            lines.append(str(response_text)[:2000])
            if log_data.get("response_tool_calls"):
                lines.append(f"\n  tool_calls: {log_data['response_tool_calls']}")
            lines.append("")

        lines.append("-" * 80)
        lines.append("STATS:")
        lines.append(f"  Timestamp:   {log_data.get('timestamp', 'N/A')}")
        lines.append(f"  Model:       {log_data.get('model', 'N/A')}")
        lines.append(f"  Backend:     {log_data.get('backend', 'N/A')}")
        lines.append(f"  Temperature: {log_data.get('temperature', 'N/A')}")

        sid = log_data.get('session_id')
        if sid and sid != 'N/A':
            lines.append(f"  Session:     {sid}")
        at = log_data.get('agent_type')
        if at and at != 'N/A':
            lines.append(f"  Agent:       {at}")

        lines.append(f"  Streaming:   {'Yes' if log_data.get('streaming', False) else 'No'}")

        if not is_request:
            duration = log_data.get("duration_seconds", 0)
            lines.append(f"  Duration:    {duration:.2f}s")
            et = log_data.get("estimated_tokens", {})
            t_in = et.get("input", 0)
            t_out = et.get("output", 0)
            lines.append(f"  Tokens:      {t_in} in + {t_out} out = {t_in + t_out} total")
            if duration > 0 and t_out > 0:
                lines.append(f"  Speed:       {t_out / duration:.1f} tokens/sec")

            if log_data.get("success", False):
                lines.append(f"  Status:      SUCCESS")
            else:
                lines.append(f"  Status:      FAILED")
                if log_data.get("error"):
                    lines.append(f"  Error:       {log_data['error']}")

        lines.append("=" * 80)
        lines.append("")
        return '\n'.join(lines)

    def _log_interaction(self, log_data: Dict):
        try:
            if "id" not in log_data:
                log_data["id"] = str(uuid.uuid4())[:8]
            formatted = self._format_human_readable(log_data)
            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write(formatted)
        except Exception as e:
            print(f"Warning: Failed to log LLM interaction: {e}")

    def _estimate_tokens(self, messages: List[Dict]) -> int:
        total = 0
        for m in messages:
            c = m.get("content") or ""
            total += len(str(c).split())
        return int(total * 1.3)

    # ------------------------------------------------------------------
    # Non-streaming chat
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
        session_id: str = None,
        agent_type: str = None,
    ):
        """Returns LLMResponse from backend.chat()."""
        from backend.core.llm_backend import LLMResponse
        start_time = time.time()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_id = str(uuid.uuid4())[:8]
        backend_name = "LlamaCppBackend"

        print(f"\n[LLM] Calling model: {model}")
        print(f"[LLM] Backend: {backend_name}")
        print(f"[LLM] Temperature: {temperature}")
        print(f"[LLM] Agent: {agent_type or 'N/A'}")
        print(f"[LLM] Messages: {len(messages)}")
        if tools:
            print(f"[LLM] Tools: {len(tools)} schemas")

        input_tokens = self._estimate_tokens(messages)
        self._log_interaction({
            "id": log_id, "timestamp": timestamp, "streaming": False,
            "model": model, "temperature": temperature, "messages": messages,
            "backend": backend_name, "session_id": session_id or "N/A",
            "agent_type": agent_type or "N/A",
            "tools_provided": len(tools) if tools else 0,
            "response": "[WAITING FOR RESPONSE...]",
            "estimated_tokens": {"input": input_tokens, "output": 0, "total": input_tokens},
        })

        response_log: Dict[str, Any] = {
            "id": log_id, "timestamp": timestamp, "streaming": False,
            "model": model, "temperature": temperature, "messages": messages,
            "backend": backend_name, "session_id": session_id or "N/A",
            "agent_type": agent_type or "N/A",
        }

        try:
            result: LLMResponse = await self.backend.chat(messages, model, temperature, tools=tools)
            duration = time.time() - start_time

            response_text = result.content or ""
            output_tokens = int(len(response_text.split()) * 1.3)

            response_log["response"] = response_text
            response_log["duration_seconds"] = duration
            response_log["success"] = True
            response_log["estimated_tokens"] = {
                "input": input_tokens, "output": output_tokens, "total": input_tokens + output_tokens,
            }
            if result.tool_calls:
                tc_summary = [{"name": tc.function.name, "args": tc.function.arguments} for tc in result.tool_calls]
                response_log["response_tool_calls"] = json.dumps(tc_summary, ensure_ascii=False)[:500]

            print(f"[LLM] Response received in {duration:.2f}s")
            if result.tool_calls:
                print(f"[LLM] Tool calls: {[tc.function.name for tc in result.tool_calls]}")
            else:
                preview = response_text[:150] + "..." if len(response_text) > 150 else response_text
                print(f"[LLM] Response preview: {preview}")

            return result

        except Exception as e:
            print(f"[LLM] ERROR: {e}")
            response_log["success"] = False
            response_log["error"] = str(e)
            response_log["duration_seconds"] = time.time() - start_time
            response_log["response"] = ""
            response_log["estimated_tokens"] = {"input": input_tokens, "output": 0, "total": input_tokens}
            raise
        finally:
            self._log_interaction(response_log)

    # ------------------------------------------------------------------
    # Streaming chat
    # ------------------------------------------------------------------

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
        session_id: str = None,
        agent_type: str = None,
    ) -> AsyncIterator:
        """Yields StreamEvent objects from backend.chat_stream()."""
        start_time = time.time()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_id = str(uuid.uuid4())[:8]
        backend_name = "LlamaCppBackend"
        input_tokens = self._estimate_tokens(messages)

        self._log_interaction({
            "id": log_id, "timestamp": timestamp, "streaming": True,
            "model": model, "temperature": temperature, "messages": messages,
            "backend": backend_name, "session_id": session_id or "N/A",
            "agent_type": agent_type or "N/A",
            "tools_provided": len(tools) if tools else 0,
            "response": "[STREAMING...]",
            "estimated_tokens": {"input": input_tokens, "output": 0, "total": input_tokens},
        })

        response_log: Dict[str, Any] = {
            "id": log_id, "timestamp": timestamp, "streaming": True,
            "model": model, "temperature": temperature, "messages": messages,
            "backend": backend_name, "session_id": session_id or "N/A",
            "agent_type": agent_type or "N/A",
        }

        collected_text = ""

        try:
            async for event in self.backend.chat_stream(messages, model, temperature, tools=tools):
                from backend.core.llm_backend import TextEvent
                if isinstance(event, TextEvent):
                    collected_text += event.content
                yield event

            duration = time.time() - start_time
            output_tokens = int(len(collected_text.split()) * 1.3)
            response_log["response"] = collected_text
            response_log["duration_seconds"] = duration
            response_log["success"] = True
            response_log["estimated_tokens"] = {
                "input": input_tokens, "output": output_tokens, "total": input_tokens + output_tokens,
            }

        except Exception as e:
            response_log["success"] = False
            response_log["error"] = str(e)
            response_log["duration_seconds"] = time.time() - start_time
            response_log["partial_response"] = collected_text
            response_log["estimated_tokens"] = {
                "input": input_tokens, "output": int(len(collected_text.split()) * 1.3),
                "total": input_tokens + int(len(collected_text.split()) * 1.3),
            }
            raise
        finally:
            self._log_interaction(response_log)

    # ------------------------------------------------------------------
    # Pass-through
    # ------------------------------------------------------------------

    async def list_models(self) -> List[str]:
        return await self.backend.list_models()

    async def is_available(self) -> bool:
        return await self.backend.is_available()
