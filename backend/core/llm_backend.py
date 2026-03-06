"""
LLM Backend for llama.cpp
Fully async, with native tool calling support via OpenAI-compatible API.
"""
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, AsyncIterator

import httpx

import config


# ============================================================================
# Response Types
# ============================================================================

@dataclass
class ToolCallFunction:
    name: str
    arguments: dict[str, Any]

@dataclass
class ToolCall:
    id: str
    function: ToolCallFunction

@dataclass
class LLMResponse:
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    finish_reason: str = "stop"

@dataclass
class StreamEvent:
    pass

@dataclass
class TextEvent(StreamEvent):
    content: str = ""

@dataclass
class ToolCallDeltaEvent(StreamEvent):
    """Accumulated tool calls parsed from the stream."""
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: str = "tool"

@dataclass
class ToolStatusEvent(StreamEvent):
    """Emitted before/after tool execution for streaming visibility."""
    tool_name: str = ""
    tool_call_id: str = ""
    status: str = ""        # "started" | "completed" | "failed"
    duration: float = 0.0


# ============================================================================
# llama.cpp Backend
# ============================================================================

class LlamaCppBackend:
    """llama.cpp backend: fully async, OpenAI-compatible, native tool calling."""

    def __init__(self, host: str = None):
        self.host = (host or config.LLAMACPP_HOST).rstrip("/")
        self._ssl_verify = self._resolve_ssl()

    def _resolve_ssl(self):
        from pathlib import Path
        cert_path = Path("C:/DigitalCity.crt")
        if cert_path.exists():
            return str(cert_path)
        return True

    async def _get_client(self, timeout: float = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            verify=self._ssl_verify,
            timeout=timeout or config.STREAM_TIMEOUT,
        )

    async def is_available(self) -> bool:
        try:
            async with await self._get_client(timeout=3.0) as client:
                resp = await client.get(f"{self.host}/v1/models")
                return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> List[str]:
        async with await self._get_client(timeout=5.0) as client:
            resp = await client.get(f"{self.host}/v1/models")
            resp.raise_for_status()
            data = resp.json()
            return [m["id"] for m in data.get("data", [])]

    # ------------------------------------------------------------------
    # Non-streaming chat (with optional tool calling)
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        async with await self._get_client() as client:
            resp = await client.post(
                f"{self.host}/v1/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        return self._parse_response(data)

    def _parse_response(self, data: dict) -> LLMResponse:
        choice = data["choices"][0]
        message = choice["message"]
        finish = choice.get("finish_reason", "stop")

        content = message.get("content")
        raw_tool_calls = message.get("tool_calls")

        tool_calls = None
        if raw_tool_calls:
            tool_calls = []
            for i, tc in enumerate(raw_tool_calls):
                func = tc.get("function", tc)
                args_raw = func.get("arguments", "{}")
                if isinstance(args_raw, str):
                    args = json.loads(args_raw)
                else:
                    args = args_raw
                call_id = tc.get("id", f"call_{i}")
                tool_calls.append(ToolCall(
                    id=call_id,
                    function=ToolCallFunction(name=func["name"], arguments=args),
                ))

        return LLMResponse(content=content, tool_calls=tool_calls, finish_reason=finish)

    # ------------------------------------------------------------------
    # Streaming chat (with optional tool calling)
    # ------------------------------------------------------------------

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[StreamEvent]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        # State for accumulating tool call deltas across SSE chunks
        pending_tool_calls: dict[int, dict] = {}  # index -> {id, name, arguments_str}
        finish_reason = "stop"

        async with await self._get_client() as client:
            async with client.stream(
                "POST",
                f"{self.host}/v1/chat/completions",
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for raw_line in resp.aiter_lines():
                    if not raw_line.startswith("data: "):
                        continue
                    data_str = raw_line[6:]
                    if data_str.strip() == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    chunk_finish = choices[0].get("finish_reason")
                    if chunk_finish:
                        finish_reason = chunk_finish

                    # Text content
                    if "content" in delta and delta["content"]:
                        yield TextEvent(content=delta["content"])

                    # Tool call deltas
                    if "tool_calls" in delta:
                        for tc_delta in delta["tool_calls"]:
                            idx = tc_delta.get("index", 0)
                            if idx not in pending_tool_calls:
                                pending_tool_calls[idx] = {
                                    "id": tc_delta.get("id", f"call_{idx}"),
                                    "name": "",
                                    "arguments_str": "",
                                }
                            entry = pending_tool_calls[idx]
                            func_delta = tc_delta.get("function", {})
                            if "name" in func_delta:
                                entry["name"] += func_delta["name"]
                            if "arguments" in func_delta:
                                entry["arguments_str"] += func_delta["arguments"]

        # After the stream finishes, if we accumulated tool calls, yield them
        if pending_tool_calls:
            tool_calls = []
            for idx in sorted(pending_tool_calls.keys()):
                entry = pending_tool_calls[idx]
                try:
                    args = json.loads(entry["arguments_str"])
                except json.JSONDecodeError:
                    args = {"_raw": entry["arguments_str"]}
                tool_calls.append(ToolCall(
                    id=entry["id"],
                    function=ToolCallFunction(name=entry["name"], arguments=args),
                ))
            yield ToolCallDeltaEvent(tool_calls=tool_calls, finish_reason=finish_reason)


# ============================================================================
# Global instance (wrapped by interceptor)
# ============================================================================

from backend.core.llm_interceptor import LLMInterceptor

_backend = LlamaCppBackend()
llm_backend = LLMInterceptor(_backend)
