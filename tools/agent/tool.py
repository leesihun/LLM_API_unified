"""
SubAgent Tool
Spawns a fresh-context AgentLoop (sub-agent) to handle complex research or
multi-step tasks without polluting the main conversation context.

Mirrors OpenClaude's AgentTool:
  - "explore"  subagent: read-only tools (file_reader, grep, file_navigator, websearch)
  - "general"  subagent: full toolset minus "agent" (no infinite recursion)
"""
from typing import Any, Dict, Optional

import config

_EXPLORE_TOOLS = ["file_reader", "grep", "file_navigator", "websearch"]


def _general_tools() -> list:
    """Full toolset minus 'agent' to prevent infinite recursion."""
    return [t for t in config.AVAILABLE_TOOLS if t != "agent"]


class SubAgentTool:
    """Spawn a sub-AgentLoop and return its text result."""

    def __init__(self, session_id: str = None, username: str = None):
        self.session_id = session_id
        self.username = username

    async def execute(
        self,
        prompt: str,
        subagent_type: str = "general",
        description: Optional[str] = None,
        child_session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Spawn a sub-agent and return its final text response.

        Args:
            prompt:        Task or question for the subagent.
            subagent_type: "explore" (read-only) or "general" (full toolset).
            description:   Short label for logging (3-5 words).

        Returns:
            {"success": True, "result": str, "subagent_type": str}
        """
        label = description or f"{subagent_type} subagent"
        print(f"\n[AGENT-TOOL] Spawning {label} ({subagent_type})")

        if subagent_type == "explore":
            tools = [t for t in _EXPLORE_TOOLS if t in config.AVAILABLE_TOOLS]
        else:
            tools = _general_tools()

        # Import here to avoid circular import at module load
        from backend.agent import AgentLoop

        sub_loop = AgentLoop(
            session_id=child_session_id or self.session_id,
            username=self.username,
            tools=tools,
        )

        messages = [{"role": "user", "content": prompt}]
        try:
            result_text = await sub_loop.run(messages)
        except Exception as exc:
            return {
                "success": False,
                "error": f"Subagent failed: {exc}",
                "subagent_type": subagent_type,
            }

        print(f"[AGENT-TOOL] {label} completed ({len(result_text)} chars)")
        return {
            "success": True,
            "result": result_text,
            "subagent_type": subagent_type,
        }
