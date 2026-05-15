"""
Shared LLM context builder.

Both the webhook handler (per-message sessions) and the heartbeat (scheduled
ticks) need to inject the same base context into the LLM: system prompt, memory
file path, skills directory path, and current memory content.  This module is
the single source of truth for that logic.

It also builds a small per-turn ambient context block (build_per_turn_context)
injected before every user message so the model retains awareness of node
identity, data paths, and memory size across long sessions.
"""
import os
import time
from datetime import datetime

import config

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

MEMORY_FILE = os.path.join(config.DATA_DIR, "memory.md")
SKILLS_DIR = str(getattr(config, "SKILLS_DIR", os.path.join(os.path.dirname(__file__), "..", "skills")))
_PROMPT_FILE = str(getattr(config, "PROMPT_FILE", os.path.join(os.path.dirname(__file__), "..", "prompts", "PROMPT.md")))

# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

_system_prompt_cache: str = ""
_system_prompt_mtime: float | None = None
_memory_cache: str = ""
_memory_mtime: float | None = None


def load_system_prompt() -> str:
    """Return PROMPT.md content, reloading when the file changes (mtime-based)."""
    global _system_prompt_cache, _system_prompt_mtime
    try:
        mtime = os.path.getmtime(_PROMPT_FILE)
        if _system_prompt_mtime == mtime:
            return _system_prompt_cache
        with open(_PROMPT_FILE, "r", encoding="utf-8") as f:
            _system_prompt_cache = f.read()
        _system_prompt_mtime = mtime
    except FileNotFoundError as exc:
        _system_prompt_cache = ""
        _system_prompt_mtime = None
        raise FileNotFoundError(f"Hoonbot prompt file is missing: {_PROMPT_FILE}") from exc
    return _system_prompt_cache


def read_memory() -> str:
    """Read the current memory file, using mtime caching to avoid repeated disk reads."""
    global _memory_cache, _memory_mtime
    try:
        mtime = os.path.getmtime(MEMORY_FILE)
        if _memory_mtime == mtime:
            return _memory_cache
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            _memory_cache = f.read()
        _memory_mtime = mtime
        return _memory_cache
    except FileNotFoundError:
        _memory_cache = ""
        _memory_mtime = None
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


# ---------------------------------------------------------------------------
# Per-turn ambient context
# ---------------------------------------------------------------------------

_PER_TURN_CACHE: dict = {"text": "", "expires_at": 0.0, "profile": None}
_PER_TURN_TTL_SECONDS = 30
_PER_TURN_MAX_CHARS = 800


def _list_skills() -> str:
    """Return a comma-separated list of *.md skill basenames in SKILLS_DIR."""
    try:
        entries = sorted(
            p.replace(".md", "")
            for p in os.listdir(SKILLS_DIR)
            if p.lower().endswith(".md") and not p.startswith(".")
        )
    except (FileNotFoundError, PermissionError):
        return ""
    return ", ".join(entries)


def _memory_size_summary() -> str:
    """Return 'N chars' for the current memory file, or '(empty)'."""
    try:
        size = os.path.getsize(MEMORY_FILE)
        return f"{size} chars" if size > 0 else "(empty)"
    except FileNotFoundError:
        return "(missing)"


def build_per_turn_context(profile: str = "flutter") -> str:
    """Return a <system-reminder> block with dynamic ambient context.

    Injected before every user message in the webhook handler so the model
    keeps awareness of node identity, data paths, memory size and available
    skills across long sessions. Cached for 30s; capped at ~800 chars.

    *profile* should be one of "flutter" (DMs / casual), "master", "slave",
    or "heartbeat". v1 only adds the always-on fields; profile-specific
    extras (lease, cluster health, last heartbeat) are stubbed for follow-up.
    """
    now = time.time()
    cached = _PER_TURN_CACHE
    if (
        cached["profile"] == profile
        and cached["expires_at"] > now
        and cached["text"]
    ):
        return cached["text"]

    lines = []
    lines.append(f"Now: {datetime.now().strftime('%Y-%m-%d %H:%M (%A, %Z)').strip()}")
    node_name = getattr(config, "NODE_NAME", "")
    cluster_role = getattr(config, "CLUSTER_ROLE", "")
    if node_name or cluster_role:
        lines.append(f"Node: {node_name or '?'} | Role: {cluster_role or '?'}")
    lines.append(f"Data dir: {os.path.abspath(config.DATA_DIR)}")
    lines.append(f"Memory file: {os.path.abspath(MEMORY_FILE)} ({_memory_size_summary()})")
    skills = _list_skills()
    if skills:
        lines.append(f"Skills available: {skills}")

    # Profile-specific stubs - v1 leaves these to follow-up work since they
    # need live cluster state (master) or in-memory worker state (slave).
    # Adding them here keeps the location obvious for future expansion.

    body = "\n".join(lines)
    if len(body) > _PER_TURN_MAX_CHARS:
        body = body[:_PER_TURN_MAX_CHARS] + "\n...[truncated]"

    block = f"<system-reminder>\n{body}\n</system-reminder>"

    _PER_TURN_CACHE["text"] = block
    _PER_TURN_CACHE["expires_at"] = now + _PER_TURN_TTL_SECONDS
    _PER_TURN_CACHE["profile"] = profile
    return block


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
        f"- `node_name`: `{getattr(config, 'NODE_NAME', 'master')}`\n"
        f"- `cluster_role`: `{getattr(config, 'CLUSTER_ROLE', 'master')}`\n"
        f"- `hoonbot_webhook_url`: `{getattr(config, 'HOONBOT_WEBHOOK_URL', '')}`\n"
        f"- `home_room_id`: `{config.MESSENGER_HOME_ROOM_ID}`\n"
        f"- `data_dir`: `{os.path.abspath(config.DATA_DIR)}`\n"
        f"- `memory_file`: `{os.path.abspath(MEMORY_FILE)}`\n"
        f"- `skills_dir`: `{os.path.abspath(SKILLS_DIR)}`\n"
    )
