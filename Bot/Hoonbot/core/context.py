"""
Shared LLM context builder.

Both the webhook handler (per-message sessions) and the heartbeat (scheduled
ticks) need to inject the same base context into the LLM: system prompt, memory
file path, skills directory path, and current memory content.  This module is
the single source of truth for that logic.
"""
import os

import config

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

MEMORY_FILE = os.path.join(config.DATA_DIR, "memory.md")
SKILLS_DIR = os.path.join(os.path.dirname(__file__), "..", "skills")
_PROMPT_FILE = os.path.join(os.path.dirname(__file__), "..", "PROMPT.md")

# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

_system_prompt_cache: str = ""


def load_system_prompt() -> str:
    """Return cached PROMPT.md content (loaded from disk on first call)."""
    global _system_prompt_cache
    if _system_prompt_cache:
        return _system_prompt_cache
    try:
        with open(_PROMPT_FILE, "r", encoding="utf-8") as f:
            _system_prompt_cache = f.read()
    except FileNotFoundError:
        _system_prompt_cache = "You are a helpful AI assistant."
    return _system_prompt_cache


def read_memory() -> str:
    """Read the current memory file, returning empty string if it doesn't exist."""
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def build_llm_context() -> str:
    """
    Return the full system context string to prepend to new LLM sessions:
      - Base system prompt (PROMPT.md)
      - Absolute path to the memory file
      - Absolute path to the skills directory
      - Current memory content
    """
    context = load_system_prompt()
    context += f"\n\n---\n\n## Memory File Location for This Session\n\nAbsolute path: `{os.path.abspath(MEMORY_FILE)}`"
    context += f"\n\n## Skills Directory\n\nAbsolute path: `{os.path.abspath(SKILLS_DIR)}`"
    memory = read_memory()
    if memory:
        context += f"\n\n## Current Memory Content\n\n{memory}"
    else:
        context += "\n\n## Current Memory\n\n(No memory saved yet)"
    return context
