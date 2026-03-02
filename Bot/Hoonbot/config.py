import os
import re

# ---------------------------------------------------------------------------
# settings.txt loader — parses KEY=VALUE lines from the project-level
# settings.txt and injects them as defaults (env vars still override).
# ---------------------------------------------------------------------------
_SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "..", "settings.txt")


def _load_settings_file() -> dict:
    """Parse settings.txt into a dict. Skips comments and blank lines."""
    result = {}
    try:
        with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
                if m:
                    key = m.group(1)
                    val = m.group(2).strip().strip('"').strip("'")
                    result[key] = val
    except FileNotFoundError:
        pass
    return result


_settings = _load_settings_file()


def _get(key: str, default: str = "") -> str:
    """Read a config value: env var > settings.txt > default."""
    return os.environ.get(key, _settings.get(key, default))


# --- Hoonbot server ---
HOONBOT_PORT = int(_get("HOONBOT_PORT", "3939"))
HOONBOT_HOST = "0.0.0.0"
USE_CLOUDFLARE = _get("USE_CLOUDFLARE", "false").lower() == "true"

# --- Messenger ---
MESSENGER_PORT = int(_get("MESSENGER_PORT", "3000"))
MESSENGER_URL = (
    "https://aihoonbot.com"
    if USE_CLOUDFLARE
    else f"http://localhost:{MESSENGER_PORT}"
)
MESSENGER_BOT_NAME = _get("HOONBOT_BOT_NAME", "Hoonbot")
MESSENGER_API_KEY = ""  # Populated at runtime after bot registration
MESSENGER_HOME_ROOM_ID = int(_get("HOONBOT_HOME_ROOM_ID", "1"))

# --- LLM API ---
LLM_API_PORT = int(_get("LLM_API_PORT", "10007"))
LLM_API_USERNAME = _get("HOONBOT_LLM_USERNAME", "admin")
LLM_API_PASSWORD = _get("HOONBOT_LLM_PASSWORD", "administrator")
_llm_api_url_override = _get("LLM_API_URL", "").strip()
if _llm_api_url_override:
    LLM_API_URL = _llm_api_url_override.rstrip("/")
else:
    LLM_API_URL = (
        "https://aihoonbot.com/llm"
        if USE_CLOUDFLARE
        else f"http://localhost:{LLM_API_PORT}"
    )


def _load_file(name: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "data", name)
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


LLM_API_KEY = _load_file(".llm_key")
LLM_MODEL = _load_file(".llm_model")

# --- Storage ---
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# --- Message limits ---
MAX_MESSAGE_LENGTH = int(_get("HOONBOT_MAX_MESSAGE_LENGTH", "2000"))

# --- Heartbeat ---
HEARTBEAT_ENABLED = _get("HOONBOT_HEARTBEAT_ENABLED", "true").lower() == "true"
HEARTBEAT_INTERVAL_SECONDS = int(_get("HOONBOT_HEARTBEAT_INTERVAL", "3600"))
HEARTBEAT_LLM_COOLDOWN_SECONDS = int(_get("HOONBOT_HEARTBEAT_LLM_COOLDOWN_SECONDS", "600"))
HEARTBEAT_ACTIVE_START = _get("HOONBOT_HEARTBEAT_ACTIVE_START", "00:00")
HEARTBEAT_ACTIVE_END = _get("HOONBOT_HEARTBEAT_ACTIVE_END", "23:59")

# --- Behavior ---
DEBOUNCE_SECONDS = float(_get("HOONBOT_DEBOUNCE_SECONDS", "1.5"))
LLM_TIMEOUT_SECONDS = int(_get("HOONBOT_LLM_TIMEOUT", "300"))
STARTUP_RETRY_ATTEMPTS = int(_get("HOONBOT_STARTUP_RETRIES", "6"))
STARTUP_RETRY_DELAY = float(_get("HOONBOT_STARTUP_RETRY_DELAY", "1.0"))
CATCHUP_MESSAGE_LIMIT = int(_get("HOONBOT_CATCHUP_LIMIT", "20"))
SESSION_MAX_AGE_DAYS = int(_get("HOONBOT_SESSION_MAX_AGE_DAYS", "7"))
MEMORY_FLUSH_THRESHOLD = int(_get("HOONBOT_MEMORY_FLUSH_THRESHOLD", "30"))
STREAMING_ENABLED = _get("HOONBOT_STREAMING", "true").lower() == "true"

# --- Incoming webhooks ---
WEBHOOK_INCOMING_SECRET = _get("HOONBOT_WEBHOOK_SECRET", "")
