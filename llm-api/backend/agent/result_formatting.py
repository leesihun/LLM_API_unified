"""FormattingMixin: message builders and tool result microcompaction."""
import json
from typing import List, Dict, Any, Optional

import config
from backend.core.llm_backend import ToolCall


class FormattingMixin:
    """Builds assistant/tool messages and applies per-tool result budgets."""

    def _build_assistant_tool_msg(self, tool_calls: List[ToolCall],
                                  content: Optional[str] = None) -> Dict[str, Any]:
        # Always send content as a string. Some vLLM chat templates
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
        content = self._truncate_tool_result(tool_call.function.name, content, call_id=tool_call.id)
        return {
            "role": "tool",
            "name": tool_call.function.name,
            "content": content,
            "tool_call_id": tool_call.id,
        }

    def _build_tool_result_preview(self, result: Any, tool_name: str) -> Any:
        """Create a bounded preview before serialising large tool payloads."""
        budget = config.TOOL_RESULT_BUDGET.get(tool_name, config.TOOL_RESULT_DEFAULT_BUDGET)
        # Use the full per-tool budget so depth-1 strings (e.g. file_reader
        # `content`) aren't pre-truncated to 600 chars (~10 lines). The final
        # char budget is enforced by _truncate_tool_result.
        text_cap = budget
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

    def _truncate_tool_result(self, tool_name: str, content: str, call_id: str = "") -> str:
        """Truncate a tool result to its per-tool budget. Save full version to disk if over budget.
        Truncation marker includes the disk path so the model can recover via file_reader."""
        budget = config.TOOL_RESULT_BUDGET.get(tool_name, config.TOOL_RESULT_DEFAULT_BUDGET)
        if len(content) <= budget:
            return content

        self._log(f"  [MICROCOMPACT] {tool_name} result truncated: {len(content)} -> {budget} chars")

        disk_hint = ""
        if self.session_id:
            # Use the deterministic tool_call.id instead of a random UUID so the model
            # can correlate the truncation marker with the on-disk result file
            safe_id = (call_id or "").replace("/", "_").replace("\\", "_")[:64] or "unknown"
            self._save_tool_result_to_disk(safe_id, content)
            rel_path = f"data/tool_results/{self.session_id}/{safe_id}.json"
            disk_hint = f" — full result at {rel_path}"

        return content[:budget] + f"\n...[truncated to {budget}/{len(content)} chars{disk_hint}]"

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
