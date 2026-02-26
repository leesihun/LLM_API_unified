"""
Background job queue endpoints.

Allows submitting long-running agent tasks as background jobs.
Clients get a job_id immediately and poll for status/output.

POST   /api/jobs              Submit job → {job_id, session_id, status}
GET    /api/jobs              List user's jobs
GET    /api/jobs/{id}         Get job status + full output
GET    /api/jobs/{id}/stream  SSE stream of job output
DELETE /api/jobs/{id}         Cancel a running job
"""
import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Form, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from backend.core.database import db, conversation_store
from backend.core.job_store import job_store
from backend.core.llm_backend import TextEvent, ToolStatusEvent
from backend.utils.auth import get_optional_user
from backend.utils.file_handler import save_uploaded_files
import config

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

# Module-level dict of running asyncio tasks for cancellation
_running_tasks: Dict[str, asyncio.Task] = {}


# ============================================================================
# Background runner
# ============================================================================

async def _run_job(
    job_id: str,
    username: str,
    session_id: str,
    messages: List[Dict[str, Any]],
    file_metadata: List[Dict[str, Any]],
    model: str,
    temperature: float,
):
    """Run the agent loop in the background, streaming output to the job file."""
    from backend.agent import AgentLoop

    job_store.update_status(job_id, "running")
    try:
        agent = AgentLoop(
            model=model,
            temperature=temperature,
            session_id=session_id,
            username=username,
        )

        assistant_message = ""
        async for event in agent.run_stream(messages, file_metadata):
            if isinstance(event, TextEvent):
                assistant_message += event.content
                job_store.append_chunk(job_id, event.content)
            elif isinstance(event, ToolStatusEvent):
                job_store.append_tool_event(
                    job_id,
                    tool_name=event.tool_name,
                    status=event.status,
                    duration=getattr(event, "duration", 0.0),
                )

        # Save final response to conversation history
        history = conversation_store.load_conversation(session_id) or []
        history.append({"role": "assistant", "content": assistant_message})
        conversation_store.save_conversation(session_id, history)
        db.update_session_message_count(session_id, len(history))

        job_store.update_status(job_id, "completed")

    except asyncio.CancelledError:
        job_store.update_status(job_id, "cancelled")
    except Exception as e:
        job_store.update_status(job_id, "failed", error=str(e))
    finally:
        _running_tasks.pop(job_id, None)


# ============================================================================
# Endpoints
# ============================================================================

@router.post("")
async def submit_job(
    model: Optional[str] = Form(None),
    messages: str = Form(...),
    temperature: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),
    files: List[UploadFile] = File(default=[]),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """
    Submit a background agent job. Returns immediately with a job_id.
    The agent runs asynchronously; poll GET /api/jobs/{job_id} for status.
    """
    try:
        messages_data = json.loads(messages)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid messages JSON")

    username = current_user["username"] if current_user else "guest"
    model_name = model or config.LLAMACPP_MODEL
    temp = float(temperature) if temperature else config.DEFAULT_TEMPERATURE

    # Session handling
    if session_id:
        session = db.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        history = conversation_store.load_conversation(session_id) or []
        for msg in messages_data:
            history.append({"role": msg["role"], "content": msg.get("content", "")})
        agent_messages = history
    else:
        session_id = str(uuid.uuid4())
        db.create_session(session_id, username)
        # Auto-title
        for msg in messages_data:
            if msg.get("role") == "user" and msg.get("content"):
                text = str(msg["content"]).strip().replace("\n", " ")
                db.update_session_title(session_id, text[:60] + ("…" if len(text) > 60 else ""))
                break
        agent_messages = [{"role": m["role"], "content": m.get("content", "")} for m in messages_data]
        conversation_store.save_conversation(session_id, agent_messages)
        db.update_session_message_count(session_id, len(agent_messages))

    # File uploads
    file_metadata: List[Dict[str, Any]] = []
    if files:
        from backend.utils.file_handler import extract_file_metadata
        from pathlib import Path
        file_paths = save_uploaded_files(files, username, session_id)
        for fp in file_paths:
            path = Path(fp)
            try:
                meta = extract_file_metadata(fp)
                file_metadata.append({"name": path.name, "path": fp, "size": path.stat().st_size, **meta})
            except Exception as e:
                file_metadata.append({"name": path.name, "path": fp, "error": str(e)})

    job_id = str(uuid.uuid4())
    job_store.create(job_id, username, session_id, agent_messages, model_name, temp)

    task = asyncio.create_task(
        _run_job(job_id, username, session_id, agent_messages, file_metadata, model_name, temp)
    )
    _running_tasks[job_id] = task

    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "session_id": session_id,
            "status": "pending",
        },
    )


@router.get("")
def list_jobs(current_user: Optional[dict] = Depends(get_optional_user)):
    """List all background jobs for the current user."""
    username = current_user["username"] if current_user else "guest"
    jobs = job_store.list_jobs(username)
    return {"jobs": jobs}


@router.get("/{job_id}")
def get_job(job_id: str, current_user: Optional[dict] = Depends(get_optional_user)):
    """Get the full status and output of a job."""
    job = job_store.load(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    username = current_user["username"] if current_user else "guest"
    if job["username"] != username:
        raise HTTPException(status_code=403, detail="Access denied")

    # Return full output as concatenated string
    output = "".join(job.get("output_chunks", []))
    return {
        "job_id": job["job_id"],
        "session_id": job["session_id"],
        "status": job["status"],
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "completed_at": job["completed_at"],
        "output": output,
        "tool_events": job.get("tool_events", []),
        "error": job.get("error"),
    }


@router.get("/{job_id}/stream")
async def stream_job(job_id: str, current_user: Optional[dict] = Depends(get_optional_user)):
    """SSE stream of job output. Sends chunks as they arrive, then closes when job finishes."""
    job = job_store.load(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    username = current_user["username"] if current_user else "guest"
    if job["username"] != username:
        raise HTTPException(status_code=403, detail="Access denied")

    async def generator():
        last_chunk = 0
        while True:
            current = job_store.load(job_id)
            if current is None:
                break

            chunks = current.get("output_chunks", [])
            new_chunks = chunks[last_chunk:]
            for chunk in new_chunks:
                yield {"data": json.dumps({"content": chunk})}
            last_chunk += len(new_chunks)

            status = current.get("status", "")
            if status in ("completed", "failed", "cancelled"):
                yield {"data": json.dumps({
                    "done": True,
                    "status": status,
                    "error": current.get("error"),
                })}
                break

            await asyncio.sleep(0.2)

    return EventSourceResponse(generator())


@router.delete("/{job_id}")
def cancel_job(job_id: str, current_user: Optional[dict] = Depends(get_optional_user)):
    """Cancel a running or pending job."""
    job = job_store.load(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    username = current_user["username"] if current_user else "guest"
    if job["username"] != username:
        raise HTTPException(status_code=403, detail="Access denied")

    if job["status"] in ("completed", "failed", "cancelled"):
        return {"job_id": job_id, "status": job["status"], "message": "Job already finished."}

    # Cancel asyncio task if still running
    task = _running_tasks.get(job_id)
    if task and not task.done():
        task.cancel()
    else:
        # Task may have already finished; mark as cancelled in store
        job_store.update_status(job_id, "cancelled")

    return {"job_id": job_id, "status": "cancelled"}
