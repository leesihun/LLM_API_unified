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
      - Session variables (credentials, paths, identifiers)
      - Current memory content
    """
    context = load_system_prompt()
    context += _build_session_variables()
    memory = read_memory()
    if memory:
        context += f"\n\n## Current Memory\n\n{memory}"
    else:
        context += "\n\n## Current Memory\n\n(No memory saved yet)"
    return context


def _build_session_variables() -> str:
    """
    All runtime values in one block — PROMPT.md references these by name.
    Regenerated each call so live config changes (e.g. re-registration) propagate.
    """
    return (
        f"\n\n---\n\n## Session Variables\n\n"
        f"Use these directly — do not read them from disk.\n\n"
        f"- `messenger_url`: `{config.MESSENGER_URL}`\n"
        f"- `messenger_api_key`: `{config.MESSENGER_API_KEY}`\n"
        f"- `bot_user_id`: `{config.BOT_USER_ID}`\n"
        f"- `bot_name`: `{config.MESSENGER_BOT_NAME}`\n"
        f"- `home_room_id`: `{config.MESSENGER_HOME_ROOM_ID}`\n"
        f"- `data_dir`: `{os.path.abspath(config.DATA_DIR)}`\n"
        f"- `memory_file`: `{os.path.abspath(MEMORY_FILE)}`\n"
        f"- `skills_dir`: `{os.path.abspath(SKILLS_DIR)}`\n"
    )
