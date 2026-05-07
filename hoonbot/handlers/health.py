from datetime import datetime, timezone
from fastapi import APIRouter

import config

router = APIRouter()


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cluster_role": getattr(config, "CLUSTER_ROLE", "master"),
        "node_name": getattr(config, "NODE_NAME", "master"),
        "prompt_profile": getattr(config, "PROMPT_PROFILE", "master"),
        "heartbeat_profile": getattr(config, "HEARTBEAT_PROFILE", "master"),
    }
