"""
Cluster runtime configuration for LLM_API_fast.

This is the root control surface for multi-node runs. App-local config.py files
import this module and expose the settings they own to their app. Edit this file
first when changing master/slave role, node name, LAN IPs, prompt profiles, or
cluster credentials.
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parent


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _csv(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _url(host: str, port: int, scheme: str = "http") -> str:
    return f"{scheme}://{host}:{port}"


def _is_ip_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _is_loopback_host(host: str) -> bool:
    if host in {"localhost", "::1"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_advertised_url(name: str, value: str, allow_loopback: bool = False) -> tuple[bool, str]:
    """
    Validate the cluster policy for URLs shared across nodes.

    Inter-node advertised URLs should be IP-style: http://<ip>:<port>. Loopback
    is allowed only for local/single-machine development or explicitly local
    service URLs.
    """
    parsed = urlparse(value)
    host = parsed.hostname or ""
    if parsed.scheme not in {"http", "https"} or not host or not parsed.port:
        return False, f"{name} must look like http://<ip>:<port>"
    lowered = host.lower()
    if lowered == "localhost":
        return False, f"{name} must use an IP address, not localhost"
    if "cloudflare" in lowered or lowered.endswith("trycloudflare.com") or lowered == "aihoonbot.com":
        return False, f"{name} must not use Cloudflare/tunnel hostnames"
    if _is_loopback_host(host):
        if allow_loopback:
            return True, ""
        return False, f"{name} must not advertise loopback outside this node"
    if not _is_ip_host(host):
        return False, f"{name} must use an IP address, not DNS"
    return True, ""


def require_valid_advertised_urls() -> None:
    checks = [
        ("MASTER_LLM_API_URL", MASTER_LLM_API_URL, NODE_ROLE == "master"),
        ("MESSENGER_URL", MESSENGER_URL, NODE_ROLE == "master"),
        ("HOONBOT_WEBHOOK_URL", HOONBOT_WEBHOOK_URL, NODE_ROLE == "master"),
        ("ADVERTISED_LLM_API_URL", ADVERTISED_LLM_API_URL, NODE_ROLE == "master"),
    ]
    errors = []
    for name, value, allow_loopback in checks:
        ok, message = validate_advertised_url(name, value, allow_loopback=allow_loopback)
        if not ok:
            errors.append(message)
    if errors:
        raise ValueError("; ".join(errors))


# ---------------------------------------------------------------------------
# Node identity
# ---------------------------------------------------------------------------

NODE_ROLE = _env("CLUSTER_ROLE", "master").lower()
if NODE_ROLE not in {"master", "slave"}:
    raise ValueError("CLUSTER_ROLE must be 'master' or 'slave'")

NODE_NAME = _env("NODE_NAME", "master" if NODE_ROLE == "master" else "slave-01")
NODE_IP = _env("NODE_IP", "127.0.0.1")
MASTER_IP = _env("MASTER_IP", NODE_IP if NODE_ROLE == "master" else "127.0.0.1")


# ---------------------------------------------------------------------------
# Ports and URLs
# ---------------------------------------------------------------------------

MESSENGER_PORT = int(_env("MESSENGER_PORT", "10006"))
HOONBOT_PORT = int(_env("HOONBOT_PORT", "10001"))
LLM_API_PORT = int(_env("LLM_API_PORT", "10007"))
LLAMACPP_PORT = int(_env("LLAMACPP_PORT", "5905"))
LLAMACPP_BACKUP_PORT = int(_env("LLAMACPP_BACKUP_PORT", "10000"))
LLM_API_BIND_HOST = _env("LLM_API_BIND_HOST", "0.0.0.0")
HOONBOT_BIND_HOST = _env("HOONBOT_BIND_HOST", "0.0.0.0")

MESSENGER_URL = _env("MESSENGER_URL", _url(MASTER_IP, MESSENGER_PORT))
LOCAL_HOONBOT_URL = _env("LOCAL_HOONBOT_URL", _url("127.0.0.1", HOONBOT_PORT))
HOONBOT_WEBHOOK_URL = _env("HOONBOT_WEBHOOK_URL", f"{_url(NODE_IP, HOONBOT_PORT)}/webhook")

LOCAL_LLM_API_URL = _env("LOCAL_LLM_API_URL", _url("127.0.0.1", LLM_API_PORT))
MASTER_LLM_API_URL = _env("MASTER_LLM_API_URL", _url(MASTER_IP, LLM_API_PORT))
ADVERTISED_LLM_API_URL = _env("ADVERTISED_LLM_API_URL", _url(NODE_IP, LLM_API_PORT))
HOONBOT_LLM_API_URL = _env("HOONBOT_LLM_API_URL", LOCAL_LLM_API_URL)

LOCAL_LLAMACPP_URL = _env("LOCAL_LLAMACPP_URL", _url("127.0.0.1", LLAMACPP_PORT))
LOCAL_LLAMACPP_BACKUP_URL = _env("LOCAL_LLAMACPP_BACKUP_URL", _url("127.0.0.1", LLAMACPP_BACKUP_PORT))


# ---------------------------------------------------------------------------
# Cluster control plane
# ---------------------------------------------------------------------------

CLUSTER_ENABLED = _env("CLUSTER_ENABLED", "true").lower() == "true"
CLUSTER_MASTER_API_URL = _env("CLUSTER_MASTER_API_URL", MASTER_LLM_API_URL)
CLUSTER_TOKEN = _env("CLUSTER_TOKEN", "change-me-cluster-token")
CLUSTER_NODE_STALE_SECONDS = int(_env("CLUSTER_NODE_STALE_SECONDS", "90"))
CLUSTER_TASK_LEASE_SECONDS = int(_env("CLUSTER_TASK_LEASE_SECONDS", "900"))
CLUSTER_SLAVE_POLL_INTERVAL_SECONDS = float(_env("CLUSTER_SLAVE_POLL_INTERVAL_SECONDS", "3"))

if NODE_ROLE == "master":
    _default_caps = ["orchestrator", "messenger", "llm-api"]
    _default_tags = ["master", "control-plane"]
else:
    _default_caps = ["agent", "llm-api", "local-model"]
    _default_tags = ["slave", "worker"]

NODE_CAPABILITIES = _csv("NODE_CAPABILITIES", _default_caps)
NODE_TAGS = _csv("NODE_TAGS", _default_tags)


# ---------------------------------------------------------------------------
# Hoonbot prompt and skill profiles
# ---------------------------------------------------------------------------

HOONBOT_PROMPTS_DIR = ROOT_DIR / "hoonbot" / "prompts"
HOONBOT_SKILLS_DIR = ROOT_DIR / "hoonbot" / "skills"
HOONBOT_SKILL_PROFILES_DIR = ROOT_DIR / "hoonbot" / "profiles"
PROMPT_PROFILE = _env("PROMPT_PROFILE", NODE_ROLE)
HEARTBEAT_PROFILE = _env("HEARTBEAT_PROFILE", NODE_ROLE)
SKILLS_PROFILE = _env("SKILLS_PROFILE", NODE_ROLE)

PROMPT_FILE = HOONBOT_PROMPTS_DIR / PROMPT_PROFILE / "PROMPT.md"
HEARTBEAT_FILE = HOONBOT_PROMPTS_DIR / HEARTBEAT_PROFILE / "HEARTBEAT.md"
_PROFILE_SKILLS_DIR = HOONBOT_SKILL_PROFILES_DIR / SKILLS_PROFILE / "skills"
_PROFILE_SKILL_FILES = [
    path for path in _PROFILE_SKILLS_DIR.glob("*.md")
    if path.name.lower() != "readme.md"
] if _PROFILE_SKILLS_DIR.exists() else []
SKILLS_DIR = _PROFILE_SKILLS_DIR if _PROFILE_SKILL_FILES else HOONBOT_SKILLS_DIR


def node_payload() -> dict:
    return {
        "node_name": NODE_NAME,
        "role": NODE_ROLE,
        "ip": NODE_IP,
        "api_url": ADVERTISED_LLM_API_URL,
        "local_llm_api_url": LOCAL_LLM_API_URL,
        "capabilities": NODE_CAPABILITIES,
        "tags": NODE_TAGS,
        "prompt_profile": PROMPT_PROFILE,
        "heartbeat_profile": HEARTBEAT_PROFILE,
        "skills_profile": SKILLS_PROFILE,
    }
