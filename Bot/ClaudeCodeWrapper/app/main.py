from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import config
from app.task_manager import Task, TaskManager
from app.tunnel import CloudflareTunnel

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "static"

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

authenticated_clients: set[WebSocket] = set()
task_manager = TaskManager()
tunnel: CloudflareTunnel | None = None


# ---------------------------------------------------------------------------
# Broadcast helper — pushes events to every connected client
# ---------------------------------------------------------------------------

async def broadcast(event_type: str, task: Task, text: str = "") -> None:
    msg = _ws_message(event_type, task, text)
    payload = json.dumps(msg)
    stale: set[WebSocket] = set()
    for ws in authenticated_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            stale.add(ws)
    authenticated_clients.difference_update(stale)


def _ws_message(event_type: str, task: Task, text: str = "") -> dict:
    if event_type == "stream":
        return {"type": "stream", "taskId": task.id, "text": text}
    base: dict = {
        "type": event_type,
        "taskId": task.id,
        "tool": task.tool,
        "prompt": task.prompt,
        "status": task.status.value,
        "delayMinutes": task.delay_minutes,
    }
    if task.error:
        base["error"] = task.error
    if task.exit_code is not None:
        base["exitCode"] = task.exit_code
    if task.scheduled_for:
        base["scheduledFor"] = task.scheduled_for.isoformat()
    return base


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(_app: FastAPI):
    global tunnel
    task_manager.set_broadcast(broadcast)
    task_manager.start()

    if config.TUNNEL_ENABLED:
        tunnel = CloudflareTunnel(
            cmd=config.CLOUDFLARED_CMD,
            local_url=f"http://localhost:{config.PORT}",
        )
        public_url = await tunnel.start()
        logger.info(f"Public URL: {public_url}")

    yield

    if tunnel:
        await tunnel.stop()
    await task_manager.stop()


app = FastAPI(lifespan=lifespan)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    is_authed = False

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type")

            if msg_type == "auth":
                if data.get("token") == config.SECRET_TOKEN:
                    is_authed = True
                    authenticated_clients.add(ws)
                    await ws.send_text(json.dumps({"type": "auth_ok"}))
                    state = task_manager.get_state()
                    state["workspaces"] = config.list_workspaces()
                    state["activeWorkspace"] = config.active_workspace
                    if tunnel and tunnel.public_url:
                        state["tunnelUrl"] = tunnel.public_url
                    await ws.send_text(json.dumps({"type": "state", **state}))
                else:
                    await ws.send_text(json.dumps({"type": "auth_fail"}))
                continue

            if not is_authed:
                await ws.send_text(
                    json.dumps({"type": "error", "message": "Not authenticated"})
                )
                continue

            if msg_type == "submit":
                prompt = data.get("prompt", "").strip()
                tool = data.get("tool", "claude").lower()
                allowed_tools = data.get("allowedTools", [])
                skip_permissions = bool(data.get("skipPermissions", False))
                try:
                    delay_minutes = float(data.get("delayMinutes", 0))
                except (ValueError, TypeError):
                    delay_minutes = 0

                if not prompt:
                    await ws.send_text(
                        json.dumps({"type": "error", "message": "Prompt cannot be empty"})
                    )
                    continue
                if len(prompt) > config.MAX_PROMPT_LENGTH:
                    await ws.send_text(
                        json.dumps({
                            "type": "error",
                            "message": f"Prompt exceeds max length ({config.MAX_PROMPT_LENGTH})"
                        })
                    )
                    continue

                if tool not in ("claude", "cursor"):
                    await ws.send_text(
                        json.dumps({"type": "error", "message": "Invalid tool selection"})
                    )
                    continue

                if delay_minutes < 0 or delay_minutes > config.MAX_DELAY_MINUTES:
                    await ws.send_text(
                        json.dumps({
                            "type": "error",
                            "message": f"Delay must be 0-{config.MAX_DELAY_MINUTES} minutes"
                        })
                    )
                    continue

                if not isinstance(allowed_tools, list) or not all(isinstance(t, str) for t in allowed_tools):
                    await ws.send_text(
                        json.dumps({"type": "error", "message": "allowedTools must be a list of strings"})
                    )
                    continue

                task = task_manager.add_task(
                    tool=tool,
                    prompt=prompt,
                    delay_minutes=delay_minutes,
                    allowed_tools=allowed_tools,
                    skip_permissions=skip_permissions,
                )
                logger.info(
                    f"Task {task.id} queued: {tool} "
                    f"({len(prompt)} chars, {delay_minutes}m delay, "
                    f"{len(allowed_tools)} permissions, skip={skip_permissions})"
                )
                await broadcast("task_queued", task)

            elif msg_type == "cancel":
                task_id = data.get("taskId")
                if not task_id:
                    await ws.send_text(
                        json.dumps({"type": "error", "message": "taskId required for cancel"})
                    )
                    continue
                ok = await task_manager.cancel_task(task_id)
                logger.info(f"Task {task_id} cancel: {'success' if ok else 'not found'}")
                await ws.send_text(
                    json.dumps({
                        "type": "cancel_result",
                        "taskId": task_id,
                        "success": ok,
                    })
                )

            elif msg_type == "set_workspace":
                name = data.get("name", "").strip()
                if not name:
                    await ws.send_text(
                        json.dumps({"type": "error", "message": "Workspace name required"})
                    )
                    continue
                try:
                    full_path = config.set_workspace(name)
                    payload = json.dumps({
                        "type": "workspace_changed",
                        "name": name,
                        "path": full_path,
                    })
                    for client in authenticated_clients:
                        try:
                            await client.send_text(payload)
                        except Exception:
                            pass
                except ValueError as e:
                    await ws.send_text(
                        json.dumps({"type": "error", "message": str(e)})
                    )

    except WebSocketDisconnect:
        logger.debug("Client disconnected")
    except Exception as e:
        logger.exception(f"WebSocket error: {e}")
    finally:
        authenticated_clients.discard(ws)


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))
