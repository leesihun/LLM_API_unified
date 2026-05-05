"""
Hoonbot configuration — single source of truth.

This is the single source of truth for all Hoonbot settings. Edit values
directly in this file. Variables that should be runtime-overridable use
``os.environ.get``; the rest are plain Python constants.

This module deliberately has NO external file dependency for static
settings — it does NOT read ``settings.txt`` or any other config file.
The only files it does read are runtime credential blobs written by the
setup scripts (``data/.llm_key``, ``data/.llm_model``).

Conventions:
    * Constants are uppercase module-level attributes.
    * Anything that callers in ``hoonbot.py`` / ``core/`` / ``handlers/``
      read from this module is preserved by name. Renames are propagated
      to all read sites or simply not done.
"""

import os
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_BASE_DIR = Path(__file__).parent
DATA_DIR = str(_BASE_DIR / "data")


def _read_credential_file(name: str) -> str:
    """Read a runtime credential file from ``data/``. Returns "" if absent.

    These files are written by the setup scripts (``scripts/setup_credentials.py``)
    and the Messenger bot registration step. They are intentionally NOT inline
    constants because they contain secrets and per-install values.
    """
    path = _BASE_DIR / "data" / name
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------
HOONBOT_PORT = 3939
HOONBOT_HOST = "0.0.0.0"
MESSENGER_PORT = 10006
LLM_API_PORT = 10007

# Cloudflare branching has been removed. This flag is kept as a constant
# (defaulting to False) only because external modules still reference it.
# Do not re-introduce conditional URL logic here.
USE_CLOUDFLARE = False


# ---------------------------------------------------------------------------
# External Services — Messenger
# ---------------------------------------------------------------------------
MESSENGER_URL = f"http://localhost:{MESSENGER_PORT}"
MESSENGER_API_KEY = ""  # populated at runtime after bot registration


# ---------------------------------------------------------------------------
# External Services — LLM API
# ---------------------------------------------------------------------------
# LLM_API_URL is the one legitimate runtime override: it lets ops point
# Hoonbot at a remote LLM API host without editing this file.
_LLM_API_URL_OVERRIDE = os.environ.get("LLM_API_URL", "").strip().rstrip("/")
_LLM_API_LOCAL_URL = f"http://localhost:{LLM_API_PORT}"

LLM_API_URL = _LLM_API_URL_OVERRIDE or _LLM_API_LOCAL_URL

# Ordered candidate list for autofind in hoonbot.py: explicit override first,
# then the local URL.
LLM_API_CANDIDATES: list[str] = []
if _LLM_API_URL_OVERRIDE:
    LLM_API_CANDIDATES.append(_LLM_API_URL_OVERRIDE)
if _LLM_API_LOCAL_URL not in LLM_API_CANDIDATES:
    LLM_API_CANDIDATES.append(_LLM_API_LOCAL_URL)

# Credentials used by scripts/setup_credentials.py to obtain an API token.
LLM_API_USERNAME = "admin"
LLM_API_PASSWORD = "administrator"

# Runtime credential files (created by setup scripts).
LLM_API_KEY = _read_credential_file(".llm_key")
LLM_MODEL = _read_credential_file(".llm_model")


# ---------------------------------------------------------------------------
# Bot Identity
# ---------------------------------------------------------------------------
MESSENGER_BOT_NAME = "Bot"
# When MESSENGER_HOME_ROOM_NAME is set, the room is resolved by name at
# startup and MESSENGER_HOME_ROOM_ID is overwritten with the resolved id.
# Set MESSENGER_HOME_ROOM_NAME = "" to fall back to the numeric id below.
MESSENGER_HOME_ROOM_NAME = "Heartbeat"
MESSENGER_HOME_ROOM_ID = 1
# Populated at startup from /api/bots/me — used for context injection.
BOT_USER_ID: int = 0


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------
HEARTBEAT_ENABLED = True
HEARTBEAT_INTERVAL_SECONDS = 3000
# If heartbeat hits LLM connectivity errors, pause heartbeat LLM calls
# for this many seconds.
HEARTBEAT_LLM_COOLDOWN_SECONDS = 600
# Active hours window (24h HH:MM). Heartbeat only runs in this window.
HEARTBEAT_ACTIVE_START = "00:00"
HEARTBEAT_ACTIVE_END = "23:59"


# ---------------------------------------------------------------------------
# Behavior
# ---------------------------------------------------------------------------
# Debounce window for rapid messages (seconds). Messages within this window
# are combined into one LLM call.
DEBOUNCE_SECONDS = 1.5
# LLM request timeout (seconds). Increase for tool-heavy calls.
LLM_TIMEOUT_SECONDS = 3000
# Max startup retry attempts for Messenger registration / webhook setup.
STARTUP_RETRY_ATTEMPTS = 6
# Base delay between startup retries (seconds, doubles each attempt).
STARTUP_RETRY_DELAY = 1.0
# How many recent messages to scan per room on startup catch-up.
CATCHUP_MESSAGE_LIMIT = 20
# Max message length before auto-splitting into multiple Messenger sends.
MAX_MESSAGE_LENGTH = 2000
# Session max age in days. Older sessions start fresh. 0 = never expire.
SESSION_MAX_AGE_DAYS = 1
# Threshold (number of messages) at which the agent flushes memory.md.
MEMORY_FLUSH_THRESHOLD = 30
# Stream LLM responses with live tool-status updates.
STREAMING_ENABLED = True


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------
# Optional shared secret for the inbound /webhook endpoint. Empty disables
# the check.
WEBHOOK_INCOMING_SECRET = ""
