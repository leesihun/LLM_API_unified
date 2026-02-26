"""
Pydantic schemas for request/response validation
"""
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field


# ============================================================================
# Auth Schemas
# ============================================================================
class SignupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="Username (3-50 characters)")
    password: str = Field(..., min_length=8, description="Password (8+ characters, max 72 bytes)")
    role: str = "user"


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ============================================================================
# Chat Schemas (OpenAI Compatible)
# ============================================================================
class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    session_id: Optional[str] = None


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    x_session_id: str


class ChatCompletionChunkDelta(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None


class ChatCompletionChunkChoice(BaseModel):
    index: int = 0
    delta: ChatCompletionChunkDelta
    finish_reason: Optional[str] = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: List[ChatCompletionChunkChoice]
    x_session_id: Optional[str] = None


class ToolStatusChunk(BaseModel):
    """Streamed event for tool execution visibility."""
    object: str = "tool.status"
    tool_name: str
    tool_call_id: str = ""
    status: str  # "started" | "completed" | "failed"
    duration: float = 0.0


# ============================================================================
# Model Schemas (OpenAI Compatible)
# ============================================================================
class ModelObject(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "system"


class ModelsListResponse(BaseModel):
    object: str = "list"
    data: List[ModelObject]


class ChangeModelRequest(BaseModel):
    model: str


# ============================================================================
# Session Schemas
# ============================================================================
class SessionInfo(BaseModel):
    session_id: str
    title: Optional[str] = None
    created_at: str
    message_count: int


class SessionsListResponse(BaseModel):
    sessions: List[SessionInfo]


class ChatHistoryResponse(BaseModel):
    messages: List[ChatMessage]


# ============================================================================
# Tools Schemas
# ============================================================================
class ToolInfo(BaseModel):
    name: str
    description: str
    enabled: bool = True


class ToolsListResponse(BaseModel):
    tools: List[ToolInfo]


class WebSearchRequest(BaseModel):
    query: str
    max_results: Optional[int] = None


class WebSearchResult(BaseModel):
    title: str
    url: str
    content: str
    score: float = 1.0


class WebSearchResponse(BaseModel):
    answer: str
    results: List[WebSearchResult]
    sources_used: List[str]
