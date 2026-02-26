import os

# --- Hoonbot server ---
HOONBOT_PORT = int(os.environ.get("HOONBOT_PORT", 3939))
HOONBOT_HOST = "0.0.0.0"
USE_CLOUDFLARE = os.environ.get("USE_CLOUDFLARE", "false").lower() == "true"

# --- Messenger ---
MESSENGER_PORT = int(os.environ.get("MESSENGER_PORT", 3000))
MESSENGER_URL = (
    "https://aihoonbot.com"
    if USE_CLOUDFLARE
    else f"http://localhost:{MESSENGER_PORT}"
)
MESSENGER_BOT_NAME = os.environ.get("HOONBOT_BOT_NAME", "Hoonbot")
MESSENGER_API_KEY = ""  # Populated at runtime after bot registration; persisted in data/.apikey
MESSENGER_HOME_ROOM_ID = int(os.environ.get("HOONBOT_HOME_ROOM_ID", 1))

# --- LLM API ---
LLM_API_PORT = int(os.environ.get("LLM_API_PORT", 10007))
# If set, this takes absolute priority (for remote/dedicated LLM servers).
_llm_api_url_override = os.environ.get("LLM_API_URL", "").strip()
if _llm_api_url_override:
    LLM_API_URL = _llm_api_url_override.rstrip("/")
else:
    LLM_API_URL = (
        "https://aihoonbot.com/llm"
        if USE_CLOUDFLARE
        else f"http://localhost:{LLM_API_PORT}"
    )
# Load LLM API key from file (set via setup.py)
def _load_llm_api_key() -> str:
    key_file = os.path.join(os.path.dirname(__file__), "data", ".llm_key")
    try:
        with open(key_file, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""

# Load LLM model from file (set via setup.py)
def _load_llm_model() -> str:
    model_file = os.path.join(os.path.dirname(__file__), "data", ".llm_model")
    try:
        with open(model_file, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""

LLM_API_KEY = _load_llm_api_key()  # Bearer token loaded from data/.llm_key
LLM_MODEL = _load_llm_model()      # Model name loaded from data/.llm_model
# --- Storage ---
SOUL_PATH = os.path.join(os.path.dirname(__file__), "SOUL.md")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MAX_HISTORY_MESSAGES = 50  # Per room

# --- Message limits ---
MAX_MESSAGE_LENGTH = int(os.environ.get("HOONBOT_MAX_MESSAGE_LENGTH", 2000))

# --- Heartbeat ---
HEARTBEAT_ENABLED = os.environ.get("HOONBOT_HEARTBEAT_ENABLED", "true").lower() == "true"
HEARTBEAT_INTERVAL_SECONDS = int(os.environ.get("HOONBOT_HEARTBEAT_INTERVAL", 3600))
# If LLM connection fails, heartbeat pauses proactive LLM calls for this many seconds.
HEARTBEAT_LLM_COOLDOWN_SECONDS = int(
    os.environ.get("HOONBOT_HEARTBEAT_LLM_COOLDOWN_SECONDS", 600)
)
# Active hours: heartbeat only runs between these local times (HH:MM 24h, default = always)
HEARTBEAT_ACTIVE_START = os.environ.get("HOONBOT_HEARTBEAT_ACTIVE_START", "00:00")
HEARTBEAT_ACTIVE_END = os.environ.get("HOONBOT_HEARTBEAT_ACTIVE_END", "23:59")

# --- Memory ---
# Extra paths to Markdown files/dirs to inject as reference documents (comma-separated)
MEMORY_EXTRA_PATHS = [
    p.strip()
    for p in os.environ.get("HOONBOT_MEMORY_EXTRA_PATHS", "").split(",")
    if p.strip()
]

# --- Notifications ---
NOTIFICATIONS_ENABLED = os.environ.get("HOONBOT_NOTIFICATIONS", "true").lower() == "true"

# --- Compaction flush ---
# When history reaches this fraction of MAX_HISTORY_MESSAGES, prompt LLM to save key memories
COMPACTION_FLUSH_THRESHOLD = float(os.environ.get("HOONBOT_COMPACTION_THRESHOLD", "0.8"))

# --- Incoming webhooks ---
# External services POST to /webhook/incoming/<source> with this secret in X-Webhook-Secret header
WEBHOOK_INCOMING_SECRET = os.environ.get("HOONBOT_WEBHOOK_SECRET", "")
