"""
Chat completions endpoint (OpenAI-compatible with extensions)
/v1/chat/completions

Accepts both:
  - application/json  (standard OpenAI SDK, Jupyter, agents, etc.)
  - multipart/form-data  (file uploads, legacy frontend)

Both streaming and non-streaming go through the AgentLoop,
which uses native tool calling via llama.cpp.
"""
import asyncio
import json
import time
import uuid
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Request
from starlette.datastructures import UploadFile
from sse_starlette.sse import EventSourceResponse

from backend.models.schemas import (
    ChatMessage,
    ChatCompletionResponse,
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
)
from backend.core.database import db, conversation_store
from backend.core.llm_backend import TextEvent, ToolStatusEvent
from backend.utils.file_handler import save_uploaded_files, extract_file_metadata, is_image_file, encode_image_base64
from backend.utils.auth import get_optional_user
from backend.agent import AgentLoop
import config

router = APIRouter(prefix="/v1", tags=["chat"])


# ---------------------------------------------------------------------------
# Request parsing — handles both JSON and multipart/form-data
# ---------------------------------------------------------------------------

async def _parse_request(request: Request) -> dict:
    """
    Parse /v1/chat/completions from either JSON or multipart form.

    Returns a dict with keys:
      messages_data, model, stream, temperature, max_tokens, session_id, files
    """
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        messages_raw = form.get("messages", "[]")
        model = form.get("model") or None
        stream = str(form.get("stream", "false")).lower() == "true"
        temperature = form.get("temperature")
        max_tokens = form.get("max_tokens")
        session_id = form.get("session_id") or None
        files = [v for v in form.getlist("files") if isinstance(v, UploadFile) and v.filename]
        try:
            messages_data = json.loads(messages_raw)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid messages JSON")
    else:
        # JSON body (standard OpenAI format)
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        messages_data = body.get("messages", [])
        model = body.get("model") or None
        stream = bool(body.get("stream", False))
        temperature = body.get("temperature")
        max_tokens = body.get("max_tokens")
        session_id = body.get("session_id") or None
        files = []

    return dict(
        messages_data=messages_data,
        model=model,
        stream=stream,
        temperature=float(temperature) if temperature is not None else None,
        max_tokens=int(max_tokens) if max_tokens is not None else None,
        session_id=session_id,
        files=files,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_text_from_content(content) -> str:
    """Extract plain text from content (str or content array)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return " ".join(parts)
    return str(content) if content else ""


def _build_storage_messages(messages: List[ChatMessage]) -> List[Dict[str, str]]:
    """Convert incoming chat messages into the persisted text-only history form."""
    return [
        {"role": msg.role, "content": _extract_text_from_content(msg.content) or ""}
        for msg in messages
    ]


def _generate_session_title(messages: list) -> str:
    for msg in messages:
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
        if role == "user" and content:
            text = _extract_text_from_content(content).strip().replace("\n", " ")
            return text[:60] + ("…" if len(text) > 60 else "")
    return "Untitled"


def _prepare_messages_with_files(
    messages: List[ChatMessage],
    file_paths: List[str],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    from pathlib import Path

    message_dicts = []
    for msg in messages:
        content = msg.content
        if isinstance(content, list):
            message_dicts.append({"role": msg.role, "content": content})
        else:
            message_dicts.append({"role": msg.role, "content": content or ""})

    image_paths: List[str] = []
    non_image_paths: List[str] = []
    file_metadata: List[Dict[str, Any]] = []

    if file_paths:
        for file_path in file_paths:
            if is_image_file(file_path):
                image_paths.append(file_path)
            else:
                non_image_paths.append(file_path)

        for file_path in non_image_paths:
            path = Path(file_path)
            try:
                file_size = path.stat().st_size
                file_type = path.suffix.lstrip('.')
                text_ext = {'txt', 'md', 'json', 'csv', 'py', 'js', 'html', 'xml', 'java', 'cpp', 'c', 'h', 'go', 'rs', 'ts', 'jsx', 'tsx'}
                data_ext = {'csv', 'xlsx', 'xls', 'json'}
                code_ext = {'py', 'js', 'java', 'cpp', 'c', 'h', 'go', 'rs', 'ts', 'jsx', 'tsx', 'html', 'css'}
                category = 'binary'
                if file_type in text_ext:
                    category = 'text'
                if file_type in data_ext:
                    category = 'data'
                if file_type in code_ext:
                    category = 'code'
                rich_metadata = extract_file_metadata(file_path)
                file_metadata.append({
                    "name": path.name, "path": file_path,
                    "size": file_size, "type": file_type, "category": category,
                    **rich_metadata,
                })
            except Exception as e:
                file_metadata.append({"name": path.name, "path": file_path, "error": str(e)})

    if image_paths:
        last_user_idx = None
        for i in range(len(message_dicts) - 1, -1, -1):
            if message_dicts[i]["role"] == "user":
                last_user_idx = i
                break
        if last_user_idx is not None:
            msg = message_dicts[last_user_idx]
            existing_content = msg["content"]
            if isinstance(existing_content, list):
                content_parts = list(existing_content)
            else:
                content_parts = [{"type": "text", "text": existing_content or ""}]
            for img_path in image_paths:
                encoded = encode_image_base64(img_path)
                if encoded:
                    content_parts.append({"type": "image_url", "image_url": encoded})
                    from pathlib import Path as _Path
                    print(f"[VISION] Embedded image: {_Path(img_path).name}")
            msg["content"] = content_parts

    return message_dicts, file_metadata


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    try:
        parsed = await _parse_request(request)
        messages_data = parsed["messages_data"]
        model_name = parsed["model"] or config.LLAMACPP_MODEL
        is_streaming = parsed["stream"]
        temp = parsed["temperature"] if parsed["temperature"] is not None else config.DEFAULT_TEMPERATURE
        session_id = parsed["session_id"]
        files: List[UploadFile] = parsed["files"]
        username = current_user["username"] if current_user else "guest"

        chat_messages = [ChatMessage(**msg) for msg in messages_data]
        new_history_messages = _build_storage_messages(chat_messages)

        # Session handling
        if session_id:
            session = db.get_session(session_id)
            if not session:
                if session_id.startswith("hb_"):
                    # Heartbeat sessions are auto-created on first tick of each hour
                    db.create_session(session_id, username)
                    db.update_session_title(session_id, f"Heartbeat {session_id[3:]}")
                    history = []
                else:
                    raise HTTPException(status_code=404, detail="Session not found")
            else:
                history = conversation_store.load_recent_conversation(session_id) or []
        else:
            session_id = str(uuid.uuid4())
            db.create_session(session_id, username)
            title = _generate_session_title(chat_messages)
            db.update_session_title(session_id, title)
            history = []

        # File uploads
        file_paths: List[str] = []
        if files:
            file_paths = save_uploaded_files(files, username, session_id)

        llm_messages, file_metadata = _prepare_messages_with_files(chat_messages, file_paths)

        # Build conversation context for the agent from bounded hot history + new request delta.
        agent_messages = list(history)
        agent_messages.extend(llm_messages)

        agent = AgentLoop(
            model=model_name,
            temperature=temp,
            session_id=session_id,
            username=username,
        )

        request_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        created_timestamp = int(time.time())

        if is_streaming:
            async def generate_stream():
                try:
                    assistant_message = ""
                    persisted_messages = [
                        *new_history_messages,
                        {"role": "assistant", "content": ""},
                    ]
                    async for event in agent.run_stream(agent_messages, file_metadata):
                        if isinstance(event, TextEvent):
                            assistant_message += event.content
                            persisted_messages[-1]["content"] = assistant_message
                            chunk = ChatCompletionChunk(
                                id=request_id,
                                created=created_timestamp,
                                model=model_name,
                                choices=[
                                    ChatCompletionChunkChoice(
                                        delta=ChatCompletionChunkDelta(content=event.content)
                                    )
                                ],
                            )
                            # Unnamed event — parsed by standard OpenAI clients
                            yield {"data": chunk.model_dump_json()}
                        elif isinstance(event, ToolStatusEvent):
                            tool_data = json.dumps({
                                "tool_status": {
                                    "tool_name": event.tool_name,
                                    "tool_call_id": event.tool_call_id,
                                    "status": event.status,
                                    "duration": event.duration,
                                }
                            })
                            # Named event — standard clients ignore unknown event types
                            yield {"event": "tool_status", "data": tool_data}

                    # Final chunk with session_id
                    final_chunk = ChatCompletionChunk(
                        id=request_id,
                        created=created_timestamp,
                        model=model_name,
                        choices=[
                            ChatCompletionChunkChoice(
                                delta=ChatCompletionChunkDelta(),
                                finish_reason="stop",
                            )
                        ],
                        x_session_id=session_id,
                    )
                    yield {"data": final_chunk.model_dump_json()}
                    yield {"data": "[DONE]"}

                    asyncio.create_task(asyncio.to_thread(
                        conversation_store.append_messages, session_id, persisted_messages
                    ))
                    asyncio.create_task(asyncio.to_thread(
                        db.increment_session_message_count, session_id, len(persisted_messages)
                    ))

                except Exception as e:
                    error_data = {"error": {"message": str(e), "type": "internal_error"}}
                    yield {"data": json.dumps(error_data)}

            return EventSourceResponse(generate_stream())

        else:
            assistant_message = await agent.run(agent_messages, file_metadata)

            persisted_messages = [
                *new_history_messages,
                {"role": "assistant", "content": assistant_message},
            ]
            asyncio.create_task(asyncio.to_thread(
                conversation_store.append_messages, session_id, persisted_messages
            ))
            asyncio.create_task(asyncio.to_thread(
                db.increment_session_message_count, session_id, len(persisted_messages)
            ))

            return ChatCompletionResponse(
                id=request_id,
                created=created_timestamp,
                model=model_name,
                choices=[
                    ChatCompletionChoice(
                        message=ChatMessage(role="assistant", content=assistant_message)
                    )
                ],
                x_session_id=session_id,
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
