"""
Chat completions endpoint (OpenAI-compatible with extensions)
/v1/chat/completions

Both streaming and non-streaming go through the AgentLoop,
which uses native tool calling via llama.cpp.
"""
import json
import time
import uuid
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Form, File, UploadFile, HTTPException, Depends
from sse_starlette.sse import EventSourceResponse

from backend.models.schemas import (
    ChatMessage,
    ChatCompletionResponse,
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
    ToolStatusChunk,
)
from backend.core.database import db, conversation_store
from backend.core.llm_backend import TextEvent, ToolStatusEvent
from backend.utils.file_handler import save_uploaded_files, extract_file_metadata
from backend.utils.auth import get_optional_user
from backend.agent import AgentLoop
import config

router = APIRouter(prefix="/v1", tags=["chat"])


def _prepare_messages_with_files(
    messages: List[ChatMessage],
    file_paths: List[str],
) -> tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
    from pathlib import Path

    message_dicts = [{"role": msg.role, "content": msg.content or ""} for msg in messages]

    file_metadata: List[Dict[str, Any]] = []
    if file_paths:
        for file_path in file_paths:
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

    return message_dicts, file_metadata


@router.post("/chat/completions")
async def chat_completions(
    model: Optional[str] = Form(None),
    messages: str = Form(...),
    stream: str = Form("false"),
    temperature: Optional[str] = Form(None),
    max_tokens: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),
    files: List[UploadFile] = File(default=[]),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    try:
        messages_data = json.loads(messages)
        chat_messages = [ChatMessage(**msg) for msg in messages_data]

        is_streaming = stream.lower() == "true"
        temp = float(temperature) if temperature else config.DEFAULT_TEMPERATURE
        model_name = model or config.LLAMACPP_MODEL
        username = current_user["username"] if current_user else "guest"

        # Session handling
        if session_id:
            session = db.get_session(session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            history = conversation_store.load_conversation(session_id) or []
            for msg in chat_messages:
                history.append({"role": msg.role, "content": msg.content or ""})
        else:
            session_id = str(uuid.uuid4())
            db.create_session(session_id, username)
            history = [{"role": msg.role, "content": msg.content or ""} for msg in chat_messages]

        # File uploads
        file_paths: List[str] = []
        if files and len(files) > 0:
            file_paths = save_uploaded_files(files, username, session_id)

        llm_messages, file_metadata = _prepare_messages_with_files(chat_messages, file_paths)

        # Build conversation context for the agent
        if len(llm_messages) > 0:
            if len(history) > len(chat_messages):
                if file_paths:
                    history[-1]["content"] = llm_messages[-1]["content"]
                agent_messages = history
            else:
                agent_messages = llm_messages
        else:
            agent_messages = []

        # Create agent
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
                    async for event in agent.run_stream(agent_messages, file_metadata):
                        if isinstance(event, TextEvent):
                            assistant_message += event.content
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
                            yield {"data": chunk.model_dump_json()}
                        elif isinstance(event, ToolStatusEvent):
                            status_chunk = ToolStatusChunk(
                                tool_name=event.tool_name,
                                tool_call_id=event.tool_call_id,
                                status=event.status,
                                duration=event.duration,
                            )
                            yield {"data": status_chunk.model_dump_json()}

                    # Final chunk
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

                    history.append({"role": "assistant", "content": assistant_message})
                    conversation_store.save_conversation(session_id, history)
                    db.update_session_message_count(session_id, len(history))

                except Exception as e:
                    error_data = {"error": {"message": str(e), "type": "internal_error"}}
                    yield {"data": json.dumps(error_data)}

            return EventSourceResponse(generate_stream())

        else:
            assistant_message = await agent.run(agent_messages, file_metadata)

            history.append({"role": "assistant", "content": assistant_message})
            conversation_store.save_conversation(session_id, history)
            db.update_session_message_count(session_id, len(history))

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

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid messages JSON")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
