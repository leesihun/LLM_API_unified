"""FormattingMixin: message builders and tool result microcompaction."""
import json
from uuid import uuid4
from typing import List, Dict, Any, Optional

import config
from backend.core.llm_backend import ToolCall


class FormattingMixin:
    """Builds assistant/tool messages and applies per-tool result budgets."""

    def _build_assistant_tool_msg(self, tool_calls: List[ToolCall],
                                  content: Optional[str] = None) -> Dict[str, Any]:
        # Always send content as a string. Some llama.cpp chat templates
        # (Qwen, GLM, certain Llama-3 tool variants) reject content=null on
        # assistant messages with tool_calls and return 400 Bad Request
        # during chat-template rendering — manifests as 0-duration, 0-token
        # failures with no useful error.
        return {
            "role": "assistant",
            "content": content or "",
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
        content = json.dumps(
            self._build_tool_result_preview(result, tool_call.function.name),
            ensure_ascii=False,
            default=str,
        )
        content = self._truncate_tool_result(tool_call.function.name, content)
        return {
            "role": "tool",
            "name": tool_call.function.name,
            "content": content,
            "tool_call_id": tool_call.id,
        }

    def _build_tool_result_preview(self, result: Any, tool_name: str) -> Any:
        """Create a bounded preview before serialising large tool payloads."""
        budget = config.TOOL_RESULT_BUDGET.get(tool_name, config.TOOL_RESULT_DEFAULT_BUDGET)
        text_cap = max(120, min(1200, budget))
        return self._summarize_tool_value(result, text_cap=text_cap, list_cap=6, depth=0)

    def _summarize_tool_value(
        self,
        value: Any,
        text_cap: int,
        list_cap: int,
        depth: int,
    ) -> Any:
        if isinstance(value, str):
            if len(value) <= text_cap:
                return value
            return value[:text_cap] + f"... [{len(value)} chars total]"

        if isinstance(value, list):
            item_cap = list_cap if depth == 0 else max(2, list_cap - 2)
            summarized = [
                self._summarize_tool_value(
                    item,
                    text_cap=max(80, text_cap // 2),
                    list_cap=max(2, list_cap - 1),
                    depth=depth + 1,
                )
                for item in value[:item_cap]
            ]
            if len(value) > item_cap:
                summarized.append(f"... [{len(value) - item_cap} more items]")
            return summarized

        if isinstance(value, dict):
            item_cap = 24 if depth == 0 else 10
            summarized = {
                key: self._summarize_tool_value(
                    item,
                    text_cap=max(80, text_cap // 2),
                    list_cap=max(2, list_cap - 1),
                    depth=depth + 1,
                )
                for key, item in list(value.items())[:item_cap]
            }
            if len(value) > item_cap:
                summarized["_truncated_keys"] = len(value) - item_cap
            return summarized

        return value

    def _truncate_tool_result(self, tool_name: str, content: str) -> str:
        """Truncate a tool result to its per-tool budget. Save full version to disk if over budget."""
        budget = config.TOOL_RESULT_BUDGET.get(tool_name, config.TOOL_RESULT_DEFAULT_BUDGET)
        if len(content) <= budget:
            return content

        self._log(f"  [MICROCOMPACT] {tool_name} result truncated: {len(content)} -> {budget} chars")

        # Save the oversized prompt representation to disk for potential re-retrieval
        if self.session_id:
            call_id = str(uuid4())[:8]
            self._save_tool_result_to_disk(call_id, content)

        return content[:budget] + f"\n...[truncated, {len(content)} chars total]"

    def _save_tool_result_to_disk(self, call_id: str, content: str):
        """Persist an oversized tool result representation to disk."""
        session_dir = config.TOOL_RESULTS_DIR / (self.session_id or "default")
        session_dir.mkdir(parents=True, exist_ok=True)
        path = session_dir / f"{call_id}.json"
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            print(f"[MICROCOMPACT] Failed to save tool result to disk: {e}")
