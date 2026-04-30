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
    """Accumulated tool calls parsed from the stream.

    is_partial=True  → one tool call whose args just completed mid-stream;
                       more tool calls may follow in subsequent events.
    is_partial=False → final batch (stream ended); all remaining tool calls.
    """
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: str = "tool"
    is_partial: bool = False

@dataclass
class ToolStatusEvent(StreamEvent):
    """Emitted before/after tool execution for streaming visibility."""
    tool_name: str = ""
    tool_call_id: str = ""
    status: str = ""        # "started" | "completed" | "failed"
    duration: float = 0.0
    activity: str = ""      # human-readable spinner text, e.g. "Reading file"
    user_name: str = ""     # display name for the tool, e.g. "File Reader"


# ============================================================================
# llama.cpp Backend
# ============================================================================

class LlamaCppBackend:
    """llama.cpp backend: fully async, OpenAI-compatible, native tool calling."""

    def __init__(self, host: str = None):
        self.host = (host or config.LLAMACPP_HOST).rstrip("/")
        self._ssl_verify = self._resolve_ssl()
        # Persistent connection pool — reuses TCP connections across requests
        pool_size = getattr(config, 'LLAMACPP_CONNECTION_POOL_SIZE', 20)
        self._client = httpx.AsyncClient(
            verify=self._ssl_verify,
            timeout=config.STREAM_TIMEOUT,
            limits=httpx.Limits(
                max_connections=pool_size,
                max_keepalive_connections=pool_size // 2,
            ),
        )

    def _resolve_ssl(self):
        from pathlib import Path
        cert_path = Path("C:/DigitalCity.crt")
        if cert_path.exists():
            return str(cert_path)
        return True

    async def close(self):
        """Shut down the persistent HTTP client."""
        await self._client.aclose()

    async def is_available(self) -> bool:
        try:
            resp = await self._client.get(
                f"{self.host}/v1/models",
                timeout=httpx.Timeout(3.0),
            )
            return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> List[str]:
        resp = await self._client.get(
            f"{self.host}/v1/models",
            timeout=httpx.Timeout(5.0),
        )
        resp.raise_for_status()
        data = resp.json()
        return [m["id"] for m in data.get("data", [])]

    # ------------------------------------------------------------------
    # Request payload
    # ------------------------------------------------------------------

    def _build_payload(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float,
        tools: Optional[List[Dict[str, Any]]] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        min_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        repeat_penalty: Optional[float] = None,
        id_slot: Optional[int] = None,
    ) -> dict[str, Any]:
        """Assemble the request payload with all llama.cpp parameters.

        Always uses streaming — there is no non-streaming path in this backend.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["parallel_tool_calls"] = True
        # KV cache reuse — skip re-evaluating shared prompt prefix
        if getattr(config, 'LLAMACPP_CACHE_PROMPT', True):
            payload["cache_prompt"] = True
        # Pin to a specific KV cache slot for consistent cache hits
        if id_slot is not None:
            payload["id_slot"] = id_slot
        # Sampling parameters
        if top_p is not None:
            payload["top_p"] = top_p
        if top_k is not None:
            payload["top_k"] = top_k
        if min_p is not None:
            payload["min_p"] = min_p
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if repeat_penalty is not None:
            payload["repeat_penalty"] = repeat_penalty
        return payload

    # ------------------------------------------------------------------
    # Streaming chat (with optional tool calling)
    # ------------------------------------------------------------------

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        min_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        repeat_penalty: Optional[float] = None,
        id_slot: Optional[int] = None,
    ) -> AsyncIterator[StreamEvent]:
        payload = self._build_payload(
            messages, model, temperature,
            tools=tools, top_p=top_p, top_k=top_k, min_p=min_p,
            max_tokens=max_tokens, repeat_penalty=repeat_penalty,
            id_slot=id_slot,
        )

        # State for accumulating tool call deltas across SSE chunks
        pending_tool_calls: dict[int, dict] = {}  # index -> {id, name, arguments_str}
        yielded_indices: set[int] = set()          # indices already dispatched mid-stream
        max_seen_idx: int = -1
        finish_reason = "stop"

        async with self._client.stream(
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

                # Text content — yield immediately
                if "content" in delta and delta["content"]:
                    yield TextEvent(content=delta["content"])

                # Tool call deltas
                if "tool_calls" in delta:
                    for tc_delta in delta["tool_calls"]:
                        idx = tc_delta.get("index", 0)

                        # A new index appearing means the PREVIOUS max index is complete.
                        # Yield it immediately so the agent can start executing it now.
                        if idx not in pending_tool_calls:
                            if max_seen_idx >= 0 and max_seen_idx not in yielded_indices:
                                prev = pending_tool_calls[max_seen_idx]
                                if prev["name"]:
                                    try:
                                        args = json.loads(prev["arguments_str"])
                                        yield ToolCallDeltaEvent(
                                            tool_calls=[ToolCall(
                                                id=prev["id"],
                                                function=ToolCallFunction(
                                                    name=prev["name"], arguments=args
                                                ),
                                            )],
                                            finish_reason="tool",
                                            is_partial=True,
                                        )
                                        yielded_indices.add(max_seen_idx)
                                    except json.JSONDecodeError:
                                        pass  # incomplete JSON — will be caught at stream end

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

                        if idx > max_seen_idx:
                            max_seen_idx = idx

        # After the stream finishes, yield any tool calls not yet dispatched
        remaining: list[ToolCall] = []
        for idx in sorted(pending_tool_calls.keys()):
            if idx in yielded_indices:
                continue
            entry = pending_tool_calls[idx]
            try:
                args = json.loads(entry["arguments_str"])
            except json.JSONDecodeError:
                args = {"_raw": entry["arguments_str"]}
            remaining.append(ToolCall(
                id=entry["id"],
                function=ToolCallFunction(name=entry["name"], arguments=args),
            ))
        if remaining:
            yield ToolCallDeltaEvent(
                tool_calls=remaining, finish_reason=finish_reason, is_partial=False
            )


# ============================================================================
# Global instance (wrapped by interceptor)
# ============================================================================

from backend.core.llm_interceptor import LLMInterceptor

_backend = LlamaCppBackend()
llm_backend = LLMInterceptor(_backend)
