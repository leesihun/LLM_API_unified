"""
Session management endpoints
/api/chat/sessions - List or search user sessions
/api/chat/sessions/{session_id} - Rename a session
/api/chat/sessions/{session_id}/compact - Summarize old history in-place
/api/chat/history/{session_id} - Get conversation history
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from backend.models.schemas import SessionsListResponse, SessionInfo, ChatHistoryResponse, ChatMessage
from backend.core.database import db, conversation_store
from backend.utils.auth import get_current_user, get_optional_user

router = APIRouter(prefix="/api/chat", tags=["sessions"])


class RenameSessionRequest(BaseModel):
    title: str


@router.get("/sessions", response_model=SessionsListResponse)
def list_sessions(
    q: Optional[str] = None,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """
    List sessions for the current user. Pass ?q=keyword to search by title or session ID.
    """
    username = current_user["username"] if current_user else "guest"

    if q and q.strip():
        sessions = db.search_sessions(username, q.strip())
    else:
        sessions = db.list_user_sessions(username)

    session_infos = [
        SessionInfo(
            session_id=session["id"],
            title=session.get("title"),
            created_at=session["created_at"],
            message_count=session["message_count"],
        )
        for session in sessions
        if not session["id"].startswith("hb_")
    ]

    return SessionsListResponse(sessions=session_infos)


@router.patch("/sessions/{session_id}", response_model=SessionInfo)
def rename_session(
    session_id: str,
    body: RenameSessionRequest,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """Rename a session by setting its title."""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if current_user:
        if session["username"] != current_user["username"] and session["username"] != "guest":
            raise HTTPException(status_code=403, detail="Access denied")

    title = body.title.strip()[:120]  # cap at 120 chars
    db.update_session_title(session_id, title)

    return SessionInfo(
        session_id=session_id,
        title=title,
        created_at=session["created_at"],
        message_count=session["message_count"],
    )


@router.post("/sessions/{session_id}/compact")
async def compact_session(
    session_id: str,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """Summarize the older half of a session's conversation history in place.

    The session_id is preserved — the conversation continues with the same
    context but a reduced message count. Useful when approaching context limits.
    """
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = conversation_store.load_conversation(session_id) or []
    original_count = len(messages)

    if original_count < 4:
        return {
            "success": False,
            "message": "Not enough messages to compact",
            "original_count": original_count,
            "new_count": original_count,
        }

    from backend.agent import UnifiedAgent
    agent = UnifiedAgent(
        session_id=session_id,
        username=session.get("username", "guest"),
    )
    compacted = await agent._summarize_and_compact_msgs(messages)

    if not compacted:
        return {
            "success": False,
            "message": "Nothing left to compact",
            "original_count": original_count,
            "new_count": original_count,
        }

    conversation_store.save_conversation(session_id, messages)
    return {
        "success": True,
        "message": f"Compacted {original_count} → {len(messages)} messages",
        "original_count": original_count,
        "new_count": len(messages),
    }


@router.get("/history/{session_id}", response_model=ChatHistoryResponse)
def get_history(
    session_id: str,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """Get conversation history for a specific session."""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if current_user:
        if session["username"] != current_user["username"] and session["username"] != "guest":
            raise HTTPException(status_code=403, detail="Access denied")

    messages = conversation_store.load_conversation(session_id)
    if messages is None:
        messages = []

    chat_messages = [ChatMessage(**msg) for msg in messages]
    return ChatHistoryResponse(messages=chat_messages)
